"""The post-meeting and compile-time pipelines, driven end to end.

Every stage in both chains was implemented and unit-tested with no caller.
Unit tests could not have caught that: each stage passed in isolation while
the sequence never ran. These drive the assembled chains — the §7 debrief
pipeline and the §3.10 compiler chain — with fake engines standing in for
the inference seams, so the *ordering and threading* are what is under test,
not the model.
"""

from __future__ import annotations

import pytest

from app.modules.compiler.citations.models import ExtractionSourceDocument
from app.modules.debrief.artifacts.models import CoverageCitation
from app.modules.debrief.pipeline.models import (
    BmadAnalystChainOutput,
    BmadDecisionDraft,
    BmadFollowUpEmailDraft,
    BmadOpenQuestionDraft,
    BmadProjectBriefDraft,
    DiarizationOutput,
    SpeakerTurn,
    TemplateSection,
    TranscriptSpan,
    TranslationOutcome,
)
from app.orchestration.compiler import CompilerSinks, submit_engagement_compile
from app.orchestration.debrief import DebriefSinks, run_debrief_pipeline
from app.orchestration.engines import (
    CompilerEngines,
    DebriefEngines,
    EngineNotConfiguredError,
    engagement_filesystem_scope,
)

SESSION = "session-1"
ENGAGEMENT = "eng-1"
SECTION = TemplateSection(key="performance", title="Performance")


# --------------------------------------------------------------------------
# Fakes for the five inference seams. Each returns the minimum well-formed
# output its stage expects, so a stage that is skipped or fed the wrong input
# fails loudly rather than degrading quietly.
# --------------------------------------------------------------------------


def _working_engines() -> DebriefEngines:
    async def diarize(session_id: str, audio_ref: str) -> DiarizationOutput:
        return DiarizationOutput(
            engine="fake",
            turns=[SpeakerTurn(start_seconds=0.0, end_seconds=1.0, speaker_tag="client")],
        )

    async def clean(session_id: str, utterances: list) -> list[str]:
        return [u.text.replace("um, ", "") for u in utterances]

    async def translate(session_id: str, utterances: list, language: str) -> list:
        return [
            TranslationOutcome(original_language="en", translated_text=None)
            for _ in utterances
        ]

    async def classify(session_id: str, utterances: list, sections: list) -> list[str]:
        return [SECTION.key for _ in utterances]

    async def run_chain(session_id: str, utterances: list) -> BmadAnalystChainOutput:
        ids = [u.utterance_id for u in utterances]
        return BmadAnalystChainOutput(
            open_questions=[
                BmadOpenQuestionDraft(
                    text="What does 'fast' mean in seconds?",
                    impact_rank=1,
                    provenance="stated",
                    citation_utterance_ids=ids,
                )
            ],
            decisions=[
                BmadDecisionDraft(
                    text="Ship the API first",
                    decided_by="client",
                    provenance="stated",
                    citation_utterance_ids=ids,
                )
            ],
            project_brief=BmadProjectBriefDraft(
                body="A logistics discovery engagement.",
                provenance="inferred",
                citation_utterance_ids=ids,
            ),
            follow_up_email=BmadFollowUpEmailDraft(
                subject="Follow-ups",
                body="Thanks — two open points.",
                provenance="inferred",
                citation_utterance_ids=ids,
            ),
        )

    return DebriefEngines(
        name="fake",
        diarize=diarize,
        clean=clean,
        translate=translate,
        classify=classify,
        run_chain=run_chain,
        # The §7 pipeline is batch; the conversational seam is FR-7.3 and has
        # no business here. Left as the raiser so that if a stage ever reaches
        # for it, these tests fail rather than quietly succeed.
        converse=DebriefEngines.unconfigured().converse,
    )


def _sinks(recorded: dict) -> DebriefSinks:
    async def record(key: str, value) -> None:
        recorded[key] = value

    async def cite(utterance_id: str, start: float, end: float) -> CoverageCitation:
        return CoverageCitation(
            utterance_id=utterance_id, start_seconds=start, end_seconds=end
        )

    async def released(session_id: str) -> None:
        recorded["audio-released"] = session_id

    return DebriefSinks(
        save_diarization=lambda v: record("diarization", v),
        save_cleaning=lambda v: record("cleaning", v),
        save_translation=lambda v: record("translation", v),
        save_classification=lambda v: record("classification", v),
        save_chain=lambda v: record("chain", v),
        save_citation_table=lambda v: record("citations", v),
        save_coverage_matrix=lambda v: record("matrix", v),
        save_requirements_state=lambda v: record("state", v),
        cite_filled_slot=cite,
        on_audio_released=released,
    )


async def _run(engines: DebriefEngines, recorded: dict):
    return await run_debrief_pipeline(
        SESSION,
        engagement_id=ENGAGEMENT,
        audio_ref="s3://retained/session-1.wav",
        spans=[TranscriptSpan(start_seconds=0.0, end_seconds=1.0, text="um, we need it fast")],
        template_sections=[SECTION],
        document_language="en",
        previous_state=None,
        engines=engines,
        sinks=_sinks(recorded),
    )


