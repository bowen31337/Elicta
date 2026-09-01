"""The production engines, exercised against a stub client.

These assert the contract the pipeline depends on — schema-enforced output
(§14.4), a cached prompt prefix (§14.3), and positional results that line up
with their input — without making a network call. The model's *judgement* is
not under test here; the wiring around it is.
"""

from __future__ import annotations

import dataclasses
import types

import httpx
import pytest
from anthropic import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OverloadedError,
    PermissionDeniedError,
    RateLimitError,
)

from app.orchestration.anthropic_engines import (
    DEFAULT_MODEL,
    _AnalystArtifacts,
    _batch_error,
    _BriefOut,
    _ClassifiedLine,
    _ClassifiedTranscript,
    _CleanedLine,
    _CleanedTranscript,
    _DecisionOut,
    _EmailOut,
    _OpenQuestionOut,
    _retry_after,
    _TranslatedLine,
    _TranslatedTranscript,
    _upstream_failure,
    _vendor_message,
    anthropic_compiler_engines,
    anthropic_debrief_engines,
    build_llm_client,
    configured_engines,
    probe_anthropic_credential,
)
from app.orchestration.engines import (
    EngineNotConfiguredError,
    UpstreamFailure,
    UpstreamUnavailableError,
)


class _StubMessages:
    def __init__(self, outputs: list) -> None:
        self._outputs = list(outputs)
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        return types.SimpleNamespace(parsed_output=self._outputs.pop(0))

    def stream(self, **kwargs):
        """The streaming form, which the Analyst pass uses.

        Recorded in `calls` beside `parse`, so a test that asserts what
        reached the model does not have to know which of the two a stage
        chose — and the direct Analyst pass streams precisely because it may
        ask for a whole bank, which a non-streaming request is not allowed to.
        """

        self.calls.append(kwargs)
        outputs = self._outputs

        class _Stream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            async def get_final_message(self):
                return types.SimpleNamespace(parsed_output=outputs.pop(0))

        return _Stream()


class _StubClient:
    def __init__(self, outputs: list) -> None:
        self.messages = _StubMessages(outputs)


def _utterance(text: str, index: int = 1):
    return types.SimpleNamespace(
        utterance_id=f"u{index}",
        text=text,
        cleaned_text=text,
        speaker_tag="client",
        section_key="performance",
    )


async def test_cleaning_returns_one_line_per_utterance() -> None:
    client = _StubClient([
        _CleanedTranscript(lines=[
            _CleanedLine(utterance=1, cleaned_text="we need it fast"),
            _CleanedLine(utterance=2, cleaned_text="by Q3"),
        ])
    ])
    engines = anthropic_debrief_engines(client)

    cleaned = await engines.clean("s1", [_utterance("um, we need it fast", 1), _utterance("by Q3", 2)])

    assert cleaned == ["we need it fast", "by Q3"]


async def test_a_short_result_never_binds_a_claim_to_the_wrong_utterance() -> None:
    """The property the old length check defended, kept by a stronger means.

    A result read positionally would put "only one" against utterance 1 and
    leave the rest to shift; refusing the whole batch prevented that at the
    cost of the meeting's documents. Now the line says which utterance it is
    for, so the answer lands where it belongs and the utterance nobody
    answered for keeps its own words.
    """

    client = _StubClient([
        _CleanedTranscript(lines=[_CleanedLine(utterance=2, cleaned_text="only one")])
    ])
    engines = anthropic_debrief_engines(client)

    cleaned = await engines.clean("s1", [_utterance("a", 1), _utterance("b", 2)])

    assert cleaned == ["a", "only one"]


async def test_translation_leaves_same_language_utterances_untranslated() -> None:
    client = _StubClient(
        [
            _TranslatedTranscript(
                lines=[
                    _TranslatedLine(
                        utterance=1, original_language="en", translated_text=None
                    )
                ]
            )
        ]
    )
    engines = anthropic_debrief_engines(client)

    outcomes = await engines.translate("s1", [_utterance("we need it fast")], "en")

    assert outcomes[0].original_language == "en"
    assert outcomes[0].translated_text is None


async def test_classification_is_given_the_section_keys_to_choose_from() -> None:
    client = _StubClient([
        _ClassifiedTranscript(lines=[_ClassifiedLine(utterance=1, section_key="performance")])
    ])
    engines = anthropic_debrief_engines(client)
    sections = [types.SimpleNamespace(key="performance", title="Performance")]

    keys = await engines.classify("s1", [_utterance("we need it fast")], sections)

    assert keys == ["performance"]
    prompt = client.messages.calls[0]["messages"][0]["content"]
    assert "performance" in prompt, "the model must be shown the allowed keys"


async def test_the_analyst_chain_carries_citations_and_provenance_through() -> None:
    """FR-8.7 and the stated/inferred split are what a reviewer relies on."""

    client = _StubClient(
        [
            _AnalystArtifacts(
                open_questions=[
                    _OpenQuestionOut(
                        text="What does 'fast' mean in seconds?",
                        impact_rank=1,
                        provenance="stated",
                        citation_utterance_ids=["u1"],
                    )
                ],
                decisions=[
                    _DecisionOut(
                        text="Ship the API first",
                        decided_by="client",
                        provenance="stated",
                        citation_utterance_ids=["u1"],
                    )
                ],
                project_brief=_BriefOut(
                    body="Logistics discovery.", provenance="inferred", citation_utterance_ids=["u1"]
                ),
                follow_up_email=_EmailOut(
                    subject="Follow-ups",
                    body="Two open points.",
                    provenance="inferred",
                    citation_utterance_ids=["u1"],
                ),
            )
        ]
    )
    engines = anthropic_debrief_engines(client)

    output = await engines.run_chain("s1", [_utterance("we need it fast")])

    assert output.open_questions[0].citation_utterance_ids == ["u1"]
    assert output.open_questions[0].provenance == "stated"
    assert output.project_brief.provenance == "inferred"


async def test_the_transcript_given_to_the_analyst_carries_utterance_ids() -> None:
    """The model can only cite ids it was shown."""

    client = _StubClient(
        [
            _AnalystArtifacts(
                open_questions=[],
                decisions=[],
                project_brief=_BriefOut(body="b", provenance="inferred", citation_utterance_ids=[]),
                follow_up_email=_EmailOut(
                    subject="s", body="b", provenance="inferred", citation_utterance_ids=[]
                ),
            )
        ]
    )
    engines = anthropic_debrief_engines(client)

    await engines.run_chain("s1", [_utterance("we need it fast", 7)])

    prompt = client.messages.calls[0]["messages"][0]["content"]
    assert "[u7]" in prompt


async def test_every_stage_caches_its_instructions_and_uses_the_configured_model() -> None:
    """§14.3: the stable half of the prompt belongs in the cached prefix."""

    client = _StubClient([
        _CleanedTranscript(lines=[_CleanedLine(utterance=1, cleaned_text="x")])
    ])
    engines = anthropic_debrief_engines(client, model=DEFAULT_MODEL)

    await engines.clean("s1", [_utterance("x")])

    call = client.messages.calls[0]
    assert call["model"] == DEFAULT_MODEL
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["output_format"] is _CleanedTranscript, "output must be schema-enforced"


