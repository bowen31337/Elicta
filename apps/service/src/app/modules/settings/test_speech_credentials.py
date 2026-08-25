"""A pool of speech credentials, and which one serves a call.

The screen had one speech field bound to `asr_vendor_api_key`, a key nothing
reads for transcription. Two keys typed into it overwrote each other while the
two keys the service actually uses stayed empty, with no field to set them —
and the readiness warning named a remedy the screen could not offer.

Replacing it with two fixed fields would fix that and nothing else. An
operator with a key per client, or replacing a key without downtime, or
holding a spare against one being revoked, still has one box per vendor.
"""

from __future__ import annotations

import pytest

from app.modules.settings.models import SpeechVendor
from app.modules.settings.speech_credentials import (
    SelectionPolicy,
    SpeechCredential,
    SpeechCredentialPool,
    secret_key_for,
)


def _cred(id: str, vendor: SpeechVendor, *, enabled: bool = True) -> SpeechCredential:
    return SpeechCredential(id=id, vendor=vendor, label=f"key {id}", enabled=enabled)


class TestWhichCredentialServesACall:
    def test_a_vendor_with_no_credential_gets_nothing(self):
        pool = SpeechCredentialPool(credentials=(), policy=SelectionPolicy.SINGLE)

        assert pool.next_for(SpeechVendor.DEEPGRAM) is None

    def test_a_deepgram_call_never_gets_an_assemblyai_key(self):
        """The failure this ordering prevents is silent.

        A key from the wrong vendor authenticates as a bad credential rather
        than as a wrong one, and the operator is sent to re-enter a key that
        was correct.
        """

        pool = SpeechCredentialPool(
            credentials=(_cred("a", SpeechVendor.ASSEMBLYAI),),
            policy=SelectionPolicy.SINGLE,
        )

        assert pool.next_for(SpeechVendor.DEEPGRAM) is None
        assert pool.next_for(SpeechVendor.ASSEMBLYAI).id == "a"

    def test_single_keeps_serving_the_active_one(self):
        pool = SpeechCredentialPool(
            credentials=(_cred("a", SpeechVendor.DEEPGRAM), _cred("b", SpeechVendor.DEEPGRAM)),
            policy=SelectionPolicy.SINGLE,
            active_id="b",
        )

        assert [pool.next_for(SpeechVendor.DEEPGRAM).id for _ in range(3)] == ["b", "b", "b"]

    def test_single_with_no_active_named_takes_the_first_enabled(self):
        pool = SpeechCredentialPool(
            credentials=(
                _cred("a", SpeechVendor.DEEPGRAM, enabled=False),
                _cred("b", SpeechVendor.DEEPGRAM),
            ),
            policy=SelectionPolicy.SINGLE,
        )

        assert pool.next_for(SpeechVendor.DEEPGRAM).id == "b"

    def test_rotate_goes_round_the_enabled_ones_in_order(self):
        pool = SpeechCredentialPool(
            credentials=(
                _cred("a", SpeechVendor.DEEPGRAM),
                _cred("b", SpeechVendor.DEEPGRAM),
                _cred("c", SpeechVendor.DEEPGRAM),
            ),
            policy=SelectionPolicy.ROTATE,
        )

        served = [pool.next_for(SpeechVendor.DEEPGRAM).id for _ in range(7)]

        assert served == ["a", "b", "c", "a", "b", "c", "a"]

    def test_rotation_is_per_vendor_rather_than_one_shared_cursor(self):
        """Otherwise a busy vendor advances a quiet one's position.

        With one cursor, a deployment transcribing live on Deepgram and
        reconciling on AssemblyAI would step the AssemblyAI cursor by however
        many live windows happened to pass, so its rotation would depend on
        somebody talking.
        """

        pool = SpeechCredentialPool(
            credentials=(
                _cred("d1", SpeechVendor.DEEPGRAM),
                _cred("d2", SpeechVendor.DEEPGRAM),
                _cred("a1", SpeechVendor.ASSEMBLYAI),
                _cred("a2", SpeechVendor.ASSEMBLYAI),
            ),
            policy=SelectionPolicy.ROTATE,
        )

        assert pool.next_for(SpeechVendor.DEEPGRAM).id == "d1"
        assert pool.next_for(SpeechVendor.DEEPGRAM).id == "d2"
        # AssemblyAI starts at its own beginning, not wherever Deepgram got to.
        assert pool.next_for(SpeechVendor.ASSEMBLYAI).id == "a1"

    def test_a_disabled_credential_is_skipped_rather_than_removed(self):
        """Disabling is how a key is taken out of service without losing it.

        Deleting to stop using something means re-entering the secret to
        resume, which an operator will not do mid-meeting.
        """

        pool = SpeechCredentialPool(
            credentials=(
                _cred("a", SpeechVendor.DEEPGRAM),
                _cred("b", SpeechVendor.DEEPGRAM, enabled=False),
                _cred("c", SpeechVendor.DEEPGRAM),
            ),
            policy=SelectionPolicy.ROTATE,
        )

        assert [pool.next_for(SpeechVendor.DEEPGRAM).id for _ in range(4)] == [
            "a",
            "c",
            "a",
            "c",
        ]

    def test_an_active_id_that_is_disabled_falls_through_rather_than_failing(self):
        pool = SpeechCredentialPool(
            credentials=(
                _cred("a", SpeechVendor.DEEPGRAM, enabled=False),
                _cred("b", SpeechVendor.DEEPGRAM),
            ),
            policy=SelectionPolicy.SINGLE,
            active_id="a",
        )

        assert pool.next_for(SpeechVendor.DEEPGRAM).id == "b"


    def test_two_pools_do_not_share_a_cursor(self):
        """A mutable default on a private attribute is shared by every instance.

        Sharing here would make rotation depend on which other pools had been
        constructed — including ones built by an unrelated request — and the
        symptom would be a key order that changes for no reason anybody can
        reproduce.
        """

        def fresh():
            return SpeechCredentialPool(
                credentials=(
                    _cred("a", SpeechVendor.DEEPGRAM),
                    _cred("b", SpeechVendor.DEEPGRAM),
                ),
                policy=SelectionPolicy.ROTATE,
            )

        first = fresh()
        first.next_for(SpeechVendor.DEEPGRAM)

        # A pool built afterwards starts at the beginning, not wherever the
        # other one had got to.
        assert fresh().next_for(SpeechVendor.DEEPGRAM).id == "a"


