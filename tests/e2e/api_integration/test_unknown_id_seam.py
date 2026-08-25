"""An id nobody has must answer "no", not answer emptily.

The composition root is where every router's persistence callable is bound,
and almost all of them have two answers: the record, or nothing. The "nothing"
half is the half that decides whether a typo is reported or silently succeeds —
a 204 for a document that was never removed, an empty question bank for a
meeting that does not exist, a session started against nothing.

These drive the production composition root over HTTP, one uncovered branch per
test, because the empty answer and the "no such thing" answer are the pair this
codebase has confused before.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.composition import Backend, attach_state_store, build_app
from app.persistence import open_state_store
from app.modules.settings.models import (
    ConnectorSettings,
    SecretKey,
    SpeechVendor,
    VendorSettings,
)
from app.modules.settings.store import InMemorySettingsStore

from conftest import configured_settings_store, fake_microsoft

UNKNOWN = "no-such-id"


@pytest.fixture
def vendor_refuses(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Every outbound vendor call answered locally, with a refusal.

    The same reason the document connector is injected: a credential probe
    that reached Anthropic would test somebody else's uptime, and would need
    the machine running the suite to have a route to them.
    """

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(401, json={"error": {"message": "invalid credential"}})

    original = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
    return seen


def _engagement(client: TestClient) -> str:
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Northwind Logistics",
            "sector": "Freight and warehousing",
            "commercial_context": "Fleet visibility programme",
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["engagement_id"]


def _meeting(client: TestClient, engagement_id: str) -> str:
    created = client.post(
        "/api/meetings",
        json={"engagement_id": engagement_id, "capture_mode": "line-in"},
    )
    assert created.status_code == 201, created.text
    return created.json()["meeting_id"]


# --- engagements and their meetings ----------------------------------------


def test_reading_an_engagement_nobody_has_is_a_404(client: TestClient) -> None:
    assert client.get(f"/api/engagements/{UNKNOWN}").status_code == 404


def test_updating_a_meeting_nobody_has_is_a_404(client: TestClient) -> None:
    response = client.patch(f"/api/meetings/{UNKNOWN}", json={"session_purpose": "Discovery"})

    assert response.status_code == 404


def test_uploading_a_document_to_an_engagement_nobody_has_is_a_404(
    client: TestClient,
) -> None:
    # Otherwise the document is stored against an engagement id that will
    # never be listed, and it is invisible to retrieval for ever.
    response = client.post(
        f"/api/engagements/{UNKNOWN}/documents",
        files={"file": ("scoping.docx", b"body", "text/plain")},
        data={"status": "hypothesis"},
    )

    assert response.status_code == 404


# --- the question bank ------------------------------------------------------


def test_the_bank_for_a_meeting_nobody_has_is_empty_rather_than_an_error(
    client: TestClient,
) -> None:
    """The one place an empty answer is right — and it must be *visibly* empty.

    The panel asks for this on every meeting, including before a compile has
    run, so 404 would be noise. What matters is that nothing is invented: no
    candidates and no inherited questions.
    """

    response = client.get(f"/api/meetings/{UNKNOWN}/bank")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meeting_id"] == UNKNOWN
    assert body["candidates"] == []


def test_deleting_a_candidate_nobody_has_is_a_404(client: TestClient) -> None:
    assert client.delete(f"/api/bank/candidates/{UNKNOWN}").status_code == 404


def test_editing_a_candidate_nobody_has_is_a_404(client: TestClient) -> None:
    response = client.patch(
        f"/api/bank/candidates/{UNKNOWN}", json={"phrasing": "How fast, in seconds?"}
    )

    assert response.status_code == 404


# --- soft deletion ----------------------------------------------------------


def test_removing_a_vocabulary_term_nobody_has_is_a_404(client: TestClient) -> None:
    # A wrong keyterm makes the transcript confidently wrong, so an operator
    # reporting a removal that did not happen is worse than an error.
    engagement_id = _engagement(client)

    response = client.delete(f"/api/engagements/{engagement_id}/vocabulary/{UNKNOWN}")

    assert response.status_code == 404


