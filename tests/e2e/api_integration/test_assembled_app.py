"""Sanity checks on the fully assembled app that no single-router test can see.

Several modules mount routers under the same prefix (`/api/meetings`:
consent, debrief/session, debrief/api, debrief/artifacts, asr-record,
compiler/bank, engagement/meetings; `/api/sessions`: asr-record,
debrief/pipeline, debrief/artifacts; `/api/engagements`: engagement/api,
engagement/documents, debrief/artifacts). Nothing guarantees that stays
collision-free as modules are added independently — this is the one place
that mounts all of them together and checks, by reading the same OpenAPI
schema a real client would see.
"""

from __future__ import annotations

from fastapi import FastAPI

EXPECTED_PATHS_AND_METHODS = {
    ("/api/admin/settings", "get"),
    ("/api/admin/settings", "put"),
    ("/api/admin/settings/{key}/test", "post"),
    ("/api/admin/settings/speech/credentials", "post"),
    ("/api/admin/settings/speech/credentials/{credential_id}", "patch"),
    ("/api/admin/settings/speech/credentials/{credential_id}", "delete"),
    ("/api/admin/settings/speech/credentials/{credential_id}/test", "post"),
    ("/api/admin/settings/speech/policy", "put"),
    ("/api/artifacts/{artifact_id}", "get"),
    ("/api/audit/egress", "get"),
    ("/api/bank/candidates/{candidate_id}", "delete"),
    ("/api/bank/candidates/{candidate_id}", "patch"),
    # Soft deletes: the row is marked, not erased, so a removal stays
    # reversible and an audit can still see what was there.
    ("/api/documents/{document_id}", "delete"),
    ("/api/documents/{document_id}/status", "patch"),
    ("/api/engagements", "get"),
    ("/api/engagements", "post"),
    ("/api/engagements/{engagement_id}", "delete"),
    ("/api/engagements/{engagement_id}", "get"),
    ("/api/engagements/{engagement_id}", "patch"),
    ("/api/engagements/{engagement_id}/bank", "get"),
    ("/api/engagements/{engagement_id}/bank/compile", "get"),
    ("/api/engagements/{engagement_id}/bank/compile", "post"),
    ("/api/engagements/{engagement_id}/documents", "get"),
    ("/api/engagements/{engagement_id}/documents", "post"),
    ("/api/engagements/{engagement_id}/documents/link", "post"),
    ("/api/engagements/{engagement_id}/meetings", "get"),
    ("/api/engagements/{engagement_id}/prd", "post"),
    ("/api/engagements/{engagement_id}/requirements-state", "get"),
    ("/api/engagements/{engagement_id}/state", "get"),
    ("/api/engagements/{engagement_id}/vocabulary", "get"),
    ("/api/engagements/{engagement_id}/vocabulary", "post"),
    ("/api/engagements/{engagement_id}/vocabulary/{term_id}", "delete"),
    ("/api/meetings", "post"),
    ("/api/meetings/{meeting_id}", "get"),
    ("/api/meetings/{meeting_id}", "delete"),
    ("/api/meetings/{meeting_id}", "patch"),
    ("/api/meetings/{meeting_id}/artifacts", "get"),
    ("/api/meetings/{meeting_id}/attendees", "post"),
    ("/api/meetings/{meeting_id}/attendees/from-calendar-invite", "post"),
    ("/api/meetings/{meeting_id}/bank", "get"),
    ("/api/meetings/{meeting_id}/consent-confirmation", "post"),
    ("/api/meetings/{meeting_id}/consent-gate", "get"),
    ("/api/meetings/{meeting_id}/consent-record", "get"),
    ("/api/meetings/{meeting_id}/debrief/completion", "get"),
    ("/api/meetings/{meeting_id}/debrief/message", "post"),
    ("/api/meetings/{meeting_id}/debrief/start", "post"),
    ("/api/meetings/{meeting_id}/debrief/run", "post"),
    ("/api/meetings/{meeting_id}/nudges/{nudge_id}/disposition", "post"),
    ("/api/meetings/{meeting_id}/record/divergences", "get"),
    ("/api/meetings/{meeting_id}/record/transcribe", "post"),
    ("/api/meetings/{meeting_id}/session/start", "post"),
    ("/api/meetings/{meeting_id}/session/stream", "get"),
    ("/api/meetings/{meeting_id}/live/utterance", "post"),
    ("/api/threads/{thread_id}/park", "post"),
    ("/api/threads/{thread_id}/go-deeper", "post"),
    ("/api/sessions/live", "get"),
    ("/api/meetings/{meeting_id}/slow-lane/tick", "post"),
    # One print per operator, so one resource: read its status, replace it,
    # remove it. The status never returns the embedding itself.
    ("/api/operator/voiceprint", "get"),
    ("/api/operator/voiceprint", "post"),
    ("/api/operator/voiceprint", "delete"),
    ("/api/replay/runs", "get"),
    ("/api/replay/runs", "post"),
    ("/api/replay/runs/{run_id}", "get"),
    ("/api/replay/runs/{run_id}/metrics", "get"),
    ("/api/replay/runs/{run_id}/ratings", "post"),
    ("/api/sessions/{session_id}/audio-chunk", "post"),
    ("/api/sessions/{session_id}/audio-destruction", "get"),
    ("/api/sessions/{session_id}/citations", "post"),
    ("/api/sessions/{session_id}/decision-log", "get"),
    ("/api/sessions/{session_id}/follow-up-email", "get"),
    ("/api/sessions/{session_id}/open-questions", "get"),
    ("/api/sessions/{session_id}/project-brief", "get"),
    ("/api/sessions/{session_id}/recording", "post"),
    ("/api/sessions/{session_id}/record-path-alignment", "get"),
    ("/api/sessions/{session_id}/record-path-transcript", "get"),
    ("/api/sessions/{session_id}/record-path-transcript", "post"),
}


def test_every_documented_endpoint_is_reachable_with_no_path_collisions(app: FastAPI) -> None:
    schema = app.openapi()

    found = {
        (path, method)
        for path, methods_by_verb in schema["paths"].items()
        for method in methods_by_verb
    }

    assert found == EXPECTED_PATHS_AND_METHODS
