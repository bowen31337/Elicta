"""End-to-end test of the prep journey: create an engagement, upload a ground-truth
reference document, compile the meeting's question bank, and render it as a
reviewable question tree (PRD FR-3.1, FR-3.4, FR-3.7, FR-4.8).

Engagement creation, document upload, and meeting creation all have real HTTP
routers wired in `conftest.py`, so this test drives every one of those stages
through the real HTTP surface via `client`.

Compiling an engagement's *base* candidate set from its reference documents
(`POST /api/engagements/{id}/bank/compile`) has no implementation anywhere in
this codebase yet -- `compiler/bank/recompile.py` and
`compiler/bank/models.py` both say so explicitly, calling that compile step
"out of this feature's footprint", and no document-to-candidate extraction
pipeline exists to back it (`compiler/techniques/models.py`). Per this repo's
existing convention for such gaps (`test_multi_meeting_arc.py` seeds
`backend.meeting_base_candidates` directly rather than inventing a compile
endpoint), this test seeds the compiled candidate set backend expects as a
precondition, standing in for that not-yet-built compile step, and drives
everything downstream of it -- the per-meeting bank recompile -- through the
real `GET /api/meetings/{id}/bank` route.

There is likewise no "reviewable question tree" component anywhere in the
codebase (backend or `apps/desktop`) to assert against directly. What such a
tree would render from is the bank response's flat candidate list grouped by
`template_section`: each section is a branch, each candidate a reviewable
leaf carrying the fields a reviewer needs (`phrasing`, `priority`,
`inherited_from_open_question`). This test asserts the real bank endpoint's
response has exactly that shape.
"""

from __future__ import annotations

from collections import defaultdict

from app.modules.compiler.bank.models import BankCandidate
from conftest import Backend
from fastapi.testclient import TestClient


def _group_by_template_section(candidates: list[dict]) -> dict[str, list[dict]]:
    """The grouping a reviewable question tree would render from: section -> its candidates."""

    sections: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        sections[candidate["template_section"]].append(candidate)
    return dict(sections)


def test_prep_journey_creates_engagement_uploads_ground_truth_and_renders_question_tree(
    client: TestClient, backend: Backend
) -> None:
    # 1. Create the engagement (PRD FR-3.1), over the real HTTP surface.
    response = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Acme Logistics",
            "sector": "manufacturing",
            "commercial_context": "Fixed-bid requirements discovery engagement",
        },
    )
    assert response.status_code == 201
    engagement_id = response.json()["engagement_id"]

    # 2. Upload a ground-truth reference document (PRD FR-3.4), over the real HTTP surface.
    response = client.post(
        f"/api/engagements/{engagement_id}/documents",
        files={
            "file": (
                "scoping-deck.pdf",
                b"%PDF-1.4 current-state scoping deck",
                "application/pdf",
            )
        },
        data={"name": "Current-state scoping deck", "status": "ground truth"},
    )
    assert response.status_code == 201
    document = response.json()
    assert document["status"] == "ground truth"

    response = client.get(f"/api/engagements/{engagement_id}/documents")
    assert response.status_code == 200
    assert [doc["document_id"] for doc in response.json()["documents"]] == [document["document_id"]]

    # 3. Create a meeting under the engagement (PRD FR-3.7), over the real HTTP surface.
    response = client.post(
        "/api/meetings",
        json={"engagement_id": engagement_id, "capture_mode": "live"},
    )
    assert response.status_code == 201
    meeting = response.json()
    meeting_id = meeting["meeting_id"]
    assert meeting["engagement_context"]["client_organisation"] == "Acme Logistics"

    # 4. Compile the bank: seed the base candidate set a real document-to-candidate
    #    compiler would eventually produce from the uploaded ground-truth document
    #    (see module docstring -- that compile step doesn't exist yet). Candidates
    #    span multiple template sections so the recompiled bank has real tree
    #    structure to render.
    backend.meeting_base_candidates[meeting_id] = [
        BankCandidate(id="c-scope-1", template_section="scope", phrasing="What is explicitly out of scope?", priority=1),
        BankCandidate(id="c-scope-2", template_section="scope", phrasing="Which sites does this cover?", priority=2),
        BankCandidate(id="c-timeline-1", template_section="timeline", phrasing="When must this go live?", priority=3),
        BankCandidate(id="c-budget-1", template_section="budget", phrasing="What is the approved budget?", priority=4),
    ]

    # 5. Render the compiled, per-meeting bank through the real recompile route (PRD FR-4.8).
    response = client.get(f"/api/meetings/{meeting_id}/bank")
    assert response.status_code == 200
    bank = response.json()
    assert bank["meeting_id"] == meeting_id

    candidates = bank["candidates"]
    assert [c["id"] for c in candidates] == ["c-scope-1", "c-scope-2", "c-timeline-1", "c-budget-1"]
    assert all(c["inherited_from_open_question"] is False for c in candidates), (
        "a first meeting's bank has no prior open questions to inherit -- every "
        "candidate must render as freshly compiled, not carried forward"
    )

    # 6. The shape a reviewable question tree renders from: sections as branches,
    #    each carrying its candidates ordered by priority, every candidate exposing
    #    the fields a reviewer acts on.
    tree = _group_by_template_section(candidates)
    assert set(tree) == {"scope", "timeline", "budget"}
    assert [c["phrasing"] for c in tree["scope"]] == [
        "What is explicitly out of scope?",
        "Which sites does this cover?",
    ]
    assert [c["priority"] for c in tree["scope"]] == sorted(c["priority"] for c in tree["scope"])
    assert tree["timeline"][0]["phrasing"] == "When must this go live?"
    assert tree["budget"][0]["phrasing"] == "What is the approved budget?"
