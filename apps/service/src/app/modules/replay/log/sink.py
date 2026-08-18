"""Hand-off point out of the replay suggestion-log package.

`SuggestionLogSink` persists one `SuggestionLogRow` to the `suggestion_log`
table per candidate evaluation (architecture section 9: "Suggestion log:
{timestamp, trigger, candidate, score, would_surface}"). Left as a
`Protocol` so the storage binding (the real `suggestion_log` table) stays
out of this package — whoever wires the replay pipeline to a real database
supplies the implementation, raising `SuggestionLogError` on failure.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.modules.replay.log.models import SuggestionLogRow


@runtime_checkable
class SuggestionLogSink(Protocol):
    def record(self, row: SuggestionLogRow) -> None: ...
