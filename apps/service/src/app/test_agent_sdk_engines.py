"""The compiler on the Claude Agent SDK (ADR-012).

ADR-012 names the Agent SDK as the compiler's harness and the Messages API as
the slow lane's. The compiler shipped on the Messages API, which works for an
API key and not for the other credential the settings screen accepts: an OAuth
token from `claude setup-token` authenticates, lists models, and is then
refused for `/v1/messages` with a 429 carrying no rate-limit headers at all.
The Agent SDK is the surface that credential is entitled to.
"""

from __future__ import annotations

import pytest

from app.orchestration.agent_sdk_engines import (
    AgentSdkUnavailableError,
    agent_sdk_compiler_engines,
    json_payload,
)
from app.orchestration.engines import UpstreamFailure, upstream_failure_in


class TestReadingAnAnswerBackOutOfProse:
    """The Agent SDK returns an assistant turn, not a parsed object.

    `messages.parse` enforces a schema server-side; the agent loop has no
    equivalent, so the answer arrives as text and this is where it becomes a
    model again. Fenced or bare, both happen.
    """

    def test_a_fenced_block_is_read(self):
        text = 'Here you go:\n```json\n{"claims": []}\n```\nHope that helps.'

        assert json_payload(text) == {"claims": []}

    def test_bare_json_is_read(self):
        assert json_payload('{"claims": [{"text": "a"}]}') == {
            "claims": [{"text": "a"}]
        }

    def test_prose_with_no_json_is_refused_rather_than_guessed(self):
        # A stage that returns `{}` here would persist an empty bank as a
        # success. The whole point of the compile is the candidates.
        with pytest.raises(AgentSdkUnavailableError) as raised:
            json_payload("I could not find any claims in those documents.")

        assert "no JSON" in str(raised.value)


class TestTheBatchApiIsNotOnThisSurface:
    def test_submitting_a_batch_refuses_as_not_entitled(self):
        """Which is what makes the existing fallback carry the analyst pass.

        `compiler.py` runs `run_analyst` only when the submission refusal was
        `NOT_ENTITLED`, so this refusal is load-bearing rather than cosmetic:
        classify it as anything else and the compile stops at
        batch-submission instead of drafting a bank.
        """

        engines = agent_sdk_compiler_engines(run=_never_called)

        with pytest.raises(Exception) as raised:
            import asyncio

            asyncio.run(engines.submit_batch("eng-1", object()))

        assert upstream_failure_in(str(raised.value)) is UpstreamFailure.NOT_ENTITLED


async def _never_called(*args, **kwargs):  # pragma: no cover - guards the test
    raise AssertionError("the model must not be called for this test")


class TestWhichHarnessTheCredentialGets:
    """The credential decides the harness, because it has to.

    An API key can drive either surface, and the Messages API is the cheaper
    and better-controlled one for a batch. An OAuth token can only drive the
    agent loop. So the choice is not a preference an operator should have to
    make — it follows from what they pasted in.
    """

    def _store(self, mode):
        from app.modules.settings.models import InferenceSettings, SecretKey
        from app.modules.settings.store import InMemorySettingsStore

        store = InMemorySettingsStore(read_environment=False)
        store.set_secret(SecretKey.ANTHROPIC_API_KEY, "sk-ant-the-key")
        store.set_secret(SecretKey.ANTHROPIC_OAUTH_TOKEN, "sk-ant-oat01-the-token")
        store.write_inference(InferenceSettings(auth_mode=mode))
        return store

    def test_an_oauth_token_gets_the_agent_sdk(self):
        from app.modules.settings.models import AuthMode
        from app.orchestration.agent_sdk_engines import AGENT_SDK
        from app.orchestration.anthropic_engines import engines_from_settings

        debrief, compiler = engines_from_settings(self._store(AuthMode.OAUTH_TOKEN))

        assert compiler.name == AGENT_SDK
        # Both halves, or the credential drafts a bank and then cannot write
        # up the meeting it was drafted for.
        assert debrief.name == AGENT_SDK

    def test_an_api_key_keeps_the_messages_api_and_its_batch(self):
        from app.modules.settings.models import AuthMode
        from app.orchestration.agent_sdk_engines import AGENT_SDK
        from app.orchestration.anthropic_engines import engines_from_settings

        _debrief, compiler = engines_from_settings(self._store(AuthMode.API_KEY))

        assert compiler.name != AGENT_SDK


