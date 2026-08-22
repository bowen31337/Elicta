"""The post-meeting and compile-time pipelines, driven end to end.

Every stage in both chains was implemented and unit-tested with no caller.
Unit tests could not have caught that: each stage passed in isolation while
the sequence never ran. These drive the assembled chains — the §7 debrief
pipeline and the §3.10 compiler chain — with fake engines standing in for
the inference seams, so the *ordering and threading* are what is under test,
not the model.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.compiler.agent.bmad_analyst import MIN_CANDIDATES
from app.modules.compiler.agent.models import (
    AnalystBatchResult,
    BmadAnalystPassOutput,
)
from app.modules.compiler.citations.models import (
    ClaimStructuringOutput,
    DocumentExtractionOutput,
    ExtractionSourceDocument,
)
from app.modules.debrief.artifacts.models import (
    CoverageCitation,
    CoverageMatrixStatus,
)
from app.modules.debrief.pipeline.models import (
    BmadAnalystChainOutput,
    BmadDecisionDraft,
    BmadFollowUpEmailDraft,
    BmadOpenQuestionDraft,
    BmadProjectBriefDraft,
    DiarizationOutput,
    FillState,
    SpeakerTurn,
    TemplateSection,
    TranscriptSpan,
    TranslationOutcome,
)
from app.orchestration.compiler import (
    DIRECT_ANALYST_STAGE,
    CompilerSinks,
    CompileRun,
    collect_engagement_compile,
    submit_engagement_compile,
)
from app.orchestration.debrief import DebriefSinks, run_debrief_pipeline
from app.orchestration.engines import (
    CompilerEngines,
    DebriefEngines,
    EngineNotConfiguredError,
    UpstreamFailure,
    UpstreamUnavailableError,
    engagement_filesystem_scope,
    upstream_failure_in,
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

    async def cite(session_id: str, start: float, end: float) -> CoverageCitation:
        # `build_coverage_matrix` passes the session id, and a citation carries
        # the record path's own wording. A fake missing those fields raised
        # inside the matrix builder, which caught it and persisted a FAILED
        # matrix — and the chain runs on regardless, so the run still looked
        # complete while confirming nothing.
        return CoverageCitation(
            session_id=session_id,
            engine="record-path-engine",
            start_seconds=start,
            end_seconds=end,
            quoted_text="we need it fast",
            transcript_completed_at=datetime(2026, 1, 1, tzinfo=UTC),
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


async def test_a_submitted_batch_does_not_stop_the_compiler_chain() -> None:
    """A submission that succeeded is `SUBMITTED`, and there is no other value.

    The stage guard asked `_completed(run.submission)`, which tests for a
    status of `"complete"` — and `BmadAnalystBatchSubmissionStatus` has only
    `SUBMITTED` and `FAILED`. So the predicate could never be true, every
    compile stopped at `batch-submission`, and `collect_engagement_compile`
    had no reachable caller. The visible symptom was `POST /bank/compile`
    answering 202 and the bank staying empty for ever, with no stage reporting
    a failure — which reads as an unconfigured model.
    """

    async def extract(engagement_id, documents):
        return DocumentExtractionOutput(claims=[])

    async def structure(engagement_id, claims):
        return ClaimStructuringOutput(candidates=[])

    async def submit_batch(engagement_id, context_pack):
        return "batch-job-1"

    async def fetch_batch(batch_job_id):
        return []

    async def save(_value) -> None:
        return None

    run = await submit_engagement_compile(
        ENGAGEMENT,
        documents=[ExtractionSourceDocument(document_id="doc-1", text="scope")],
        context_pack=None,
        engines=CompilerEngines(
            name="test-engine",
            extract=extract,
            structure=structure,
            submit_batch=submit_batch,
            fetch_batch=fetch_batch,
        ),
        sinks=CompilerSinks(
            save_extraction=save,
            save_structuring=save,
            save_batch_submission=save,
            save_analyst_pass=save,
        ),
    )

    assert run.stopped_at is None, f"the chain stopped at {run.stopped_at}"
    assert "batch-submission" in run.stages_completed
    assert run.batch_job_id == "batch-job-1"


async def test_a_failed_submission_still_stops_the_chain() -> None:
    """The guard has to keep catching the case it was there for."""

    async def extract(engagement_id, documents):
        return DocumentExtractionOutput(claims=[])

    async def structure(engagement_id, claims):
        return ClaimStructuringOutput(candidates=[])

    async def submit_batch(engagement_id, context_pack):
        raise RuntimeError("the Batch API refused the workload")

    async def fetch_batch(batch_job_id):
        return []

    async def save(_value) -> None:
        return None

    run = await submit_engagement_compile(
        ENGAGEMENT,
        documents=[ExtractionSourceDocument(document_id="doc-1", text="scope")],
        context_pack=None,
        engines=CompilerEngines(
            name="test-engine",
            extract=extract,
            structure=structure,
            submit_batch=submit_batch,
            fetch_batch=fetch_batch,
        ),
        sinks=CompilerSinks(
            save_extraction=save,
            save_structuring=save,
            save_batch_submission=save,
            save_analyst_pass=save,
        ),
    )

    assert run.stopped_at == "batch-submission"


async def test_a_collection_that_succeeds_on_a_later_attempt_clears_the_stop() -> None:
    """A batch is collected by retrying, so the retry has to undo the stop.

    The first attempt runs microseconds after submission and always comes back
    empty, setting `stopped_at = "batch-collection"`. If a later attempt that
    actually collects leaves that in place, the run reports itself stopped at
    the stage it just completed — and anything asking `run.complete` reads a
    finished compile as a failed one.
    """

    from app.modules.compiler.agent.models import (
        AnalystBatchResult,
        BmadAnalystPassOutput,
        BmadCandidateDraft,
    )
    from app.orchestration.compiler import CompileRun, collect_engagement_compile

    drafts = [
        BmadCandidateDraft(
            template_section="Performance",
            trigger_types=["vague_adjective"],
            phrasing=f"Question {n}?",
            stub=f"stub {n}",
            lang="en",
            priority=n + 1,
            requires=[],
            authority_match=[],
            source_doc=None,
        )
        for n in range(150)
    ]
    ready = {"yet": False}

    async def fetch_batch(batch_job_id: str):
        if not ready["yet"]:
            return []
        return [
            AnalystBatchResult(
                custom_id=ENGAGEMENT,
                output=BmadAnalystPassOutput(candidates=drafts),
            )
        ]

    async def save(_value) -> None:
        return None

    engines = CompilerEngines(
        name="test-engine",
        extract=lambda *a: None,
        structure=lambda *a: None,
        submit_batch=lambda *a: None,
        fetch_batch=fetch_batch,
    )
    sinks = CompilerSinks(
        save_extraction=save,
        save_structuring=save,
        save_batch_submission=save,
        save_analyst_pass=save,
    )

    run = CompileRun(engagement_id=ENGAGEMENT)
    run.submission = type("S", (), {"batch_job_id": "batch-1"})()

    first = await collect_engagement_compile(run, engines=engines, sinks=sinks)
    assert first.stopped_at == "batch-collection", "the batch is not ready yet"

    ready["yet"] = True
    second = await collect_engagement_compile(run, engines=engines, sinks=sinks)

    assert second.stopped_at is None, "a successful collection still reports a stop"
    assert second.complete is True
    assert "batch-collection" in second.stages_completed


def _debrief_with(**overrides) -> DebriefEngines:
    """The working engine set with one seam replaced by a broken one."""

    working = _working_engines()
    fields = {
        "name": "fake",
        "diarize": working.diarize,
        "clean": working.clean,
        "translate": working.translate,
        "classify": working.classify,
        "run_chain": working.run_chain,
        "converse": working.converse,
    }
    return DebriefEngines(**{**fields, **overrides})


async def _broken(*_args, **_kwargs):
    raise RuntimeError("vendor unreachable")


async def test_a_failed_cleanup_is_not_translated() -> None:
    """Translating a transcript the cleanup stage never produced would translate nothing."""

    recorded: dict = {}

    run = await _run(_debrief_with(clean=_broken), recorded)

    assert not run.complete
    assert run.stopped_at == "cleaning"
    assert run.stages_completed == ["diarization", "audio-discard"]
    assert "translation" not in recorded
    assert "state" not in recorded


async def test_a_failed_classification_does_not_produce_a_coverage_matrix() -> None:
    """A matrix built from a failed classification would report coverage nobody demonstrated.

    This is the shape the empty case takes here: every section unfilled reads
    as "the meeting covered nothing" rather than "the stage did not run".
    """

    recorded: dict = {}

    run = await _run(_debrief_with(classify=_broken), recorded)

    assert not run.complete
    assert run.stopped_at == "classification"
    assert "matrix" not in recorded
    assert "chain" not in recorded
    assert "state" not in recorded


async def test_a_failed_analyst_chain_leaves_no_citations_and_no_state_merge() -> None:
    """The artifacts are what the citations bind to; without them there is nothing to bind."""

    recorded: dict = {}

    run = await _run(_debrief_with(run_chain=_broken), recorded)

    assert not run.complete
    assert run.stopped_at == "analyst-chain"
    # The matrix precedes the chain, so it is persisted; the two stages that
    # depend on the chain's artifacts are not.
    assert "matrix" in recorded
    assert "citations" not in recorded
    assert "state" not in recorded


async def test_a_failed_structuring_pass_is_never_submitted_as_a_batch() -> None:
    """An analyst batch is minutes and money; submitting one over failed input wastes both."""

    recorded: dict = {}

    async def save(key: str, value) -> None:
        recorded[key] = value

    working = CompilerEngines.unconfigured()

    async def extract(engagement_id: str, documents: list) -> DocumentExtractionOutput:
        return DocumentExtractionOutput(
            claims=[],
            source_documents=list(documents),
        )

    run = await submit_engagement_compile(
        ENGAGEMENT,
        documents=[ExtractionSourceDocument(document_id="doc-1", text="scope")],
        context_pack=None,
        engines=CompilerEngines(
            name="fake",
            extract=extract,
            structure=_broken,
            submit_batch=working.submit_batch,
            fetch_batch=working.fetch_batch,
        ),
        sinks=CompilerSinks(
            save_extraction=lambda v: save("extraction", v),
            save_structuring=lambda v: save("structuring", v),
            save_batch_submission=lambda v: save("submission", v),
            save_analyst_pass=lambda v: save("pass", v),
        ),
    )

    assert run.stopped_at == "structuring"
    assert "submission" not in recorded


async def test_collecting_a_compile_that_was_never_submitted_reports_the_submission() -> None:
    """Nothing to collect, and the reason is the submission — not an empty bank.

    A run that returns no candidates because it was never submitted must not
    be indistinguishable from one whose analyst pass genuinely found nothing.
    """

    recorded: dict = {}

    async def save(key: str, value) -> None:
        recorded[key] = value

    run = CompileRun(engagement_id=ENGAGEMENT)
    assert run.batch_job_id is None

    collected = await collect_engagement_compile(
        run,
        engines=CompilerEngines.unconfigured(),
        sinks=CompilerSinks(
            save_extraction=lambda v: save("extraction", v),
            save_structuring=lambda v: save("structuring", v),
            save_batch_submission=lambda v: save("submission", v),
            save_analyst_pass=lambda v: save("pass", v),
        ),
    )

    assert collected.stopped_at == "batch-submission"
    assert "pass" not in recorded


# --------------------------------------------------------------------------
# Reading a recorded stage error back. A stage persists its failure as text,
# and the HTTP surface has to recover the *kind* from that text to choose a
# status code. Anything it cannot recognise must read as "not a provider
# problem" rather than as a guess.
# --------------------------------------------------------------------------


def test_a_recorded_provider_failure_is_read_back_by_kind() -> None:
    assert (
        upstream_failure_in("the debrief conversation (FR-7.3) [rate_limited]: wait")
        is UpstreamFailure.RATE_LIMITED
    )


def test_a_stage_error_carrying_no_marker_is_not_a_provider_problem() -> None:
    # A bug in this codebase must never be reported as the provider's fault.
    assert upstream_failure_in("section classification failed: list index out of range") is None


def test_an_unrecognised_marker_is_not_invented_into_a_failure_kind() -> None:
    # The marker shape matches but the name is not one this version knows —
    # a record written by a newer build, or a stage message that happens to
    # look like one. Neither is a provider verdict.
    assert upstream_failure_in("some stage [teapot]: brewing") is None


async def test_the_coverage_matrix_completes_rather_than_merely_being_written() -> None:
    """A FAILED matrix is still a persisted matrix, and the chain runs on.

    `build_coverage_matrix` catches whatever the citation lookup raises and
    records a FAILED matrix with no entries. Asserting only that something was
    persisted therefore passes while every section is uncovered and FR-8.9's
    standing state confirms nothing — which is exactly what was happening.
    """

    recorded: dict = {}

    run = await _run(_working_engines(), recorded)

    assert run.complete
    matrix = recorded["matrix"]
    assert matrix.status is CoverageMatrixStatus.COMPLETE, matrix.error
    filled = [entry for entry in matrix.entries if entry.fill_state is FillState.FILLED]
    assert filled, "the meeting covered a section and the matrix does not say so"
    assert filled[0].citations, "a filled slot with no citation cannot be audited"


async def test_a_direct_analyst_pass_that_comes_back_unusable_stops_the_compile() -> None:
    """The fallback is a second route, not a second chance to fabricate.

    A direct pass outside the accepted candidate band is rejected by the
    same collection the batch path uses. What must not happen is the run
    reporting itself finished over a bank the collection threw away — an empty
    bank that says "complete" is the failure this whole route exists to end.
    """

    recorded: dict = {}

    async def save(key: str, value) -> None:
        recorded[key] = value

    async def ok(*_args, **_kwargs):
        return type("Out", (), {"claims": [], "candidates": []})()

    async def submit_batch(*_args, **_kwargs):
        raise UpstreamUnavailableError(
            "batch submission", UpstreamFailure.NOT_ENTITLED, "no batch scope."
        )

    async def run_analyst(engagement_id: str, _context_pack):
        # Fewer candidates than the accepted band allows, whatever it is set to.
        return [
            AnalystBatchResult(
                custom_id=engagement_id,
                output=BmadAnalystPassOutput(
                    candidates=[
                        {
                            "template_section": "volumes",
                            "trigger_types": ["unquantified-quantity"],
                            "phrasing": f"How many consignments a month? ({index})",
                            "stub": f"How many? ({index})",
                            "lang": "en",
                            "priority": index,
                        }
                        for index in range(1, 4)
                    ]
                ),
            )
        ]

    async def fetch_batch(_job_id: str):  # pragma: no cover - never reached
        raise AssertionError("a refused submission has no batch to fetch")

    run = await submit_engagement_compile(
        ENGAGEMENT,
        documents=[ExtractionSourceDocument(document_id="doc-1", text="scope")],
        context_pack=None,
        engines=CompilerEngines(
            name="test-provider",
            extract=ok,
            structure=ok,
            submit_batch=submit_batch,
            fetch_batch=fetch_batch,
            run_analyst=run_analyst,
        ),
        sinks=CompilerSinks(
            save_extraction=lambda v: save("extraction", v),
            save_structuring=lambda v: save("structuring", v),
            save_batch_submission=lambda v: save("submission", v),
            save_analyst_pass=lambda v: save("pass", v),
        ),
    )

    assert not run.complete
    # Named for the stage that actually failed: reporting it as
    # `batch-submission` would make a fallback that ran and failed
    # indistinguishable from one that was never wired.
    assert run.stopped_at == DIRECT_ANALYST_STAGE
    assert DIRECT_ANALYST_STAGE not in run.stages_completed
    assert str(MIN_CANDIDATES) in (run.direct_analyst_error or ""), (
        "the reason the pass was thrown away is not recorded"
    )