async def test_diarization_is_not_treated_as_a_model_call() -> None:
    """It is a speech-vendor seam; wiring Claude to it would be wrong.

    And it refuses as an *unset seam* rather than as a bare `RuntimeError`.
    Nothing downstream can tell a crash from a missing vendor by reading prose,
    and the debrief screen tried: a live run rendered this refusal's internals
    to an operator, because that was the only way anything had to classify it.
    """

    from app.orchestration.engines import EngineNotConfiguredError

    engines = anthropic_debrief_engines(_StubClient([]))

    with pytest.raises(EngineNotConfiguredError, match="speech vendor"):
        await engines.diarize("s1", "s3://audio")


async def test_a_supplied_diarizer_is_passed_through_untouched() -> None:
    async def vendor_diarize(session_id: str, audio_ref: str) -> str:
        return "vendor-output"

    engines = anthropic_debrief_engines(_StubClient([]), diarize=vendor_diarize)

    assert await engines.diarize("s1", "s3://audio") == "vendor-output"


async def test_compiler_extraction_binds_each_claim_to_a_document_span() -> None:
    from app.orchestration.anthropic_engines import _ExtractedClaimOut, _ExtractionOut

    client = _StubClient(
        [
            _ExtractionOut(
                claims=[
                    _ExtractedClaimOut(
                        text="Deliveries must be same-day",
                        document_id="doc-1",
                        cited_text="same-day delivery",
                        start_char_index=10,
                        end_char_index=27,
                    )
                ]
            )
        ]
    )
    engines = anthropic_compiler_engines(client)

    output = await engines.extract(
        "eng-1", [types.SimpleNamespace(document_id="doc-1", text="... same-day delivery ...")]
    )

    claim = output.claims[0]
    assert claim.citation.document_id == "doc-1"
    assert claim.citation.end_char_index > claim.citation.start_char_index


