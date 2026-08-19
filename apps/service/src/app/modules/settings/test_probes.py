"""Speech-vendor credential probes.

The point of a probe is that "configured" and "working" are different claims.
These assert it distinguishes them, and that it never costs money or uploads
audio to find out.
"""

from __future__ import annotations

import httpx
import pytest

from .probes import ProbeFailed, probe_assemblyai, probe_deepgram, probe_for_vendor


class _Transport(httpx.AsyncBaseTransport):
    def __init__(self, status: int = 200, error: Exception | None = None) -> None:
        self.status = status
        self.error = error
        self.seen: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if self.error is not None:
            raise self.error
        return httpx.Response(self.status, json={})


@pytest.fixture
def patched(monkeypatch):
    def install(transport: _Transport):
        original = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
        return transport

    return install


async def test_a_working_deepgram_key_passes(patched) -> None:
    patched(_Transport(200))
    await probe_deepgram("dg-key")  # no exception is the assertion


async def test_deepgram_sends_its_own_auth_scheme(patched) -> None:
    transport = patched(_Transport(200))

    await probe_deepgram("dg-key")

    assert transport.seen[0].headers["authorization"] == "Token dg-key"


async def test_assemblyai_sends_the_bare_key(patched) -> None:
    transport = patched(_Transport(200))

    await probe_assemblyai("aai-key")

    # AssemblyAI takes the key with no scheme prefix; sending "Bearer" fails.
    assert transport.seen[0].headers["authorization"] == "aai-key"


async def test_a_probe_never_uploads_audio(patched) -> None:
    transport = patched(_Transport(200))

    await probe_deepgram("dg-key")
    await probe_assemblyai("aai-key")

    for request in transport.seen:
        assert request.method == "GET"
        assert not request.content


@pytest.mark.parametrize("status", [401, 403])
async def test_a_rejected_credential_says_so(patched, status: int) -> None:
    patched(_Transport(status))

    with pytest.raises(ProbeFailed, match="rejected the credential"):
        await probe_deepgram("wrong")


async def test_unreachable_is_reported_differently_from_unauthorised(patched) -> None:
    """An operator acts on these differently: one is a key, one is a network."""

    patched(_Transport(error=httpx.ConnectError("no route")))

    with pytest.raises(ProbeFailed, match="could not be reached"):
        await probe_assemblyai("aai-key")


def test_a_custom_vendor_has_no_probe() -> None:
    # Which is what makes the screen say "configured, not verified" rather
    # than inventing a reachability signal for an API we do not know.
    assert probe_for_vendor("custom") is None
    assert probe_for_vendor("deepgram") is probe_deepgram
    assert probe_for_vendor("assemblyai") is probe_assemblyai
