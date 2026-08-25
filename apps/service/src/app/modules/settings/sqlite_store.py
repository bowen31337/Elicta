"""SQLite-backed settings, with secret values encrypted at rest.

The in-memory store loses everything on restart, which the admin screen had to
warn about. This one persists — and persistence is exactly what makes the
encryption non-optional. A settings row holding a plaintext vendor credential
turns a stolen file, a backup, or a stray `sqlite3` session into a credential
leak, so writing secrets in the clear here would be a *regression* on the
in-memory store rather than an improvement on it (NFR-2.5).

**How the key is handled.** Values are encrypted with Fernet (AES-128-CBC plus
an HMAC, so a tampered ciphertext fails loudly rather than decrypting to
garbage). The key comes from a managed secret store when
`ELICTA_SETTINGS_KEY_COMMAND` is set, from `ELICTA_SETTINGS_KEY` if that is
set instead; otherwise it is
generated once into a `0600` key file beside the database. That file is the
thing to protect — it is deliberately *not* stored in the database, because a
key sitting next to the ciphertext it protects is not a key.

This mirrors the shape `core/shared/crypto` already uses on the device, where
a SQLCipher database is unlocked with a key held in the platform keystore. The
key store there is the OS keychain; here it is a file, because a service tier
has no keychain to talk to. Substituting a KMS or a mounted secret is a matter
of pointing `ELICTA_SETTINGS_KEY` at one.

**A key change is not a data loss.** A secret that cannot be decrypted with
the current key is reported as *not configured* rather than raising, so
rotating or losing the key degrades to "re-enter your credentials" instead of
a service that will not start.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .models import (
    ConnectorSettings,
    ConsentSettings,
    DocumentSourceSettings,
    InferenceSettings,
    SecretKey,
    SecretStatus,
    SecretValue,
    ServiceSettings,
    VendorSettings,
)
from .speech_credentials import SpeechCredentialPool

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS secrets (
    key        TEXT PRIMARY KEY,
    ciphertext BLOB NOT NULL,
    updated_at TEXT NOT NULL
);
"""

def _key_text(key: object) -> str:
    """The string a secret is stored under.

    The table has always been keyed by plain string; only `SecretKey`
    constrained it. Speech credentials address their secrets by a derived name
    (`asr.<id>`), so both forms reach here — an enum member and the string it
    stands for store and read identically.
    """

    return key.value if isinstance(key, SecretKey) else str(key)


KEY_ENV_VAR = "ELICTA_SETTINGS_KEY"
KEY_COMMAND_ENV_VAR = "ELICTA_SETTINGS_KEY_COMMAND"


class SettingsKeyUnavailableError(RuntimeError):
    """The configured managed secret store could not be reached.

    Raised rather than falling back to a generated local key. A fallback would
    quietly re-encrypt every secret under a key the secret store does not
    know — so the settings would appear to work, and would be unreadable by
    every other node in the deployment, which is a far worse outcome than a
    service that refuses to start and says why.
    """


def _key_from_command(command: str) -> bytes:
    """Runs the operator's secret-store command and takes its output as the key.

    A command rather than an integration with any particular vendor. Every
    secret manager worth using already ships a CLI that prints a secret to
    stdout — `op read`, `vault kv get -field`, `aws secretsmanager
    get-secret-value --query SecretString`, `gcloud secrets versions access` —
    so one seam covers all of them, and covers the next one too. Building
    against a specific vendor's SDK would have meant choosing which customers
    get supported.

    Run through the shell so that pipes and flags work as the operator wrote
    them. That is a deliberate trade: this value comes from the deployment's
    own configuration, exactly like the command line that started the service,
    and is not reachable by any request.
    """

    import subprocess

    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            timeout=30,
            check=True,
        )
    except subprocess.TimeoutExpired as error:
        raise SettingsKeyUnavailableError(
            f"{KEY_COMMAND_ENV_VAR} timed out after 30s"
        ) from error
    except subprocess.CalledProcessError as error:
        # stderr, not stdout: whatever the command printed on the way to
        # failing is the diagnosis, and stdout may contain key material.
        detail = error.stderr.decode(errors="replace").strip()
        raise SettingsKeyUnavailableError(
            f"{KEY_COMMAND_ENV_VAR} exited {error.returncode}: {detail}"
        ) from error

    key = completed.stdout.strip()
    if not key:
        raise SettingsKeyUnavailableError(f"{KEY_COMMAND_ENV_VAR} produced no output")
    return key


def _load_or_create_key(database_path: Path) -> bytes:
    """The encryption key.

    Three sources, in the order a deployment should prefer them:

    1. `ELICTA_SETTINGS_KEY_COMMAND` — a command that fetches the key from a
       managed secret store. This is the shared-deployment answer: the key
       never lands on any node's disk, and rotating it is a secret-store
       operation rather than a fleet-wide file edit.
    2. `ELICTA_SETTINGS_KEY` — the key itself. Fine for a container whose
       environment is already injected from a secret store.
    3. A 0600 file beside the database, generated on first run. This is the
       single-user desktop case, where there is no secret store and the
       threat model is another user on the same machine.
    """

    command = os.environ.get(KEY_COMMAND_ENV_VAR)
    if command:
        return _key_from_command(command)

    configured = os.environ.get(KEY_ENV_VAR)
    if configured:
        return configured.encode()

    key_path = database_path.with_suffix(".key")
    if key_path.exists():
        return key_path.read_bytes().strip()

    key = Fernet.generate_key()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    # Written before the mode is tightened would leave a window where the key
    # is world-readable, so create it closed and write into it.
    handle = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "wb") as file:
        file.write(key)
    logger.info("settings: generated a new encryption key at %s", key_path)
    return key