async def test_the_whole_debrief_pipeline_runs_in_the_order_section_7_specifies() -> None:
    recorded: dict = {}

    run = await _run(_working_engines(), recorded)

    assert run.complete, f"pipeline stopped at {run.stopped_at}"
    assert run.stages_completed == [
        "diarization",
        "audio-discard",
        "cleaning",
        "translation",
        "classification",
        "coverage-matrix",
        "analyst-chain",
        "citation-binding",
        "state-merge",
    ]


async def test_every_stage_persists_its_own_record() -> None:
    """A stage that runs but never persists leaves nothing to audit."""

    recorded: dict = {}

    await _run(_working_engines(), recorded)

    for key in (
        "diarization",
        "cleaning",
        "translation",
        "classification",
        "matrix",
        "chain",
        "citations",
        "state",
    ):
        assert key in recorded, f"{key} was never persisted"


async def test_audio_is_released_before_the_text_only_stages() -> None:
    """§7 step 3: steps 4-8 operate on text, so the discard precedes them."""

    recorded: dict = {}

    run = await _run(_working_engines(), recorded)

    assert recorded.get("audio-released") == SESSION
    order = run.stages_completed
    assert order.index("audio-discard") < order.index("cleaning")


async def test_an_unconfigured_engine_stops_the_chain_at_the_stage_that_needed_it() -> None:
    """Failing closed beats fabricating output.

    An unconfigured deployment must not look like a working one: the run
    stops at the first stage that needed a model, and nothing downstream is
    persisted from invented input.
    """

    recorded: dict = {}

    run = await _run(DebriefEngines.unconfigured(), recorded)

    assert not run.complete
    assert run.stopped_at == "diarization"
    assert "cleaning" not in recorded
    assert "state" not in recorded


async def test_a_failing_stage_halts_the_chain_rather_than_feeding_the_next_one() -> None:
    """Classifying a failed translation would produce confident nonsense."""

    engines = _working_engines()

    async def broken_translate(*_args) -> list:
        raise RuntimeError("translation vendor unreachable")

    recorded: dict = {}
    run = await _run(
        DebriefEngines(
            name="fake",
            diarize=engines.diarize,
            clean=engines.clean,
            translate=broken_translate,
            classify=engines.classify,
            run_chain=engines.run_chain,
            converse=engines.converse,
        ),
        recorded,
    )

    assert run.stopped_at == "translation"
    assert "classification" not in recorded
    assert "chain" not in recorded


def test_the_unconfigured_error_names_the_stage_and_the_setting() -> None:
    """A FAILED record should explain itself without a log dive."""

    with pytest.raises(EngineNotConfiguredError) as caught:
        raise EngineNotConfiguredError("section classification (§7 step 5)")

    message = str(caught.value)
    assert "section classification" in message
    assert "ANTHROPIC_API_KEY" in message


# --------------------------------------------------------------------------
# Compiler chain (§3.10) and the §3.11 permission scoping it runs under.
# --------------------------------------------------------------------------


async def test_the_compiler_chain_stops_cleanly_when_no_engine_is_configured() -> None:
    recorded: dict = {}

    async def save(key: str, value) -> None:
        recorded[key] = value

    run = await submit_engagement_compile(
        ENGAGEMENT,
        documents=[ExtractionSourceDocument(document_id="doc-1", text="scope")],
        context_pack=None,
        engines=CompilerEngines.unconfigured(),
        sinks=CompilerSinks(
            save_extraction=lambda v: save("extraction", v),
            save_structuring=lambda v: save("structuring", v),
            save_batch_submission=lambda v: save("submission", v),
            save_analyst_pass=lambda v: save("pass", v),
        ),
    )

    assert run.stopped_at == "extraction"
    assert "structuring" not in recorded, "a failed extraction must not be structured"


async def test_the_compiler_refuses_to_read_another_engagements_documents() -> None:
    """§3.11: the scoping that keeps one client's data out of another's agent.

    The document id is attacker-influenced in the sense that it comes from
    stored data, so traversal out of the engagement's own root must be denied
    structurally rather than by convention.
    """

    recorded: dict = {}

    async def save(key: str, value) -> None:
        recorded[key] = value

    with pytest.raises(PermissionError):
        await submit_engagement_compile(
            ENGAGEMENT,
            documents=[
                ExtractionSourceDocument(
                    document_id="../../eng-2/documents/secret", text="other client"
                )
            ],
            context_pack=None,
            engines=_compiler_engines_that_should_never_run(),
            sinks=CompilerSinks(
                save_extraction=lambda v: save("extraction", v),
                save_structuring=lambda v: save("structuring", v),
                save_batch_submission=lambda v: save("submission", v),
                save_analyst_pass=lambda v: save("pass", v),
            ),
        )

    assert recorded == {}, "nothing may run once the scope check fails"


def _compiler_engines_that_should_never_run() -> CompilerEngines:
    async def explode(*_args, **_kwargs):
        raise AssertionError("the scope check must reject this before any engine runs")

    return CompilerEngines(
        name="fake",
        extract=explode,
        structure=explode,
        submit_batch=explode,
        fetch_batch=explode,
    )


def test_the_engagement_scope_allows_only_its_own_documents_and_outputs() -> None:
    scope = engagement_filesystem_scope(ENGAGEMENT)

    assert scope.read_roots == [f"engagements/{ENGAGEMENT}/documents"]
    assert scope.write_roots == [
        f"engagements/{ENGAGEMENT}/bank",
        f"engagements/{ENGAGEMENT}/artifacts",
    ]
