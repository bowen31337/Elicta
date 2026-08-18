"""Recorded-transcript data model for the replay harness (architecture section 9).

Field names mirror the `utterances` table (`speaker_tag`, `start_ms`) so a
transcript loaded from that table needs no translation before replay.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class RecordedUtterance:
    """One utterance from a recorded meeting, keyed to its wall-clock offset
    from the start of that recording."""

    utterance_id: str
    speaker_tag: str
    text: str
    start_ms: int

    def __post_init__(self) -> None:
        if self.start_ms < 0:
            raise ValueError(f"start_ms must be non-negative, got {self.start_ms}")


@dataclass(frozen=True)
class RecordedTranscript:
    """A full recorded meeting: every utterance that will be replayed."""

    utterances: Sequence[RecordedUtterance]

    def ordered_by_offset(self) -> list[RecordedUtterance]:
        """Utterances in replay order.

        `sorted` is stable, so utterances sharing a `start_ms` (cross-talk)
        keep their original relative order rather than being reshuffled.
        """
        return sorted(self.utterances, key=lambda utterance: utterance.start_ms)
