"""The settings store seam, and the rules that make secrets safe to hold.

`SettingsStore` is a protocol rather than a class so the durable
implementation can be a platform secret store — the macOS Keychain or Windows
Credential Manager that `core/shared/crypto` already reaches for the database
key — without this package depending on any of it.

`InMemorySettingsStore` is the default. It is a real implementation, not a
stub: an operator who configures a key gets a working service for that
process's lifetime. What it does not do is survive a restart, which is why
`durable` is on the protocol — the admin UI tells the operator plainly when
their settings will not outlive the process, rather than letting them find
out after a restart.

Reading environment variables is kept as a *fallback*, not a competitor. A
value configured in the UI wins, because it is the more specific and more
recent statement of intent; the environment still works for a headless
deployment that has no operator at a screen.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Protocol

from .models import (
    ConnectorSettings,
    InferenceSettings,
    SecretKey,
    SecretStatus,
    SecretValue,
    ServiceSettings,
    VendorSettings,
)

# The environment variable each secret falls back to, so an existing headless
# deployment keeps working unchanged after this module lands.
_ENV_FALLBACK: dict[SecretKey, tuple[str, ...]] = {
    SecretKey.ANTHROPIC_API_KEY: ("ANTHROPIC_API_KEY",),
    # Both names are honoured: the SDK reads ANTHROPIC_AUTH_TOKEN, while this
    # repo's own tooling documents ANTHROPIC_OAUTH_TOKEN for a
    # `claude setup-token` credential.
    SecretKey.ANTHROPIC_OAUTH_TOKEN: ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_OAUTH_TOKEN"),
    SecretKey.ASR_VENDOR_API_KEY: ("ELICTA_ASR_API_KEY",),
    SecretKey.CAPTURE_VENDOR_API_KEY: ("ELICTA_CAPTURE_API_KEY",),
}


class SettingsStore(Protocol):
    """Reads and writes operator-administered settings."""

    @property
    def durable(self) -> bool:
        """Whether values survive a service restart."""

    def read(self) -> ServiceSettings: ...

    def write_inference(self, inference: InferenceSettings) -> None: ...

    def write_vendors(self, vendors: VendorSettings) -> None: ...

    def write_connectors(self, connectors: ConnectorSettings) -> None: ...

    def set_secret(self, key: SecretKey, value: str) -> None:
        """Store a secret. An empty value clears it."""

    def get_secret(self, key: SecretKey) -> SecretValue | None:
        """The secret, from the store or the environment fallback."""


class InMemorySettingsStore:
    """Process-lifetime settings. Durable only for as long as the service runs."""

    def __init__(self, *, read_environment: bool = True) -> None:
        self._inference = InferenceSettings()
        self._vendors = VendorSettings()
        self._connectors = ConnectorSettings()
        self._secrets: dict[SecretKey, SecretValue] = {}
        self._secret_updated: dict[SecretKey, datetime] = {}
        self._updated_at: datetime | None = None
        self._read_environment = read_environment

    @property
    def durable(self) -> bool:
        return False

    def read(self) -> ServiceSettings:
        return ServiceSettings(
            inference=self._inference,
            vendors=self._vendors,
            connectors=self._connectors,
            secrets=[self._status(key) for key in SecretKey],
            durable=self.durable,
            updated_at=self._updated_at,
        )

    def _status(self, key: SecretKey) -> SecretStatus:
        secret = self.get_secret(key)
        return SecretStatus(
            key=key,
            configured=secret is not None,
            hint=secret.hint() if secret is not None else None,
            updated_at=self._secret_updated.get(key),
        )

    def write_inference(self, inference: InferenceSettings) -> None:
        self._inference = inference
        self._touch()

    def write_vendors(self, vendors: VendorSettings) -> None:
        self._vendors = vendors
        self._touch()

    def write_connectors(self, connectors: ConnectorSettings) -> None:
        self._connectors = connectors
        self._touch()

    def set_secret(self, key: SecretKey, value: str) -> None:
        if value == "":
            # Clearing is explicit and must actually remove the value —
            # leaving it in place would make the UI lie about what is stored.
            self._secrets.pop(key, None)
            self._secret_updated.pop(key, None)
        else:
            self._secrets[key] = SecretValue(value)
            self._secret_updated[key] = datetime.now(UTC)
        self._touch()

    def get_secret(self, key: SecretKey) -> SecretValue | None:
        stored = self._secrets.get(key)
        if stored is not None:
            return stored
        if not self._read_environment:
            return None
        for name in _ENV_FALLBACK.get(key, ()):
            value = os.environ.get(name)
            if value:
                return SecretValue(value)
        return None

    def _touch(self) -> None:
        self._updated_at = datetime.now(UTC)