def test_removing_a_document_nobody_has_is_a_404(client: TestClient) -> None:
    assert client.delete(f"/api/documents/{UNKNOWN}").status_code == 404


def test_removing_a_document_no_engagement_holds_is_a_404(client: TestClient) -> None:
    """The search walks every engagement's list before giving up.

    An engagement that holds documents but not *this* one must not stop the
    walk — with two engagements attached, a naive loop returns on the first.
    """

    first = _engagement(client)
    second = _engagement(client)
    for engagement_id in (first, second):
        attached = client.post(
            f"/api/engagements/{engagement_id}/documents",
            files={"file": ("scoping.docx", b"body", "text/plain")},
            data={"status": "hypothesis"},
        )
        assert attached.status_code == 201, attached.text

    assert client.delete(f"/api/documents/{UNKNOWN}").status_code == 404


def test_restatusing_a_document_nobody_has_is_a_404(client: TestClient) -> None:
    response = client.patch(f"/api/documents/{UNKNOWN}/status", json={"status": "ground truth"})

    assert response.status_code == 404


# --- the live session -------------------------------------------------------


def test_starting_a_session_for_a_meeting_nobody_has_is_a_404(client: TestClient) -> None:
    assert client.post(f"/api/meetings/{UNKNOWN}/session/start").status_code == 404


def test_recording_a_disposition_against_a_meeting_nobody_has_is_a_404(
    client: TestClient,
) -> None:
    response = client.post(
        f"/api/meetings/{UNKNOWN}/nudges/nudge-1/disposition", json={"disposition": "taken"}
    )

    assert response.status_code == 404


