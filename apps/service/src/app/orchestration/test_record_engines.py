"""The record path's engines come from the settings (spec §5.6)."""

from __future__ import annotations

import pytest

from app.modules.settings.models import SecretKey, SpeechVendor
from app.modules.settings.store import InMemorySettingsStore
from app.orchestration.engines import EngineNotConfiguredError
from app.orchestration.record_engines import (
    UnconfiguredVendor,
    build_record_engines,
    describe_record_engines,
)


def _store(*vendors: SpeechVendor) -> InMemorySettingsStore:
    """A store with these record vendors selected.

    Written through `write_connectors` rather than by mutating what `read()`
    returned: `read()` builds a fresh `ServiceSettings` every call and only
    happens to reuse the nested `connectors` object.
    """

    from app.modules.settings.models import ConnectorSettings

    store = InMemorySettingsStore()
    store.write_connectors(ConnectorSettings(record_vendors=list(vendors)))
    return store


def test_one_engine_is_built_per_selected_vendor() -> None:
    store = _store(SpeechVendor.DEEPGRAM, SpeechVendor.ASSEMBLYAI)
    store.set_secret(SecretKey.DEEPGRAM_API_KEY, "dg")
    store.set_secret(SecretKey.ASSEMBLYAI_API_KEY, "aai")

    engines = build_record_engines(store, lambda _session: b"pcm")

    assert [name for name, _ in engines] == ["deepgram", "assemblyai"]


async def test_an_uncredentialed_vendor_still_builds_an_engine_that_fails_closed() -> None:
    """Never skipped silently — but never a startup refusal either.

    An unconfigured Anthropic key does not stop this service from starting;
    an unconfigured speech key must not either (main.py's own precedent).
    What the original refusal protected is still true: the setting claims
    two engines, so the operator must see two transcripts, one of them a
    named, actionable failure rather than a missing entry.
    """

    store = _store(SpeechVendor.DEEPGRAM, SpeechVendor.ASSEMBLYAI)
    store.set_secret(SecretKey.DEEPGRAM_API_KEY, "dg")

    engines = build_record_engines(store, lambda _session: b"pcm")

    assert [name for name, _ in engines] == ["deepgram", "assemblyai"]

    _name, transcribe = engines[1]
    with pytest.raises(EngineNotConfiguredError, match="assemblyai_api_key"):
        await transcribe("session-1", "fixture://audio", [])


def test_describe_record_engines_distinguishes_configured_from_fails_closed() -> None:
    """The startup log line names which engine will actually run."""

    store = _store(SpeechVendor.DEEPGRAM, SpeechVendor.ASSEMBLYAI)
    store.set_secret(SecretKey.DEEPGRAM_API_KEY, "dg")

    labels = describe_record_engines(store)

    assert labels == ["deepgram (configured)", "assemblyai (NO CREDENTIAL, fails closed)"]


def test_no_speech_credentials_at_all_still_builds_two_engines() -> None:
    """The CI / fresh-checkout case: nothing configured, nothing raised.

    A settings store with neither vendor's credential set is exactly what a
    brand-new deployment or a CI runner starts with. Building the engine list
    must not raise here, or the service — and every test that imports it —
    could not start at all without a speech credential on day one.
    """

    store = _store(SpeechVendor.DEEPGRAM, SpeechVendor.ASSEMBLYAI)

    engines = build_record_engines(store, lambda _session: b"pcm")

    assert [name for name, _ in engines] == ["deepgram", "assemblyai"]


def test_a_vendor_with_no_client_is_refused_by_name() -> None:
    """A custom endpoint has no batch client here, and pretending otherwise
    produces a session with fewer transcripts than engines.

    `ConnectorSettings.record_vendors` requires exactly two distinct vendors
    (PRD FR-2.6, architecture T3), so this pairs the custom vendor with a
    configured Deepgram credential rather than selecting it alone — the
    engine under test is still the second one built, refused by name.
    """

    from app.modules.settings.models import ConnectorSettings

    store = InMemorySettingsStore()
    store.write_connectors(
        ConnectorSettings(
            record_vendors=[SpeechVendor.DEEPGRAM, SpeechVendor.CUSTOM],
            custom_base_url="https://custom.example/asr",
        )
    )
    store.set_secret(SecretKey.DEEPGRAM_API_KEY, "dg")

    with pytest.raises(UnconfiguredVendor, match="custom"):
        build_record_engines(store, lambda _session: b"pcm")
