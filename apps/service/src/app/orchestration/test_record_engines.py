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


def _custom_vendor_store() -> InMemorySettingsStore:
    """A save the settings model permits: one real vendor and one with no client.

    `ConnectorSettings.record_vendors` requires exactly two distinct vendors
    (PRD FR-2.6, architecture T3), so the custom vendor is paired with
    Deepgram rather than selected alone — which is exactly what an operator
    can save from the Settings form, `custom_base_url` being its only extra
    requirement.
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
    return store


def test_a_vendor_with_no_client_still_builds_an_engine() -> None:
    """Never a startup refusal: this list is built from a saved form.

    A vendor with no batch client is unusable, but refusing to build the
    engine list for it stopped the whole service starting — including the
    Settings screen the selection would be corrected on.
    """

    engines = build_record_engines(_custom_vendor_store(), lambda _session: b"pcm")

    assert [name for name, _ in engines] == ["deepgram", "custom"]


async def test_a_vendor_with_no_client_fails_closed_by_name_when_called() -> None:
    """Unusable, and it says so where the operator is looking.

    `run_record_path_transcription` turns this into a `FAILED` transcript for
    that engine, so the setting's claim of two engines stays honest: two
    transcripts, one of them a named, actionable failure.
    """

    engines = build_record_engines(_custom_vendor_store(), lambda _session: b"pcm")

    _name, transcribe = engines[1]
    with pytest.raises(UnconfiguredVendor, match="custom") as excinfo:
        await transcribe("session-1", "fixture://audio", [])

    assert "no batch client" in str(excinfo.value)


def test_describe_record_engines_names_a_vendor_with_no_client() -> None:
    """The startup log distinguishes "no key yet" from "no client, ever"."""

    labels = describe_record_engines(_custom_vendor_store())

    assert labels == ["deepgram (configured)", "custom (NO CLIENT, fails closed)"]


async def test_a_credential_entered_after_startup_takes_effect_without_a_restart() -> None:
    """The credential is read per call, not sampled at boot.

    This is the same promise `SettingsBackedClient` keeps for inference, and
    the reason `build_record_engines` builds the vendor's real engine rather
    than choosing a stand-in from what happened to be configured at startup.
    An operator who pastes a key into the Settings screen mid-deployment must
    not have to restart the service to use it.
    """

    from app.orchestration.assemblyai_engines import AssemblyAIUnavailable

    store = _store(SpeechVendor.DEEPGRAM, SpeechVendor.ASSEMBLYAI)
    store.set_secret(SecretKey.DEEPGRAM_API_KEY, "dg")

    # No audio held, so the vendor engine stops at its first check and this
    # test never reaches a network — the credential gate is what is under
    # test, and it sits in front of that check.
    engines = build_record_engines(store, lambda _session: b"")
    _name, transcribe = engines[1]

    with pytest.raises(EngineNotConfiguredError, match="assemblyai_api_key"):
        await transcribe("session-1", "fixture://audio", [])

    store.set_secret(SecretKey.ASSEMBLYAI_API_KEY, "aai")

    with pytest.raises(AssemblyAIUnavailable, match="nothing to transcribe"):
        await transcribe("session-1", "fixture://audio", [])
