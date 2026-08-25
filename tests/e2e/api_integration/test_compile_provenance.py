"""Where each drafted question came from, carried to the screen.

The Analyst emits `source_doc` and `authority_match` alongside every
candidate, and the extraction pass has already validated its citations
against the document's own text. All of it was dropped at the API boundary:
the wire model and the `candidates` table kept six fields, and provenance was
not among them.

The cost is a judgement the operator cannot make. A bank drafted from a rich
scoping pack and one reasoned out of a one-page invite arrive looking
identical — same shape, same count, same confidence — and "can I trust these
164 questions" has no answer on the screen that shows them. It is also what
makes pruning a read of every row rather than a filter.

Nothing here asks the model for anything new. The work was done, validated,
and thrown away one layer from the person who needed it.
"""

from __future__ import annotations

import contextlib

from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.modules.compiler.agent.models import BmadAnalystPassOutput
from app.orchestration.engines import CompilerEngines
from tests.e2e.api_integration.conftest import configured_settings_store


def _candidate(index: int, *, source: str | None) -> dict:
    return {
        "template_section": "volumes",
        "trigger_types": ["unquantified-quantity"],
        "phrasing": f"How many consignments a month, question {index}?",
        "stub": f"How many, exactly? ({index})",
        "lang": "en",
        "priority": index,
        "source_doc": source,
        "authority_match": ["ground truth"] if source else [],
    }


async def _ok(*_args, **_kwargs):
    return type("Out", (), {"claims": [], "candidates": []})()


def _engines() -> CompilerEngines:
    """Ten candidates: half grounded in a document, half reasoned."""

    async def submit_batch(*_args, **_kwargs):
        return "batch-1"

    async def fetch_batch(_job_id: str):
        from app.modules.compiler.agent.models import AnalystBatchResult

        return [
            AnalystBatchResult(
                custom_id="eng-1",
                output=BmadAnalystPassOutput(
                    candidates=[
                        _candidate(i + 1, source="depot-pack.pdf" if i % 2 == 0 else None)
                        for i in range(10)
                    ]
                ),
            )
        ]

    return CompilerEngines(
        name="test-provider",
        extract=_ok,
        structure=_ok,
        submit_batch=submit_batch,
        fetch_batch=fetch_batch,
    )


@contextlib.contextmanager
def _client():
    app = build_app(
        Backend(),
        compiler_engines=_engines(),
        settings_store=configured_settings_store(),
    )
    with TestClient(app) as client:
        yield client


def _compiled_bank(client: TestClient) -> list[dict]:
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Northwind Logistics",
            "sector": "Freight",
            "commercial_context": "Depot scheduling rebuild",
        },
    )
    engagement_id = created.json()["engagement_id"]
    client.post(f"/api/engagements/{engagement_id}/bank/compile")
    for _ in range(400):
        body = client.get(f"/api/engagements/{engagement_id}/bank/compile").json()
        if body.get("state") != "running":
            break
    bank = client.get(f"/api/engagements/{engagement_id}/bank").json()
    return [c for section in bank["sections"] for c in section["candidates"]]


def test_a_question_says_which_document_it_came_from() -> None:
    grounded = [c for c in _compiled_bank_cached() if c.get("source_doc")]

    assert grounded, "no candidate carried its source document"
    assert grounded[0]["source_doc"] == "depot-pack.pdf"


def test_a_question_the_analyst_reasoned_out_says_so_by_carrying_nothing() -> None:
    """Absence is the signal, and it has to survive the boundary as absence.

    A default of "unknown" or an empty string would make an inferred question
    indistinguishable from one whose provenance was lost in transit, which is
    the failure this is fixing rather than a new way to have it.
    """

    inferred = [c for c in _compiled_bank_cached() if not c.get("source_doc")]

    assert inferred, "every candidate claimed a source; the split is not surviving"
    assert inferred[0]["source_doc"] is None


def test_the_authority_the_question_rests_on_travels_with_it() -> None:
    """`ground truth` and `hypothesis` are not the same standing to ask from."""

    grounded = [c for c in _compiled_bank_cached() if c.get("source_doc")]

    assert grounded[0]["authority_match"] == ["ground truth"]


_CACHE: list[dict] = []


def _compiled_bank_cached() -> list[dict]:
    """One compile, read by three assertions — it is the same run each asks of."""

    if not _CACHE:
        with _client() as client:
            _CACHE.extend(_compiled_bank(client))
    return _CACHE
