"""Sanity checks on the fully assembled app that no single-router test can see.

Several modules mount routers under the same prefix (`/api/meetings`:
consent, debrief/session, debrief/api, debrief/artifacts, asr-record,
compiler/bank; `/api/sessions`: asr-record, debrief/pipeline,
debrief/artifacts). Nothing
guarantees that stays collision-free as modules are added independently —
this is the one place that mounts all of them together and checks, by
reading the same OpenAPI schema a real client would see.
"""

from __future__ import annotations

from fastapi import FastAPI

EXPECTED_PATHS_AND_METHODS = {
    ("/api/meetings/{meeting_id}/consent-gate", "get"),
    ("/api/meetings/{meeting_id}/consent-confirmation", "post"),
    ("/api/audit/egress", "get"),
    ("/api/engagements", "post"),
    ("/api/engagements/{engagement_id}", "patch"),
    ("/api/sessions/{session_id}/record-path-transcript", "get"),
    ("/api/sessions/{session_id}/record-path-transcript", "post"),
    ("/api/sessions/{session_id}/record-path-alignment", "get"),
    ("/api/meetings/{meeting_id}/record/transcribe", "post"),
    ("/api/meetings/{meeting_id}/record/divergences", "get"),
    ("/api/sessions/{session_id}/citations", "post"),
    ("/api/meetings/{meeting_id}/debrief/start", "post"),
    ("/api/meetings/{meeting_id}/debrief/message", "post"),
    ("/api/meetings/{meeting_id}/artifacts", "get"),
    ("/api/artifacts/{artifact_id}", "get"),
    ("/api/engagements/{engagement_id}/prd", "post"),
    ("/api/engagements/{engagement_id}/requirements-state", "get"),
    ("/api/sessions/{session_id}/project-brief", "get"),
    ("/api/sessions/{session_id}/decision-log", "get"),
    ("/api/sessions/{session_id}/open-questions", "get"),
    ("/api/sessions/{session_id}/follow-up-email", "get"),
    ("/api/meetings/{meeting_id}/bank", "get"),
    ("/api/replay/runs/{run_id}/ratings", "post"),
    ("/api/replay/runs/{run_id}", "get"),
}


def test_every_documented_endpoint_is_reachable_with_no_path_collisions(app: FastAPI) -> None:
    schema = app.openapi()

    found = {
        (path, method)
        for path, methods_by_verb in schema["paths"].items()
        for method in methods_by_verb
    }

    assert found == EXPECTED_PATHS_AND_METHODS
