"""The record path's engines come from the settings (spec §5.6)."""

from __future__ import annotations

import pytest

from app.modules.settings.models import SecretKey, SpeechVendor
from app.modules.settings.store import InMemorySettingsStore
from app.orchestration.record_engines import UnconfiguredVendor, build_record_engines


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


def test_a_selected_vendor_with_no_credential_is_refused_by_name() -> None:
    """Never skipped silently: the setting would then claim an engine that is
    not running, and the operator would read one transcript as two."""

    store = _store(SpeechVendor.DEEPGRAM, SpeechVendor.ASSEMBLYAI)
    store.set_secret(SecretKey.DEEPGRAM_API_KEY, "dg")

    with pytest.raises(UnconfiguredVendor, match="assemblyai"):
        build_record_engines(store, lambda _session: b"pcm")


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
