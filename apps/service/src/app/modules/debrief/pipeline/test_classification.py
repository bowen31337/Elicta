"""Tests for the section-classification orchestrator and coverage-slot fill_state derivation (PRD FR-8.2)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.modules.debrief.pipeline.classification import (
    compute_slot_fill_states,
    normalize_section_key,
    run_section_classification,
)
from app.modules.debrief.pipeline.models import (
    UNCLASSIFIED_SECTION_KEY,
    ClassifiedUtterance,
    FillState,
    SectionClassificationStatus,
    SessionSectionClassification,
    TemplateSection,
    TranslatedUtterance,
)

FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_cleaned_utterances() -> list[TranslatedUtterance]:
    return [
        TranslatedUtterance(
            utterance_id="utt-1",
            session_id="session-1",
            start_seconds=0.0,
            end_seconds=1.0,
            speaker_tag="alice",
            verbatim_text="um we need the thing by friday",
            cleaned_text="We need the thing by Friday.",
            original_language="en",
        ),
        TranslatedUtterance(
            utterance_id="utt-2",
            session_id="session-1",
            start_seconds=1.0,
            end_seconds=2.0,
            speaker_tag="bob",
            verbatim_text="yeah that works for me",
            cleaned_text="Yeah, that works for me.",
            original_language="en",
        ),
    ]


def make_slots() -> list[TemplateSection]:
    return [
        TemplateSection(key="timeline", title="Timeline"),
        TemplateSection(key="budget", title="Budget"),
    ]


def make_classify(section_keys: list[str], *, fail: bool = False):
    async def classify(
        session_id: str, utterances: list[TranslatedUtterance], slots: list[TemplateSection]
    ) -> list[str]:
        if fail:
            raise RuntimeError("classification vendor timed out")
        return section_keys

    return classify


def test_a_successful_run_classifies_every_utterance_and_fills_its_slot():
    saved: list[SessionSectionClassification] = []

    async def save(record: SessionSectionClassification) -> None:
        saved.append(record)

    utterances = make_cleaned_utterances()
    slots = make_slots()

    result = asyncio.run(
        run_section_classification(
            "session-1",
            utterances,
            slots,
            "classifier-a",
            make_classify(["timeline", "budget"]),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == SectionClassificationStatus.COMPLETE
    assert result.session_id == "session-1"
    assert result.engine == "classifier-a"
    assert [u.section_key for u in result.utterances] == ["timeline", "budget"]
    assert [u.utterance_id for u in result.utterances] == ["utt-1", "utt-2"]
    assert [u.verbatim_text for u in result.utterances] == [u.verbatim_text for u in utterances]
    assert [u.cleaned_text for u in result.utterances] == [u.cleaned_text for u in utterances]
    assert [u.original_language for u in result.utterances] == [u.original_language for u in utterances]
    assert [u.translated_text for u in result.utterances] == [u.translated_text for u in utterances]
    assert all(u.session_id == "session-1" for u in result.utterances)

    slots_by_key = {slot.section_key: slot for slot in result.slots}
    assert slots_by_key["timeline"].fill_state == FillState.FILLED
    assert slots_by_key["timeline"].utterance_ids == ["utt-1"]
    assert slots_by_key["budget"].fill_state == FillState.FILLED
    assert slots_by_key["budget"].utterance_ids == ["utt-2"]
    assert saved == [result]


def test_an_unrecognized_section_key_is_normalized_to_unclassified_not_left_as_is():
    async def save(record: SessionSectionClassification) -> None:
        pass

    result = asyncio.run(
        run_section_classification(
            "session-1",
            make_cleaned_utterances(),
            make_slots(),
            "classifier-a",
            make_classify(["timeline", "some-made-up-section"]),
            save,
        )
    )

    assert [u.section_key for u in result.utterances] == ["timeline", UNCLASSIFIED_SECTION_KEY]


def test_a_slot_with_no_classified_utterances_is_empty():
    async def save(record: SessionSectionClassification) -> None:
        pass

    result = asyncio.run(
        run_section_classification(
            "session-1",
            make_cleaned_utterances(),
            make_slots(),
            "classifier-a",
            make_classify(["timeline", "timeline"]),
            save,
        )
    )

    slots_by_key = {slot.section_key: slot for slot in result.slots}
    assert slots_by_key["timeline"].fill_state == FillState.FILLED
    assert slots_by_key["timeline"].utterance_ids == ["utt-1", "utt-2"]
    assert slots_by_key["budget"].fill_state == FillState.EMPTY
    assert slots_by_key["budget"].utterance_ids == []


def test_a_failed_classification_run_persists_a_failed_record_with_no_utterances_or_slots():
    saved: list[SessionSectionClassification] = []

    async def save(record: SessionSectionClassification) -> None:
        saved.append(record)

    result = asyncio.run(
        run_section_classification(
            "session-1",
            make_cleaned_utterances(),
            make_slots(),
            "classifier-a",
            make_classify([], fail=True),
            save,
            requested_at=FIXED,
        )
    )

    assert result.status == SectionClassificationStatus.FAILED
    assert result.engine == "classifier-a"
    assert result.utterances == []
    assert result.slots == []
    assert result.error == "classification vendor timed out"
    assert result.requested_at == FIXED
    assert saved == [result]


def test_a_mismatched_section_key_count_persists_a_failed_record_instead_of_raising():
    async def save(record: SessionSectionClassification) -> None:
        pass

    result = asyncio.run(
        run_section_classification(
            "session-1",
            make_cleaned_utterances(),
            make_slots(),
            "classifier-a",
            make_classify(["timeline"]),
            save,
        )
    )

    assert result.status == SectionClassificationStatus.FAILED
    assert result.utterances == []
    assert result.slots == []
    assert result.error is not None


def test_no_utterances_persists_a_complete_record_with_every_slot_empty():
    async def save(record: SessionSectionClassification) -> None:
        pass

    result = asyncio.run(
        run_section_classification(
            "session-1", [], make_slots(), "classifier-a", make_classify([]), save
        )
    )

    assert result.status == SectionClassificationStatus.COMPLETE
    assert result.utterances == []
    assert all(slot.fill_state == FillState.EMPTY for slot in result.slots)
    assert {slot.section_key for slot in result.slots} == {"timeline", "budget"}


def test_requested_at_defaults_and_completed_at_is_not_before_it():
    async def save(record: SessionSectionClassification) -> None:
        pass

    result = asyncio.run(
        run_section_classification(
            "session-1",
            make_cleaned_utterances(),
            make_slots(),
            "classifier-a",
            make_classify(["timeline", "budget"]),
            save,
        )
    )

    assert result.completed_at >= result.requested_at


def test_compute_slot_fill_states_orders_output_by_the_supplied_slots():
    slots = [
        TemplateSection(key="timeline", title="Timeline"),
        TemplateSection(key="budget", title="Budget"),
    ]
    utterances = [
        ClassifiedUtterance(
            utterance_id="utt-1",
            session_id="session-1",
            start_seconds=0.0,
            end_seconds=1.0,
            speaker_tag="alice",
            verbatim_text="v",
            cleaned_text="c",
            original_language="en",
            section_key="budget",
        )
    ]

    states = compute_slot_fill_states(slots, utterances)

    assert [state.section_key for state in states] == ["timeline", "budget"]
    assert states[0].fill_state == FillState.EMPTY
    assert states[1].fill_state == FillState.FILLED
    assert states[1].utterance_ids == ["utt-1"]


def test_compute_slot_fill_states_ignores_unclassified_utterances():
    slots = [TemplateSection(key="timeline", title="Timeline")]
    utterances = [
        ClassifiedUtterance(
            utterance_id="utt-1",
            session_id="session-1",
            start_seconds=0.0,
            end_seconds=1.0,
            speaker_tag="alice",
            verbatim_text="v",
            cleaned_text="c",
            original_language="en",
            section_key=UNCLASSIFIED_SECTION_KEY,
        )
    ]

    states = compute_slot_fill_states(slots, utterances)

    assert states[0].fill_state == FillState.EMPTY
    assert states[0].utterance_ids == []


def test_normalize_section_key_passes_through_known_keys():
    assert normalize_section_key("timeline", {"timeline", "budget"}) == "timeline"


def test_normalize_section_key_falls_back_to_unclassified_for_unknown_keys():
    assert normalize_section_key("nonsense", {"timeline", "budget"}) == UNCLASSIFIED_SECTION_KEY


def test_a_cross_language_utterances_translation_rides_along_onto_the_classified_utterance():
    async def save(record: SessionSectionClassification) -> None:
        pass

    utterances = [
        TranslatedUtterance(
            utterance_id="utt-1",
            session_id="session-1",
            start_seconds=0.0,
            end_seconds=1.0,
            speaker_tag="alice",
            verbatim_text="necesitamos esto para el viernes",
            cleaned_text="Necesitamos esto para el viernes.",
            original_language="es",
            translated_text="We need this by Friday.",
        )
    ]

    result = asyncio.run(
        run_section_classification(
            "session-1", utterances, make_slots(), "classifier-a", make_classify(["timeline"]), save
        )
    )

    assert result.utterances[0].original_language == "es"
    assert result.utterances[0].translated_text == "We need this by Friday."
