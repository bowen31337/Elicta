"""Which recogniser the live path runs on, chosen by the operator.

It was a keyword-argument default of `deepgram_live_recogniser` fixed at
`nova-3` — a choice that existed in a Python signature and nowhere anybody
could reach. A model is now a setting, and a setting has to survive the trip
from the screen it is typed on to the request it changes; this drives the
production composition root so what is asserted is the assembly that ships.

Two of these are about the *report* rather than the request, and they are the
ones worth the file. `live_transcription` on the panel's lane frame answers
"could anything said here be written down", and it answered it by asking
whether a Deepgram credential existed. Against a deployment transcribing on
the operator's own machine that is the wrong question entirely: it reports the
lane down while it works, sending an operator to buy a key they do not need —
the same gate-and-report drift `_live_transcription_ready` was written to end.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.modules.settings.models import (
    ConnectorSettings,
    LiveSpeechModel,
    SecretKey,
)
from app.modules.settings.store import InMemorySettingsStore


def _store(**connectors: object) -> InMemorySettingsStore:
    store = InMemorySettingsStore(read_environment=False)
    store.write_connectors(ConnectorSettings(**connectors))  # type: ignore[arg-type]
    return store


def _meeting(client: TestClient) -> str:
    created = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Northgate Chilled Logistics",
            "sector": "logistics",
            "commercial_context": "Discovery",
        },
    )
    assert created.status_code == 201, created.text
    meeting = client.post(
        "/api/meetings",
        json={"engagement_id": created.json()["engagement_id"], "capture_mode": "live"},
    )
    assert meeting.status_code == 201, meeting.text
    return meeting.json()["meeting_id"]


def _lane(client: TestClient, meeting_id: str) -> dict:
    with client.stream("GET", f"/api/meetings/{meeting_id}/session/stream") as response:
        assert response.status_code == 200, response.text
        name: str | None = None
        for line in response.iter_lines():
            if line.startswith(":"):
                break
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: ") and name == "lane":
                return json.loads(line.removeprefix("data: "))
    raise AssertionError("the stream carried no lane frame")


def test_the_default_is_the_vendor_model_and_it_needs_a_key() -> None:
    """The default is Flux — streamed, and still a Deepgram credential.

    Chosen on measurement rather than on the benchmark: the fixed window was
    five to nine seconds of the delay and the model about four per cent of it,
    so the transport is what mattered. Its published word error rate is worse
    than Nova-3's, and on this path a whole sentence a second later beats half
    a sentence eight seconds later — the recording is transcribed again
    afterwards by two engines bought on accuracy.
    """

    store = _store()
    client = TestClient(build_app(Backend(), settings_store=store))
    meeting_id = _meeting(client)

    assert store.read().connectors.live_model is LiveSpeechModel.FLUX_GENERAL_EN
    assert _lane(client, meeting_id)["live_transcription"] is False

    store.set_secret(SecretKey.DEEPGRAM_API_KEY, "a-key")

    assert _lane(client, meeting_id)["live_transcription"] is True


def test_a_local_model_reports_ready_on_an_address_rather_than_a_key() -> None:
    """The report that would otherwise be wrong in the most expensive way.

    An operator running Whisper on their own machine has no Deepgram key and
    never will. Asked for one, the panel says the room will not be transcribed
    while it is being transcribed perfectly — and the remedy it implies is to
    go and buy something.
    """

    store = _store(
        live_model=LiveSpeechModel.WHISPER_SMALL,
        local_asr_base_url="http://127.0.0.1:8178/v1",
    )
    client = TestClient(build_app(Backend(), settings_store=store))
    meeting_id = _meeting(client)

    assert _lane(client, meeting_id)["live_transcription"] is True


def test_a_local_model_with_no_address_is_reported_as_not_ready() -> None:
    """And the other way, or the check is only ever an optimistic one."""

    store = _store(live_model=LiveSpeechModel.WHISPER_SMALL, local_asr_base_url=None)
    client = TestClient(build_app(Backend(), settings_store=store))
    meeting_id = _meeting(client)

    assert _lane(client, meeting_id)["live_transcription"] is False


def test_a_deepgram_key_does_not_make_a_local_model_ready() -> None:
    """The drift, in the direction that loses a meeting.

    A key left over from a previous arrangement would otherwise report the
    lane up for a local model with nowhere to send audio, and every window of
    the meeting would fail against a server that is not there.
    """

    store = _store(live_model=LiveSpeechModel.PARAKEET_TDT_0_6B_V2, local_asr_base_url=None)
    store.set_secret(SecretKey.DEEPGRAM_API_KEY, "a-key")
    client = TestClient(build_app(Backend(), settings_store=store))
    meeting_id = _meeting(client)

    assert _lane(client, meeting_id)["live_transcription"] is False


def test_switching_the_model_changes_the_report_without_a_restart() -> None:
    """Every other credential and switch in this service takes effect live.

    This one especially: the model is what an operator reaches for *because*
    the current one is not working, and a restart is not available to somebody
    mid-meeting.
    """

    store = _store()
    store.set_secret(SecretKey.DEEPGRAM_API_KEY, "a-key")
    client = TestClient(build_app(Backend(), settings_store=store))
    meeting_id = _meeting(client)
    assert _lane(client, meeting_id)["live_transcription"] is True

    store.write_connectors(
        ConnectorSettings(live_model=LiveSpeechModel.WHISPER_SMALL, local_asr_base_url=None)
    )

    assert _lane(client, meeting_id)["live_transcription"] is False


def test_the_choice_survives_the_round_trip_through_the_settings_api(
    client: TestClient,
) -> None:
    """Typed on a screen, read by a recogniser — with a DTO in between.

    This repo has lost a field to exactly that shape before: `stub` was
    written, stored and read under a name the model between them never
    mentioned, and 554 compiled candidates came back empty with nothing
    raising. `ConnectorSettings` forbids extras rather than ignoring them, so
    the failure here is the opposite one — a 422 on save — and either way the
    only place it shows is a setting that will not stick.
    """

    before = client.get("/api/admin/settings").json()["connectors"]
    assert before["live_model"] == "flux-general-en"
    assert before["local_asr_base_url"] is None

    saved = client.put(
        "/api/admin/settings",
        json={
            "connectors": {
                **before,
                "live_model": "parakeet-tdt-0.6b-v2",
                "local_asr_base_url": "http://127.0.0.1:8178",
            }
        },
    )
    assert saved.status_code == 200, saved.text

    after = client.get("/api/admin/settings").json()["connectors"]
    assert after["live_model"] == "parakeet-tdt-0.6b-v2"
    assert after["local_asr_base_url"] == "http://127.0.0.1:8178"


def test_a_local_model_is_never_told_it_needs_a_speech_credential() -> None:
    """The answer to "why does local ASR require a key?" — it does not.

    The lane was right to report itself unready: a local model with no server
    address transcribes nothing. What was wrong was the *sentence*. The panel
    carried one hardcoded reason from when there was only one way to be
    unready, so an operator running Parakeet on their own machine was told no
    speech credential was configured — true, irrelevant, and pointing at the
    one action that would cost them money and change nothing.
    """

    store = _store(
        live_model=LiveSpeechModel.PARAKEET_TDT_0_6B_V2, local_asr_base_url=None
    )
    client = TestClient(build_app(Backend(), settings_store=store))
    meeting_id = _meeting(client)

    lane = _lane(client, meeting_id)

    assert lane["live_transcription"] is False
    assert "credential" not in lane["live_transcription_reason"]
    assert "local transcription server address" in lane["live_transcription_reason"]


def test_a_vendor_model_still_names_the_credential() -> None:
    store = _store(live_model=LiveSpeechModel.NOVA_3)
    client = TestClient(build_app(Backend(), settings_store=store))
    meeting_id = _meeting(client)

    assert _lane(client, meeting_id)["live_transcription_reason"] == (
        "no speech credential is configured"
    )


def test_the_reason_and_the_readiness_cannot_disagree() -> None:
    """One decision, reported once.

    A reason computed separately from the flag is the gate-and-report drift
    that lost an evening to a credential check nobody could see, wearing a
    different hat. Asserted across every arrangement rather than argued.
    """

    arrangements = [
        (LiveSpeechModel.NOVA_3, None, False),
        (LiveSpeechModel.NOVA_3, None, True),
        (LiveSpeechModel.WHISPER_SMALL, None, False),
        (LiveSpeechModel.WHISPER_SMALL, "http://127.0.0.1:8178/v1", False),
        (LiveSpeechModel.PARAKEET_TDT_0_6B_V2, "http://127.0.0.1:8178", True),
    ]

    for model, address, with_key in arrangements:
        store = _store(live_model=model, local_asr_base_url=address)
        if with_key:
            store.set_secret(SecretKey.DEEPGRAM_API_KEY, "a-key")
        client = TestClient(build_app(Backend(), settings_store=store))
        lane = _lane(client, _meeting(client))

        assert lane["live_transcription"] is (lane["live_transcription_reason"] is None), (
            f"{model} / address={address} / key={with_key} reported "
            f"{lane['live_transcription']} with reason {lane['live_transcription_reason']!r}"
        )


def test_a_streamed_model_never_touches_the_windowed_recogniser(monkeypatch) -> None:
    """The model decides the transport, and it is not a preference.

    Flux is `/v2/listen` only: a Nova model on that endpoint connects and
    never produces a turn, and a Flux model on the batch endpoint is refused.
    So picking the model picks the transport, and the two must not both run —
    a windowed request alongside a stream would bill the meeting twice and
    interleave two transcripts of one room.
    """

    import base64

    from app import composition
    from app.modules.trigger.listener import WINDOW_BYTES

    windowed: list[str] = []

    def never(store, get_vocabulary, **kwargs):
        async def recognise(session_id: str, pcm: bytes) -> str:
            windowed.append(session_id)
            return ""

        return recognise

    opened: list[str] = []

    class _Lane:
        def __init__(self, *args, **kwargs) -> None:
            self.model = kwargs.get("model")

        async def feed(self, session_id: str, pcm: bytes) -> None:
            opened.append(session_id)

    monkeypatch.setattr(composition, "deepgram_live_recogniser", never)
    monkeypatch.setattr(composition, "FluxUtterances", _Lane)

    store = _store(live_model=LiveSpeechModel.FLUX_GENERAL_EN)
    store.set_secret(SecretKey.DEEPGRAM_API_KEY, "dg-key")
    client = TestClient(build_app(Backend(), settings_store=store))

    client.post("/api/sessions/meeting-1/recording")
    sent = client.post(
        "/api/sessions/meeting-1/audio-chunk",
        json={
            "sequence": 0,
            "pcm": base64.b64encode(b"\x00\x01" * (WINDOW_BYTES // 2)).decode(),
        },
    )

    assert sent.status_code in (200, 202), sent.text
    assert opened == ["meeting-1"]
    assert windowed == []


def test_a_windowed_model_never_opens_a_stream(monkeypatch) -> None:
    """And the other way, or the choice only works in one direction."""

    import base64

    from app import composition
    from app.modules.trigger.listener import WINDOW_BYTES

    windowed: list[str] = []
    streamed: list[str] = []

    def recogniser(store, get_vocabulary, **kwargs):
        async def recognise(session_id: str, pcm: bytes) -> str:
            windowed.append(session_id)
            return ""

        return recognise

    class _Lane:
        def __init__(self, *args, **kwargs) -> None:
            streamed.append("opened")

        async def feed(self, session_id: str, pcm: bytes) -> None:
            streamed.append(session_id)

    monkeypatch.setattr(composition, "deepgram_live_recogniser", recogniser)
    monkeypatch.setattr(composition, "FluxUtterances", _Lane)

    store = _store(live_model=LiveSpeechModel.NOVA_3)
    store.set_secret(SecretKey.DEEPGRAM_API_KEY, "dg-key")
    client = TestClient(build_app(Backend(), settings_store=store))

    client.post("/api/sessions/meeting-1/recording")
    client.post(
        "/api/sessions/meeting-1/audio-chunk",
        json={
            "sequence": 0,
            "pcm": base64.b64encode(b"\x00\x01" * (WINDOW_BYTES // 2)).decode(),
        },
    )

    assert windowed == ["meeting-1"]
    assert streamed == []
