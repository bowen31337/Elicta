"""Nudges package: recording an operator's disposition of a surfaced nudge (PRD FR-6.6/6.7).

Exposes no mounted router -- `build_nudge_disposition_router` needs
`record_disposition` injected first -- so this package is consumed directly
by whoever wires the app factory. `POST
/api/meetings/{meeting_id}/nudges/{nudge_id}/disposition` returns 200 with
the recorded disposition, or 404 if `record_disposition` returns `None` for
an unknown meeting/nudge pair.
"""

from __future__ import annotations

from app.modules.nudges.models import (
    NudgeDispositionRequest,
    NudgeDispositionResponse,
    OperatorNudgeDisposition,
)
from app.modules.nudges.router import RecordDisposition, build_nudge_disposition_router

__all__ = [
    "NudgeDispositionRequest",
    "NudgeDispositionResponse",
    "OperatorNudgeDisposition",
    "RecordDisposition",
    "build_nudge_disposition_router",
]
