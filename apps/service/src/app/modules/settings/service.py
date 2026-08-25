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
    SecretValue,
    ServiceSettings,
    SettingsUpdateRequest,
)
from .probes import ProbeFailed
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

    reachable, detail = await verdict_on(store.get_secret(key), probe)
    return ConnectionCheck(key=key, reachable=reachable, detail=detail)


async def verdict_on(
    secret: SecretValue | None, probe: object | None
) -> tuple[bool, str]:
    """Whether a credential works, and the sentence to show the operator.

    Extracted so the pooled speech keys answer in exactly the same words as
    the fixed ones. They are reached through different routes and carry
    different identifiers, but "the vendor rejected this" is one fact and had
    no business being phrased twice.
    """

    if secret is None:
        return False, "No credential is configured."

    if probe is None:
        return (
            False,
            f"Configured (…{secret.hint()}), but not verified: no probe is wired for this vendor.",
        )

    try:
        await probe(secret.reveal())  # type: ignore[operator]
    except ProbeFailed as exc:
        # The probe ran and came back with a verdict. Its message is already
        # written for an operator -- it names the vendor and what the vendor
        # said -- so it is passed through as-is. Prefixing the exception class
        # put `ProbeFailed:` into a form field, which reads as a crash rather
        # than an answer and tells the operator nothing they can act on.
        return False, str(exc)
    except Exception as exc:
        # Anything else is the probe itself misbehaving rather than the vendor
        # answering, and there the type is the only clue worth keeping. The
        # vendor's error, never the credential: `exc` is formatted by type and
        # message, and a credential is not part of either.
        return False, f"{type(exc).__name__}: {exc}"

    return True, f"Verified (…{secret.hint()})."
