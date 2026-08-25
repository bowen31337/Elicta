"""The key string a transcription call actually gets.

`SpeechCredentialPool` decides *which* credential; this turns that into the
secret, and is where a deployment that predates the pool keeps working.

Migration is on read rather than by rewriting the store. A settings file is
the last thing that should be edited by a version that might be rolled back,
and a fixed `deepgram_api_key` costs one lookup to honour — so an existing
deployment keeps transcribing with no action from anybody, and stops using the
fixed key the moment a pooled one exists.
"""

from __future__ import annotations

from typing import Any

from .models import SecretKey, SpeechVendor
from .speech_credentials import SpeechCredentialPool, secret_key_for

#: What each vendor's key was called before the pool. Consulted only when the
#: pool has nothing for that vendor.
_LEGACY_KEY: dict[SpeechVendor, SecretKey] = {
    SpeechVendor.DEEPGRAM: SecretKey.DEEPGRAM_API_KEY,
    SpeechVendor.ASSEMBLYAI: SecretKey.ASSEMBLYAI_API_KEY,
}


def resolve_speech_key(
    store: Any,
    vendor: SpeechVendor,
    *,
    pool: SpeechCredentialPool | None = None,
) -> str | None:
    """The secret the next call to `vendor` should authenticate with.

    `None` when nothing is configured. Deliberately not an exception: the
    stages above already know how to say which stage stopped and why, and a
    stack trace from the point of transcription says less than they do.
    """

    pool = pool if pool is not None else getattr(store.read(), "speech", None)
    if pool is not None:
        # Every enabled credential is tried, not only the one whose turn it
        # is: metadata and secret live in different tables and can disagree,
        # and a credential listed with no stored value would otherwise hand
        # back nothing on its turn — an intermittent outage on a rotation,
        # which is the hardest kind of failure to attribute.
        for _ in range(len(pool.enabled_for(vendor)) or 0):
            candidate = pool.next_for(vendor)
            if candidate is None:
                break
            secret = store.get_secret(secret_key_for(candidate.id))
            if secret is not None:
                return secret.reveal()

    legacy = _LEGACY_KEY.get(vendor)
    if legacy is not None:
        secret = store.get_secret(legacy)
        if secret is not None:
            return secret.reveal()
    return None
