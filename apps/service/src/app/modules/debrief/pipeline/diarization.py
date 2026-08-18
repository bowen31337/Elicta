"""Tags each transcript span with the speaker diarization attributes most of its duration to (PRD FR-7.2).

Tagging here is time-based, the same style `asr-record/alignment.py` uses to
reconcile two engines' output: a diarization engine returns `SpeakerTurn`s
(continuous stretches of retained audio attributed to one speaker) on a
timeline that rarely lines up exactly with the transcript's own span
boundaries, so a transcript span is tagged with whichever speaker's turns
overlap it for the most total time rather than requiring an exact boundary
match.
"""

from __future__ import annotations

from .models import UNKNOWN_SPEAKER_TAG, SpeakerTurn, TranscriptSpan


def _overlap_seconds(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


def tag_span_speaker(span: TranscriptSpan, turns: list[SpeakerTurn]) -> str:
    """Return the speaker_tag whose turns overlap `span` for the most total time.

    Falls back to `UNKNOWN_SPEAKER_TAG` rather than `None` when no diarized
    turn overlaps the span at all — PRD FR-7.2 requires every utterance to
    persist a speaker_tag, so "diarization couldn't attribute this" must
    still be a persisted value. Ties in total overlap are broken by whichever
    speaker's turns started earliest, so tagging a given span and turn set is
    deterministic rather than depending on dict iteration order.
    """

    overlap_by_speaker: dict[str, float] = {}
    earliest_start_by_speaker: dict[str, float] = {}

    for turn in turns:
        overlap = _overlap_seconds(span.start_seconds, span.end_seconds, turn.start_seconds, turn.end_seconds)
        if overlap <= 0:
            continue
        overlap_by_speaker[turn.speaker_tag] = overlap_by_speaker.get(turn.speaker_tag, 0.0) + overlap
        earliest_start_by_speaker[turn.speaker_tag] = min(
            earliest_start_by_speaker.get(turn.speaker_tag, turn.start_seconds), turn.start_seconds
        )

    if not overlap_by_speaker:
        return UNKNOWN_SPEAKER_TAG

    return max(
        overlap_by_speaker,
        key=lambda tag: (overlap_by_speaker[tag], -earliest_start_by_speaker[tag]),
    )


def tag_spans_with_speakers(spans: list[TranscriptSpan], turns: list[SpeakerTurn]) -> list[str]:
    """Tag every span in `spans` in order, returning one speaker_tag per span."""

    return [tag_span_speaker(span, turns) for span in spans]