class TestTestingTheCredentialTheWayItWillBeUsed:
    """The probe has to follow the harness, because the harness follows the credential.

    Testing an OAuth token against `/v1/messages` reports a 429 for a
    credential that drafts a bank perfectly well through the agent loop — the
    same defect as the `models.list` probe that preceded it, inverted. Then it
    passed something that could not work; now it fails something that does.
    """

    def test_an_oauth_token_is_probed_through_the_agent_sdk(self):
        import asyncio

        from app.modules.settings.models import AuthMode
        from app.orchestration.anthropic_engines import probe_anthropic_credential

        asked: list[tuple[str, str]] = []

        async def fake_run(system: str, prompt: str) -> str:
            asked.append((system, prompt))
            return "ok"

        asyncio.run(
            probe_anthropic_credential(
                "sk-ant-oat01-token",
                mode=AuthMode.OAUTH_TOKEN,
                model="claude-opus-5",
                run=fake_run,
            )
        )

        assert asked, "the agent loop was never asked anything"

    def test_an_api_key_is_still_probed_on_the_messages_api(self, monkeypatch):
        import asyncio

        import httpx

        from app.modules.settings.models import AuthMode
        from app.orchestration.anthropic_engines import probe_anthropic_credential

        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                json={
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-opus-5",
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "max_tokens",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            )

        original = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            original(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

        asyncio.run(
            probe_anthropic_credential("sk-ant-the-key", mode=AuthMode.API_KEY)
        )

        assert seen and "/v1/messages" in str(seen[0].url)


class TestTheDebriefEngineOnTheAgentSdk:
    """ADR-012 puts the debrief engine on the Agent SDK too.

    It shipped on the Messages API alongside the compiler, which is fine for
    an API key and refuses an OAuth token — so a credential that drafts a
    bank could not write up the meeting afterwards.
    """

    def _engines(self, answer: str):
        from app.orchestration.agent_sdk_engines import agent_sdk_debrief_engines

        async def run(_system: str, _prompt: str) -> str:
            return answer

        return agent_sdk_debrief_engines(run=run)

    def test_it_names_the_harness_it_ran_on(self):
        from app.orchestration.agent_sdk_engines import AGENT_SDK

        assert self._engines("{}").name == AGENT_SDK

    def test_cleaning_reuses_the_messages_api_stage_logic(self):
        """The gap handling is not reimplemented.

        An utterance the model skips keeps its own words rather than another
        utterance's, and the same must hold on both harnesses — it is the one
        failure that corrupts artifacts while still looking well-formed.
        """

        import asyncio
        import types

        engines = self._engines(
            '{"lines": [{"utterance": 1, "cleaned_text": "first, tidied"}]}'
        )
        utterances = [
            types.SimpleNamespace(text="first, um, tidied"),
            types.SimpleNamespace(text="second, untouched"),
        ]

        cleaned = asyncio.run(engines.clean("session-1", utterances))

        assert cleaned[0] == "first, tidied"
        # The skipped one keeps its own words.
        assert cleaned[1] == "second, untouched"

    def test_conversing_returns_content_blocks_the_way_the_screen_persists_them(self):
        import asyncio

        engines = self._engines("Here is what I found.")

        blocks = asyncio.run(engines.converse([{"role": "user", "content": "hi"}]))

        assert blocks == [{"type": "text", "text": "Here is what I found."}]

    def test_diarize_is_passed_through_untouched(self):
        """A speech-vendor seam, not a model call — this module supplies neither."""

        import asyncio

        from app.orchestration.agent_sdk_engines import agent_sdk_debrief_engines
        from app.orchestration.engines import EngineNotConfiguredError

        engines = agent_sdk_debrief_engines(run=lambda *_a: None)

        with pytest.raises(EngineNotConfiguredError):
            asyncio.run(engines.diarize("session-1"))
