"""The live recogniser's request, without a live network or a spent credit.

Two things are asserted that cost real money to get wrong: that the vendor
retention opt-out is on the wire (NFR-2.3), and that the engagement's own
vocabulary travels with the audio (FR-2.9). Both are settings an operator
changes on a screen, and both are invisible from the outside once wrong.
"""

from __future__ import annotations

import httpx
import pytest

from app.modules.settings.models import SecretKey
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
    keyterm_prompting = True
    disable_vendor_retention = True


class _Settings:
    connectors = _Connectors()


class _Store:
    def __init__(self, secret: object | None) -> None:
        self._secret = secret

    def get_secret(self, key: SecretKey) -> object | None:
        assert key is SecretKey.DEEPGRAM_API_KEY
        return self._secret

    def read(self) -> _Settings:
        return _Settings()


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
