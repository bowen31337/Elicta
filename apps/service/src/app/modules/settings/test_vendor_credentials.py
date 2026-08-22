"""Each speech vendor carries its own credential (spec §2, D3).

One `asr_vendor_api_key` served two record vendors, which cannot be right:
the two are chosen precisely because they are independent, and independent
vendors do not share an API key.
"""

from __future__ import annotations

import pytest

from app.modules.settings.models import SecretKey
from app.modules.settings.store import InMemorySettingsStore


@pytest.mark.parametrize(
    "key",
    [SecretKey.DEEPGRAM_API_KEY, SecretKey.ASSEMBLYAI_API_KEY],
)
def test_each_record_vendor_has_its_own_secret(key: SecretKey) -> None:
    store = InMemorySettingsStore()
    store.set_secret(key, "vendor-key-1234")

    stored = store.get_secret(key)

    assert stored is not None
    assert stored.reveal() == "vendor-key-1234"


def test_the_two_vendor_secrets_are_independent() -> None:
    """Setting one must not disturb the other, or a save wipes a key."""

    store = InMemorySettingsStore()
    store.set_secret(SecretKey.DEEPGRAM_API_KEY, "deepgram-key")
    store.set_secret(SecretKey.ASSEMBLYAI_API_KEY, "assemblyai-key")

    assert store.get_secret(SecretKey.DEEPGRAM_API_KEY).reveal() == "deepgram-key"
    assert store.get_secret(SecretKey.ASSEMBLYAI_API_KEY).reveal() == "assemblyai-key"


def test_the_live_path_credential_is_not_orphaned() -> None:
    """`ASR_VENDOR_API_KEY` still serves the live path and must survive."""

    assert SecretKey.ASR_VENDOR_API_KEY.value == "asr_vendor_api_key"


@pytest.mark.parametrize(
    ("key", "variable"),
    [
        (SecretKey.DEEPGRAM_API_KEY, "ELICTA_DEEPGRAM_API_KEY"),
        (SecretKey.ASSEMBLYAI_API_KEY, "ELICTA_ASSEMBLYAI_API_KEY"),
    ],
)
def test_a_headless_deployment_can_supply_the_key_by_environment(
    key: SecretKey, variable: str
) -> None:
    from app.modules.settings.store import _ENV_FALLBACK

    assert variable in _ENV_FALLBACK[key]
