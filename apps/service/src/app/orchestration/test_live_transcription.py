"""The live recogniser's request, without a live network or a spent credit.

Two things are asserted that cost real money to get wrong: that the vendor
retention opt-out is on the wire (NFR-2.3), and that the engagement's own
vocabulary travels with the audio (FR-2.9). Both are settings an operator
changes on a screen, and both are invisible from the outside once wrong.
"""

from __future__ import annotations

import httpx
import pytest

from app.modules.settings.models import LiveSpeechModel, SecretKey
from app.orchestration.deepgram_engines import DeepgramUnavailable
from app.orchestration.live_transcription import deepgram_live_recogniser, transcript_of

SPOKEN = {
    "results": {"channels": [{"alternatives": [{"transcript": "the dashboard has to be fast"}]}]}
}


class _Secret:
    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value


class _Connectors:
    def __init__(self, live_model: str = "nova-3", keyterm_prompting: bool = True) -> None:
        self.live_model = LiveSpeechModel(live_model)
        self.keyterm_prompting = keyterm_prompting
        self.disable_vendor_retention = True


class _Settings:
    def __init__(self, connectors: _Connectors | None = None) -> None:
        self.connectors = connectors or _Connectors()


class _Store:
    def __init__(
        self, secret: object | None, connectors: _Connectors | None = None
    ) -> None:
        self._secret = secret
        self._connectors = connectors

    def get_secret(self, key: SecretKey) -> object | None:
        assert key is SecretKey.DEEPGRAM_API_KEY
        return self._secret

    def read(self) -> _Settings:
        return _Settings(self._connectors)


async def _vocabulary(session_id: str) -> list[str]:
    return ["FROSTLINE", "marshalling area"]


def test_a_window_with_no_speech_in_it_reads_as_silence_rather_than_an_error() -> None:
    """People pause. A pause is not a failure, and must not be reported as one."""

    assert transcript_of({"results": {"channels": [{"alternatives": [{"transcript": ""}]}]}}) == ""
    assert transcript_of({}) == ""
    assert transcript_of(None) == ""


@pytest.mark.asyncio
async def test_the_words_come_back_from_the_window() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=SPOKEN)

    recognise = deepgram_live_recogniser(
        _Store(_Secret("dg-key")), _vocabulary, transport=httpx.MockTransport(handle)
    )

    heard = await recognise("meeting-1", b"\x00" * 64)

    assert heard == "the dashboard has to be fast"
    assert seen[0].content == b"\x00" * 64


@pytest.mark.asyncio
async def test_the_engagements_vocabulary_travels_with_the_audio() -> None:
    """FR-2.9 on the live path, which is where mis-hearing a system name costs most."""

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=SPOKEN)

    recognise = deepgram_live_recogniser(
        _Store(_Secret("dg-key")), _vocabulary, transport=httpx.MockTransport(handle)
    )
    await recognise("meeting-1", b"\x00" * 64)

    assert "keyterm=FROSTLINE" in str(seen[0].url)
    # NFR-2.3, on the wire rather than in a contract.
    assert "mip_opt_out=true" in str(seen[0].url)


@pytest.mark.asyncio
async def test_an_unconfigured_credential_refuses_rather_than_returning_silence() -> None:
    """Silence and "no key" look identical on a panel, and have different remedies."""

    recognise = deepgram_live_recogniser(_Store(None), _vocabulary)

    with pytest.raises(DeepgramUnavailable):
        await recognise("meeting-1", b"\x00" * 64)


@pytest.mark.asyncio
async def test_a_refused_request_is_reported_rather_than_read_as_silence() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"err_msg": "no"})

    recognise = deepgram_live_recogniser(
        _Store(_Secret("dg-key")), _vocabulary, transport=httpx.MockTransport(handle)
    )

    with pytest.raises(DeepgramUnavailable):
        await recognise("meeting-1", b"\x00" * 64)


# --- which model the live path runs on ----------------------------------
#
# It was a keyword-argument default of `deepgram_live_recogniser` fixed at
# `nova-3`, which nothing in the product passed: the choice existed in a
# signature and nowhere an operator could reach it.


@pytest.mark.asyncio
async def test_the_model_comes_from_settings_and_is_read_per_window() -> None:
    """Per call, not bound when the recogniser was built.

    A restart to change a recogniser is a restart in the middle of a meeting.
    The credential is already read this way; the model follows it.
    """

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=SPOKEN)

    connectors = _Connectors(live_model="nova-3")
    recognise = deepgram_live_recogniser(
        _Store(_Secret("key"), connectors),
        _vocabulary,
        transport=httpx.MockTransport(handle),
    )

    await recognise("session-1", b"\x00\x00")
    # The operator changes it on the Settings screen, mid-session.
    connectors.live_model = LiveSpeechModel.NOVA_2
    await recognise("session-1", b"\x00\x00")

    assert "model=nova-3" in str(seen[0].url)
    assert "model=nova-2" in str(seen[1].url)


@pytest.mark.asyncio
async def test_the_vocabulary_is_not_sent_to_a_model_that_ignores_it() -> None:
    """`keyterm` is Nova-3 only.

    Sent anyway it is discarded by the vendor, and the request log then agrees
    with the operator's belief that their vocabulary is being used. A
    silently-ignored vocabulary is indistinguishable from one that worked,
    which is the worst of the three possible outcomes.
    """

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=SPOKEN)

    recognise = deepgram_live_recogniser(
        _Store(_Secret("key"), _Connectors(live_model="nova-2")),
        _vocabulary,
        transport=httpx.MockTransport(handle),
    )

    await recognise("session-1", b"\x00\x00")

    assert "keyterm" not in str(seen[0].url)
    assert "model=nova-2" in str(seen[0].url)


@pytest.mark.asyncio
async def test_the_vocabulary_is_not_even_looked_up_for_such_a_model() -> None:
    """One database read per four-second window, for terms nothing can use."""

    asked: list[str] = []

    async def vocabulary(session_id: str) -> list[str]:
        asked.append(session_id)
        return ["FROSTLINE"]

    recognise = deepgram_live_recogniser(
        _Store(_Secret("key"), _Connectors(live_model="enhanced")),
        vocabulary,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=SPOKEN)),
    )

    await recognise("session-1", b"\x00\x00")

    assert asked == []


@pytest.mark.asyncio
async def test_an_explicit_model_still_pins_it() -> None:
    """For a caller that means to — a replay against a fixed recogniser."""

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=SPOKEN)

    recognise = deepgram_live_recogniser(
        _Store(_Secret("key"), _Connectors(live_model="nova-2")),
        _vocabulary,
        model="nova-3",
        transport=httpx.MockTransport(handle),
    )

    await recognise("session-1", b"\x00\x00")

    assert "model=nova-3" in str(seen[0].url)


@pytest.mark.asyncio
async def test_the_model_never_reaches_the_url_as_an_enum_repr() -> None:
    """The failure this would have produced is a vendor 400 mid-meeting.

    `LiveSpeechModel.NOVA_3` formats as `LiveSpeechModel.NOVA_3` in a query
    parameter, which Deepgram refuses — and a refused request is reported by
    the lane as the credential being unusable, sending an operator to check a
    key that was fine.
    """

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=SPOKEN)

    recognise = deepgram_live_recogniser(
        _Store(_Secret("key"), _Connectors()),
        _vocabulary,
        transport=httpx.MockTransport(handle),
    )

    await recognise("session-1", b"\x00\x00")

    assert "LiveSpeechModel" not in str(seen[0].url)
