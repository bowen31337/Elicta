"""The pool survives a restart, and its secrets travel with it.

Credential metadata and credential values live in two tables — settings and
secrets — and a pool that persisted one without the other would come back
listing keys it could not use, or holding values nothing referenced.
"""

from __future__ import annotations

from app.modules.settings.models import SpeechVendor
from app.modules.settings.speech_credentials import (
    SelectionPolicy,
    SpeechCredential,
    SpeechCredentialPool,
    secret_key_for,
)
from app.modules.settings.speech_resolution import resolve_speech_key


def _pool() -> SpeechCredentialPool:
    return SpeechCredentialPool(
        credentials=(
            SpeechCredential(id="dg1", vendor=SpeechVendor.DEEPGRAM, label="Northwind"),
            SpeechCredential(id="dg2", vendor=SpeechVendor.DEEPGRAM, label="spare", enabled=False),
        ),
        policy=SelectionPolicy.ROTATE,
        active_id="dg1",
    )


class TestItComesBack:
    def test_in_memory(self):
        from app.modules.settings.store import InMemorySettingsStore

        store = InMemorySettingsStore(read_environment=False)
        store.write_speech(_pool())

        back = store.read().speech
        assert [c.id for c in back.credentials] == ["dg1", "dg2"]
        assert back.policy is SelectionPolicy.ROTATE
        assert back.credentials[1].enabled is False

    def test_on_disk(self, tmp_path):
        from app.modules.settings.sqlite_store import SqliteSettingsStore

        path = tmp_path / "settings.db"
        first = SqliteSettingsStore(path, read_environment=False)
        first.write_speech(_pool())
        first.set_secret(secret_key_for("dg1"), "dg-one")

        reopened = SqliteSettingsStore(path, read_environment=False)
        back = reopened.read().speech

        assert [c.label for c in back.credentials] == ["Northwind", "spare"]
        # And the value the metadata points at came back with it.
        assert resolve_speech_key(reopened, SpeechVendor.DEEPGRAM) == "dg-one"

    def test_a_store_that_never_had_a_pool_reads_as_empty_rather_than_missing(self):
        """An older settings file has no pool row, and must still open.

        Returning `None` here would push the absent case into every caller;
        an empty pool answers "nothing configured" in the same shape a
        populated one does.
        """

        from app.modules.settings.store import InMemorySettingsStore

        pool = InMemorySettingsStore(read_environment=False).read().speech

        assert pool is not None
        assert pool.credentials == ()
