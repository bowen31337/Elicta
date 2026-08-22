"""Which batch engines the record path runs, read from the settings.

FR-2.6 runs two engines and T3 requires that they diverge independently, which
is why the vendor list is a setting rather than a constant. Building it from
that setting is what keeps the screen and the behaviour the same thing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.modules.settings.models import SecretKey, SpeechVendor
from app.orchestration.assemblyai_engines import assemblyai_record_engine
from app.orchestration.deepgram_engines import deepgram_record_engine


class UnconfiguredVendor(Exception):
    """A selected record vendor cannot run.

    Raised at startup rather than skipped, because a silently-dropped engine
    leaves the settings claiming a pair and the recording screen showing one
    transcript with nothing to compare it against — which reads as an engine
    that failed rather than one that was never built.
    """


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
    """One `(name, transcribe)` pair per selected vendor, in the configured order."""

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
            raise UnconfiguredVendor(
                f"{name}: selected as a record engine, but {key.value} is not "
                "configured"
            )
        engines.append((name, build(read_audio, store, name=name)))
    return engines