def test_no_engines_are_built_when_no_credentials_are_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Half-configured is worse than unconfigured: the fallback is explicit."""

    for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"):
        monkeypatch.delenv(name, raising=False)

    assert configured_engines() is None


def test_engines_are_built_when_credentials_are_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-not-real")

    built = configured_engines()

    assert built is not None
    debrief, compiler = built
    assert debrief.name == DEFAULT_MODEL
    assert compiler.name == DEFAULT_MODEL


# --------------------------------------------------------------------------
# The analyst batch. §3.10 budgets minutes for this, so submit and collect
# are separate steps and the collector must tolerate "not finished yet".
# --------------------------------------------------------------------------


class _StubBatches:
    def __init__(self, status: str = "ended", entries: list | None = None) -> None:
        self.status = status
        self.entries = entries or []
        self.created: list[dict] = []

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return types.SimpleNamespace(id="batch-1")

    async def retrieve(self, batch_id: str):
        return types.SimpleNamespace(id=batch_id, processing_status=self.status)

    async def results(self, batch_id: str):
        async def gen():
            for entry in self.entries:
                yield entry

        return gen()


class _BatchClient:
    def __init__(self, batches: _StubBatches) -> None:
        self.messages = types.SimpleNamespace(batches=batches, parse=None)


def _succeeded(custom_id: str, payload: str):
    return types.SimpleNamespace(
        custom_id=custom_id,
        result=types.SimpleNamespace(
            type="succeeded",
            message=types.SimpleNamespace(
                content=[types.SimpleNamespace(type="text", text=payload)]
            ),
        ),
    )


async def test_the_analyst_batch_is_submitted_with_an_enforced_schema() -> None:
    """A batch result is collected hours later by another process.

    Prose that merely "looks parseable" is unrecoverable at that point, so
    the schema has to be attached at submission time (§14.4).
    """

    batches = _StubBatches()
    engines = anthropic_compiler_engines(_BatchClient(batches))
    pack = types.SimpleNamespace(sector="logistics", project_type="discovery", documents=[])

    batch_id = await engines.submit_batch("eng-1", pack)

    assert batch_id == "batch-1"
    params = batches.created[0]["requests"][0]["params"]
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert "candidates" in params["output_config"]["format"]["schema"]["properties"]


async def test_collecting_an_unfinished_batch_returns_nothing_rather_than_blocking() -> None:
    engines = anthropic_compiler_engines(_BatchClient(_StubBatches(status="in_progress")))

    assert await engines.fetch_batch("batch-1") == []


async def test_a_finished_batch_is_parsed_into_bank_candidates() -> None:
    payload = (
        '{"candidates": [{"template_section": "performance", '
        '"trigger_types": ["vague_adjective"], "phrasing": "How fast, in seconds?", '
        '"stub": "How fast?", "lang": "en", "priority": 1}]}'
    )
    engines = anthropic_compiler_engines(
        _BatchClient(_StubBatches(entries=[_succeeded("eng-1", payload)]))
    )

    results = await engines.fetch_batch("batch-1")

    assert len(results) == 1
    assert results[0].custom_id == "eng-1"
    assert results[0].output is not None
    assert results[0].output.candidates[0].phrasing == "How fast, in seconds?"


async def test_an_errored_batch_entry_is_recorded_rather_than_raising() -> None:
    """One failed entry must not discard the ones that succeeded."""

    errored = types.SimpleNamespace(
        custom_id="eng-1",
        result=types.SimpleNamespace(
            type="errored", error=types.SimpleNamespace(type="invalid_request")
        ),
    )
    engines = anthropic_compiler_engines(_BatchClient(_StubBatches(entries=[errored])))

    results = await engines.fetch_batch("batch-1")

    assert results[0].output is None
    assert "invalid_request" in results[0].error


async def test_unparseable_batch_output_is_reported_not_swallowed() -> None:
    engines = anthropic_compiler_engines(
        _BatchClient(_StubBatches(entries=[_succeeded("eng-1", "not json at all")]))
    )

    results = await engines.fetch_batch("batch-1")

    assert results[0].output is None
    assert "unparseable" in results[0].error


# --------------------------------------------------------------------------
# Bring your own key *or* token. The header pairing is the part that fails
# confusingly when wrong: a bearer token without the beta flag returns a 401
# that reads like a bad credential rather than a missing header.
# --------------------------------------------------------------------------


def test_an_api_key_is_sent_as_an_api_key_header() -> None:
    from app.modules.settings.models import AuthMode
    from app.orchestration.anthropic_engines import build_anthropic_client

    client = build_anthropic_client(AuthMode.API_KEY, "sk-ant-key")

    assert client.auth_headers.get("X-Api-Key") == "sk-ant-key"
    assert "Authorization" not in client.auth_headers


def test_an_oauth_token_is_sent_as_a_bearer_token() -> None:
    from app.modules.settings.models import AuthMode
    from app.orchestration.anthropic_engines import build_anthropic_client

    client = build_anthropic_client(AuthMode.OAUTH_TOKEN, "oat-token")

    assert client.auth_headers.get("Authorization") == "Bearer oat-token"
    assert "X-Api-Key" not in client.auth_headers


def test_an_oauth_token_carries_the_beta_flag_that_unlocks_bearer_auth() -> None:
    """The SDK only injects this for credentials it manages itself.

    A static bring-your-own token skips that path, so the flag has to be set
    here or every call 401s.
    """

    from app.modules.settings.models import AuthMode
    from app.orchestration.anthropic_engines import OAUTH_BETA_HEADER, build_anthropic_client

    client = build_anthropic_client(AuthMode.OAUTH_TOKEN, "oat-token")

    assert OAUTH_BETA_HEADER in client.default_headers.get("anthropic-beta", "")


def test_an_api_key_does_not_carry_the_oauth_beta_flag() -> None:
    from app.modules.settings.models import AuthMode
    from app.orchestration.anthropic_engines import OAUTH_BETA_HEADER, build_anthropic_client

    client = build_anthropic_client(AuthMode.API_KEY, "sk-ant-key")

    assert OAUTH_BETA_HEADER not in client.default_headers.get("anthropic-beta", "")


def test_a_base_url_override_applies_to_either_credential_type() -> None:
    from app.modules.settings.models import AuthMode
    from app.orchestration.anthropic_engines import build_anthropic_client

    for mode in (AuthMode.API_KEY, AuthMode.OAUTH_TOKEN):
        client = build_anthropic_client(mode, "secret", base_url="https://proxy.example")
        assert str(client.base_url).startswith("https://proxy.example")


def test_the_engine_uses_the_credential_the_selected_mode_names() -> None:
    """An operator with both configured must control which one is live."""

    from app.modules.settings.models import AuthMode, InferenceSettings, SecretKey
    from app.modules.settings.store import InMemorySettingsStore
    from app.orchestration.anthropic_engines import SettingsBackedClient

    store = InMemorySettingsStore(read_environment=False)
    store.set_secret(SecretKey.ANTHROPIC_API_KEY, "sk-ant-the-key")
    store.set_secret(SecretKey.ANTHROPIC_OAUTH_TOKEN, "oat-the-token")
    store.write_inference(InferenceSettings(auth_mode=AuthMode.OAUTH_TOKEN))

    resolved = SettingsBackedClient(store)._resolve()

    assert resolved.auth_headers.get("Authorization") == "Bearer oat-the-token"


def test_selecting_a_mode_whose_credential_is_missing_fails_closed() -> None:
    from app.modules.settings.models import AuthMode, InferenceSettings, SecretKey
    from app.modules.settings.store import InMemorySettingsStore
    from app.orchestration.anthropic_engines import SettingsBackedClient

    store = InMemorySettingsStore(read_environment=False)
    store.set_secret(SecretKey.ANTHROPIC_API_KEY, "sk-ant-the-key")
    store.write_inference(InferenceSettings(auth_mode=AuthMode.OAUTH_TOKEN))

    with pytest.raises(EngineNotConfiguredError, match="oauth token"):
        SettingsBackedClient(store)._resolve()


# --- Provider failures ------------------------------------------------------
#
# A rate limit escaping this module reaches FastAPI as a bare 500, and the
# operator goes looking for a broken deployment when the correct move was to
# wait. The translation is per stage, so the guard that matters is the one that
# enumerates *every* stage: a stage added later without the decorator is the
# way this comes back.


class _AlwaysFailingMessages:
    def __init__(self, error: BaseException) -> None:
        self._error = error
        self.batches = _AlwaysFailingBatches(error)

    async def parse(self, **_kwargs):
        raise self._error

    def stream(self, **_kwargs):
        """Fails where the real one would: on entering the stream.

        The Analyst pass streams, so a provider refusal reaches it here rather
        than from `parse`, and a stage that could not report a rate limit as
        one is the whole point of the test this serves.
        """

        error = self._error

        class _Failing:
            async def __aenter__(self):
                raise error

            async def __aexit__(self, *_exc):
                return False

        return _Failing()

    async def create(self, **_kwargs):
        raise self._error


class _AlwaysFailingBatches:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    async def create(self, **_kwargs):
        raise self._error

    async def retrieve(self, *_args, **_kwargs):
        raise self._error

    async def results(self, *_args, **_kwargs):
        raise self._error


class _FailingClient:
    def __init__(self, error: BaseException) -> None:
        self.messages = _AlwaysFailingMessages(error)


def _rate_limited() -> RateLimitError:
    return RateLimitError(
        "rate limited",
        response=httpx.Response(
            429,
            headers={"retry-after": "12"},
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        ),
        body=None,
    )


def _debrief_calls(engines):
    """Every debrief stage that is a model call, ready to await.

    `diarize` is excluded deliberately: it is an audio-vendor seam, not a
    Claude call, and this module neither makes nor wraps it.
    """

    utterance = types.SimpleNamespace(
        utterance_id="u1",
        text="x",
        cleaned_text="x",
        speaker="A",
        speaker_tag="A",
        section_key="performance",
    )
    return {
        "clean": lambda: engines.clean("session-1", [utterance]),
        "translate": lambda: engines.translate("session-1", [utterance], "en"),
        "classify": lambda: engines.classify("session-1", [utterance], []),
        "run_chain": lambda: engines.run_chain("session-1", [utterance]),
        "converse": lambda: engines.converse([{"role": "user", "content": "hello"}]),
    }


def _compiler_calls(engines):
    pack = types.SimpleNamespace(documents=[], sector="logistics", project_type="brownfield")
    return {
        "extract": lambda: engines.extract("eng-1", []),
        "structure": lambda: engines.structure("eng-1", []),
        "submit_batch": lambda: engines.submit_batch("eng-1", pack),
        "fetch_batch": lambda: engines.fetch_batch("batch-1"),
        "run_analyst": lambda: engines.run_analyst("eng-1", pack),
    }


# `diarize` is an audio-vendor seam and `name` is a label, so neither is a
# model call this module makes.
_NOT_MODEL_CALLS = {"name", "diarize"}


def test_every_model_call_on_the_engines_is_probed_below() -> None:
    """The list of stages is hand-written, so this is what keeps it honest.

    A stage added to either dataclass without a probe here would otherwise be
    a stage nobody ever checked translates its provider failures — which is
    exactly how a rate limit gets back out as a 500. Adding one fails this
    test until it is probed, and probing it fails until it is decorated.
    """

    for engines, probes in (
        (anthropic_debrief_engines(_FailingClient(_rate_limited())), _debrief_calls),
        (anthropic_compiler_engines(_FailingClient(_rate_limited())), _compiler_calls),
    ):
        declared = {f.name for f in dataclasses.fields(engines)} - _NOT_MODEL_CALLS
        assert declared == set(probes(engines)), (
            f"{type(engines).__name__} has stages with no provider-failure probe: "
            f"{sorted(declared - set(probes(engines)))}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["clean", "translate", "classify", "run_chain", "converse"])
async def test_every_debrief_stage_reports_a_rate_limit_as_one(stage: str) -> None:
    engines = anthropic_debrief_engines(_FailingClient(_rate_limited()))

    with pytest.raises(UpstreamUnavailableError) as caught:
        await _debrief_calls(engines)[stage]()

    assert caught.value.failure is UpstreamFailure.RATE_LIMITED
    assert caught.value.stage, "the failure does not say which stage hit the limit"
    assert caught.value.retry_after == 12


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage", ["extract", "structure", "submit_batch", "fetch_batch", "run_analyst"]
)
async def test_every_compiler_stage_reports_a_rate_limit_as_one(stage: str) -> None:
    engines = anthropic_compiler_engines(_FailingClient(_rate_limited()))

    with pytest.raises(UpstreamUnavailableError) as caught:
        await _compiler_calls(engines)[stage]()

    assert caught.value.failure is UpstreamFailure.RATE_LIMITED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "failure"),
    [
        (APITimeoutError(request=httpx.Request("POST", "https://x")), UpstreamFailure.UNAVAILABLE),
        (
            APIConnectionError(request=httpx.Request("POST", "https://x")),
            UpstreamFailure.UNAVAILABLE,
        ),
        (
            OverloadedError(
                "overloaded",
                response=httpx.Response(529, request=httpx.Request("POST", "https://x")),
                body=None,
            ),
            UpstreamFailure.UNAVAILABLE,
        ),
        (
            AuthenticationError(
                "bad key",
                response=httpx.Response(401, request=httpx.Request("POST", "https://x")),
                body=None,
            ),
            UpstreamFailure.CREDENTIAL_REJECTED,
        ),
    ],
    ids=["timeout", "connection", "overloaded", "bad-credential"],
)
async def test_the_other_provider_failures_are_told_apart(
    error: BaseException, failure: UpstreamFailure
) -> None:
    engines = anthropic_debrief_engines(_FailingClient(error))

    with pytest.raises(UpstreamUnavailableError) as caught:
        await engines.converse([{"role": "user", "content": "hello"}])

    assert caught.value.failure is failure


@pytest.mark.asyncio
async def test_a_request_the_provider_rejects_as_malformed_stays_ours() -> None:
    """A 400 means this codebase sent something wrong. That is a bug, and a bug
    dressed as a provider outage is a bug nobody investigates."""

    error = BadRequestError(
        "max_tokens exceeds model maximum",
        response=httpx.Response(400, request=httpx.Request("POST", "https://x")),
        body=None,
    )
    engines = anthropic_debrief_engines(_FailingClient(error))

    with pytest.raises(BadRequestError):
        await engines.converse([{"role": "user", "content": "hello"}])


@pytest.mark.asyncio
async def test_a_plain_bug_in_a_stage_is_not_dressed_up_as_a_provider_failure() -> None:
    engines = anthropic_debrief_engines(_FailingClient(ZeroDivisionError("division by zero")))

    with pytest.raises(ZeroDivisionError):
        await engines.converse([{"role": "user", "content": "hello"}])


# --------------------------------------------------------------------------
# Two refusals that are not what the product used to call them.
#
# Both cost a real misdiagnosis: a working OAuth token was reported as rate
# limited and as a rejected credential, and neither was true. The provider had
# said exactly what was wrong in both cases and the translation threw it away.
# --------------------------------------------------------------------------


def _scope_denied() -> PermissionDeniedError:
    return PermissionDeniedError(
        "forbidden",
        response=httpx.Response(
            403,
            request=httpx.Request("GET", "https://api.anthropic.com/v1/messages/batches"),
        ),
        body={
            "type": "error",
            "error": {
                "type": "permission_error",
                "message": (
                    "OAuth token does not meet scope requirement "
                    "any_of(user:batch, user:developer, workspace:developer, "
                    "workspace:inference)"
                ),
            },
        },
    )


def _rate_limited_without_a_hint() -> RateLimitError:
    """A 429 carrying no `retry-after` and no rate-limit headers.

    What Anthropic returns when the *model* is not available to the
    credential's plan: the body says `rate_limit_error`, and the same request
    repeated a second later is refused identically. Every retry is wasted.
    """

    return RateLimitError(
        "rate limited",
        response=httpx.Response(
            429,
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        ),
        body={"type": "error", "error": {"type": "rate_limit_error", "message": "Error"}},
    )


class TestARefusalThatWaitingCannotFix:
    def test_a_missing_scope_is_not_reported_as_a_rejected_credential(self):
        failure = _upstream_failure("analyst batch", _scope_denied())

        assert failure is not None
        assert failure.failure is UpstreamFailure.NOT_ENTITLED
        # "Re-enter it on the Settings screen" sends an operator round a loop
        # that cannot help: the credential is valid, and re-typing it changes
        # nothing about which scopes it carries.
        assert "re-enter" not in str(failure).lower()

    def test_the_provider_s_own_words_survive_because_they_name_the_fix(self):
        failure = _upstream_failure("analyst batch", _scope_denied())

        assert "user:batch" in str(failure)

    def test_a_credential_that_really_is_rejected_still_says_so(self):
        rejected = AuthenticationError(
            "unauthorized",
            response=httpx.Response(
                401,
                request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
            ),
            body=None,
        )

        failure = _upstream_failure("cleaning", rejected)

        assert failure is not None
        assert failure.failure is UpstreamFailure.CREDENTIAL_REJECTED
        assert "Settings" in str(failure)


class TestARateLimitWithNoRetryHint:
    def test_it_does_not_promise_the_request_will_succeed_shortly(self):
        failure = _upstream_failure("extraction", _rate_limited_without_a_hint())

        assert failure is not None
        assert "should succeed shortly" not in str(failure)

    def test_it_points_at_settings_and_names_both_causes_in_order(self):
        # This used to ask for the model advice alone. The model is a real
        # cause and stays named -- it is the second one, after the credential.
        failure = _upstream_failure("extraction", _rate_limited_without_a_hint())

        text = str(failure)
        assert "Settings" in text
        assert "model" in text
        assert text.index("credential") < text.index("the plan does not include")

    def test_it_is_not_classified_as_a_throttle_at_all(self):
        """The wording said one thing and the kind said another.

        `NOT_ENTITLED` is documented as "a missing OAuth scope *or a model the
        plan does not include*", which is precisely this. Raised as
        `RATE_LIMITED`, the sentence advised checking Settings while the kind
        told every reader downstream to wait — and a screen that classifies by
        kind, as it must, would repeat the advice the sentence had just ruled
        out. A real compile stopped here four times.
        """

        failure = _upstream_failure("extraction", _rate_limited_without_a_hint())

        assert failure is not None
        assert failure.failure is UpstreamFailure.NOT_ENTITLED
        assert failure.retry_after is None, "there is nothing to come back after"

    def test_a_throttle_that_says_when_to_come_back_is_still_a_throttle(self):
        failure = _upstream_failure("extraction", _rate_limited())

        assert failure is not None
        assert failure.failure is UpstreamFailure.RATE_LIMITED
        assert failure.retry_after == 12
        assert "this is a limit, not a fault" in str(failure)


# --- reading the provider's own words ---------------------------------------


def test_a_batch_that_ended_without_erroring_is_still_reported_by_name() -> None:
    # `expired` and `canceled` are not errors and carry no `error` object, but
    # they are still the reason a bank came back empty.
    result = types.SimpleNamespace(type="expired")

    assert _batch_error(result) == "analyst batch expired"


def test_a_rate_limit_with_no_headers_asks_us_to_wait_no_particular_time() -> None:
    # A guessed delay is worse than none: a client that trusts it retries
    # straight back into the same limit.
    assert _retry_after(types.SimpleNamespace()) is None
    assert _retry_after(types.SimpleNamespace(response=types.SimpleNamespace(headers=None))) is None


def test_a_vendor_error_with_no_message_falls_back_to_the_exception() -> None:
    error = BadRequestError(
        message="schema rejected",
        response=httpx.Response(
            400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        ),
        body=None,
    )

    assert "schema rejected" in _vendor_message(error)


# --- the two stages no other test drives ------------------------------------


class _CreateMessages:
    """A client for the one stage that returns prose rather than a schema."""

    def __init__(self, blocks: list) -> None:
        self._blocks = blocks
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return types.SimpleNamespace(content=self._blocks)


async def test_the_conversation_returns_the_blocks_the_api_sent() -> None:
    """The caller persists these verbatim and replays them as the next turn.

    Flattening them to a string would lose the block structure the next
    request needs, and the loss would only show up on the second turn.
    """

    block = types.SimpleNamespace(
        model_dump=lambda: {"type": "text", "text": "Which four hours?"}
    )
    messages = _CreateMessages([block])
    engines = anthropic_debrief_engines(types.SimpleNamespace(messages=messages))

    turns = [{"role": "user", "content": "What did they commit to?"}]
    reply = await engines.converse(turns)

    assert reply == [{"type": "text", "text": "Which four hours?"}]
    assert messages.calls[0]["messages"] == turns
    # §14.3: the instructions are a cache breakpoint, not part of the turn.
    assert messages.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


async def test_structuring_carries_every_candidate_through() -> None:
    from app.orchestration.anthropic_engines import _StructuringOut

    parsed = _StructuringOut.model_validate(
        {
            "candidates": [
                {
                    "claim_id": "c1",
                    "template_section": "performance",
                    "trigger_types": ["vague_adjective"],
                    "phrasing": "How fast, in seconds?",
                    "stub": "How fast?",
                    "lang": "en",
                    "priority": 1,
                }
            ]
        }
    )
    client = _StubClient([parsed])
    engines = anthropic_compiler_engines(client)

    output = await engines.structure(
        "eng-1", [types.SimpleNamespace(id="c1", text="it should be fast")]
    )

    assert [c.phrasing for c in output.candidates] == ["How fast, in seconds?"]
    # The candidate stays bound to the claim it was drawn from.
    assert output.candidates[0].claim_id == "c1"
    # The claim ids are what the model is asked to structure against.
    assert "[c1] it should be fast" in client.messages.calls[0]["messages"][0]["content"]


# --- one client class per Messages API surface -------------------------------
#
# Each reseller differs in request signing and in how model ids are addressed,
# so pointing the plain client at their endpoint produces authentication
# failures that read like bad credentials. These pin the mapping.


def _inference(**overrides):
    from app.modules.settings.models import InferenceSettings

    return InferenceSettings(**overrides)


def test_bedrock_authenticates_through_the_hosts_own_credential_chain() -> None:
    from anthropic import AsyncAnthropicBedrockMantle

    from app.modules.settings.models import LlmProvider

    client = build_llm_client(
        _inference(provider=LlmProvider.BEDROCK, region="us-east-1"), None
    )

    # No secret is taken from settings: an IAM role beats a pasted key.
    assert isinstance(client, AsyncAnthropicBedrockMantle)


def test_vertex_is_addressed_by_project_and_region() -> None:
    from anthropic import AsyncAnthropicVertex

    from app.modules.settings.models import LlmProvider

    client = build_llm_client(
        _inference(provider=LlmProvider.VERTEX, project_id="elicta-prod", region="us-east5"),
        None,
    )

    assert isinstance(client, AsyncAnthropicVertex)


def test_foundry_takes_a_key_and_a_resource() -> None:
    from anthropic import AsyncAnthropicFoundry

    from app.modules.settings.models import LlmProvider

    client = build_llm_client(
        _inference(provider=LlmProvider.FOUNDRY, resource="elicta-eastus"), "foundry-key"
    )

    assert isinstance(client, AsyncAnthropicFoundry)


def test_foundry_without_a_key_fails_closed() -> None:
    from app.modules.settings.models import LlmProvider

    with pytest.raises(EngineNotConfiguredError, match="Foundry"):
        build_llm_client(_inference(provider=LlmProvider.FOUNDRY, resource="r"), None)


def test_anthropic_direct_without_a_credential_fails_closed() -> None:
    # An unconfigured deployment must not look like a working one.
    from app.modules.settings.models import LlmProvider

    with pytest.raises(EngineNotConfiguredError, match="no credential configured"):
        build_llm_client(_inference(provider=LlmProvider.ANTHROPIC), None)


# --- credentials re-read per call --------------------------------------------


def test_the_messages_surface_resolves_the_client_on_every_access() -> None:
    """A key entered in the UI takes effect without a restart.

    Holding a client built at startup is what would make the operator restart
    the service after saving a key.
    """

    from app.modules.settings.models import InferenceSettings, SecretKey
    from app.modules.settings.store import InMemorySettingsStore
    from app.orchestration.anthropic_engines import SettingsBackedClient

    store = InMemorySettingsStore(read_environment=False)
    store.set_secret(SecretKey.ANTHROPIC_API_KEY, "sk-ant-first")
    client = SettingsBackedClient(store)

    assert client.messages is not None

    store.set_secret(SecretKey.ANTHROPIC_API_KEY, "sk-ant-second")
    store.write_inference(InferenceSettings(model="claude-opus-5"))

    assert client.messages is not None
    assert client.current_model() == "claude-opus-5"


def test_the_model_falls_back_to_the_default_when_none_is_set() -> None:
    from app.modules.settings.models import SecretKey
    from app.modules.settings.store import InMemorySettingsStore
    from app.orchestration.anthropic_engines import SettingsBackedClient

    store = InMemorySettingsStore(read_environment=False)
    store.set_secret(SecretKey.ANTHROPIC_API_KEY, "sk-ant-first")

    assert SettingsBackedClient(store).current_model() == DEFAULT_MODEL


# --- probing a credential -----------------------------------------------------


async def test_probing_a_credential_sends_it_on_the_header_its_mode_requires(
    monkeypatch,
) -> None:
    """An API key goes on `x-api-key`, whatever request the probe makes.

    This once asserted a `GET /v1/models`, on the reasoning that listing costs
    no tokens. What the probe sends is now a one-token message -- see
    `probe_anthropic_credential` for why listing proved nothing -- and the
    part worth keeping is the pairing of credential to header, which is its
    own trap.
    """

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": DEFAULT_MODEL,
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

    await probe_anthropic_credential("sk-ant-the-key")

    assert seen, "the probe made no request"
    assert seen[0].headers["x-api-key"] == "sk-ant-the-key"
    assert b'"max_tokens":1' in seen[0].content.replace(b", ", b",")


async def test_an_oauth_token_is_sent_with_the_bearer_pairing(monkeypatch) -> None:
    """A bearer token without the beta flag returns a 401 that reads like a bad credential.

    Asserted against `build_anthropic_client`, which owns the pairing, rather
    than through the credential probe. The probe used to reach it because it
    called `/v1/messages` for every credential; it now follows the harness and
    tests an OAuth token through the Agent SDK, so it no longer travels this
    path. The pairing still does — the debrief engine and the slow lane both
    build a client this way — so the check moved to where the behaviour is
    instead of being deleted with the route that happened to exercise it.
    """

    from app.modules.settings.models import AuthMode
    from app.orchestration.anthropic_engines import build_anthropic_client

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": DEFAULT_MODEL,
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

    client = build_anthropic_client(AuthMode.OAUTH_TOKEN, "oat-the-token")
    await client.messages.create(
        model=DEFAULT_MODEL, max_tokens=1, messages=[{"role": "user", "content": "."}]
    )

    assert seen[0].headers["authorization"] == "Bearer oat-the-token"
    assert "oauth-2025-04-20" in seen[0].headers["anthropic-beta"]


async def test_a_probe_that_is_rejected_raises_the_vendors_own_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})

    original = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    with pytest.raises(AuthenticationError):
        await probe_anthropic_credential("sk-ant-wrong")


async def test_the_direct_analyst_pass_returns_what_a_collected_batch_would() -> None:
    """The fallback route feeds the same collection the batch route does.

    Returning a different shape here would mean a second implementation of the
    candidate-count contract and the per-engagement failure handling — the part
    most worth having only one of.
    """

    from app.modules.compiler.agent.models import BmadAnalystPassOutput

    parsed = BmadAnalystPassOutput.model_validate(
        {
            "candidates": [
                {
                    "template_section": "volumes",
                    "trigger_types": ["unquantified-quantity"],
                    "phrasing": "How many consignments a month?",
                    "stub": "How many?",
                    "lang": "en",
                    "priority": 1,
                }
            ]
        }
    )
    client = _StubClient([parsed])
    engines = anthropic_compiler_engines(client)
    pack = types.SimpleNamespace(sector="logistics", project_type="discovery", documents=[])

    (result,) = await engines.run_analyst("eng-1", pack)

    # Attributed under the same `custom_id` convention a batch result carries,
    # so the collection keys it by engagement the same way.
    assert result.custom_id == "eng-1"
    assert result.error is None
    assert result.output.candidates[0].phrasing == "How many consignments a month?"
    # §14.4: schema-enforced, and §14.3: the instructions are a cache boundary.
    assert client.messages.calls[0]["output_format"] is BmadAnalystPassOutput
    assert client.messages.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


class TestTheCompilerAsksForAQuestionBank:
    """The compiler's Analyst pass was sending the debrief's instructions.

    `_ANALYST_SYSTEM` tells a model to produce "open questions, a decision log,
    a project brief and a follow-up email" from a *transcript*, citing utterance
    ids. The compiler runs before any meeting exists: there is no transcript,
    no utterance to cite, and what it needs is a bank of candidate questions
    tagged with the template section each one serves.

    The model did as it was told. A live compile over three documents came back
    with thirteen candidates filed under `open_questions` and `decision_log`,
    six of which were statements rather than questions — and the count was
    always going to fall short of a bank, because nothing had asked for one.
    """

    @staticmethod
    def _prose() -> str:
        """The prompt as one line. It is wrapped for reading, and a phrase that
        straddles a line break is still the phrase."""

        from app.orchestration.anthropic_engines import _COMPILER_ANALYST_SYSTEM

        return " ".join(_COMPILER_ANALYST_SYSTEM.lower().split())

    def test_it_asks_for_candidate_questions_rather_than_meeting_artifacts(self):
        lowered = self._prose()

        assert "candidate questions" in lowered
        # The debrief's artifacts are named here only to be ruled out — that is
        # exactly what the live compile filed its candidates under, so saying
        # nothing about them is weaker than forbidding them.
        assert "never file a candidate under a meeting artifact" in lowered
        assert "follow-up email" not in lowered

    def test_it_never_mentions_a_transcript_it_will_not_be_given(self):
        lowered = self._prose()
        assert "transcript" not in lowered
        assert "utterance" not in lowered

    def test_it_asks_for_the_tagging_the_bank_is_indexed_by(self):
        """A candidate with no template section cannot be grouped, and one with
        no trigger type can never be selected at runtime."""

        lowered = self._prose()
        assert "template_section" in lowered
        assert "trigger_types" in lowered

    def test_the_debrief_keeps_its_own_instructions(self):
        """The two passes are different work and must not share a prompt again."""

        from app.orchestration.anthropic_engines import (
            _ANALYST_SYSTEM,
            _COMPILER_ANALYST_SYSTEM,
        )

        assert _ANALYST_SYSTEM != _COMPILER_ANALYST_SYSTEM
        assert "transcript" in _ANALYST_SYSTEM.lower()

    def test_both_routes_to_the_pass_send_the_same_instructions(self):
        """The batch and the direct call are one pass asked two ways.

        Written twice they would drift, and a bank drafted by the fallback
        would quietly stop matching one drafted by the batch.
        """

        import inspect
        import re

        from app.orchestration import anthropic_engines

        source = inspect.getsource(anthropic_engines.anthropic_compiler_engines)
        assert source.count("_COMPILER_ANALYST_SYSTEM") == 2
        # Word boundary: `_COMPILER_ANALYST_SYSTEM` contains the debrief name
        # as a substring, so a plain `in` check can never fail.
        assert not re.search(r"(?<![A-Z_])_ANALYST_SYSTEM\b", source)


class TestTheBankIsKeyedToASectionList:
    """A live compile put 65 of 97 candidates into one section called "Operations".

    Not because the model was careless — because nothing had ever told it which
    sections exist. The prompt said "use the sections the documents themselves
    imply — volumes, integrations, performance, compliance, and so on", and
    "and so on" is an invitation to invent a bin and fill it.

    A bank is meant to be reviewable section by section, and coverage is
    tracked against the same sections. Both of those need the list to be known
    in advance rather than discovered per compile — two engagements whose banks
    are filed under different sections cannot be compared, and a section the
    coverage meter has never heard of can never be marked covered.
    """

    def test_the_context_pack_carries_the_sections_to_file_candidates_under(self):
        from app.modules.compiler.agent.models import AnalystContextPack

        assert "template_sections" in AnalystContextPack.model_fields

    def test_there_is_a_default_taxonomy_to_fall_back_on(self):
        """An engagement that has not named a template still needs a bank.

        Resolving an engagement's own template name into a section list is a
        separate, still-open piece of work; until it lands, a stated default is
        better than each compile inventing its own.
        """

        from app.modules.compiler.agent.models import DEFAULT_TEMPLATE_SECTIONS

        assert len(DEFAULT_TEMPLATE_SECTIONS) >= 5
        assert len(set(DEFAULT_TEMPLATE_SECTIONS)) == len(DEFAULT_TEMPLATE_SECTIONS)

    def test_the_prompt_names_the_sections_and_closes_the_list(self):
        from app.orchestration.anthropic_engines import _COMPILER_ANALYST_SYSTEM

        prose = " ".join(_COMPILER_ANALYST_SYSTEM.lower().split())
        assert "and so on" not in prose, "an open list is what produced the catch-all"
        assert "only" in prose and "listed" in prose

    def test_the_prompt_asks_for_spread_rather_than_one_full_bin(self):
        from app.orchestration.anthropic_engines import _COMPILER_ANALYST_SYSTEM

        prose = " ".join(_COMPILER_ANALYST_SYSTEM.lower().split())
        assert "every section" in prose

    @pytest.mark.asyncio
    async def test_the_sections_reach_the_model_in_the_request(self):
        """Naming them in the system prompt is not enough.

        They vary per engagement and the system prompt is cached across all of
        them, so a section list baked into the cached half would be the same
        list for every client Elicta ever works with.
        """

        from app.modules.compiler.agent.models import (
            AnalystContextPack,
            BmadAnalystPassOutput,
        )

        client = _StubClient([BmadAnalystPassOutput(candidates=[])])
        engines = anthropic_compiler_engines(client)

        await engines.run_analyst(
            "eng-1",
            AnalystContextPack(
                engagement_id="eng-1",
                sector="Freight",
                project_type="discovery",
                documents=[],
                template_sections=["Volumes", "Berth allocation"],
            ),
        )

        sent = client.messages.calls[0]["messages"][0]["content"]
        assert "Volumes" in sent
        assert "Berth allocation" in sent, "the engagement's own sections must travel"

    @pytest.mark.asyncio
    async def test_an_engagement_with_no_sections_still_gets_a_closed_list(self):
        from app.modules.compiler.agent.models import (
            DEFAULT_TEMPLATE_SECTIONS,
            AnalystContextPack,
            BmadAnalystPassOutput,
        )

        client = _StubClient([BmadAnalystPassOutput(candidates=[])])
        engines = anthropic_compiler_engines(client)

        await engines.run_analyst(
            "eng-1",
            AnalystContextPack(
                engagement_id="eng-1", sector="Freight", project_type="discovery", documents=[]
            ),
        )

        sent = client.messages.calls[0]["messages"][0]["content"]
        for section in DEFAULT_TEMPLATE_SECTIONS:
            assert section in sent


# --------------------------------------------------------------------------
# Results that line up because they say what they are for, not because the
# model counted correctly.
# --------------------------------------------------------------------------


async def test_a_dropped_line_no_longer_shifts_every_later_utterance() -> None:
    """The model answers 1 and 3 of 3. Entry 2 must still be utterance 2.

    Measured against a live model over a 37-utterance meeting, two runs in
    three came back one entry short or one entry long and the whole write-up
    was thrown away. Rejecting the batch protected the citations — a short
    result read positionally binds every later claim to the wrong utterance —
    but it made a finished meeting's documents a coin flip.

    So the result no longer has to be counted: each line says which utterance
    it is for, and the reassembly puts it there. An utterance the model
    skipped keeps its own verbatim text, which is honest — not cleaned, rather
    than cleaned into somebody else's words.
    """

    client = _StubClient([
        _CleanedTranscript(lines=[
            _CleanedLine(utterance=3, cleaned_text="by Q3"),
            _CleanedLine(utterance=1, cleaned_text="we need it fast"),
        ])
    ])
    engines = anthropic_debrief_engines(client)

    cleaned = await engines.clean(
        "s1",
        [
            _utterance("um, we need it fast", 1),
            _utterance("er, sorry, go on", 2),
            _utterance("by Q3", 3),
        ],
    )

    assert cleaned == ["we need it fast", "er, sorry, go on", "by Q3"]


async def test_a_line_for_an_utterance_that_does_not_exist_is_dropped() -> None:
    """An extra entry must not lengthen the result or displace a real one."""

    client = _StubClient([
        _CleanedTranscript(lines=[
            _CleanedLine(utterance=1, cleaned_text="we need it fast"),
            _CleanedLine(utterance=9, cleaned_text="something nobody said"),
        ])
    ])
    engines = anthropic_debrief_engines(client)

    cleaned = await engines.clean("s1", [_utterance("um, we need it fast", 1)])

    assert cleaned == ["we need it fast"]


async def test_a_stage_that_answers_nothing_usable_is_still_rejected() -> None:
    """Filling every gap would report a stage that did nothing as a success."""

    client = _StubClient([_CleanedTranscript(lines=[])])
    engines = anthropic_debrief_engines(client)

    with pytest.raises(ValueError, match="nothing"):
        await engines.clean("s1", [_utterance("a", 1), _utterance("b", 2)])


async def test_an_untranslated_utterance_keeps_its_original(monkeypatch) -> None:
    """A gap in translation retains the original, which is what FR-2.19 wants anyway."""

    client = _StubClient([
        _TranslatedTranscript(lines=[
            _TranslatedLine(utterance=2, original_language="cmn", translated_text="in English"),
        ])
    ])
    engines = anthropic_debrief_engines(client)

    outcomes = await engines.translate(
        "s1", [_utterance("a", 1), _utterance("b", 2)], "en"
    )

    assert len(outcomes) == 2
    assert outcomes[0].translated_text is None
    assert outcomes[0].original_language == "en"
    assert outcomes[1].translated_text == "in English"


async def test_an_unclassified_utterance_is_marked_so_rather_than_guessed() -> None:
    """A gap in classification must not borrow the next utterance's section."""

    from app.modules.debrief.pipeline.models import UNCLASSIFIED_SECTION_KEY

    client = _StubClient([
        _ClassifiedTranscript(lines=[
            _ClassifiedLine(utterance=2, section_key="performance"),
        ])
    ])
    engines = anthropic_debrief_engines(client)

    keys = await engines.classify(
        "s1",
        [_utterance("a", 1), _utterance("b", 2)],
        [types.SimpleNamespace(key="performance", title="Performance")],
    )

    assert keys == [UNCLASSIFIED_SECTION_KEY, "performance"]


