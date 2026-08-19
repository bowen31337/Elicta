"""The production engines, exercised against a stub client.

These assert the contract the pipeline depends on — schema-enforced output
(§14.4), a cached prompt prefix (§14.3), and positional results that line up
with their input — without making a network call. The model's *judgement* is
not under test here; the wiring around it is.
"""

from __future__ import annotations

import types

import pytest

from app.orchestration.anthropic_engines import (
    DEFAULT_MODEL,
    _AnalystArtifacts,
    _BriefOut,
    _ClassifiedTranscript,
    _CleanedTranscript,
    _DecisionOut,
    _EmailOut,
    _OpenQuestionOut,
    _TranslatedLine,
    _TranslatedTranscript,
    anthropic_compiler_engines,
    anthropic_debrief_engines,
    configured_engines,
)
from app.orchestration.engines import EngineNotConfiguredError


class _StubMessages:
    def __init__(self, outputs: list) -> None:
        self._outputs = list(outputs)
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        return types.SimpleNamespace(parsed_output=self._outputs.pop(0))


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
    client = _StubClient([_CleanedTranscript(cleaned_text=["we need it fast", "by Q3"])])
    engines = anthropic_debrief_engines(client)

    cleaned = await engines.clean("s1", [_utterance("um, we need it fast", 1), _utterance("by Q3", 2)])

    assert cleaned == ["we need it fast", "by Q3"]


async def test_a_stage_that_drops_an_utterance_is_rejected() -> None:
    """Positional results must line up, or every downstream citation shifts.

    A short result would silently bind claims to the wrong utterance while
    still looking well-formed — the one failure that corrupts artifacts
    without looking like a failure.
    """

    client = _StubClient([_CleanedTranscript(cleaned_text=["only one"])])
    engines = anthropic_debrief_engines(client)

    with pytest.raises(ValueError, match="positional"):
        await engines.clean("s1", [_utterance("a", 1), _utterance("b", 2)])


async def test_translation_leaves_same_language_utterances_untranslated() -> None:
    client = _StubClient(
        [_TranslatedTranscript(lines=[_TranslatedLine(original_language="en", translated_text=None)])]
    )
    engines = anthropic_debrief_engines(client)

    outcomes = await engines.translate("s1", [_utterance("we need it fast")], "en")

    assert outcomes[0].original_language == "en"
    assert outcomes[0].translated_text is None


async def test_classification_is_given_the_section_keys_to_choose_from() -> None:
    client = _StubClient([_ClassifiedTranscript(section_keys=["performance"])])
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

    client = _StubClient([_CleanedTranscript(cleaned_text=["x"])])
    engines = anthropic_debrief_engines(client, model=DEFAULT_MODEL)

    await engines.clean("s1", [_utterance("x")])

    call = client.messages.calls[0]
    assert call["model"] == DEFAULT_MODEL
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["output_format"] is _CleanedTranscript, "output must be schema-enforced"


async def test_diarization_is_not_treated_as_a_model_call() -> None:
    """It is a speech-vendor seam; wiring Claude to it would be wrong."""

    engines = anthropic_debrief_engines(_StubClient([]))

    with pytest.raises(RuntimeError, match="speech-vendor"):
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
