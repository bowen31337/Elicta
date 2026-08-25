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
    AuthMode,
    ConnectorSettings,
    ConsentSettings,
    DocumentSourceSettings,
    InferenceSettings,
    SecretKey,
    SecretStatus,
    SecretValue,
    ServiceSettings,
    StorageSettings,
    VendorSettings,
)
from .speech_credentials import SpeechCredentialPool

# The environment variable each secret falls back to, so an existing headless
# deployment keeps working unchanged after this module lands.
_ENV_FALLBACK: dict[SecretKey, tuple[str, ...]] = {
    SecretKey.ANTHROPIC_API_KEY: ("ANTHROPIC_API_KEY",),
    # Both names are honoured: the SDK reads ANTHROPIC_AUTH_TOKEN, while this
    # repo's own tooling documents ANTHROPIC_OAUTH_TOKEN for a
    # `claude setup-token` credential.
    SecretKey.ANTHROPIC_OAUTH_TOKEN: ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_OAUTH_TOKEN"),
    SecretKey.ASR_VENDOR_API_KEY: ("ELICTA_ASR_API_KEY",),
    SecretKey.DEEPGRAM_API_KEY: ("ELICTA_DEEPGRAM_API_KEY",),
    SecretKey.ASSEMBLYAI_API_KEY: ("ELICTA_ASSEMBLYAI_API_KEY",),
    SecretKey.CAPTURE_VENDOR_API_KEY: ("ELICTA_CAPTURE_API_KEY",),
    SecretKey.MICROSOFT_GRAPH_CLIENT_SECRET: ("ELICTA_GRAPH_CLIENT_SECRET",),
    SecretKey.STATE_DATABASE_URL: ("DATABASE_URL",),
}

#: The non-secret halves of the document connector. Same contract as the
#: secrets above: the environment is a fallback for a headless deployment, and
#: anything set through the UI wins.
_DOCUMENT_ENV = {
    "tenant_id": "ELICTA_GRAPH_TENANT_ID",
    "client_id": "ELICTA_GRAPH_CLIENT_ID",
}


def _storage_view(configured: SecretValue | None) -> StorageSettings:
    """What the settings say about the database, safe to hand back.

    The URL is a credential, so this resolves what would actually be used and
    strips the password out of it. Nothing here is writable: the URL is set as
    a secret, which is the only shape that keeps it out of a read.
    """

    from app.persistence.store import redact_database_url, resolve_database_url

    return StorageSettings(
        database=redact_database_url(
            resolve_database_url(configured.reveal() if configured else None)
        )
    )


def _inference_with_environment(
    configured: InferenceSettings, read_environment: bool, written: bool
) -> InferenceSettings:
    """Fill the model from the environment when nobody has chosen one.

    `written` is the load-bearing argument. The field has a built-in default,
    so "what the settings say" and "what somebody chose" were the same value,
    and `ELICTA_INFERENCE_MODEL` lost to a default it was meant to override —
    silently, which is the part that cost an afternoon.
    """

    if written or not read_environment:
        return configured

    update: dict[str, object] = {}
    chosen = os.environ.get("ELICTA_INFERENCE_MODEL")
    if chosen:
        update["model"] = chosen

    # A deployment given only a bearer token cannot select the mode that uses
    # it — `.env.example` says the Settings screen selects it, which a headless
    # service does not have. Defaulting to `api_key` there fails closed with
    # "no api key configured" while holding a working token. With both present
    # there is a genuine choice and it is not ours to make.
    has_key = any(os.environ.get(name) for name in _ENV_FALLBACK[SecretKey.ANTHROPIC_API_KEY])
    has_token = any(
        os.environ.get(name) for name in _ENV_FALLBACK[SecretKey.ANTHROPIC_OAUTH_TOKEN]
    )
    if has_token and not has_key:
        update["auth_mode"] = AuthMode.OAUTH_TOKEN

    return configured.model_copy(update=update) if update else configured


def _documents_with_environment(
    configured: DocumentSourceSettings, read_environment: bool
) -> DocumentSourceSettings:
    if not read_environment:
        return configured
    filled = {
        field: getattr(configured, field) or os.environ.get(name) or None
        for field, name in _DOCUMENT_ENV.items()
    }
    return configured.model_copy(update=filled)


class SettingsStore(Protocol):
    """Reads and writes operator-administered settings."""

    @property
    def durable(self) -> bool:
        """Whether values survive a service restart."""

    def read(self) -> ServiceSettings: ...

    def write_inference(self, inference: InferenceSettings) -> None: ...

    def write_vendors(self, vendors: VendorSettings) -> None: ...

    def write_connectors(self, connectors: ConnectorSettings) -> None: ...

    def write_documents(self, documents: DocumentSourceSettings) -> None: ...

    def write_consent(self, consent: ConsentSettings) -> None: ...

    def set_secret(self, key: SecretKey, value: str) -> None:
        """Store a secret. An empty value clears it."""

    def get_secret(self, key: SecretKey) -> SecretValue | None:
        """The secret, from the store or the environment fallback."""


class InMemorySettingsStore:
    """Process-lifetime settings. Durable only for as long as the service runs."""

    def __init__(self, *, read_environment: bool = True) -> None:
        self._inference = InferenceSettings()
        self._inference_written = False
        self._vendors = VendorSettings()
        self._connectors = ConnectorSettings()
        self._documents = DocumentSourceSettings()
        self._consent = ConsentSettings()
        # Empty rather than absent: an empty pool answers "nothing
        # configured" in the same shape a populated one does, so the missing
        # case does not have to be handled by every caller.
        self._speech = SpeechCredentialPool()
        self._secrets: dict[SecretKey, SecretValue] = {}
        self._secret_updated: dict[SecretKey, datetime] = {}
        self._updated_at: datetime | None = None
        self._read_environment = read_environment

    @property
    def durable(self) -> bool:
        return False

    def read(self) -> ServiceSettings:
        return ServiceSettings(
            inference=_inference_with_environment(
                self._inference, self._read_environment, self._inference_written
            ),
            vendors=self._vendors,
            connectors=self._connectors,
            documents=_documents_with_environment(self._documents, self._read_environment),
            storage=_storage_view(self.get_secret(SecretKey.STATE_DATABASE_URL)),
            consent=self._consent,
            speech=self._speech,
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

    def write_speech(self, speech: SpeechCredentialPool) -> None:
        self._speech = speech

    def write_inference(self, inference: InferenceSettings) -> None:
        self._inference = inference
        self._inference_written = True
        self._touch()

    def write_vendors(self, vendors: VendorSettings) -> None:
        self._vendors = vendors
        self._touch()

    def write_connectors(self, connectors: ConnectorSettings) -> None:
        self._connectors = connectors
        self._touch()

    def write_documents(self, documents: DocumentSourceSettings) -> None:
        self._documents = documents
        self._touch()

    def write_consent(self, consent: ConsentSettings) -> None:
        self._consent = consent
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