async def test_probing_a_credential_makes_the_call_the_credential_must_make(
    monkeypatch,
) -> None:
    """A probe that only lists models says Verified for a credential that cannot work.

    Listing exercises authentication and nothing else. An OAuth token
    authenticates fine and is then refused for `/v1/messages` -- so the
    Settings screen reported "Verified" while every compile stopped at the
    first model call, and the credential was the last thing anybody suspected.
    The probe has to make the request the product makes, on the model the
    operator chose, or it is not evidence of anything.
    """

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

    await probe_anthropic_credential("sk-ant-the-key", model="claude-opus-5")

    assert seen, "the probe made no request"
    assert seen[0].method == "POST"
    assert "/v1/messages" in str(seen[0].url)
    assert b"claude-opus-5" in seen[0].content, "the configured model must be the one tested"


class TestARefusalNamesTheCredentialNotOnlyTheModel:
    def test_the_advice_names_the_credential_as_a_cause(self):
        """The model was the only cause named, and it was the wrong one.

        A live engagement had `claude-opus-5` configured and an OAuth token
        for a credential. `models.list` returned that very model, so the
        advice -- check the model in Settings -- sent the operator to verify
        something already correct. What the provider was refusing was the
        credential's right to call `/v1/messages` at all.
        """

        failure = _upstream_failure("extraction", _rate_limited_without_a_hint())

        assert failure is not None
        text = str(failure).lower()
        assert "credential" in text
        assert "api key" in text, "the remedy that works has to be named"

    def test_it_still_says_waiting_will_not_help(self):
        failure = _upstream_failure("extraction", _rate_limited_without_a_hint())

        assert "should succeed shortly" not in str(failure)
        assert failure is not None and failure.retry_after is None


