"""Whether a chunk is offered to the live lane at all.

The gate and the recogniser ask two different questions about one fact —
"is there a Deepgram credential?" — and they have to ask it of the same
place. They did not: the recogniser was moved to the pool and the gate kept
reading the fixed `deepgram_api_key`, so an operator who added their key on
the Settings screen got silence. Not an error, not a log line — the chunk
returned quietly, exactly as it does on a deployment that has bought no
speech at all.

That is the failure this file exists for, and it is the second time the same
one has been shipped: an evening was already lost to a live panel that sat
at its resting state because a credential check nobody could see said no.
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from app import composition
from app.composition import Backend, build_app
from app.modules.settings.models import SecretKey, SpeechVendor
from app.modules.settings.speech_admin import SpeechCredentialCreate, add_credential
from app.modules.settings.store import InMemorySettingsStore
from app.modules.trigger.listener import WINDOW_BYTES

#: A whole window, because the lane recognises windows rather than chunks —
#: a short chunk is buffered and nothing is offered to anything, which looks
#: exactly like a closed gate and would make this file pass either way.
PCM = base64.b64encode(b"\x00\x01" * (WINDOW_BYTES // 2)).decode()


@pytest.fixture
def offered(monkeypatch) -> list[str]:
    """Session ids the default live lane was actually asked to transcribe."""

    seen: list[str] = []

    def recogniser(store, get_vocabulary, **kwargs):
        async def recognise(session_id: str, pcm: bytes) -> str:
            seen.append(session_id)
            return ""

        return recognise

    monkeypatch.setattr(composition, "deepgram_live_recogniser", recogniser)
    return seen


def _post(store: InMemorySettingsStore) -> TestClient:
    """One chunk, through the routes a real capture actually walks.

    The recording is opened first because a chunk with nothing to belong to
    is refused at the door — before the gate this file is about ever runs.
    """

    client = TestClient(build_app(Backend(), settings_store=store))
    opened = client.post("/api/sessions/meeting-1/recording", json={})
    assert opened.status_code in (200, 201), opened.text
    sent = client.post(
        "/api/sessions/meeting-1/audio-chunk", json={"sequence": 0, "pcm": PCM}
    )
    assert sent.status_code in (200, 202), sent.text
    return client


def test_a_pooled_key_opens_the_gate(offered) -> None:
    store = InMemorySettingsStore(read_environment=False)
    add_credential(
        store,
        SpeechCredentialCreate(vendor=SpeechVendor.DEEPGRAM, label="Northwind", value="dg-key"),
    )

    _post(store)

    assert offered == ["meeting-1"]


def test_the_fixed_key_still_opens_it(offered) -> None:
    """A deployment predating the pool is not broken by it."""

    store = InMemorySettingsStore(read_environment=False)
    store.set_secret(SecretKey.DEEPGRAM_API_KEY, "dg-key")

    _post(store)

    assert offered == ["meeting-1"]


def test_no_credential_anywhere_stays_quiet(offered) -> None:
    """The honest answer, and it must stay quiet rather than raise.

    Nothing is transcribed, the recording is unaffected, and the panel says
    so through its own lane frame. Raising here would log an exception every
    four seconds of every meeting on a deployment that simply has not bought
    this.
    """

    _post(InMemorySettingsStore(read_environment=False))

    assert offered == []


def test_a_disabled_pooled_key_does_not_open_it(offered) -> None:
    """Out of service means out of service, not merely unlisted."""

    store = InMemorySettingsStore(read_environment=False)
    made = add_credential(
        store,
        SpeechCredentialCreate(vendor=SpeechVendor.DEEPGRAM, label="spare", value="dg-key"),
    )
    from app.modules.settings.speech_admin import SpeechCredentialUpdate, update_credential

    update_credential(store, made.id, SpeechCredentialUpdate(enabled=False))

    _post(store)

    assert offered == []
