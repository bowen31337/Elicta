"""The record path's two engines are a seam, like every other model call.

`build_app` already takes `debrief_engines` and `compiler_engines`, for the
reason `orchestration/engines.py` gives: inference is injected, never imported,
so an unconfigured deployment fails honestly instead of looking healthy. The
record path was the exception — two `stub_engine` stand-ins returning a fixed
string, wired in production code with no way past them. Nothing could supply a
real vendor, and nothing could supply a recorded transcript either, so every
stage downstream of transcription had only "hello there" to work from.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.composition import Backend, _asr_models, build_app


def _engagement(client: TestClient) -> str:
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Northgate Chilled Logistics",
            "sector": "Cold-chain distribution",
            "commercial_context": "Fixed-price discovery",
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["engagement_id"]


def _meeting(client: TestClient, engagement_id: str) -> str:
    created = client.post(
        "/api/meetings",
        json={"engagement_id": engagement_id, "capture_mode": "record"},
    )
    assert created.status_code == 201, created.text
    return created.json()["meeting_id"]


def _engine(name: str, text: str) -> tuple[str, Any]:
    async def transcribe(session_id: str, audio_ref: str, keyterms: list[str]) -> Any:
        return _asr_models.BatchTranscriptionOutput(
            engine=name,
            segments=[
                _asr_models.TranscriptSegment(
                    start_seconds=0.0, end_seconds=4.0, text=text
                )
            ],
            text=text,
        )

    return (name, transcribe)


def test_the_record_path_transcribes_with_the_engines_it_was_given() -> None:
    """A supplied pair replaces the stand-ins rather than sitting beside them."""

    backend = Backend()
    app = build_app(
        backend,
        record_path_engines=[
            _engine("vendor-a", "the chilled dock rule is fifteen minutes"),
            _engine("vendor-b", "the chilled dock rule is fifty minutes"),
        ],
    )
    with TestClient(app) as client:
        engagement_id = _engagement(client)
        meeting_id = _meeting(client, engagement_id)

        response = client.post(
            f"/api/sessions/{meeting_id}/record-path-transcript",
            json={"audio_ref": "fixture://northgate-1"},
        )
        assert response.status_code == 201, response.text

        engines = sorted(row["engine"] for row in response.json())
        assert engines == ["vendor-a", "vendor-b"]
        texts = {row["engine"]: row["segments"][0]["text"] for row in response.json()}
        assert texts["vendor-a"] == "the chilled dock rule is fifteen minutes"
        assert "hello there" not in texts.values()


def test_the_stand_ins_are_still_the_default() -> None:
    """Nothing that does not ask for engines changes behaviour."""

    backend = Backend()
    with TestClient(build_app(backend)) as client:
        engagement_id = _engagement(client)
        meeting_id = _meeting(client, engagement_id)
        response = client.post(
            f"/api/sessions/{meeting_id}/record-path-transcript",
            json={"audio_ref": "fixture://northgate-1"},
        )
        assert response.status_code == 201, response.text
        assert sorted(row["engine"] for row in response.json()) == ["engine-a", "engine-b"]


def test_the_engagement_vocabulary_reaches_the_transcriber_as_keyterms() -> None:
    """FR-2.9: the client's own words go to the engine that has to hear them.

    `engagement_vocabulary` is keyed by engagement, and the record path calls
    the lookup with a *meeting* id — so it missed on every real meeting and
    handed both engines an empty keyterm list. Nothing failed: the transcript
    came back, slightly wronger, and the one preparation step the guide calls
    the most effective thing you can do for accuracy reached nothing at all.
    """

    received: list[list[str]] = []

    def capturing(name: str) -> tuple[str, Any]:
        async def transcribe(session_id: str, audio_ref: str, keyterms: list[str]) -> Any:
            received.append(list(keyterms))
            return _asr_models.BatchTranscriptionOutput(
                engine=name,
                segments=[
                    _asr_models.TranscriptSegment(
                        start_seconds=0.0, end_seconds=1.0, text="FROSTLINE"
                    )
                ],
                text="FROSTLINE",
            )

        return (name, transcribe)

    backend = Backend()
    app = build_app(
        backend,
        record_path_engines=[capturing("vendor-a"), capturing("vendor-b")],
    )
    with TestClient(app) as client:
        engagement_id = _engagement(client)
        for term in ("FROSTLINE", "NAVISTOCK"):
            added = client.post(
                f"/api/engagements/{engagement_id}/vocabulary",
                json={"term": term, "term_type": "internal_system"},
            )
            assert added.status_code == 201, added.text
        meeting_id = _meeting(client, engagement_id)

        response = client.post(
            f"/api/sessions/{meeting_id}/record-path-transcript",
            json={"audio_ref": "fixture://northgate-1"},
        )
        assert response.status_code == 201, response.text

    assert received, "no engine was called"
    for keyterms in received:
        assert sorted(keyterms) == ["FROSTLINE", "NAVISTOCK"], keyterms


def test_the_write_up_is_built_from_one_engine_not_both() -> None:
    """FR-2.6/2.8: two engines are a confidence signal, not two transcripts to merge.

    The pipeline built its spans from every COMPLETE transcript, so with two
    engines running every utterance reached the write-up twice — once as each
    engine heard it, including the one that misheard. Nobody saw it because the
    two stand-ins returned the same single segment, so "twice" and "once"
    looked identical.

    The alignment already names a reference engine and scores the other against
    it. The write-up follows the same reference, so what the operator reviews
    as divergences and what the documents are drafted from agree about which
    reading is the basis.
    """

    seen: list[int] = []

    async def clean(_session_id: str, texts: list[str]) -> list[str]:
        seen.append(len(texts))
        return list(texts)

    async def diarize(_session_id: str, _audio_ref: str) -> Any:
        from app.modules.debrief.pipeline.models import DiarizationOutput, SpeakerTurn

        return DiarizationOutput(
            engine="fixture",
            turns=[SpeakerTurn(start_seconds=0.0, end_seconds=9.0, speaker_tag="S1")],
        )

    def two_segment_engine(name: str, second: str) -> tuple[str, Any]:
        async def transcribe(session_id: str, audio_ref: str, keyterms: list[str]) -> Any:
            return _asr_models.BatchTranscriptionOutput(
                engine=name,
                segments=[
                    _asr_models.TranscriptSegment(
                        start_seconds=0.0, end_seconds=4.0, text="fifteen minutes on the dock"
                    ),
                    _asr_models.TranscriptSegment(
                        start_seconds=4.0, end_seconds=9.0, text=second
                    ),
                ],
                text=f"fifteen minutes on the dock {second}",
            )

        return (name, transcribe)

    from app.orchestration.engines import DebriefEngines

    engines = DebriefEngines.unconfigured()
    engines = DebriefEngines(
        name="fixture",
        diarize=diarize,
        clean=clean,
        translate=engines.translate,
        classify=engines.classify,
        run_chain=engines.run_chain,
        converse=engines.converse,
    )

    backend = Backend()
    app = build_app(
        backend,
        debrief_engines=engines,
        record_path_engines=[
            two_segment_engine("vendor-a", "the Derby site is open"),
            two_segment_engine("vendor-b", "the Darby site is open"),
        ],
    )
    with TestClient(app) as client:
        engagement_id = _engagement(client)
        meeting_id = _meeting(client, engagement_id)
        response = client.post(
            f"/api/sessions/{meeting_id}/record-path-transcript",
            json={"audio_ref": "fixture://northgate-1"},
        )
        assert response.status_code == 201, response.text

    assert seen, "the cleaning stage never ran"
    assert seen[0] == 2, (
        f"cleaning saw {seen[0]} utterances for a two-segment meeting: "
        "both engines' transcripts reached the write-up"
    )