class TestTheBatchSchemaIsOneTheApiAccepts:
    """A schema the provider refuses makes every compile hang, not fail.

    Observed on a live engagement. The batch was accepted, ended forty-six
    seconds later with `errored=1, succeeded=0`, and the reason was in the
    result rather than in the submission:

        output_config.format.schema: For 'integer' type, property 'minimum'
        is not supported

    So the bank could never be drafted through the batch path at all — and
    because the collector cannot tell an ended-and-errored batch from one
    still processing, the screen said the drafting job was with the provider
    and would come back on its own, indefinitely.

    The constraint bought nothing. `priority` is validated where it is parsed;
    asserting it again in a schema the provider will not take costs the whole
    feature.
    """

    def _numeric_keywords(self, node, path="schema"):
        """Every numeric bound anywhere in the schema, with where it is."""

        found = []
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {
                    "minimum",
                    "maximum",
                    "exclusiveMinimum",
                    "exclusiveMaximum",
                    "multipleOf",
                }:
                    found.append(f"{path}.{key}")
                found.extend(self._numeric_keywords(value, f"{path}.{key}"))
        elif isinstance(node, list):
            for index, item in enumerate(node):
                found.extend(self._numeric_keywords(item, f"{path}[{index}]"))
        return found

    def test_the_bank_schema_carries_no_numeric_bounds(self):
        from app.orchestration.anthropic_engines import _BANK_SCHEMA

        offending = self._numeric_keywords(_BANK_SCHEMA)

        assert offending == [], (
            "the provider refuses these outright, and the batch errors rather "
            f"than returning anything: {offending}"
        )

    def test_priority_is_still_required_and_still_an_integer(self):
        """Dropping the bound must not quietly drop the field."""

        from app.orchestration.anthropic_engines import _BANK_SCHEMA

        item = _BANK_SCHEMA["properties"]["candidates"]["items"]
        assert item["properties"]["priority"] == {"type": "integer"}
        assert "priority" in item["required"]


