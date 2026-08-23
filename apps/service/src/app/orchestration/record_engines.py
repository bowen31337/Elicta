"""Which batch engines the record path runs, read from the settings.

FR-2.6 runs two engines and T3 requires that they diverge independently, which
is why the vendor list is a setting rather than a constant. Building it from
that setting is what keeps the screen and the behaviour the same thing.

Nothing an operator can save here stops the service starting. Both ways a
selected vendor can be unusable — no credential, or no batch client at all —
produce an engine that fails closed by name on the call, plus a loud startup
log. A form entry that bricks a boot is the wrong shape of failure: the
service is the thing that serves the screen the mistake would be corrected on.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.modules.settings.models import SecretKey, SpeechVendor
from app.orchestration.assemblyai_engines import assemblyai_record_engine
from app.orchestration.deepgram_engines import deepgram_record_engine
from app.orchestration.engines import EngineNotConfiguredError

logger = logging.getLogger(__name__)


class UnconfiguredVendor(Exception):
    """A selected record vendor has no batch client at all.

    Raised per call rather than at startup. Nothing short of code can fix it —
    unlike a missing credential, there is no setting an operator can enter to
    make a vendor with no client exist — but `record_vendors = [deepgram,
    custom]` is a save `ConnectorSettings` explicitly permits, and a saved
    form entry must not be able to stop the service booting. `CUSTOM` is the
    current example: the endpoint is administered, but no client for it lives
    here.
    """


def _no_client_engine(vendor: SpeechVendor) -> Callable[[str, str, list[str]], Awaitable[Any]]:
    """A record-path engine standing in for a selected vendor with no client.

    Fails on the call, by name, exactly as the missing-credential stand-in
    does — `run_record_path_transcription` persists that as a `FAILED`
    transcript for this engine, so the gap is visible on the recording screen
    instead of as a service that will not start.
    """

    async def transcribe(session_id: str, audio_ref: str, keyterms: list[str]) -> Any:
        raise UnconfiguredVendor(
            f"{vendor.value}: selected as a record engine, but no batch client "
            "exists for it — no credential makes one appear, so this needs a "
            "supported vendor selected on the Settings screen"
        )

    return transcribe


def _credential_checked(
    name: str,
    key: SecretKey,
    store: Any,
    transcribe: Callable[[str, str, list[str]], Awaitable[Any]],
) -> Callable[[str, str, list[str]], Awaitable[Any]]:
    """The vendor's own engine, refused by name while its credential is absent.

    Checked on the call and not at startup, so a key entered on the Settings
    screen after the service came up takes effect without a restart —
    the same promise `SettingsBackedClient` keeps for inference, and the
    reason the engine below is the real one rather than a stand-in chosen
    from what happened to be configured at boot.

    The vendor clients each refuse a missing credential before touching the
    network too. This wrapper exists for what it *says*: it names the engine
    and the setting that would enable it, in the sentence a `FAILED`
    transcript carries to the recording screen, rather than the vendor's own
    "no credential is configured".
    """

    async def call(session_id: str, audio_ref: str, keyterms: list[str]) -> Any:
        if store.get_secret(key) is None:
            raise EngineNotConfiguredError(
                f"the {name} record-path engine",
                f"a credential ({key.value}) to authenticate with",
            )
        return await transcribe(session_id, audio_ref, keyterms)

    return call


_FACTORIES: dict[SpeechVendor, tuple[str, SecretKey, Any]] = {
    SpeechVendor.DEEPGRAM: ("deepgram", SecretKey.DEEPGRAM_API_KEY, deepgram_record_engine),
    SpeechVendor.ASSEMBLYAI: (
        "assemblyai",
        SecretKey.ASSEMBLYAI_API_KEY,
        assemblyai_record_engine,
    ),
}


def build_record_engines(
    store: Any, read_audio: Callable[[str], bytes]
) -> list[tuple[str, Any]]:
    """One `(name, transcribe)` pair per selected vendor, in the configured order.

    Never raises. A vendor with no client, and a vendor with a client but no
    credential, both still get an engine — one that fails closed, by name, the
    moment it is called — so an unusable speech setting behaves exactly like
    an unconfigured inference key does elsewhere in this service: a startup
    warning and an honest per-call failure, not a service that will not start.

    The credential is read per call rather than here, so one entered after
    startup takes effect without a restart.
    """

    engines: list[tuple[str, Any]] = []
    for vendor in store.read().connectors.record_vendors:
        factory = _FACTORIES.get(vendor)
        if factory is None:
            logger.error(
                "startup: %s is selected as a record-path engine and no batch "
                "client exists for it — it will fail closed on every call, and "
                "no credential can change that; select a supported vendor",
                vendor.value,
            )
            engines.append((vendor.value, _no_client_engine(vendor)))
            continue
        name, key, build = factory
        if store.get_secret(key) is None:
            logger.warning(
                "startup: %s selected as a record-path engine, but %s is not "
                "configured — it will fail closed on every call until it is",
                name,
                key.value,
            )
        engines.append(
            (name, _credential_checked(name, key, store, build(read_audio, store, name=name)))
        )
    return engines


def describe_record_engines(store: Any) -> list[str]:
    """One label per engine `build_record_engines` will build, for the startup log.

    A separate pass over the same settings rather than a richer return type
    from `build_record_engines`: that function's `list[tuple[str, Any]]` is
    the shape both `build_app` and its own tests expect, and threading status
    metadata through it would change that shape for every caller to serve
    one log line. `store.get_secret` is re-read here exactly as it is in
    `build_record_engines`, so the label can never disagree with which engine
    was actually built. It describes the moment the service started: a
    credential entered later takes effect on the next call, and this line
    does not go back and correct itself.
    """

    labels: list[str] = []
    for vendor in store.read().connectors.record_vendors:
        factory = _FACTORIES.get(vendor)
        if factory is None:
            labels.append(f"{vendor.value} (NO CLIENT, fails closed)")
            continue
        name, key, _build = factory
        status = "configured" if store.get_secret(key) is not None else "NO CREDENTIAL, fails closed"
        labels.append(f"{name} ({status})")
    return labels