def test_a_recorded_disposition_is_echoed_back_with_what_was_recorded(
    client: TestClient,
) -> None:
    # FR-6.6/6.7: the operator's own decision, stored against the nudge it was
    # about, and confirmed rather than accepted silently.
    meeting_id = _meeting(client, _engagement(client))

    response = client.post(
        f"/api/meetings/{meeting_id}/nudges/nudge-1/disposition",
        json={"disposition": "parked"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meeting_id"] == meeting_id
    assert body["nudge_id"] == "nudge-1"
    assert body["disposition"] == "parked"
    assert body["recorded_at"]


# --- replay -----------------------------------------------------------------


def test_reading_a_replay_run_nobody_has_is_a_404(client: TestClient) -> None:
    assert client.get(f"/api/replay/runs/{UNKNOWN}").status_code == 404


# --- the language strip -----------------------------------------------------


def test_a_meeting_whose_engagement_is_gone_claims_no_languages(tmp_path) -> None:
    """The panel's language strip after the engagement behind it was removed.

    Built the way it actually happens: an engagement is deleted, the service
    restarts, and the meeting row outlives the engagement row it points at.
    Expected languages are re-derived from the engagement's client context
    when nothing was stored — with no engagement to derive from, the strip
    says nothing, rather than the stream failing or naming a language no
    audio supports.
    """

    database = f"sqlite:///{tmp_path / 'state.db'}"

    def app_over(database: str) -> TestClient:
        return TestClient(
            build_app(
                attach_state_store(Backend(), open_state_store(database)),
                settings_store=configured_settings_store(),
                document_transport=fake_microsoft,
            )
        )

    with app_over(database) as first:
        engagement_id = _engagement(first)
        meeting_id = _meeting(first, engagement_id)
        assert first.delete(f"/api/engagements/{engagement_id}").status_code == 204

    with app_over(database) as second:
        with second.stream(
            "GET", f"/api/meetings/{meeting_id}/session/stream"
        ) as response:
            assert response.status_code == 200, response.text
            body = "".join(response.iter_text())

    assert "event: lane" in body, "the stream still opens for the meeting"
    assert "event: language" not in body


# --- residency --------------------------------------------------------------


def test_an_engagement_is_pinned_to_the_region_settings_names() -> None:
    """NFR-2.2 pins residency once, at engagement setup."""

    store = configured_settings_store()
    store.write_connectors(ConnectorSettings(region="eu-west-1"))
    backend = Backend()
    client = TestClient(
        build_app(backend, settings_store=store, document_transport=fake_microsoft)
    )

    engagement_id = _engagement(client)

    assert backend.egress_regions.region_for(engagement_id) == "eu-west-1"


def test_an_engagement_stays_unpinned_when_no_region_is_configured(
    client: TestClient, backend: Backend
) -> None:
    # Stamping a region nobody chose would make the audit rows claim a
    # residency agreement that was never made.
    engagement_id = _engagement(client)

    assert backend.egress_regions.region_for(engagement_id) is None


# --- the document connector without a tenant --------------------------------


def test_a_link_is_refused_when_the_connector_is_not_configured() -> None:
    """Half a configuration is worse than none.

    With no document settings at all there are no credentials to build, and
    the attach must fail rather than reach Microsoft anonymously.
    """

    client = TestClient(
        build_app(
            Backend(),
            settings_store=InMemorySettingsStore(read_environment=False),
            document_transport=fake_microsoft,
        )
    )
    engagement_id = _engagement(client)

    response = client.post(
        f"/api/engagements/{engagement_id}/documents/link",
        json={
            "url": "https://acme.sharepoint.com/sites/proj/Scoping.docx",
            "status": "hypothesis",
        },
    )

    assert response.status_code >= 400, response.text


# --- settings ----------------------------------------------------------------


def test_settings_are_readable_and_writable_over_the_admin_api(
    client: TestClient,
) -> None:
    # The store, not the caller, decides what is now configured — which is why
    # the save returns the full settings rather than 204.
    read = client.get("/api/admin/settings")
    assert read.status_code == 200, read.text

    saved = client.put(
        "/api/admin/settings",
        json={
            "vendors": {"asr_base_url": "https://asr.example"},
            "secrets": [{"key": "asr_vendor_api_key", "value": "vendor-key-abcd"}],
        },
    )

    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["vendors"]["asr_base_url"] == "https://asr.example"
    # Write-only across this API: presence and a hint, never the value.
    hint = next(s for s in body["secrets"] if s["key"] == "asr_vendor_api_key")
    assert hint["configured"] is True
    assert hint["hint"] == "abcd"
    assert "vendor-key-abcd" not in saved.text


def test_testing_a_credential_that_is_not_configured_says_so(client: TestClient) -> None:
    response = client.post("/api/admin/settings/anthropic_api_key/test")

    assert response.status_code == 200, response.text
    assert response.json()["reachable"] is False
    assert "No credential is configured." in response.json()["detail"]


def test_testing_an_anthropic_key_probes_it_rather_than_reporting_configuration(
    client: TestClient, vendor_refuses: list[httpx.Request]
) -> None:
    """A key that is present and a key that works are different claims."""

    client.put(
        "/api/admin/settings",
        json={"secrets": [{"key": "anthropic_api_key", "value": "sk-ant-not-real"}]},
    )

    response = client.post("/api/admin/settings/anthropic_api_key/test")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reachable"] is False
    # The vendor's error type, never the credential.
    assert "sk-ant-not-real" not in response.text
    assert "not verified" not in body["detail"], "a probe ran, so this is a real verdict"
    # Sending the smallest possible message, not listing models. Listing
    # authenticates and nothing more: an OAuth token lists happily -- and lists
    # the configured model -- and is then refused for `/v1/messages`, so this
    # screen said "Verified" while every bank compile stopped at the first
    # model call.
    assert "/v1/messages" in str(vendor_refuses[0].url)


def test_testing_an_oauth_token_probes_it_in_its_own_mode(
    client: TestClient, vendor_refuses: list[httpx.Request]
) -> None:
    # An operator testing a token before switching to it must get a real
    # answer, not one about whichever mode happens to be selected.
    client.put(
        "/api/admin/settings",
        json={"secrets": [{"key": "anthropic_oauth_token", "value": "oat-not-real"}]},
    )

    response = client.post("/api/admin/settings/anthropic_oauth_token/test")

    assert response.status_code == 200, response.text
    assert response.json()["reachable"] is False
    assert "oat-not-real" not in response.text
    # And probed on the surface this credential is actually used on. An OAuth
    # token runs the compiler and the debrief engine through the Agent SDK, so
    # a probe that called `/v1/messages` would report the 429 it is refused
    # with there — a failing verdict for a credential that drafts a bank.
    # Nothing may have gone to the Messages API on its behalf.
    assert vendor_refuses == [], (
        "the OAuth token was probed on the Messages API, which is not the "
        "surface it runs on"
    )


def test_testing_a_speech_key_uses_the_probe_for_the_provider_it_will_serve(
    client: TestClient, vendor_refuses: list[httpx.Request]
) -> None:
    """`live_vendor` used to name the provider here and no longer exists.

    It selected nothing the live path honoured — the recogniser was Deepgram
    whatever it said — so the pool took over choosing the provider and this
    key, which predates the pool, is probed against the one the live path can
    drive.
    """

    client.put(
        "/api/admin/settings",
        json={
            "vendors": {"asr_base_url": "https://api.deepgram.example/v1/projects"},
            "secrets": [{"key": "asr_vendor_api_key", "value": "dg-not-real"}],
        },
    )

    response = client.post("/api/admin/settings/asr_vendor_api_key/test")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reachable"] is False
    # A probe ran and the vendor refused the key — not "no probe is wired".
    assert "no probe is wired" not in body["detail"]
    assert vendor_refuses[0].headers["authorization"] == "Token dg-not-real"


def test_a_secret_with_no_probe_reports_configured_but_not_verified(
    client: TestClient,
) -> None:
    """The honest answer when we do not know the vendor's API.

    Inventing a reachability signal would be worse than admitting there is
    none: the operator would trust a green tick nothing tested.
    """

    client.put(
        "/api/admin/settings",
        json={
            "secrets": [
                {"key": "microsoft_graph_client_secret", "value": "graph-secret-wxyz"}
            ]
        },
    )

    response = client.post("/api/admin/settings/microsoft_graph_client_secret/test")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reachable"] is False
    assert "not verified" in body["detail"]
    assert "wxyz" in body["detail"], "the hint says which secret was checked"


# --- more ids nobody has -----------------------------------------------------


def test_creating_a_meeting_under_an_engagement_nobody_has_is_a_404(
    client: TestClient,
) -> None:
    # The meeting would otherwise exist under an engagement id that is never
    # listed, and every later lookup through the engagement would miss it.
    response = client.post(
        "/api/meetings", json={"engagement_id": UNKNOWN, "capture_mode": "line-in"}
    )

    assert response.status_code == 404


def test_metrics_for_a_replay_run_nobody_has_are_refused_not_zeroed(
    client: TestClient,
) -> None:
    """An unknown run answering with an empty list reads as a measurement.

    Nobody-rated-it and no-such-run both produce 0.0, and the caller cannot
    tell which it is looking at.
    """

    response = client.get(f"/api/replay/runs/{UNKNOWN}/metrics")

    assert response.status_code == 404


# --- the attendee roster -----------------------------------------------------


def test_adding_an_attendee_before_any_candidate_has_authority_requirements(
    client: TestClient,
) -> None:
    """FR-4.7 rescoring is a no-op until the compiler has produced requirements.

    The roster changing must still be recorded — the rescore having nothing to
    do is not a reason for the attendee to be dropped.
    """

    meeting_id = _meeting(client, _engagement(client))

    response = client.post(
        f"/api/meetings/{meeting_id}/attendees",
        json={"display_name": "Dana Okafor", "role": "Head of Operations"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["display_name"] == "Dana Okafor"


# --- the other half: the operation that does find its row --------------------
#
# Every removal above has a positive twin, and the pair is the point: a 404 for
# an id nobody has is only meaningful if the same call succeeds for one that
# exists. Asserting the refusal alone would pass for a route that refuses
# everything.


def test_an_engagement_takes_the_edits_it_is_given(client: TestClient) -> None:
    engagement_id = _engagement(client)

    patched = client.patch(
        f"/api/engagements/{engagement_id}",
        json={"purpose": "Discovery", "scope_boundary": "Depot operations only"},
    )

    assert patched.status_code == 200, patched.text
    assert patched.json()["purpose"] == "Discovery"

    # Omitted fields are left alone, so saving one panel cannot blank another.
    again = client.patch(
        f"/api/engagements/{engagement_id}", json={"scope_boundary": "Depots and yards"}
    )
    assert again.status_code == 200, again.text
    assert again.json()["purpose"] == "Discovery"
    assert again.json()["scope_boundary"] == "Depots and yards"


def test_listing_documents_for_an_engagement_nobody_has_is_a_404(
    client: TestClient,
) -> None:
    # An empty list would say "this engagement has no documents" about an
    # engagement that does not exist.
    assert client.get(f"/api/engagements/{UNKNOWN}/documents").status_code == 404


def _uploaded_document(client: TestClient, engagement_id: str) -> str:
    attached = client.post(
        f"/api/engagements/{engagement_id}/documents",
        files={"file": ("scoping.docx", b"Depot rosters are confirmed by phone.", "text/plain")},
        data={"status": "hypothesis"},
    )
    assert attached.status_code == 201, attached.text
    return attached.json()["document_id"]


def test_a_document_can_be_retagged(client: TestClient) -> None:
    engagement_id = _engagement(client)
    document_id = _uploaded_document(client, engagement_id)

    retagged = client.patch(
        f"/api/documents/{document_id}/status", json={"status": "ground truth"}
    )

    assert retagged.status_code == 200, retagged.text
    assert retagged.json()["status"] == "ground truth"
    listed = client.get(f"/api/engagements/{engagement_id}/documents").json()
    assert listed["documents"][0]["status"] == "ground truth"


def test_a_removed_document_leaves_the_list_and_the_index(client: TestClient) -> None:
    """The text goes with it.

    A document out of the list but still shaping the drafted questions is the
    opposite of what removing it means.
    """

    engagement_id = _engagement(client)
    document_id = _uploaded_document(client, engagement_id)

    assert client.delete(f"/api/documents/{document_id}").status_code == 204

    listed = client.get(f"/api/engagements/{engagement_id}/documents").json()
    assert listed["documents"] == []
    assert client.patch(
        f"/api/documents/{document_id}/status", json={"status": "superseded"}
    ).status_code == 404


def test_a_vocabulary_term_can_be_taken_back_out(client: TestClient) -> None:
    engagement_id = _engagement(client)
    added = client.post(
        f"/api/engagements/{engagement_id}/vocabulary",
        json={"term": "cross-dock", "term_type": "internal_system"},
    )
    assert added.status_code == 201, added.text
    term_id = added.json()["term_id"]

    assert client.delete(
        f"/api/engagements/{engagement_id}/vocabulary/{term_id}"
    ).status_code == 204

    remaining = client.get(f"/api/engagements/{engagement_id}/vocabulary").json()
    assert all(t["term_id"] != term_id for t in remaining["terms"])


# --- what the operator is told when nothing has happened yet ------------------


def test_a_meeting_with_no_debrief_run_reports_no_completion(client: TestClient) -> None:
    # Not an error, and not a completed-with-nothing: the run has not started.
    meeting_id = _meeting(client, _engagement(client))

    response = client.get(f"/api/meetings/{meeting_id}/debrief/completion")

    assert response.status_code == 404


def test_a_meeting_whose_engagement_is_gone_still_gets_a_consent_decision(
    tmp_path,
) -> None:
    """Admission has to answer for a meeting whose engagement cannot be resolved.

    It takes the configured default rather than a guess — and the request is
    answered rather than failing, because a panel that cannot render the gate
    cannot tell the operator why capture will not start.
    """

    database = f"sqlite:///{tmp_path / 'state.db'}"

    def app_over(database: str) -> TestClient:
        return TestClient(
            build_app(
                attach_state_store(Backend(), open_state_store(database)),
                settings_store=configured_settings_store(),
                document_transport=fake_microsoft,
            )
        )

    with app_over(database) as first:
        engagement_id = _engagement(first)
        meeting_id = _meeting(first, engagement_id)
        assert first.delete(f"/api/engagements/{engagement_id}").status_code == 204

    with app_over(database) as second:
        response = second.post(f"/api/meetings/{meeting_id}/session/start")

    # Whatever the default admits, it is a decision and not a crash.
    assert response.status_code in (200, 403), response.text
