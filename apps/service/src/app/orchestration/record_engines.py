"""Which batch engines the record path runs, read from the settings.

FR-2.6 runs two engines and T3 requires that they diverge independently, which
is why the vendor list is a setting rather than a constant. Building it from
that setting is what keeps the screen and the behaviour the same thing.
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

    Raised at startup, because nothing short of code can fix it: unlike a
    missing credential, there is no setting an operator can enter to make a
    vendor with no client exist. `CUSTOM` is the current example — the
    endpoint is administered, but no client for it lives here.
    """


def _unconfigured_credential_engine(
    name: str, key: SecretKey
) -> Callable[[str, str, list[str]], Awaitable[Any]]:
    """A record-path engine standing in for a selected vendor with no credential.

    Built rather than refused at startup: an unconfigured Anthropic key does
    not stop this service either — "the service still starts and serves its
    full API" — and a settings UI means the credential can arrive after
    startup exactly as it does for inference. Failing here, per call, keeps
    the settings' claim of two engines honest without stopping the service —
    `run_record_path_transcription` already persists this as a `FAILED`
    transcript per engine, so the gap surfaces on the recording screen
    rather than only in a log.
    """

    async def transcribe(session_id: str, audio_ref: str, keyterms: list[str]) -> Any:
        raise EngineNotConfiguredError(
            f"the {name} record-path engine",
            f"a credential ({key.value}) to authenticate with",
        )

    return transcribe


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

    A vendor with no client at all (`UnconfiguredVendor`) still stops
    startup — that is a configuration error nothing can recover from while
    running. A vendor with a client but no credential does not: it still
    gets an engine, one that fails closed, by name, the moment it is called,
    so an unconfigured speech key behaves exactly like an unconfigured
    inference key does elsewhere in this service — a startup warning and an
    honest per-call failure, not a service that will not start.
    """

    engines: list[tuple[str, Any]] = []
    for vendor in store.read().connectors.record_vendors:
        factory = _FACTORIES.get(vendor)
        if factory is None:
            raise UnconfiguredVendor(
                f"{vendor.value}: selected as a record engine, but no batch "
                "client exists for it"
            )
        name, key, build = factory
        if store.get_secret(key) is None:
            logger.warning(
                "startup: %s selected as a record-path engine, but %s is not "
                "configured — it will fail closed on every call until it is",
                name,
                key.value,
            )
            engines.append((name, _unconfigured_credential_engine(name, key)))
            continue
        engines.append((name, build(read_audio, store, name=name)))
    return engines


def describe_record_engines(store: Any) -> list[str]:
    """One label per engine `build_record_engines` will build, for the startup log.

    A separate pass over the same settings rather than a richer return type
    from `build_record_engines`: that function's `list[tuple[str, Any]]` is
    the shape both `build_app` and its own tests expect, and threading status
    metadata through it would change that shape for every caller to serve
    one log line. `store.get_secret` is re-read here exactly as it is in
    `build_record_engines`, so the label can never disagree with which engine
    was actually built.
    """

    labels: list[str] = []
    for vendor in store.read().connectors.record_vendors:
        factory = _FACTORIES.get(vendor)
        if factory is None:
            continue  # build_record_engines raises for this before logging runs
        name, key, _build = factory
        status = "configured" if store.get_secret(key) is not None else "NO CREDENTIAL, fails closed"
        labels.append(f"{name} ({status})")
    return labels
