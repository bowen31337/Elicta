"""SQLite-backed settings, with secret values encrypted at rest.

The in-memory store loses everything on restart, which the admin screen had to
warn about. This one persists — and persistence is exactly what makes the
encryption non-optional. A settings row holding a plaintext vendor credential
turns a stolen file, a backup, or a stray `sqlite3` session into a credential
leak, so writing secrets in the clear here would be a *regression* on the
in-memory store rather than an improvement on it (NFR-2.5).

**How the key is handled.** Values are encrypted with Fernet (AES-128-CBC plus
an HMAC, so a tampered ciphertext fails loudly rather than decrypting to
garbage). The key comes from `ELICTA_SETTINGS_KEY` if set; otherwise it is
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
    InferenceSettings,
    SecretKey,
    SecretStatus,
    SecretValue,
    ServiceSettings,
    VendorSettings,
)

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

KEY_ENV_VAR = "ELICTA_SETTINGS_KEY"


def _load_or_create_key(database_path: Path) -> bytes:
    """The encryption key, from the environment or a 0600 file beside the DB."""

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

    def write_inference(self, inference: InferenceSettings) -> None:
        self._write_json("inference", inference.model_dump(mode="json"))

    def write_vendors(self, vendors: VendorSettings) -> None:
        self._write_json("vendors", vendors.model_dump(mode="json"))

    def write_connectors(self, connectors: ConnectorSettings) -> None:
        self._write_json("connectors", connectors.model_dump(mode="json"))

    # -- secrets -----------------------------------------------------------

    def set_secret(self, key: SecretKey, value: str) -> None:
        with self._connect() as connection:
            if value == "":
                connection.execute("DELETE FROM secrets WHERE key = ?", (key.value,))
                return
            connection.execute(
                "INSERT INTO secrets (key, ciphertext, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET ciphertext = excluded.ciphertext, "
                "updated_at = excluded.updated_at",
                (
                    key.value,
                    self._fernet.encrypt(value.encode()),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def get_secret(self, key: SecretKey) -> SecretValue | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT ciphertext FROM secrets WHERE key = ?", (key.value,)
            ).fetchone()

        if row is not None:
            try:
                return SecretValue(self._fernet.decrypt(row[0]).decode())
            except InvalidToken:
                # A rotated or lost key, or a tampered row. Reporting "not
                # configured" turns this into "re-enter your credential"
                # rather than a service that will not start.
                logger.warning(
                    "settings: %s could not be decrypted with the current key", key.value
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
        inference = self._read_json("inference")
        vendors = self._read_json("vendors")
        connectors = self._read_json("connectors")

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
            inference=InferenceSettings(**inference) if inference else InferenceSettings(),
            vendors=VendorSettings(**vendors) if vendors else VendorSettings(),
            connectors=ConnectorSettings(**connectors) if connectors else ConnectorSettings(),
            secrets=statuses,
            durable=True,
            updated_at=datetime.fromisoformat(updated) if updated else None,
        )