class TestWhereTheSecretItselfLives:
    def test_each_credential_addresses_its_own_secret(self):
        assert secret_key_for("abc123") == "asr.abc123"

    def test_the_id_may_not_smuggle_a_different_key_name(self):
        """The store is keyed by string, so an id is an address.

        An id carrying a dot or whitespace could name another secret entirely
        — `anthropic_api_key` is one write away — so ids are constrained where
        they become addresses rather than where they are displayed.
        """

        with pytest.raises(ValueError):
            secret_key_for("../anthropic_api_key")
        with pytest.raises(ValueError):
            secret_key_for("a b")
        with pytest.raises(ValueError):
            secret_key_for("")


class TestOneCredentialAtATimeAcrossProviders:
    """The ASR service takes one credential; the credential carries its vendor.

    A pool spanning providers makes it the single place a provider is
    configured, and the vendor selector redundant — choosing the credential is
    choosing the vendor. What it also creates is a pool that can hold a key
    for a provider this service cannot drive, which selection has to account
    for rather than discover mid-meeting.
    """

    def test_selection_is_filtered_by_what_the_service_can_drive(self):
        from app.modules.settings.speech_credentials import SpeechCredentialPool

        pool = SpeechCredentialPool(
            credentials=(
                _cred("g1", SpeechVendor.GEMINI),
                _cred("d1", SpeechVendor.DEEPGRAM),
            ),
            policy=SelectionPolicy.ROTATE,
        )

        # Only Deepgram has a live recogniser today.
        chosen = [pool.next_among({SpeechVendor.DEEPGRAM}).id for _ in range(3)]

        assert chosen == ["d1", "d1", "d1"]

    def test_a_pool_of_only_undrivable_credentials_selects_nothing(self):
        """Distinct from an empty pool, and the caller must be able to tell.

        "No key" and "a key this service cannot use" send an operator to two
        different places, and one of them is a key they already set.
        """

        from app.modules.settings.speech_credentials import SpeechCredentialPool

        pool = SpeechCredentialPool(credentials=(_cred("g1", SpeechVendor.GEMINI),))

        assert pool.next_among({SpeechVendor.DEEPGRAM}) is None
        assert pool.has_any_for({SpeechVendor.GEMINI})
        assert not pool.has_any_for({SpeechVendor.DEEPGRAM})

    def test_rotation_across_providers_takes_each_in_turn(self):
        from app.modules.settings.speech_credentials import SpeechCredentialPool

        pool = SpeechCredentialPool(
            credentials=(
                _cred("d1", SpeechVendor.DEEPGRAM),
                _cred("a1", SpeechVendor.ASSEMBLYAI),
            ),
            policy=SelectionPolicy.ROTATE,
        )
        drivable = {SpeechVendor.DEEPGRAM, SpeechVendor.ASSEMBLYAI}

        served = [pool.next_among(drivable).id for _ in range(4)]

        assert served == ["d1", "a1", "d1", "a1"]