class TestTheAnalystPassHasRoomForABank:
    """One token budget for five stages, and only one of them emits a bank.

    Watched live: the batch succeeded at the provider and the compile stopped
    with an empty bank and this reason —

        analyst batch returned unparseable output: Unterminated string
        starting at: line 1 column 15243 (char 15242)

    Truncated output, cut mid-string, because `MAX_TOKENS` is 16000 and shared
    by every stage. Extraction returns a handful of claims; the Analyst pass
    returns up to `MAX_CANDIDATES` candidates, each carrying a section, a
    trigger list, a phrasing, a stub, a language and a priority. A bank near
    its own ceiling cannot fit, and what comes back is not a smaller bank but
    a broken one — the truncation lands mid-token, so the whole pass is lost
    rather than shortened.
    """

    def test_the_analyst_budget_is_larger_than_the_shared_one(self):
        from app.orchestration.anthropic_engines import ANALYST_MAX_TOKENS, MAX_TOKENS

        assert ANALYST_MAX_TOKENS > MAX_TOKENS

    def test_the_direct_route_asks_for_a_whole_bank_too(self):
        """It streams, which is the only way it may ask for one.

        The SDK refuses a *non-streaming* request whose budget implies more
        than ten minutes — "Streaming is required for operations that may take
        longer than 10 minutes" — so capping the call instead just moved the
        failure: a bank that did not fit came back truncated mid-token and
        failed to parse. Neither a smaller bank nor an error; a whole pass
        lost.
        """

        import inspect

        from app.orchestration import anthropic_engines

        source = inspect.getsource(anthropic_engines.anthropic_compiler_engines)
        direct = source[source.index("async def run_analyst") :]
        direct = direct[: direct.index("async def submit_batch")]

        assert "client.messages.stream(" in direct, "a capped request truncates instead"
        assert "max_tokens=ANALYST_MAX_TOKENS" in direct

    def test_the_budget_is_the_most_the_model_will_take(self):
        """Measured against the provider, not chosen.

            max_tokens=  32,000  accepted
            max_tokens=  64,000  accepted
            max_tokens= 128,000  accepted
            max_tokens= 200,000  REFUSED — "max_tokens: 200000 > 128000,
                                  which is the maximum allowed number of
                                  output tokens for claude-opus-5"

        A cap is not a spend: the bill is for what is produced, so setting it
        at the ceiling costs nothing until an answer actually needs the room.
        One twenty-eight thousand character document already draws fourteen
        thousand output tokens, so a handful of documents walks past anything
        smaller.
        """

        from app.orchestration.anthropic_engines import ANALYST_MAX_TOKENS

        assert ANALYST_MAX_TOKENS == 128_000

    def test_it_leaves_room_for_a_bank_at_its_own_ceiling(self):
        """The contract the pass is held to is what it has to be able to emit.

        A rough floor rather than an exact size: a candidate is a short object
        and fifty tokens apiece is conservative, but a budget under that
        cannot express the bank the contract demands and the shortfall shows
        up as unparseable JSON rather than as a refusal.
        """

        from app.modules.compiler.agent import MAX_CANDIDATES
        from app.orchestration.anthropic_engines import ANALYST_MAX_TOKENS

        assert ANALYST_MAX_TOKENS >= MAX_CANDIDATES * 50