class SqliteSettingsStore:
    """Settings persisted to SQLite, with secrets encrypted at rest."""

    def __init__(self, database_path: str | Path, *, read_environment: bool = True) -> None:
        self._path = Path(database_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(_load_or_create_key(self._path))
        self._read_environment = read_environment
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        # Concurrent readers alongside a writer, and a durable commit — a
        # settings save that survives the response but not a power cut would
        # be worse than not persisting at all.
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @property
    def durable(self) -> bool:
        return True

    # -- non-secret values -------------------------------------------------

    def _read_json(self, key: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def _write_json(self, key: str, payload: dict) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (key, json.dumps(payload), datetime.now(UTC).isoformat()),
            )

    def write_speech(self, speech: SpeechCredentialPool) -> None:
        self._write_json("speech", speech.model_dump(mode="json"))

    def write_inference(self, inference: InferenceSettings) -> None:
        self._write_json("inference", inference.model_dump(mode="json"))

    def write_vendors(self, vendors: VendorSettings) -> None:
        self._write_json("vendors", vendors.model_dump(mode="json"))

    def write_connectors(self, connectors: ConnectorSettings) -> None:
        self._write_json("connectors", connectors.model_dump(mode="json"))

    def write_documents(self, documents: DocumentSourceSettings) -> None:
        self._write_json("documents", documents.model_dump(mode="json"))

    def write_consent(self, consent: ConsentSettings) -> None:
        self._write_json("consent", consent.model_dump(mode="json"))

    # -- secrets -----------------------------------------------------------

    def set_secret(self, key: SecretKey, value: str) -> None:
        with self._connect() as connection:
            if value == "":
                connection.execute("DELETE FROM secrets WHERE key = ?", (_key_text(key),))
                return
            connection.execute(
                "INSERT INTO secrets (key, ciphertext, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET ciphertext = excluded.ciphertext, "
                "updated_at = excluded.updated_at",
                (
                    _key_text(key),
                    self._fernet.encrypt(value.encode()),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def get_secret(self, key: SecretKey) -> SecretValue | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT ciphertext FROM secrets WHERE key = ?", (_key_text(key),)
            ).fetchone()

        if row is not None:
            try:
                return SecretValue(self._fernet.decrypt(row[0]).decode())
            except InvalidToken:
                # A rotated or lost key, or a tampered row. Reporting "not
                # configured" turns this into "re-enter your credential"
                # rather than a service that will not start.
                logger.warning(
                    "settings: %s could not be decrypted with the current key", _key_text(key)
                )
                return None

        if not self._read_environment:
            return None
        from .store import _ENV_FALLBACK

        for name in _ENV_FALLBACK.get(key, ()):
            value = os.environ.get(name)
            if value:
                return SecretValue(value)
        return None

    # -- assembled view ----------------------------------------------------

    def read(self) -> ServiceSettings:
        # Imported here for the same reason `_ENV_FALLBACK` is: `store` owns
        # the environment-fallback contract, and importing it at module scope
        # would make the two stores import each other.
        from .store import (
            _documents_with_environment,
            _inference_with_environment,
            _storage_view,
        )

        inference = self._read_json("inference")
        vendors = self._read_json("vendors")
        connectors = self._read_json("connectors")
        documents = self._read_json("documents")
        consent = self._read_json("consent")
        speech = self._read_json("speech")

        with self._connect() as connection:
            updated = connection.execute(
                "SELECT MAX(updated_at) FROM ("
                "  SELECT updated_at FROM settings UNION ALL"
                "  SELECT updated_at FROM secrets)"
            ).fetchone()[0]
            secret_times = dict(
                connection.execute("SELECT key, updated_at FROM secrets").fetchall()
            )

        statuses = []
        for key in SecretKey:
            secret = self.get_secret(key)
            stamp = secret_times.get(key.value)
            statuses.append(
                SecretStatus(
                    key=key,
                    configured=secret is not None,
                    hint=secret.hint() if secret is not None else None,
                    updated_at=datetime.fromisoformat(stamp) if stamp else None,
                )
            )

        return ServiceSettings(
            speech=SpeechCredentialPool(**speech) if speech else SpeechCredentialPool(),
            inference=_inference_with_environment(
                InferenceSettings(**inference) if inference else InferenceSettings(),
                self._read_environment,
                # `None` from `_read_json` is the honest "nobody has saved this
                # section", which the in-memory store has to track by hand.
                written=inference is not None,
            ),
            vendors=VendorSettings(**vendors) if vendors else VendorSettings(),
            connectors=ConnectorSettings(**connectors) if connectors else ConnectorSettings(),
            storage=_storage_view(self.get_secret(SecretKey.STATE_DATABASE_URL)),
            documents=_documents_with_environment(
                DocumentSourceSettings(**documents) if documents else DocumentSourceSettings(),
                self._read_environment,
            ),
            consent=ConsentSettings(**consent) if consent else ConsentSettings(),
            secrets=statuses,
            durable=True,
            updated_at=datetime.fromisoformat(updated) if updated else None,
        )
