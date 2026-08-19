"""The post-meeting debrief pipeline (architecture §7), assembled end to end.

Every stage below existed, was unit-tested, and had no caller. Each one is
written to be driven by "whoever wires the app factory", and nothing did, so
the eight steps §7 describes never ran as a sequence. This module is that
caller.

The order is not a choice made here — §7 fixes it, and two constraints in
particular are load-bearing:

* **Steps 1–3 are ordered deliberately.** Transcription and diarization are
  the only steps that need audio, and the discard happens the moment the last
  of them finishes (ADR-008, NFR-2.4). Steps 4–8 operate on text only, which
  is why this module never receives an `audio_ref` for them.
* **Every artifact derives from the record path, never the live transcript**
  (FR-2.7). The utterances entering step 4 come from diarization over the
  record-path output, not from the live stream that drove nudges.

Stages fail closed. Each underlying stage already converts an engine
exception into a persisted `FAILED` record rather than raising, so this
orchestrator checks each result and stops the chain at the first
non-complete stage: running section classification over a failed translation
would produce confident nonsense, and persisting it would be worse than
stopping.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.modules.debrief.artifacts.matrix import build_coverage_matrix
from app.modules.debrief.artifacts.state import merge_requirements_state_forward
from app.modules.debrief.pipeline.bmad_analyst import run_bmad_analyst_chain
from app.modules.debrief.pipeline.citations import persist_citation_table
from app.modules.debrief.pipeline.classification import run_section_classification
from app.modules.debrief.pipeline.cleaning import run_transcript_cleaning
from app.modules.debrief.pipeline.service import run_diarization
from app.modules.debrief.pipeline.translation import run_transcript_translation

from .engines import DebriefEngines

_COMPLETE = "complete"


def _completed(record: Any) -> bool:
    """Whether a stage record reached its own COMPLETE state.

    Each stage owns a distinct status enum with the same two members, so this
    compares values rather than importing seven enums to say one thing.
    """

    return getattr(getattr(record, "status", None), "value", None) == _COMPLETE


@dataclass(frozen=True)
class DebriefSinks:
    """Where each stage's durable record goes.

    One callable per stage rather than one store, mirroring how every stage
    takes its own `save`: the pipeline never assumes the records share a
    backend, and a caller can persist the coverage matrix somewhere different
    from the transcripts without touching this module.
    """

    save_diarization: Callable[[Any], Awaitable[None]]
    save_cleaning: Callable[[Any], Awaitable[None]]
    save_translation: Callable[[Any], Awaitable[None]]
    save_classification: Callable[[Any], Awaitable[None]]
    save_chain: Callable[[Any], Awaitable[None]]
    save_citation_table: Callable[[Any], Awaitable[None]]
    save_coverage_matrix: Callable[[Any], Awaitable[None]]
    save_requirements_state: Callable[[Any], Awaitable[None]]
    cite_filled_slot: Callable[..., Awaitable[Any]]
    on_audio_released: Callable[[str], Awaitable[Any]] | None = None


@dataclass
class DebriefPipelineRun:
    """What actually happened, stage by stage.

    `stopped_at` names the first stage that did not complete, so a caller can
    tell "the model is not configured" from "the pipeline never ran" without
    reconstructing it from persisted records.
    """

    session_id: str
    diarization: Any = None
    cleaning: Any = None
    translation: Any = None
    classification: Any = None
    coverage_matrix: Any = None
    analyst_chain: Any = None
    citation_table: Any = None
    requirements_state: Any = None
    stages_completed: list[str] = field(default_factory=list)
    stopped_at: str | None = None

    @property
    def complete(self) -> bool:
        return self.stopped_at is None


async def run_debrief_pipeline(
    session_id: str,
    *,
    engagement_id: str,
    audio_ref: str,
    spans: list[Any],
    template_sections: list[Any],
    document_language: str,
    previous_state: Any,
    engines: DebriefEngines,
    sinks: DebriefSinks,
) -> DebriefPipelineRun:
    """Run architecture §7 steps 2–8 for one session.

    Step 1 (record-path transcription) is driven by the record-path router
    and is this function's precondition: `spans` is its output. Step 3 (audio
    discard) is delegated to `sinks.on_audio_released`, because the discard
    gate also depends on record-path completion, which lives outside this
    pipeline.
    """

    run = DebriefPipelineRun(session_id=session_id)

    # --- §7.2 full diarization and attribution (FR-7.2) ------------------
    run.diarization = await run_diarization(
        session_id, audio_ref, spans, engines.name, engines.diarize, sinks.save_diarization
    )
    if not _completed(run.diarization):
        run.stopped_at = "diarization"
        return run
    run.stages_completed.append("diarization")

    # --- §7.3 audio discarded (NFR-2.4, ADR-008) -------------------------
    # Both stages that needed the audio have now finished, so it goes. Steps
    # 4-8 below touch text only.
    if sinks.on_audio_released is not None:
        await sinks.on_audio_released(session_id)
        run.stages_completed.append("audio-discard")

    # --- §7.4 transcript cleanup -----------------------------------------
    run.cleaning = await run_transcript_cleaning(
        session_id,
        run.diarization.utterances,
        engines.name,
        engines.clean,
        sinks.save_cleaning,
    )
    if not _completed(run.cleaning):
        run.stopped_at = "cleaning"
        return run
    run.stages_completed.append("cleaning")

    # --- §7.4 translation, retaining the original (FR-2.19) --------------
    run.translation = await run_transcript_translation(
        session_id,
        run.cleaning.utterances,
        document_language,
        engines.name,
        engines.translate,
        sinks.save_translation,
    )
    if not _completed(run.translation):
        run.stopped_at = "translation"
        return run
    run.stages_completed.append("translation")

    # --- §7.5 section classification, backfilling coverage ---------------
    run.classification = await run_section_classification(
        session_id,
        run.translation.utterances,
        template_sections,
        engines.name,
        engines.classify,
        sinks.save_classification,
    )
    if not _completed(run.classification):
        run.stopped_at = "classification"
        return run
    run.stages_completed.append("classification")

    run.coverage_matrix = await build_coverage_matrix(
        run.classification, sinks.cite_filled_slot, sinks.save_coverage_matrix
    )
    run.stages_completed.append("coverage-matrix")

    # --- §7.6 BMAD analyst chain -----------------------------------------
    run.analyst_chain = await run_bmad_analyst_chain(
        session_id,
        run.classification.utterances,
        engines.name,
        engines.run_chain,
        sinks.save_chain,
    )
    if not _completed(run.analyst_chain) or run.analyst_chain.artifacts is None:
        run.stopped_at = "analyst-chain"
        return run
    run.stages_completed.append("analyst-chain")

    # --- §7.7 citation binding (FR-8.7/8.7a) ------------------------------
    run.citation_table = await persist_citation_table(
        session_id, run.analyst_chain.artifacts, sinks.save_citation_table
    )
    run.stages_completed.append("citation-binding")

    # --- §7.8 state merge, carried to the next meeting (FR-8.9) ----------
    run.requirements_state = await merge_requirements_state_forward(
        engagement_id,
        previous_state,
        run.coverage_matrix,
        run.analyst_chain.artifacts,
        sinks.save_requirements_state,
    )
    run.stages_completed.append("state-merge")

    return run
