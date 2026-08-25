"""What is not configured, and what it costs (the operator's own question).

An evening was spent on "the live panel shows no nudge" that ended at a
Deepgram key nobody had set. Every individual fact was already on the settings
screen — `deepgram_api_key: configured=false` sat there the whole time — and
none of them said what it *stopped*. A screen that lists unset keys leaves the
operator to know which ones matter and what breaks; that knowledge lives in
the composition root and nowhere an operator can read it.
"""

from __future__ import annotations

from app.modules.settings.models import AuthMode, SecretKey, SpeechVendor
from app.modules.settings.readiness import Capability, readiness_of


def _configured(*keys: SecretKey) -> set[SecretKey]:
    return set(keys)


class TestWhatIsMissingAndWhatItCosts:
    def test_nothing_configured_reports_every_capability_unready(self):
        report = readiness_of(
            configured=set(), auth_mode=AuthMode.API_KEY, live_vendor=SpeechVendor.DEEPGRAM
        )

        assert report, "an empty deployment must not read as ready"
        assert all(not entry.ready for entry in report)

    def test_the_live_lane_names_the_key_and_the_consequence(self):
        report = readiness_of(
            configured=_configured(SecretKey.ANTHROPIC_API_KEY),
            auth_mode=AuthMode.API_KEY,
            live_vendor=SpeechVendor.DEEPGRAM,
        )
        live = next(e for e in report if e.capability is Capability.LIVE_NUDGES)

        assert not live.ready
        assert SecretKey.DEEPGRAM_API_KEY in live.missing
        # The sentence an operator acts on: what stops, not which field is blank.
        assert "nudge" in live.consequence.lower()

    def test_an_api_key_satisfies_inference_and_an_oauth_token_does_not_stand_in(self):
        """The mode decides which secret counts.

        Both can be stored. Reporting inference ready because *some* Anthropic
        credential exists would pass a deployment whose selected mode points at
        an empty field.
        """

        report = readiness_of(
            configured=_configured(SecretKey.ANTHROPIC_OAUTH_TOKEN),
            auth_mode=AuthMode.API_KEY,
            live_vendor=SpeechVendor.DEEPGRAM,
        )
        inference = next(e for e in report if e.capability is Capability.INFERENCE)

        assert not inference.ready
        assert SecretKey.ANTHROPIC_API_KEY in inference.missing

    def test_an_oauth_token_satisfies_inference_in_its_own_mode(self):
        report = readiness_of(
            configured=_configured(SecretKey.ANTHROPIC_OAUTH_TOKEN),
            auth_mode=AuthMode.OAUTH_TOKEN,
            live_vendor=SpeechVendor.DEEPGRAM,
        )
        inference = next(e for e in report if e.capability is Capability.INFERENCE)

        assert inference.ready

    def test_the_live_lane_follows_the_selected_vendor(self):
        """A Deepgram key does not make an AssemblyAI live lane work."""

        report = readiness_of(
            configured=_configured(SecretKey.DEEPGRAM_API_KEY),
            auth_mode=AuthMode.API_KEY,
            live_vendor=SpeechVendor.ASSEMBLYAI,
        )
        live = next(e for e in report if e.capability is Capability.LIVE_NUDGES)

        assert not live.ready
        assert SecretKey.ASSEMBLYAI_API_KEY in live.missing

    def test_document_links_are_reported_separately_from_uploads(self):
        """Graph credentials are optional in a way a speech key is not.

        Uploading a document needs nothing; only *linking* one from SharePoint
        does. Reporting the whole document capability broken would send an
        operator to configure Entra ID for a feature they are not using.
        """

        report = readiness_of(
            configured=set(), auth_mode=AuthMode.API_KEY, live_vendor=SpeechVendor.DEEPGRAM
        )
        links = next(e for e in report if e.capability is Capability.DOCUMENT_LINKS)

        assert not links.ready
        assert links.optional, "linking is an extra, not a prerequisite"


class TestTheScreenIsToldWithoutAsking:
    """Readiness rides on the settings read the screen already performs.

    A separate endpoint would be a second call the screen has to remember to
    make, and a screen that forgets it is exactly the screen that shows a blank
    field with no warning beside it — which is where this started.
    """

    def test_the_settings_read_carries_it(self):
        from app.modules.settings.store import InMemorySettingsStore

        store = InMemorySettingsStore(read_environment=False)
        store.set_secret(SecretKey.ANTHROPIC_API_KEY, "sk-ant-key")

        settings = store.read()

        blocked = {e.capability for e in settings.readiness if not e.ready}
        assert Capability.LIVE_NUDGES in blocked
        assert Capability.INFERENCE not in blocked
