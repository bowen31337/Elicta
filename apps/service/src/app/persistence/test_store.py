"""Durability tests: state has to be there after the process that wrote it is gone.

Each test writes through the real HTTP API, throws the application away, builds
a second one against the same database file, and reads back over HTTP. Nothing
is carried between the two apps in Python — the only channel is the file — so a
pass means the data genuinely round-tripped through storage rather than through
a shared object a test fixture kept alive.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.composition import Backend, attach_state_store, build_app
from app.persistence import open_state_store
from app.persistence.store import DurableMapping


@pytest.fixture
def database(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'state.db'}"


def client_for(database: str) -> TestClient:
    """A fresh application bound to an existing database file.

    Deliberately builds a brand-new `Backend`, so anything a previous client
    wrote can only reappear by being read back off disk.
    """

    return TestClient(build_app(attach_state_store(Backend(), open_state_store(database))))


def test_an_engagement_survives_a_restart(database: str) -> None:
    with client_for(database) as first:
        created = first.post(
            "/api/engagements",
            json={
                "client_organisation": "Northwind Logistics",
                "sector": "Freight and warehousing",
                "commercial_context": "Fleet visibility programme",
            },
        )
        assert created.status_code == 201, created.text
        engagement_id = created.json()["engagement_id"]

    with client_for(database) as second:
        # The engagement is known to an application that never saw the POST.
        patched = second.patch(
            f"/api/engagements/{engagement_id}",
            json={"purpose": "Discovery"},
        )
        assert patched.status_code == 200, patched.text


def test_an_unknown_engagement_is_still_unknown_after_a_restart(database: str) -> None:
    # The mirror of the test above: durability that answered 200 for
    # everything would pass that one while being useless.
    with client_for(database) as client:
        assert client.patch("/api/engagements/eng-404", json={"purpose": "x"}).status_code == 404


def test_carried_forward_state_survives_a_restart(database: str) -> None:
    """The FR-8.9 / FR-4.8 premise: what an engagement remembers outlives it."""

    from datetime import UTC, datetime

    from app.modules.compiler.api.recompile import InheritedOpenQuestion
    from app.modules.debrief.artifacts.models import RequirementsState

    store = open_state_store(database)
    questions = store.open_questions(lambda row: InheritedOpenQuestion(**row))
    questions["eng-1"] = [
        InheritedOpenQuestion(text="What does “fast” mean in seconds?", impact_rank=1),
        InheritedOpenQuestion(text="Which integrations are in scope?", impact_rank=2),
    ]
    state = store.requirements_state(lambda row: RequirementsState(**row))
    state["eng-1"] = RequirementsState(
        engagement_id="eng-1",
        confirmed_requirements=[],
        contradictions=[],
        decisions=[],
        updated_at=datetime.now(UTC),
    )
    store.close()

    reopened = open_state_store(database)
    reloaded = reopened.open_questions(lambda row: InheritedOpenQuestion(**row))
    # Ranked ascending on the way back out, not merely present.
    assert [q.impact_rank for q in reloaded["eng-1"]] == [1, 2]
    assert reloaded["eng-1"][0].text.startswith("What does")
    assert reopened.requirements_state(lambda row: RequirementsState(**row))["eng-1"]


def test_the_candidate_bank_keeps_its_compiled_order(database: str) -> None:
    from app.modules.compiler.api.models import BankCandidate

    store = open_state_store(database)
    bank = store.candidates(lambda row: BankCandidate(**row))
    # Priority and position disagree on purpose: the bank is stored in the
    # order it was compiled in, and a store that sorted by priority on the way
    # back would look correct on any list where the two happen to agree.
    bank["eng-1"] = [
        BankCandidate(id="c-1", template_section="Performance", phrasing="How fast?", priority=3),
        BankCandidate(id="c-2", template_section="Integrations", phrasing="Which systems?", priority=1),
    ]
    store.close()

    reloaded = open_state_store(database).candidates(lambda row: BankCandidate(**row))
    assert [c.id for c in reloaded["eng-1"]] == ["c-1", "c-2"]


def test_where_a_question_came_from_survives_a_restart(database: str) -> None:
    """Provenance is the operator's grounds for trusting the bank at all.

    Held only in memory it would come back undone on the next launch, which
    is the same shape as the pruning flag beside it: a judgement about the
    bank that has to outlast the process that computed it. And the absence of
    a source is the *signal* for a reasoned question, so it has to reload as
    absence rather than as a lost value.
    """

    from app.modules.compiler.api.models import BankCandidate

    store = open_state_store(database)
    bank = store.candidates(lambda row: BankCandidate(**row))
    bank["eng-1"] = [
        BankCandidate(
            id="c-1",
            template_section="Volumes",
            phrasing="How many a month?",
            priority=1,
            source_doc="depot-pack.pdf",
            authority_match=["ground truth"],
        ),
        BankCandidate(
            id="c-2",
            template_section="Volumes",
            phrasing="And on a bad day?",
            priority=2,
        ),
    ]
    store.close()

    reloaded = open_state_store(database).candidates(lambda row: BankCandidate(**row))
    grounded, reasoned = reloaded["eng-1"]
    assert grounded.source_doc == "depot-pack.pdf"
    assert grounded.authority_match == ["ground truth"]
    assert reasoned.source_doc is None
    assert reasoned.authority_match == []


def test_replacing_a_list_does_not_leave_the_old_entries_behind(database: str) -> None:
    from app.modules.compiler.api.recompile import InheritedOpenQuestion

    store = open_state_store(database)
    questions = store.open_questions(lambda row: InheritedOpenQuestion(**row))
    questions["eng-1"] = [InheritedOpenQuestion(text="Old", impact_rank=1)]
    questions["eng-1"] = [InheritedOpenQuestion(text="New", impact_rank=1)]
    store.close()

    reloaded = open_state_store(database).open_questions(lambda row: InheritedOpenQuestion(**row))
    assert [q.text for q in reloaded["eng-1"]] == ["New"]


def test_deleting_removes_the_row(database: str) -> None:
    from app.modules.engagement.api.schemas import EngagementCreateRequest

    store = open_state_store(database)
    decode = lambda row: EngagementCreateRequest(**row)  # noqa: E731
    engagements = store.engagements(decode)
    engagements["eng-1"] = EngagementCreateRequest(
        client_organisation="Northwind", sector="Freight", commercial_context="Fleet"
    )
    del engagements["eng-1"]
    store.close()

    assert "eng-1" not in open_state_store(database).engagements(decode)


def test_a_durable_mapping_is_still_a_mapping(database: str) -> None:
    """The substitution only works because routers cannot tell the difference."""

    from app.modules.engagement.api.schemas import EngagementCreateRequest

    decode = lambda row: EngagementCreateRequest(**row)  # noqa: E731
    engagements = open_state_store(database).engagements(decode)
    assert isinstance(engagements, DurableMapping)

    payload = EngagementCreateRequest(
        client_organisation="Northwind", sector="Freight", commercial_context="Fleet"
    )
    engagements["eng-1"] = payload
    assert engagements.get("eng-1") == payload
    assert engagements.get("eng-2") is None
    assert "eng-1" in engagements
    assert len(engagements) == 1
    assert list(engagements) == ["eng-1"]
    assert [value.sector for value in engagements.values()] == ["Freight"]


def test_only_the_continuity_fields_are_made_durable() -> None:
    """Per-run pipeline scratch stays in memory, and that is deliberate."""

    backend = attach_state_store(Backend(), open_state_store("sqlite://"))

    assert isinstance(backend.engagements, DurableMapping)
    assert isinstance(backend.requirements_states, DurableMapping)
    assert isinstance(backend.engagement_open_questions, DurableMapping)
    assert isinstance(backend.compiled_candidates, DurableMapping)
    assert isinstance(backend.meeting_details, DurableMapping)

    # Rebuilt from the transcript on demand; storing it would mean maintaining
    # a second copy of something derived.
    assert isinstance(backend.transcript_cleanings, dict)
    assert not isinstance(backend.transcript_cleanings, DurableMapping)


def test_session_audio_is_never_made_durable() -> None:
    """FR-1.7 as a test, not as an intention.

    Raw audio is never written to disk. `session_audio` holding bytes makes
    that a live risk rather than a theoretical one, so the guard is here
    beside the other durability decisions.
    """

    backend = attach_state_store(Backend(), open_state_store("sqlite://"))

    assert isinstance(backend.session_audio, dict)
    assert not isinstance(backend.session_audio, DurableMapping)


def _engagement(client: TestClient, organisation: str) -> str:
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": organisation,
            "sector": "Freight and warehousing",
            "commercial_context": "Fleet visibility programme",
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["engagement_id"]


def test_a_linked_document_id_is_not_reissued_after_a_restart(database: str) -> None:
    """The link intake mints its own ids, into the table uploads already use.

    `attach_document` hands back `reference-document-N` and keeps it — FR-3.2
    makes a link a second intake path, not a second kind of document — and the
    text lands in `reference_documents` beside the uploaded `doc-N` rows.
    `next_reference_document_id` was the last counter still starting at 0 with
    the process.

    It does not fail loudly the way the vocabulary one did. `document_texts`
    persists by updating the row with that id and only inserting when no row
    matched, so a reissued id finds the earlier row and overwrites its text:
    one engagement's document replaced by another's, no error anywhere. The two
    schemes share a table and must be counted apart, which is what the second
    half asserts.
    """

    first = open_state_store(database)
    first.document_texts()["reference-document-1"] = "CLIENT A — merger terms"
    first.document_texts()["reference-document-2"] = "CLIENT A — heads of terms"
    # An uploaded document, which mints on the other scheme.
    first.document_texts()["doc-9"] = "CLIENT A — a file somebody dropped"

    second = attach_state_store(Backend(), open_state_store(database))
    assert second.next_reference_document_id == 2
    # So the next link is `reference-document-3`, not a second `-1`.
    assert (
        f"reference-document-{second.next_reference_document_id + 1}"
        == "reference-document-3"
    )
    # Counted apart: the uploaded row neither raises the link counter nor is
    # raised by it.
    assert second.next_document_id == 9


def test_a_vocabulary_term_created_after_a_restart_does_not_collide(
    database: str,
) -> None:
    """The same counter bug as meetings and documents, in the third collection.

    `vocabulary_terms` was moved to durable storage because nothing rebuilds
    what somebody typed, but `next_vocabulary_term_id` stayed a field on
    `Backend` that starts at 0 — so a restarted service mints `term-1` again.
    `vocabulary_terms.id` is a primary key, so it is not a quiet overwrite: it
    is `UNIQUE constraint failed: vocabulary_terms.id`, reaching the operator
    as a 500 on the first word they add after a restart. Found on a live
    service holding `term-1` through `term-18`, where every attempt to add a
    word failed and the list stayed empty.
    """

    with client_for(database) as first:
        engagement_id = _engagement(first, "Northwind Logistics")
        created = first.post(
            f"/api/engagements/{engagement_id}/vocabulary",
            json={"term": "Freightlink", "term_type": "internal_system"},
        )
        assert created.status_code == 201, created.text
        original = created.json()["term_id"]

    with client_for(database) as second:
        again = second.post(
            f"/api/engagements/{engagement_id}/vocabulary",
            json={"term": "NAVISTOCK", "term_type": "product_name"},
        )
        assert again.status_code == 201, again.text
        assert again.json()["term_id"] != original

        # And the first word is still itself, not the second wearing its id.
        listed = second.get(f"/api/engagements/{engagement_id}/vocabulary")
        assert listed.status_code == 200, listed.text
        assert [row["term"] for row in listed.json()["terms"]] == [
            "Freightlink",
            "NAVISTOCK",
        ]


def test_a_meeting_created_after_a_restart_does_not_overwrite_an_earlier_one(
    database: str,
) -> None:
    """The meeting id counter has to be derived from the rows, not the process.

    `meeting_details` is durable and `next_meeting_id` was not, so a restarted
    service minted `meeting-1` again and it landed on top of whichever real
    meeting already held that id — the exact collision
    `highest_engagement_ordinal`'s docstring describes for engagements, with no
    equivalent guard for meetings.
    """

    with client_for(database) as first:
        engagement_id = _engagement(first, "Northwind Logistics")
        created = first.post(
            "/api/meetings",
            json={"engagement_id": engagement_id, "capture_mode": "live"},
        )
        assert created.status_code == 201, created.text
        original = created.json()["meeting_id"]

    with client_for(database) as second:
        second_meeting = second.post(
            "/api/meetings",
            json={"engagement_id": engagement_id, "capture_mode": "record"},
        )
        assert second_meeting.status_code == 201, second_meeting.text
        assert second_meeting.json()["meeting_id"] != original

        # And the first one is still itself, not the second wearing its id.
        response = second.get(f"/api/meetings/{original}")
        assert response.status_code == 200, response.text
        assert response.json()["capture_mode"] == "live"

        listed = second.get(f"/api/engagements/{engagement_id}/meetings")
        assert listed.status_code == 200, listed.text
        assert [row["meeting_id"] for row in listed.json()["meetings"]] == [
            original,
            second_meeting.json()["meeting_id"],
        ]


def test_a_document_uploaded_after_a_restart_does_not_collide_with_an_earlier_one(
    database: str,
) -> None:
    """The document id counter has the same hole meetings had, and it 500s.

    `reference_documents` is durable and `next_document_id` was not, so a
    restarted service minted `doc-1` again — and unlike a meeting, which was
    quietly overwritten, the table's primary key refuses it. The upload fails
    with a `UNIQUE constraint` 500, which is the first thing a returning
    operator does on the screen the guide sends them to.
    """

    with client_for(database) as first:
        engagement_id = _engagement(first, "Northwind Logistics")
        uploaded = first.post(
            f"/api/engagements/{engagement_id}/documents",
            files={"file": ("Scoping deck.pdf", b"%PDF-1.4 fake body", "application/pdf")},
            data={"status": "ground truth"},
        )
        assert uploaded.status_code == 201, uploaded.text
        original = uploaded.json()["document_id"]

    with client_for(database) as second:
        again = second.post(
            f"/api/engagements/{engagement_id}/documents",
            files={"file": ("Throughput study.pdf", b"%PDF-1.4 second body", "application/pdf")},
            data={"status": "hypothesis"},
        )
        assert again.status_code == 201, again.text
        assert again.json()["document_id"] != original

        # And the first one is still itself, not the second wearing its id.
        listed = second.get(f"/api/engagements/{engagement_id}/documents")
        assert listed.status_code == 200, listed.text
        assert [(row["document_id"], row["name"]) for row in listed.json()["documents"]] == [
            (original, "Scoping deck.pdf"),
            (again.json()["document_id"], "Throughput study.pdf"),
        ]


def test_the_engagement_list_keeps_creation_order_across_a_restart(database: str) -> None:
    """A restart must not reorder the list an operator navigates by.

    `engagement_ids` only holds what the running process minted, so ordering
    on it put the engagement created a minute ago ahead of every engagement
    that came before it.
    """

    with client_for(database) as first:
        older = _engagement(first, "Northwind Logistics")

    with client_for(database) as second:
        newer = _engagement(second, "Harbourline Ferries")

        response = second.get("/api/engagements")

        assert response.status_code == 200, response.text
        assert [row["engagement_id"] for row in response.json()["items"]] == [older, newer]


# ── What the operator typed, which nothing can rebuild ────────────────────
#
# `models.py` scoped durability to "an engagement's memory" and left the rest
# in memory as "per-run pipeline output ... rebuilt from the transcript on
# demand". That reasoning does not hold for these two: a reference document and
# a vocabulary term are *input an operator typed*, no transcript reconstructs
# them, and a live run proved the cost — a restart came back with 0 documents
# and 0 vocabulary against engagements that had both, silently.


def test_an_uploaded_document_survives_a_restart(database: str) -> None:
    with client_for(database) as first:
        engagement_id = _engagement(first, "Northwind Logistics")
        uploaded = first.post(
            f"/api/engagements/{engagement_id}/documents",
            files={"file": ("Scoping deck.md", b"Depots confirm rosters by phone.", "text/markdown")},
            data={"status": "ground truth"},
        )
        assert uploaded.status_code == 201, uploaded.text

    with client_for(database) as second:
        listed = second.get(f"/api/engagements/{engagement_id}/documents")
        documents = listed.json()["documents"]

    assert [d["name"] for d in documents] == ["Scoping deck.md"]
    assert documents[0]["status"] == "ground truth"


def test_a_documents_extracted_text_survives_a_restart(database: str) -> None:
    """The list surviving is not enough — the compiler reads the text.

    A document that comes back as a name with no content is worse than one that
    is gone: it looks like preparation that happened, and drafts questions from
    nothing.
    """

    with client_for(database) as first:
        engagement_id = _engagement(first, "Northwind Logistics")
        uploaded = first.post(
            f"/api/engagements/{engagement_id}/documents",
            files={"file": ("Scoping.md", b"Depots confirm rosters by phone.", "text/markdown")},
            data={"status": "ground truth"},
        )
        document_id = uploaded.json()["document_id"]

    second_backend = attach_state_store(Backend(), open_state_store(database))
    assert "Depots confirm rosters by phone." in second_backend.document_texts[document_id]


def test_a_retag_survives_a_restart(database: str) -> None:
    with client_for(database) as first:
        engagement_id = _engagement(first, "Northwind Logistics")
        uploaded = first.post(
            f"/api/engagements/{engagement_id}/documents",
            files={"file": ("Old RFP.md", b"superseded content", "text/markdown")},
            data={"status": "ground truth"},
        )
        first.patch(
            f"/api/documents/{uploaded.json()['document_id']}/status",
            json={"status": "superseded"},
        )

    with client_for(database) as second:
        documents = second.get(f"/api/engagements/{engagement_id}/documents").json()["documents"]

    assert documents[0]["status"] == "superseded"


def test_the_vocabulary_list_survives_a_restart(database: str) -> None:
    with client_for(database) as first:
        engagement_id = _engagement(first, "Northwind Logistics")
        for term, term_type in (("Zephyr WMS", "product_name"), ("TMS", "acronym")):
            added = first.post(
                f"/api/engagements/{engagement_id}/vocabulary",
                json={"term": term, "term_type": term_type},
            )
            assert added.status_code == 201, added.text

    with client_for(database) as second:
        terms = second.get(f"/api/engagements/{engagement_id}/vocabulary").json()["terms"]

    assert [t["term"] for t in terms] == ["Zephyr WMS", "TMS"]
    assert [t["term_type"] for t in terms] == ["product_name", "acronym"]


def test_one_engagements_documents_do_not_leak_into_another(database: str) -> None:
    with client_for(database) as first:
        a = _engagement(first, "Northwind Logistics")
        b = _engagement(first, "Calder & Rowe")
        first.post(
            f"/api/engagements/{a}/documents",
            files={"file": ("A.md", b"a", "text/markdown")},
            data={"status": "ground truth"},
        )

    with client_for(database) as second:
        assert len(second.get(f"/api/engagements/{a}/documents").json()["documents"]) == 1
        assert second.get(f"/api/engagements/{b}/documents").json()["documents"] == []


def test_documents_and_vocabulary_are_now_continuity_not_scratch() -> None:
    backend = attach_state_store(Backend(), open_state_store("sqlite://"))

    assert isinstance(backend.engagement_documents, DurableMapping)
    assert isinstance(backend.engagement_vocabulary, DurableMapping)
    assert isinstance(backend.document_texts, DurableMapping)


# ── Which database, and how an operator changes it ────────────────────────


def test_with_nothing_configured_the_data_lives_in_a_local_sqlite_file(monkeypatch, tmp_path):
    """The default is a file, because the desktop product has no database server."""
    from app.persistence.store import resolve_database_url

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ELICTA_STATE_DIR", str(tmp_path))

    resolved = resolve_database_url()

    assert resolved.startswith("sqlite:///")
    assert resolved.endswith("state.db")


def test_the_environment_can_point_it_somewhere_else(monkeypatch, tmp_path):
    from app.persistence.store import resolve_database_url

    monkeypatch.setenv("ELICTA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", "postgresql://elicta:pw@db.internal:5432/elicta")

    assert resolve_database_url() == "postgresql://elicta:pw@db.internal:5432/elicta"


def test_a_url_saved_in_settings_wins_over_the_environment(monkeypatch, tmp_path):
    """Same precedence as every other setting: what somebody chose beats a fallback."""
    from app.persistence.store import resolve_database_url

    monkeypatch.setenv("ELICTA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", "postgresql://elicta:pw@from-env/elicta")

    resolved = resolve_database_url("postgresql://elicta:pw@from-settings/elicta")

    assert "from-settings" in resolved


def test_the_async_driver_marker_is_stripped_whichever_way_it_arrived(monkeypatch, tmp_path):
    """`DATABASE_URL` is documented with `+asyncpg`; these collections are not async."""
    from app.persistence.store import resolve_database_url

    monkeypatch.setenv("ELICTA_STATE_DIR", str(tmp_path))

    assert "+asyncpg" not in resolve_database_url("postgresql+asyncpg://e:pw@h/db")


def test_a_database_url_is_shown_back_without_its_password():
    """It is a credential, and the settings API never returns one."""
    from app.persistence.store import redact_database_url

    shown = redact_database_url("postgresql://elicta:hunter2@db.internal:5432/elicta")

    assert "hunter2" not in shown
    assert "elicta@db.internal:5432/elicta" in shown


def test_a_sqlite_path_is_shown_as_it_is_because_it_hides_nothing():
    from app.persistence.store import redact_database_url

    assert redact_database_url("sqlite:////var/lib/elicta/state.db") == (
        "sqlite:////var/lib/elicta/state.db"
    )


def test_something_unparseable_is_not_echoed_back_in_case_it_holds_a_password():
    from app.persistence.store import redact_database_url

    assert "hunter2" not in redact_database_url("not a url at all hunter2")


# ── Soft delete: removed from view, kept in the database ──────────────────
#
# Deletion in a product that records client meetings is not a tidy-up button.
# Marking rather than erasing keeps the decision reversible and leaves the
# harder question — whether a real erasure should also destroy recordings,
# consent records and artifacts — open rather than answered by accident.


def _rows_in(database: str, table: str) -> int:
    import sqlite3

    return sqlite3.connect(database.removeprefix("sqlite:///")).execute(
        f"select count(*) from {table}"
    ).fetchone()[0]


def test_a_deleted_engagement_leaves_the_list(database: str) -> None:
    with client_for(database) as first:
        keep = _engagement(first, "Northwind Logistics")
        drop = _engagement(first, "Mistake Ltd")

        assert first.delete(f"/api/engagements/{drop}").status_code == 204

        listed = first.get("/api/engagements").json()
        assert [e["engagement_id"] for e in listed["items"]] == [keep]
        assert listed["total"] == 1


def test_a_deleted_engagement_stays_gone_after_a_restart(database: str) -> None:
    with client_for(database) as first:
        drop = _engagement(first, "Mistake Ltd")
        first.delete(f"/api/engagements/{drop}")

    with client_for(database) as second:
        assert second.get("/api/engagements").json()["items"] == []


def test_a_deleted_engagement_is_still_in_the_database(database: str) -> None:
    """The whole point of soft: it is recoverable, and an audit can still see it."""

    with client_for(database) as first:
        drop = _engagement(first, "Mistake Ltd")
        first.delete(f"/api/engagements/{drop}")

    assert _rows_in(database, "engagements") == 1


def test_deleting_something_that_was_never_there_is_not_found(database: str) -> None:
    with client_for(database) as client:
        assert client.delete("/api/engagements/eng-nope").status_code == 404


def _a_document(client: TestClient, engagement_id: str, name: str) -> str:
    uploaded = client.post(
        f"/api/engagements/{engagement_id}/documents",
        files={"file": (name, b"some content", "text/markdown")},
        data={"status": "ground truth"},
    )
    assert uploaded.status_code == 201, uploaded.text
    return uploaded.json()["document_id"]


def test_a_deleted_document_leaves_the_list_and_stays_gone(database: str) -> None:
    with client_for(database) as first:
        engagement_id = _engagement(first, "Northwind Logistics")
        keep = _a_document(first, engagement_id, "Keep.md")
        drop = _a_document(first, engagement_id, "Drop.md")

        assert first.delete(f"/api/documents/{drop}").status_code == 204

    with client_for(database) as second:
        documents = second.get(f"/api/engagements/{engagement_id}/documents").json()["documents"]

    assert [d["document_id"] for d in documents] == [keep]


def test_adding_a_document_after_a_delete_does_not_resurrect_it(database: str) -> None:
    """The trap that makes soft delete quietly not work.

    The document list is rewritten whole on every change, and the rewrite used
    to delete every row for the engagement first. A soft-deleted row would be
    swept away by the next upload — the mark survives one write and not two.
    """

    with client_for(database) as first:
        engagement_id = _engagement(first, "Northwind Logistics")
        drop = _a_document(first, engagement_id, "Drop.md")
        first.delete(f"/api/documents/{drop}")
        _a_document(first, engagement_id, "Later.md")

    with client_for(database) as second:
        names = [
            d["name"]
            for d in second.get(f"/api/engagements/{engagement_id}/documents").json()["documents"]
        ]

    assert names == ["Later.md"]
    # Still on disk: the soft-deleted row plus the new one.
    assert _rows_in(database, "reference_documents") == 2


def test_a_deleted_documents_text_stops_feeding_the_compiler(database: str) -> None:
    """A document removed from the list must not still shape the questions."""

    with client_for(database) as first:
        engagement_id = _engagement(first, "Northwind Logistics")
        drop = _a_document(first, engagement_id, "Drop.md")
        first.delete(f"/api/documents/{drop}")

    backend = attach_state_store(Backend(), open_state_store(database))
    assert drop not in backend.document_texts


def test_a_deleted_vocabulary_term_leaves_the_list_and_stays_gone(database: str) -> None:
    with client_for(database) as first:
        engagement_id = _engagement(first, "Northwind Logistics")
        for term, kind in (("Zephyr WMS", "product_name"), ("Typo", "acronym")):
            first.post(
                f"/api/engagements/{engagement_id}/vocabulary",
                json={"term": term, "term_type": kind},
            )
        terms = first.get(f"/api/engagements/{engagement_id}/vocabulary").json()["terms"]
        typo = next(t["term_id"] for t in terms if t["term"] == "Typo")

        deleted = first.delete(f"/api/engagements/{engagement_id}/vocabulary/{typo}")
        assert deleted.status_code == 204, deleted.text

    with client_for(database) as second:
        remaining = second.get(f"/api/engagements/{engagement_id}/vocabulary").json()["terms"]

    assert [t["term"] for t in remaining] == ["Zephyr WMS"]
    assert _rows_in(database, "vocabulary_terms") == 2


def test_a_deleted_engagement_takes_its_documents_out_of_view(database: str) -> None:
    with client_for(database) as first:
        engagement_id = _engagement(first, "Mistake Ltd")
        _a_document(first, engagement_id, "Attached.md")
        first.delete(f"/api/engagements/{engagement_id}")

        assert first.get(f"/api/engagements/{engagement_id}/documents").status_code == 404


def test_a_database_written_before_a_column_existed_still_opens(tmp_path) -> None:
    """Upgrading must not brick an existing file.

    `metadata.create_all()` creates missing *tables* and never missing
    *columns*, so adding one to a model left every existing `state.db` failing
    on the first query — "no such column: engagements.deleted_at" — with the
    operator's engagements still sitting in the file, unreadable. Alembic
    covers the PostgreSQL deployment; the file the desktop product makes for
    itself has to catch up on open.
    """

    import sqlite3

    database = f"sqlite:///{tmp_path / 'state.db'}"
    with client_for(database) as first:
        _engagement(first, "Northwind Logistics")

    # Wind the file back to before the column was added.
    with sqlite3.connect(tmp_path / "state.db") as connection:
        connection.execute("ALTER TABLE engagements DROP COLUMN deleted_at")

    with client_for(database) as second:
        listed = second.get("/api/engagements")

    assert listed.status_code == 200, listed.text
    assert [e["client_organisation"] for e in listed.json()["items"]] == [
        "Northwind Logistics"
    ]


def test_the_expected_languages_survive_a_restart(database: str, monkeypatch) -> None:
    """Derived once, when the engagement is created — so it has to be kept.

    `derive_and_persist_expected_languages` runs on creation and nothing runs it
    again. Holding the result in memory meant the panel's language strip worked
    until the service restarted and then went quiet for every existing
    engagement, with no way to get it back short of re-creating the client.

    The `engagements` table has carried the column since its first revision.
    """

    # The stream holds its connection open for minutes in a deployment. Read
    # to the end here, so the window is shortened the way a deployment behind
    # a short-lived proxy would shorten it.
    monkeypatch.setenv("ELICTA_SESSION_STREAM_HOLD_SECONDS", "0.02")

    with client_for(database) as first:
        created = first.post(
            "/api/engagements",
            json={
                "client_organisation": "Northwind Logistics",
                "sector": "Freight",
                "commercial_context": "Discovery with the Shenzhen depot team",
            },
        )
        engagement_id = created.json()["engagement_id"]
        meeting = first.post(
            "/api/meetings",
            json={"engagement_id": engagement_id, "capture_mode": "line-in"},
        )
        assert meeting.status_code == 201, meeting.text
        meeting_id = meeting.json()["meeting_id"]

    with client_for(database) as second:
        with second.stream("GET", f"/api/meetings/{meeting_id}/session/stream") as response:
            body = "".join(response.iter_text())

    assert '"language": "zh"' in body or '"language":"zh"' in body, (
        f"the second process lost the derived languages: {body!r}"
    )


def _bank_on_disk(database: str, *candidates: object) -> str:
    """An engagement with a compiled bank already stored against it.

    The Analyst pass that would normally produce one is not what these two
    tests are about — the edit that follows it is, and that goes over HTTP
    like everything else here. Seeding through the durable mapping is the
    storage API, not a shortcut around it.
    """

    with client_for(database) as client:
        engagement_id = _engagement(client, "Northgate Chilled Logistics")

    store = open_state_store(database)
    attach_state_store(Backend(), store).compiled_candidates[engagement_id] = list(candidates)
    store.close()
    return engagement_id


def _served_bank(client: TestClient, engagement_id: str) -> dict[str, dict]:
    response = client.get(f"/api/engagements/{engagement_id}/bank")
    assert response.status_code == 200, response.text
    return {
        candidate["id"]: candidate
        for section in response.json()["sections"]
        for candidate in section["candidates"]
    }


def test_a_pruned_candidate_stays_pruned_across_a_restart(database: str) -> None:
    """Pruning is the operator's judgement, and it was being kept in RAM.

    `candidates` had no `pruned` column, so the flag had nowhere to go: the
    PATCH answered 200, the screen redrew, and the next restart handed back a
    bank with the whole review undone. A pruned question is also promised to
    stay pruned in every later meeting, which a flag that does not survive the
    process cannot do.
    """

    from app.modules.compiler.api.models import BankCandidate

    engagement_id = _bank_on_disk(
        database,
        BankCandidate(id="c-1", template_section="Performance", phrasing="How fast?", priority=1),
        BankCandidate(
            id="c-2", template_section="Performance", phrasing="Which systems?", priority=1
        ),
    )

    with client_for(database) as first:
        pruned = first.patch("/api/bank/candidates/c-1", json={"pruned": True})
        assert pruned.status_code == 200, pruned.text

    with client_for(database) as second:
        served = _served_bank(second, engagement_id)
        assert served["c-1"]["pruned"] is True
        assert served["c-2"]["pruned"] is False


def test_a_reordered_candidate_keeps_its_new_priority_across_a_restart(database: str) -> None:
    """`update_candidate` wrote into the list, never through the mapping.

    `DurableMapping` persists on `__setitem__` alone, and the edit was
    `candidates[index] = updated` — a mutation of the list *inside* the
    mapping. Memory and the database diverged silently, every write returning
    200, and the loss only showed up on the next restart.
    """

    from app.modules.compiler.api.models import BankCandidate

    engagement_id = _bank_on_disk(
        database,
        BankCandidate(id="c-1", template_section="Performance", phrasing="How fast?", priority=1),
        BankCandidate(
            id="c-2", template_section="Performance", phrasing="Which systems?", priority=3
        ),
    )

    with client_for(database) as first:
        moved = first.patch("/api/bank/candidates/c-2", json={"priority": 1})
        assert moved.status_code == 200, moved.text

    with client_for(database) as second:
        assert _served_bank(second, engagement_id)["c-2"]["priority"] == 1


def test_a_deleted_candidate_does_not_come_back_after_a_restart(database: str) -> None:
    """`delete_candidate` had `update_candidate`'s bug, one line differently.

    `del candidates[index]` mutates the list inside the mapping, so the
    deletion never reached the table either. A question removed from the bank
    reappeared at the next restart, which is worse than the prune case: the
    operator has no reason to look for it again.
    """

    from app.modules.compiler.api.models import BankCandidate

    engagement_id = _bank_on_disk(
        database,
        BankCandidate(id="c-1", template_section="Performance", phrasing="How fast?", priority=1),
        BankCandidate(
            id="c-2", template_section="Performance", phrasing="Which systems?", priority=1
        ),
    )

    with client_for(database) as first:
        removed = first.delete("/api/bank/candidates/c-1")
        assert removed.status_code == 204, removed.text

    with client_for(database) as second:
        assert set(_served_bank(second, engagement_id)) == {"c-2"}


def test_a_database_written_before_a_not_null_column_existed_still_opens(tmp_path) -> None:
    """The catch-up skipped exactly the kind of column that needed it.

    `_add_missing_columns` refused any column declared `NOT NULL`, reasoning
    that a schema fixer able to retype or drop is more dangerous than the
    problem it solves. That is true of retyping and dropping, and not of
    adding a `NOT NULL` column that carries a default: it cannot lose a row
    and cannot change one. `candidates.pruned` is the first such column, and
    without this every existing `state.db` fails on "no such column:
    candidates.pruned" with the operator's whole bank sitting in the file,
    unreadable.
    """

    import sqlite3

    from app.modules.compiler.api.models import BankCandidate

    database = f"sqlite:///{tmp_path / 'state.db'}"
    engagement_id = _bank_on_disk(
        database,
        BankCandidate(id="c-1", template_section="Performance", phrasing="How fast?", priority=1),
    )

    # Wind the file back to before the column was added.
    with sqlite3.connect(tmp_path / "state.db") as connection:
        connection.execute("ALTER TABLE candidates DROP COLUMN pruned")

    with client_for(database) as second:
        assert set(_served_bank(second, engagement_id)) == {"c-1"}


def _client_with_consent_model(database: str, engagement_id: str, model: str) -> TestClient:
    """An app whose engagement asks for consent at every meeting.

    The per-engagement override is the product's own mechanism and simply has
    no screen yet, so a test sets it directly. Without it every engagement
    takes the engagement-level default, the gate answers `not_required`, and a
    test of confirmation durability would pass while proving nothing.
    """

    from app.core.consent.models import ConsentModel

    backend = attach_state_store(Backend(), open_state_store(database))
    backend.consent_models[engagement_id] = ConsentModel(model)
    return TestClient(build_app(backend))


def test_a_consent_confirmation_survives_a_restart(database: str) -> None:
    """Who disclosed the recording is a legal record, not a cache.

    It lived in a plain list on `Backend` with no table behind it, so the
    answer to "did we have permission for this?" was only ever as durable as
    the process. A restart mid-engagement lost it, and nothing rebuilds a
    consent confirmation — unlike a document, it cannot be retyped from a
    source, because it describes a moment.
    """

    with client_for(database) as first:
        written = first.post(
            "/api/meetings/meeting-1/consent-confirmation",
            json={"confirmed_by": "Dana Whitfield, COO"},
        )
        assert written.status_code == 201, written.text
        confirmed_at = written.json()["confirmed_at"]

    with client_for(database) as second:
        read = second.get("/api/meetings/meeting-1/consent-record")
        assert read.status_code == 200, read.text
        assert read.json()["confirmed_by"] == "Dana Whitfield, COO"
        # The moment itself, not merely that some confirmation happened.
        assert read.json()["confirmed_at"] == confirmed_at


def test_the_gate_stays_open_after_a_restart(database: str) -> None:
    """The record and the gate are one event, and both have to survive.

    Keeping the durable record and the gate's own answer in separate fields is
    what once let consent be captured perfectly and read back as never given.
    A restart that restored the record and not the gate would be that same
    failure, arriving a different way.
    """

    with _client_with_consent_model(database, "eng-1", "per_meeting") as first:
        gate = first.get("/api/meetings/meeting-1/consent-gate?engagement_id=eng-1")
        assert gate.json()["status"] == "awaiting_confirmation"
        first.post(
            "/api/meetings/meeting-1/consent-confirmation",
            json={"confirmed_by": "Dana Whitfield, COO"},
        )
        assert (
            first.get("/api/meetings/meeting-1/consent-gate?engagement_id=eng-1").json()["status"]
            == "confirmed"
        )

    with _client_with_consent_model(database, "eng-1", "per_meeting") as second:
        reopened = second.get("/api/meetings/meeting-1/consent-gate?engagement_id=eng-1")
        assert reopened.json()["status"] == "confirmed", (
            "the gate shut again on restart, so the meeting would be asked to "
            "confirm consent it has already given"
        )


# ── The record path's own artifacts ──────────────────────────────────────
#
# These three were classified as pipeline output "rebuilt from the transcript",
# which two of them are and the third describes audio NFR-2.4 has already
# destroyed. Nothing rebuilds any of them, so the classification meant "lost on
# restart" — and because all three key on the session, they were lost together:
# a meeting that really was recorded came back answering 404 on its transcripts,
# its divergences and its destruction record at once, which is exactly what a
# meeting that never happened answers.


def _recorded_session(client: TestClient) -> str:
    """A meeting whose audio has been through both record-path engines."""

    engagement_id = _engagement(client, "Ridgeway Health")
    meeting = client.post(
        "/api/meetings",
        json={"engagement_id": engagement_id, "capture_mode": "record"},
    )
    assert meeting.status_code == 201, meeting.text
    session_id = meeting.json()["meeting_id"]

    transcribed = client.post(
        f"/api/sessions/{session_id}/record-path-transcript",
        json={"audio_ref": f"audio://{session_id}"},
    )
    assert transcribed.status_code == 201, transcribed.text
    return session_id


def test_a_record_path_transcript_survives_a_restart(database: str) -> None:
    """The one artifact that cannot be regenerated.

    NFR-2.4 destroys the raw audio the moment transcription and diarization
    finish, so a lost transcript is not a lost cache — it is the only surviving
    account of what was said in the meeting.
    """

    with client_for(database) as first:
        session_id = _recorded_session(first)
        engines = [entry["engine"] for entry in first.get(
            f"/api/sessions/{session_id}/record-path-transcript"
        ).json()]

    with client_for(database) as second:
        response = second.get(f"/api/sessions/{session_id}/record-path-transcript")

    assert response.status_code == 200, response.text
    assert [entry["engine"] for entry in response.json()] == engines
    # Not merely a list of engine names: the words have to come back too, or
    # the row is a claim that a recording was transcribed with nothing in it.
    assert all(entry["segments"] for entry in response.json())


def test_the_divergences_survive_a_restart(database: str) -> None:
    """Read through the meeting-keyed route the recording screen actually uses."""

    with client_for(database) as first:
        session_id = _recorded_session(first)
        before = first.get(f"/api/meetings/{session_id}/record/divergences")
        assert before.status_code == 200, before.text

    with client_for(database) as second:
        response = second.get(f"/api/meetings/{session_id}/record/divergences")

    assert response.status_code == 200, response.text
    assert response.json()["spans"] == before.json()["spans"]
    assert response.json()["reference_engine"] == before.json()["reference_engine"]


def test_the_audio_destruction_record_survives_a_restart(database: str) -> None:
    """The evidence for a privacy control, which is the whole point of having it.

    Seeded through the collection rather than driven over HTTP: destruction is
    gated on diarization as well as transcription, so producing one for real
    needs the whole debrief pipeline and its engines. What is being proved here
    is the round trip through the file, and the seeding still fails on the old
    code — the field was a list, which has no place to put a session key.
    """

    from app.modules.debrief.pipeline.models import (
        AudioDestructionEvent,
        AudioDestructionStatus,
    )

    moment = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    first = attach_state_store(Backend(), open_state_store(database))
    first.audio_destruction_events["session-9"] = [
        AudioDestructionEvent(
            session_id="session-9",
            audio_ref="audio://session-9",
            status=AudioDestructionStatus.FAILED,
            requested_at=moment,
            completed_at=moment,
            error="the object store refused the delete",
        ),
        # The retry, which is what describes where the audio stands now. Both
        # are kept: the pair is the record, and a failure that vanished behind
        # its retry would hide that the audio was ever at risk.
        AudioDestructionEvent(
            session_id="session-9",
            audio_ref="audio://session-9",
            status=AudioDestructionStatus.COMPLETE,
            requested_at=moment,
            completed_at=moment,
        ),
    ]

    with client_for(database) as second:
        response = second.get("/api/sessions/session-9/audio-destruction")

    assert response.status_code == 200, response.text
    # The latest attempt, not the first.
    assert response.json()["status"] == "complete"
    assert (
        len(attach_state_store(Backend(), open_state_store(database)).audio_destruction_events[
            "session-9"
        ])
        == 2
    ), "the failed attempt is part of the record and must not be dropped"


def test_a_never_recorded_meeting_still_404s_after_a_restart(database: str) -> None:
    """The mirror, and the one that keeps the fix honest.

    Durability that answered 200 for a meeting nobody recorded would be worse
    than losing the data: the recording screen reads these three 404s as "not
    recorded yet", and a stored empty would read as a comparison that ran.
    """

    with client_for(database) as first:
        engagement_id = _engagement(first, "Ridgeway Health")
        meeting = first.post(
            "/api/meetings",
            json={"engagement_id": engagement_id, "capture_mode": "record"},
        )
        session_id = meeting.json()["meeting_id"]

    with client_for(database) as second:
        assert second.get(
            f"/api/sessions/{session_id}/record-path-transcript"
        ).status_code == 404
        assert second.get(
            f"/api/meetings/{session_id}/record/divergences"
        ).status_code == 404
        assert second.get(
            f"/api/sessions/{session_id}/audio-destruction"
        ).status_code == 404


def test_the_record_path_artifacts_are_now_continuity_not_scratch() -> None:
    backend = attach_state_store(Backend(), open_state_store("sqlite://"))

    assert isinstance(backend.record_path_transcripts, DurableMapping)
    assert isinstance(backend.session_alignments, DurableMapping)
    assert isinstance(backend.audio_destruction_events, DurableMapping)


def _engagement_with_a_meeting(client: TestClient) -> tuple[str, str]:
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Northwind Logistics",
            "sector": "Freight and warehousing",
            "commercial_context": "Fleet visibility programme",
        },
    )
    assert created.status_code == 201, created.text
    engagement_id = created.json()["engagement_id"]

    meeting = client.post(
        "/api/meetings",
        json={"engagement_id": engagement_id, "capture_mode": "live"},
    )
    assert meeting.status_code == 201, meeting.text
    return engagement_id, meeting.json()["meeting_id"]


def test_a_deleted_meeting_stays_deleted_after_a_restart(database: str) -> None:
    """A removal that only emptied a dict would come back on the next launch."""

    with client_for(database) as first:
        engagement_id, meeting_id = _engagement_with_a_meeting(first)
        assert first.delete(f"/api/meetings/{meeting_id}").status_code == 204

    with client_for(database) as second:
        listed = second.get(f"/api/engagements/{engagement_id}/meetings")
        assert listed.status_code == 200, listed.text
        assert listed.json()["meetings"] == []
        assert second.get(f"/api/meetings/{meeting_id}").status_code == 404


def test_a_deleted_meeting_does_not_hand_its_id_to_the_next_one(database: str) -> None:
    """`next_meeting_id` counts rows, so the marked row has to still be counted.

    This is the reason the removal marks rather than erases at the storage
    layer as well as the API one: an erased row lowers the high-water mark, and
    the next launch mints an id that is not free.
    """

    with client_for(database) as first:
        engagement_id, meeting_id = _engagement_with_a_meeting(first)
        assert first.delete(f"/api/meetings/{meeting_id}").status_code == 204

    with client_for(database) as second:
        replacement = second.post(
            "/api/meetings",
            json={"engagement_id": engagement_id, "capture_mode": "record"},
        )
        assert replacement.status_code == 201, replacement.text
        assert replacement.json()["meeting_id"] != meeting_id


def test_a_meeting_can_be_renamed_after_a_restart(database: str) -> None:
    """PATCH guarded on a dict only creation writes, so a rename 404'd after a launch.

    The durable record of which engagement a meeting belongs to is the meeting's
    own row; `meeting_engagement_ids` is a same-process shortcut to it.
    """

    with client_for(database) as first:
        _, meeting_id = _engagement_with_a_meeting(first)

    with client_for(database) as second:
        renamed = second.patch(
            f"/api/meetings/{meeting_id}",
            json={"session_purpose": "Validate the depot scheduling scope"},
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["session_purpose"] == "Validate the depot scheduling scope"


def test_a_renamed_meeting_keeps_its_purpose_across_a_restart(database: str) -> None:
    """The rename is what the operator typed, so it belongs on disk, not in a dict."""

    with client_for(database) as first:
        engagement_id, meeting_id = _engagement_with_a_meeting(first)
        renamed = first.patch(
            f"/api/meetings/{meeting_id}",
            json={"session_purpose": "Validate the depot scheduling scope"},
        )
        assert renamed.status_code == 200, renamed.text

    with client_for(database) as second:
        listed = second.get(f"/api/engagements/{engagement_id}/meetings")
        assert listed.status_code == 200, listed.text
        purposes = {row["meeting_id"]: row["session_purpose"] for row in listed.json()["meetings"]}
        assert purposes[meeting_id] == "Validate the depot scheduling scope"


def test_a_deleted_meeting_cannot_be_renamed_after_a_restart(database: str) -> None:
    """The marked row is still on disk; it must not be reachable through PATCH."""

    with client_for(database) as first:
        _, meeting_id = _engagement_with_a_meeting(first)
        assert first.delete(f"/api/meetings/{meeting_id}").status_code == 204

    with client_for(database) as second:
        renamed = second.patch(
            f"/api/meetings/{meeting_id}",
            json={"session_purpose": "Should not resurrect it"},
        )
        assert renamed.status_code == 404, renamed.text
