"""Which key string a transcription call actually gets.

The pool decides *which credential*; this is where that becomes the secret,
and where a deployment that predates the pool keeps working.
"""

from __future__ import annotations

from app.modules.settings.models import SecretKey, SpeechVendor
from app.modules.settings.speech_credentials import (
    SelectionPolicy,
    SpeechCredential,
    SpeechCredentialPool,
    secret_key_for,
)
from app.modules.settings.speech_resolution import resolve_speech_key
from app.modules.settings.store import InMemorySettingsStore


def _store() -> InMemorySettingsStore:
    return InMemorySettingsStore(read_environment=False)


class TestResolvingAKeyToUse:
    def test_a_pooled_credential_supplies_its_own_secret(self):
        store = _store()
        store.set_secret(secret_key_for("dg1"), "dg-one")
        pool = SpeechCredentialPool(
            credentials=(
                SpeechCredential(id="dg1", vendor=SpeechVendor.DEEPGRAM, label="one"),
            ),
            policy=SelectionPolicy.SINGLE,
        )

        assert resolve_speech_key(store, SpeechVendor.DEEPGRAM, pool=pool) == "dg-one"

    def test_rotation_hands_out_each_key_in_turn(self):
        store = _store()
        store.set_secret(secret_key_for("dg1"), "dg-one")
        store.set_secret(secret_key_for("dg2"), "dg-two")
        pool = SpeechCredentialPool(
            credentials=(
                SpeechCredential(id="dg1", vendor=SpeechVendor.DEEPGRAM),
                SpeechCredential(id="dg2", vendor=SpeechVendor.DEEPGRAM),
            ),
            policy=SelectionPolicy.ROTATE,
        )

        served = [resolve_speech_key(store, SpeechVendor.DEEPGRAM, pool=pool) for _ in range(4)]

        assert served == ["dg-one", "dg-two", "dg-one", "dg-two"]

    def test_a_credential_whose_secret_is_gone_is_passed_over(self):
        """Metadata and secret live in different tables and can disagree.

        A credential listed with no stored value would otherwise hand back
        `None` on its turn — an intermittent outage on a rotation, which is
        the hardest kind of failure to attribute.
        """

        store = _store()
        store.set_secret(secret_key_for("dg2"), "dg-two")
        pool = SpeechCredentialPool(
            credentials=(
                SpeechCredential(id="dg1", vendor=SpeechVendor.DEEPGRAM),
                SpeechCredential(id="dg2", vendor=SpeechVendor.DEEPGRAM),
            ),
            policy=SelectionPolicy.ROTATE,
        )

        served = {resolve_speech_key(store, SpeechVendor.DEEPGRAM, pool=pool) for _ in range(4)}

        assert served == {"dg-two"}

    def test_a_deployment_that_predates_the_pool_still_works(self):
        """The fixed key is the fallback, so nothing already set is lost.

        Migrating on read rather than rewriting the store: a settings file is
        the last thing that should be edited by a version that might be rolled
        back.
        """

        store = _store()
        store.set_secret(SecretKey.DEEPGRAM_API_KEY, "legacy-dg")

        assert resolve_speech_key(store, SpeechVendor.DEEPGRAM) == "legacy-dg"

    def test_the_pool_wins_over_the_fixed_key_once_there_is_one(self):
        store = _store()
        store.set_secret(SecretKey.DEEPGRAM_API_KEY, "legacy-dg")
        store.set_secret(secret_key_for("dg1"), "pooled-dg")
        pool = SpeechCredentialPool(
            credentials=(SpeechCredential(id="dg1", vendor=SpeechVendor.DEEPGRAM),),
        )

        assert resolve_speech_key(store, SpeechVendor.DEEPGRAM, pool=pool) == "pooled-dg"

    def test_nothing_anywhere_is_none_rather_than_an_error(self):
        """The caller reports "not configured" better than this can.

        Raising here would turn a missing credential into a stack trace at the
        point of transcription, where the stages above already know how to say
        which stage stopped and why.
        """

        assert resolve_speech_key(_store(), SpeechVendor.DEEPGRAM) is None
