"""Adding, changing and removing the credentials in the pool.

Kept apart from `speech_credentials`, which is the pure shape and the
selection rule and has no idea a store exists — the same split `probes` and
`service` already follow, and what lets the selection logic be tested without
one.

Two invariants live here because both span the two tables a credential
occupies. Adding writes the value before the metadata that references it, so a
crash between them leaves an unreferenced secret rather than a listed
credential with nothing behind it — the second is an intermittent failure on a
rotation, the first is invisible. Removing does the reverse, and takes the
secret with it: an orphaned value for an id nothing references is a live
credential nobody can see.
"""

from __future__ import annotations

import secrets as _secrets
from typing import Any

from pydantic import BaseModel, Field

from .models import SpeechVendor
from .speech_credentials import (
    SelectionPolicy,
    SpeechCredential,
    SpeechCredentialPool,
    secret_key_for,
)


class SpeechCredentialCreate(BaseModel):
    """A key an operator is adding, with the value they typed."""

    vendor: SpeechVendor
    label: str = Field(default="", max_length=120)
    value: str = Field(min_length=1)


class SpeechCredentialUpdate(BaseModel):
    """What may be changed after the fact. Not the value: replace it instead.

    Editing a stored secret in place would need the old one to be readable to
    show what is being edited, and it is deliberately not.
    """

    label: str | None = Field(default=None, max_length=120)
    enabled: bool | None = None


class SpeechPolicyUpdate(BaseModel):
    policy: SelectionPolicy
    active_id: str | None = None


class SpeechCredentialView(BaseModel):
    """One credential as the screen sees it — never the value."""

    id: str
    vendor: SpeechVendor
    label: str
    enabled: bool
    hint: str | None = Field(
        default=None,
        description="Last four characters of the stored value, or null if it is gone.",
    )


def _new_id() -> str:
    """Short, unguessable, and inside what `secret_key_for` will accept."""

    return _secrets.token_hex(6)


def _view(store: Any, credential: SpeechCredential) -> SpeechCredentialView:
    stored = store.get_secret(secret_key_for(credential.id))
    return SpeechCredentialView(
        id=credential.id,
        vendor=credential.vendor,
        label=credential.label,
        enabled=credential.enabled,
        hint=stored.hint() if stored is not None else None,
    )


def _pool_of(store: Any) -> SpeechCredentialPool:
    return store.read().speech or SpeechCredentialPool()


def add_credential(store: Any, payload: SpeechCredentialCreate) -> SpeechCredentialView:
    credential = SpeechCredential(
        id=_new_id(), vendor=payload.vendor, label=payload.label, enabled=True
    )
    # Value first: a crash between the two writes then leaves an unreferenced
    # secret rather than a credential listed with nothing behind it.
    store.set_secret(secret_key_for(credential.id), payload.value)
    pool = _pool_of(store)
    store.write_speech(
        pool.model_copy(update={"credentials": (*pool.credentials, credential)})
    )
    return _view(store, credential)


def update_credential(
    store: Any, credential_id: str, payload: SpeechCredentialUpdate
) -> SpeechCredentialView:
    pool = _pool_of(store)
    updated: SpeechCredential | None = None
    rebuilt: list[SpeechCredential] = []
    for candidate in pool.credentials:
        if candidate.id != credential_id:
            rebuilt.append(candidate)
            continue
        changes: dict[str, Any] = {}
        if payload.label is not None:
            changes["label"] = payload.label
        if payload.enabled is not None:
            changes["enabled"] = payload.enabled
        updated = candidate.model_copy(update=changes)
        rebuilt.append(updated)

    if updated is None:
        raise KeyError(f"no speech credential {credential_id!r}")

    store.write_speech(pool.model_copy(update={"credentials": tuple(rebuilt)}))
    return _view(store, updated)


def remove_credential(store: Any, credential_id: str) -> None:
    pool = _pool_of(store)
    remaining = tuple(c for c in pool.credentials if c.id != credential_id)
    if len(remaining) == len(pool.credentials):
        raise KeyError(f"no speech credential {credential_id!r}")

    changes: dict[str, Any] = {"credentials": remaining}
    if pool.active_id == credential_id:
        # Otherwise `single` keeps naming a credential that is gone, and falls
        # through to whichever happens to be first — a silent change of which
        # key serves.
        changes["active_id"] = None
    store.write_speech(pool.model_copy(update=changes))
    # Metadata first here, so a crash between the writes leaves an
    # unreferenced secret rather than a listed credential with none. An empty
    # value is how this store clears one; there is no separate delete.
    store.set_secret(secret_key_for(credential_id), "")


def set_policy(store: Any, payload: SpeechPolicyUpdate) -> SpeechCredentialPool:
    pool = _pool_of(store)
    updated = pool.model_copy(
        update={"policy": payload.policy, "active_id": payload.active_id}
    )
    store.write_speech(updated)
    return updated