class TestAStageThatCouldNotParseSaysSo:
    """`'NoneType' object has no attribute 'claims'` is not an explanation.

    Watched on a real engagement. A twenty-eight thousand character document
    went in, the extraction pass came back unparseable — `parsed_output` is
    `None` when the model's answer did not fit the schema, and the commonest
    reason is that it was truncated — and the screen showed the operator an
    `AttributeError` about a type they have never heard of.

    Extraction returns a claim per fact in the corpus and structuring a
    candidate per claim, so both grow with their input exactly as the Analyst
    pass does. They shared a sixteen-thousand token budget with stages that
    return a handful of lines.
    """

    def test_extraction_and_structuring_get_the_long_output_budget(self):
        import inspect

        from app.orchestration import anthropic_engines

        source = inspect.getsource(anthropic_engines.anthropic_compiler_engines)
        for stage in ("extract", "structure"):
            body = source[source.index(f"async def {stage}(") :]
            body = body[: body.index("return ")]
            assert "ANALYST_MAX_TOKENS" in body, (
                f"{stage} grows with its input and had the short budget"
            )
            assert "client.messages.stream(" in body, (
                f"{stage} cannot ask for a long answer without streaming"
            )

    def test_an_unparseable_answer_is_reported_as_one(self):
        from app.orchestration.anthropic_engines import _parsed_or_refuse
        from app.orchestration.engines import UpstreamFailure, upstream_failure_in

        class _Unparsed:
            parsed_output = None

        with pytest.raises(Exception) as caught:
            _parsed_or_refuse(_Unparsed(), "document claim extraction")

        said = str(caught.value)
        assert "NoneType" not in said, said
        assert "document claim extraction" in said
        assert upstream_failure_in(said) is UpstreamFailure.UNAVAILABLE

    def test_a_parsed_answer_is_handed_straight_back(self):
        from app.orchestration.anthropic_engines import _parsed_or_refuse

        class _Parsed:
            parsed_output = "the answer"

        assert _parsed_or_refuse(_Parsed(), "any stage") == "the answer"


