"""Applying a settings change, and testing a credential.

Kept out of the router so the ordering rule below is testable on its own:
non-secret fields are written first, then secrets, then the state is read
back. Reading back rather than assembling a response from the request is what
makes the returned hint correct — the store, not the caller, decides what is
now configured.
"""

from __future__ import annotations

from .models import (
    ConnectionCheck,
    SecretKey,
    ServiceSettings,
    SettingsUpdateRequest,
)
from .store import SettingsStore


async def apply_settings_update(
    store: SettingsStore, payload: SettingsUpdateRequest
) -> ServiceSettings:
    """Apply one settings save.

    Omitted sections are left untouched: the admin UI saves one panel at a
    time and must never blank a section it did not render.
    """

    if payload.inference is not None:
        store.write_inference(payload.inference)
    if payload.vendors is not None:
        store.write_vendors(payload.vendors)
    if payload.connectors is not None:
        store.write_connectors(payload.connectors)
    if payload.documents is not None:
        store.write_documents(payload.documents)
    if payload.consent is not None:
        store.write_consent(payload.consent)
    for update in payload.secrets:
        store.set_secret(update.key, update.value)

    return store.read()


async def check_secret_connection(
    store: SettingsStore, key: SecretKey, probe: object | None = None
) -> ConnectionCheck:
    """Report whether a configured credential works.

    With no `probe` supplied this reports configuration only — an honest
    "configured, not verified" rather than claiming a reachability it never
    tested.
    """

    secret = store.get_secret(key)
    if secret is None:
        return ConnectionCheck(
            key=key, reachable=False, detail="No credential is configured."
        )

    if probe is None:
        return ConnectionCheck(
            key=key,
            reachable=False,
            detail=f"Configured (…{secret.hint()}), but not verified: no probe is wired for this vendor.",
        )

    try:
        await probe(secret.reveal())  # type: ignore[operator]
    except Exception as exc:
        # The vendor's error, never the credential. `exc` is formatted by
        # type and message; a credential is not part of either.
        return ConnectionCheck(
            key=key, reachable=False, detail=f"{type(exc).__name__}: {exc}"
        )

    return ConnectionCheck(
        key=key, reachable=True, detail=f"Verified (…{secret.hint()})."
    )
