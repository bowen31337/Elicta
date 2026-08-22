"""The production app, with fixtures behind the four seams that have no vendor.

The rule this file exists to keep: **substitute the seams, never the pipeline.**
`build_app` here is the same `build_app` `main.py` calls, the debrief engines are
the same ones `engines_from_settings` builds from the credential in the settings
store, and the state store is the real one. What is replaced is exactly the set
of callables that today have no implementation behind them:

  * the two record-path transcription engines (`stub_engine` in production,
    answering the fixed string "hello there"), and
  * the diarizer (`_no_diarizer` in production, which raises).

Everything from transcript cleaning onward — translation, section
classification, the coverage matrix, the BMAD analyst chain, citation binding
and the forward state merge — runs against the live model, unchanged. If a
stage fails here it has failed for real.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "apps" / "service" / "src"))

from app.composition import (  # noqa: E402
    Backend,
    _asr_models,
    attach_state_store,
    build_app,
)
from app.main import default_settings_database  # noqa: E402
from app.modules.debrief.pipeline.models import (  # noqa: E402
    DiarizationOutput,
    SpeakerTurn,
    TemplateSection,
)
from app.modules.settings.models import SecretKey  # noqa: E402
from app.modules.settings.sqlite_store import SqliteSettingsStore  # noqa: E402
from app.orchestration.anthropic_engines import engines_from_settings  # noqa: E402
from app.persistence import open_state_store  # noqa: E402
from app.persistence.store import redact_database_url, resolve_database_url  # noqa: E402

from . import fixtures  # noqa: E402
from .fixture_engines import fixture_debrief_engines  # noqa: E402


def record_path_engine(name: str, *, mishear: bool) -> tuple[str, Any]:
    """One record-path engine, returning the recorded transcript.

    Signature matches what `build_record_path_router` calls: the keyterms the
    engagement's vocabulary supplies arrive here exactly as a vendor would
    receive them, and are recorded so the run can show they were sent.
    """

    sent_keyterms: list[list[str]] = []

    async def transcribe(session_id: str, audio_ref: str, keyterms: list[str]) -> Any:
        sent_keyterms.append(list(keyterms))
        payload = fixtures.vendor_transcript(name, mishear=mishear)
        return _asr_models.BatchTranscriptionOutput(
            engine=payload["engine"],
            segments=[
                _asr_models.TranscriptSegment(**segment)
                for segment in payload["segments"]
            ],
            text=payload["text"],
        )

    transcribe.sent_keyterms = sent_keyterms  # type: ignore[attr-defined]
    return (name, transcribe)


def fixture_diarizer(engine: str = "fixture-diarizer") -> Any:
    """The diarization vendor's answer for this session's audio.

    Returns speaker turns, not utterances: `run_diarization` is what turns
    turns into speaker-tagged utterances, and that is real code doing real
    work over this input.
    """

    async def diarize(session_id: str, audio_ref: str) -> DiarizationOutput:
        return DiarizationOutput(
            engine=engine,
            turns=[SpeakerTurn(**turn) for turn in fixtures.diarization_turns()],
        )

    return diarize


def build_fixture_app(
    *, state_dir: Path | None = None, offline: bool = False
) -> tuple[Any, Backend, dict[str, Any]]:
    """The app, its backend, and what the harness had to stand in for.

    `state_dir` keeps a run out of the deployment's own database by default:
    a fixture meeting written into the state a real engagement lives in is
    hard to tell from a real one later. Pass `None` to use the configured
    store, which is what makes a run visible in the running desktop app.
    """

    store = SqliteSettingsStore(default_settings_database())

    if state_dir is None:
        configured = store.get_secret(SecretKey.STATE_DATABASE_URL)
        database_url = resolve_database_url(configured.reveal() if configured else None)
    else:
        state_dir.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{state_dir / 'state.db'}"

    backend = attach_state_store(Backend(), open_state_store(database_url))
    # `TemplateSection`s, not bare strings: the taxonomy is a caller decision
    # (PRD D5), and `classify` has to be told the stable key it must return.
    # Nothing in the product writes these yet, which is why a run has to.
    backend.template_sections = [
        TemplateSection(key=section.lower().replace(" ", "-"), title=section)
        for section in fixtures.TEMPLATE_SECTIONS
    ]

    diarize = fixture_diarizer()
    debrief_engines, compiler_engines = engines_from_settings(store, diarize=diarize)
    if offline:
        # No model, so no rate limit, no overload, and no run-to-run drift —
        # which is what lets a happy path be asserted rather than observed.
        debrief_engines = fixture_debrief_engines(diarize)
    engine_a = record_path_engine("fixture-engine-a", mishear=False)
    engine_b = record_path_engine("fixture-engine-b", mishear=True)

    app = build_app(
        backend,
        debrief_engines=debrief_engines,
        compiler_engines=compiler_engines,
        settings_store=store,
        record_path_engines=[engine_a, engine_b],
    )

    return app, backend, {
        "database": redact_database_url(database_url),
        "model": debrief_engines.name,
        "engines": [engine_a, engine_b],
        "substituted": [
            "record-path engine A (no speech vendor)",
            "record-path engine B (no speech vendor)",
            "diarizer (no speech vendor)",
            "the live path's nudges (scripted; see fixtures.SESSION_SCRIPT)",
        ],
    }