class TestThinkingDoesNotEatTheAnswer:
    """Extended thinking spends the same budget the answer comes out of.

    Watched on a twenty-eight thousand character document:

        stop_reason  : max_tokens
        output_tokens: 32000
        details      : thinking_tokens=32000

    All of it. The answer stopped a few hundred characters in, the JSON would
    not parse, and the compile reported an `AttributeError`. Raising the budget
    only bought more thinking; the truncation point moved and stayed random.

    With thinking off the same call ends `end_turn` on 14,820 tokens and parses
    — thirty-five thousand characters of it. These stages ask for a
    schema-shaped answer about text that is already in the prompt, which is the
    kind of work that needs none.
    """

    def test_every_structured_call_turns_thinking_off(self):
        import inspect
        import re

        from app.orchestration import anthropic_engines

        source = inspect.getsource(anthropic_engines)
        calls = [
            match
            for match in re.finditer(
                r"client\.messages\.(parse|stream)\((.*?)\n        \)", source, re.S
            )
        ]
        assert calls, "no structured calls found — this test has stopped watching"
        for call in calls:
            assert "thinking=" in call.group(2), (
                "a call that can spend its whole budget thinking:\n"
                f"{call.group(0)[:200]}"
            )

    def test_the_batch_request_turns_it_off_too(self):
        """It is collected hours later, so a wasted budget is found late."""

        import inspect

        from app.orchestration import anthropic_engines

        source = inspect.getsource(anthropic_engines.anthropic_compiler_engines)
        submit = source[source.index("async def submit_batch") :]
        assert '"thinking"' in submit
