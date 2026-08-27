"""Which harness runs is decided per call, not once at startup.

The settings screen promises that a credential entered there takes effect
without a restart, and `SettingsBackedClient` keeps that promise for the
*value* of a secret: it re-reads on every request. The choice of harness kept
none of it. `engines_from_settings` runs once, in `create_app`, so the
decision between the Messages API and the Claude Agent SDK is made from
whatever the settings said at boot and never revisited.

Reported from a live deployment. The admin had switched inference to an API
key -- `auth_mode: api_key`, with a key configured that day -- and the
write-up still failed with "You've hit your weekly limit", which is a Claude
Code allowance and belongs to the OAuth credential. The service had been
started while the mode was `oauth_token` and was still on that harness,
against a token the operator had stopped meaning to use.

Nothing said so. The Settings screen marks the database as
`applies_on_restart`; the inference block makes no such claim, and the
storage field's existence is what shows the difference is deliberate
elsewhere and accidental here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.settings.models import AuthMode
from app.orchestration.anthropic_engines import engines_from_settings


@dataclass
class _Recording:
    """A store whose auth mode can change under a running service."""

    auth_mode: AuthMode = AuthMode.API_KEY
    reads: int = 0
    secrets: dict[str, str] = field(default_factory=dict)

    def read(self) -> Any:
        self.reads += 1
        from app.modules.settings.models import InferenceSettings, ServiceSettings

        settings = ServiceSettings()
        return settings.model_copy(
            update={
                "inference": InferenceSettings(
                    provider=settings.inference.provider,
                    auth_mode=self.auth_mode,
                    model="claude-opus-5",
                )
            }
        )

    def get_secret(self, key: Any) -> Any:
        return None


def test_switching_the_auth_mode_changes_the_harness_without_a_restart(monkeypatch):
    """Asserted on which harness runs, not on how often the store is read.

    The store is read on every call regardless — `SettingsBackedClient` does
    that for the secret's value — so a read count passes against a service
    that chose its harness at boot and never revisited it. What has to change
    is where the work goes.
    """

    reached: list[str] = []

    def fake_agent_sdk_debrief(*_args, **kwargs):
        reached.append("agent-sdk")
        from app.orchestration.engines import DebriefEngines

        return DebriefEngines.unconfigured()

    monkeypatch.setattr(
        "app.orchestration.agent_sdk_engines.agent_sdk_debrief_engines",
        fake_agent_sdk_debrief,
    )

    store = _Recording(auth_mode=AuthMode.API_KEY)
    debrief, _compiler = engines_from_settings(store)
    assert reached == [], "an API key must not reach the Agent SDK"

    # Built once, as `create_app` does. Now the operator changes the mode on
    # the Settings screen, which is the whole point of that screen.
    store.auth_mode = AuthMode.OAUTH_TOKEN

    import asyncio
    import contextlib

    with contextlib.suppress(Exception):
        asyncio.run(debrief.clean("session", []))

    assert reached == ["agent-sdk"], (
        "the harness was chosen at startup and never asked again — an operator "
        "who switches credentials stays on the old one until the app restarts"
    )


def test_an_api_key_keeps_using_the_messages_api(monkeypatch):
    """The other direction, which is the one that was reported.

    A deployment on an API key was still spending a Claude Code weekly
    allowance, because it had booted on an OAuth token.
    """

    from app.orchestration.engines import DebriefEngines

    reached: list[str] = []

    def fake_agent_sdk_debrief(*_args, **_kwargs):
        reached.append("agent-sdk")
        return DebriefEngines.unconfigured()

    monkeypatch.setattr(
        "app.orchestration.agent_sdk_engines.agent_sdk_debrief_engines",
        fake_agent_sdk_debrief,
    )

    store = _Recording(auth_mode=AuthMode.OAUTH_TOKEN)
    debrief, _compiler = engines_from_settings(store)
    # One call is expected at construction: `name` labels every persisted
    # record and the dataclass is frozen, so it is resolved once. What must
    # not happen is another one after the mode changes.
    after_build = len(reached)
    store.auth_mode = AuthMode.API_KEY

    import asyncio
    import contextlib

    with contextlib.suppress(Exception):
        asyncio.run(debrief.clean("session", []))

    assert len(reached) == after_build, (
        "an API key must not be run through the Agent SDK"
    )
