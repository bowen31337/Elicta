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


def test_each_vendor_key_is_probed_against_its_own_vendor() -> None:
    """Not against whichever vendor the live path happens to name.

    The single ASR key was probed against `connectors.live_vendor`. With a key
    per vendor that is simply the wrong endpoint: an AssemblyAI key checked
    against Deepgram returns 401 and the screen calls a working key broken.
    """

    from app.composition import _vendor_probe_for
    from app.modules.settings.probes import probe_assemblyai, probe_deepgram
    from app.modules.settings.store import InMemorySettingsStore

    store = InMemorySettingsStore()

    assert _vendor_probe_for(SecretKey.DEEPGRAM_API_KEY, store) is probe_deepgram
    assert _vendor_probe_for(SecretKey.ASSEMBLYAI_API_KEY, store) is probe_assemblyai


def test_the_generic_key_is_probed_against_the_provider_the_live_path_drives() -> None:
    """There is no vendor setting for it to follow any more.

    It followed `connectors.live_vendor`, which the live path did not: the
    recogniser was Deepgram whatever that said. The pool decides the provider
    now — choosing a credential is choosing a vendor — so this key, which
    predates the pool, is probed against the provider the live path can
    actually drive.
    """

    from app.composition import _vendor_probe_for
    from app.modules.settings.probes import probe_deepgram
    from app.modules.settings.store import InMemorySettingsStore

    store = InMemorySettingsStore()

    assert _vendor_probe_for(SecretKey.ASR_VENDOR_API_KEY, store) is probe_deepgram
