"""Production inference engines, backed by Claude.

ADR-012 assigns the harnesses: the Agent SDK for the genuinely agentic
workloads, the plain Messages API for single-shot structured extraction. The
debrief pipeline in `orchestration/debrief.py` decomposes into exactly the
latter — each stage takes a transcript and returns one schema-shaped result,
with no tool use and no multi-turn state — so each stage is one
`messages.parse` call rather than an agent loop. `converse`, the FR-7.3
conversational half, is the one exception: it is multi-turn and its output is
prose, so it is a plain `messages.create` and carries its own history.

Two design rules come straight from §14.4 ("schema, not prose") and §14.3
("the cache prefix is the whole game"):

* **Every stage uses structured outputs.** `messages.parse(output_format=...)`
  validates the response against a Pydantic model, so a stage either gets a
  well-formed result or raises — it never hands half-parsed prose to the next
  stage. Nothing here parses free text.
* **The stable half of every prompt is cached.** Each stage's system prompt is
  frozen and marked `cache_control`, and the volatile transcript follows it,
  so repeated stages across a long debrief pay the cached rate on the
  instructions.

`diarize` is deliberately absent. It is an audio-vendor seam, not a model
call — the speech engine that clusters speakers, not Claude — so it is
supplied separately by whoever configures capture.
"""

from __future__ import annotations

import functools
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

from anthropic import (
    AnthropicError,
    APIConnectionError,
    APITimeoutError,
    AsyncAnthropic,
    AuthenticationError,
    InternalServerError,
    OverloadedError,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import BaseModel, Field

from app.modules.compiler.agent.models import (
    AnalystBatchResult,
    BmadAnalystPassOutput,
    BmadCandidateDraft,
)
from app.modules.compiler.citations.models import (
    CitedSpan,
    ClaimStructuringDraft,
    ClaimStructuringOutput,
    DocumentExtractionOutput,
    ExtractedClaimDraft,
)
from app.modules.debrief.pipeline.models import (
    BmadAnalystChainOutput,
    BmadDecisionDraft,
    BmadFollowUpEmailDraft,
    BmadOpenQuestionDraft,
    BmadProjectBriefDraft,
    TranslationOutcome,
)

from .engines import (
    STAGE_CLASSIFY,
    STAGE_CLEAN,
    STAGE_CONVERSE,
    STAGE_EXTRACT,
    STAGE_FETCH_BATCH,
    STAGE_RUN_CHAIN,
    STAGE_STRUCTURE,
    STAGE_SUBMIT_BATCH,
    STAGE_TRANSLATE,
    CompilerEngines,
    DebriefEngines,
    EngineNotConfiguredError,
    UpstreamFailure,
    UpstreamUnavailableError,
)

# Best available model: the compiler and debrief run offline with no latency
# constraint, and §3.10 is explicit that this is "where model spend goes and
# where it belongs".
DEFAULT_MODEL = "claude-opus-5"

# Non-streaming calls; keep clear of the SDK's HTTP timeout.
MAX_TOKENS = 16000



# The bank shape the analyst batch must return. Derived from the domain model
# so the two cannot drift: a hand-copied schema is a second source of truth.
_BANK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "template_section": {"type": "string"},
                    "trigger_types": {"type": "array", "items": {"type": "string"}},
                    "phrasing": {"type": "string"},
                    "stub": {"type": "string"},
                    "lang": {"type": "string"},
                    "priority": {"type": "integer", "minimum": 1},
                    "requires": {"type": "array", "items": {"type": "string"}},
                    "authority_match": {"type": "array", "items": {"type": "string"}},
                    "source_doc": {"type": ["string", "null"]},
                },
                "required": [
                    "template_section",
                    "trigger_types",
                    "phrasing",
                    "stub",
                    "lang",
                    "priority",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["candidates"],
    "additionalProperties": False,
}


def _batch_error(result: Any) -> str:
    """A readable reason for a non-succeeded batch entry."""

    if result.type == "errored":
        return f"analyst batch errored: {getattr(result.error, 'type', 'unknown')}"
    return f"analyst batch {result.type}"


def _cached_system(text: str) -> list[dict[str, Any]]:
    """A frozen system prompt, marked as a cache breakpoint.

    The instructions never vary per call, so they belong in the cached
    prefix; the transcript that does vary goes in the user turn after it.
    """

    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


# --------------------------------------------------------------------------
# Response schemas. These constrain what the model may return — they are not
# the domain models, which the adapters build from them.
# --------------------------------------------------------------------------


class _CleanedTranscript(BaseModel):
    """One cleaned line per input utterance, in the same order."""

    cleaned_text: list[str] = Field(
        description="Cleaned text for each utterance, same length and order as the input."
    )


class _TranslatedLine(BaseModel):
    original_language: str = Field(description="BCP-47 code of the language actually spoken.")
    translated_text: str | None = Field(
        default=None,
        description="Translation into the document language, or null if already in it.",
    )


class _TranslatedTranscript(BaseModel):
    lines: list[_TranslatedLine]


class _ClassifiedTranscript(BaseModel):
    section_keys: list[str] = Field(
        description="Template section key for each utterance, same length and order as the input."
    )


class _OpenQuestionOut(BaseModel):
    text: str
    impact_rank: int = Field(ge=1)
    provenance: str = Field(description="'stated' if the client said it, 'inferred' otherwise.")
    citation_utterance_ids: list[str]


class _DecisionOut(BaseModel):
    text: str
    decided_by: str
    provenance: str
    citation_utterance_ids: list[str]


class _BriefOut(BaseModel):
    body: str
    provenance: str
    citation_utterance_ids: list[str]


class _EmailOut(BaseModel):
    subject: str
    body: str
    provenance: str
    citation_utterance_ids: list[str]


class _AnalystArtifacts(BaseModel):
    open_questions: list[_OpenQuestionOut]
    decisions: list[_DecisionOut]
    project_brief: _BriefOut
    follow_up_email: _EmailOut


class _ExtractedClaimOut(BaseModel):
    text: str
    document_id: str
    cited_text: str
    start_char_index: int = Field(ge=0)
    end_char_index: int = Field(gt=0)


class _ExtractionOut(BaseModel):
    claims: list[_ExtractedClaimOut]


class _StructuredCandidateOut(BaseModel):
    claim_id: str
    template_section: str
    trigger_types: list[str]
    phrasing: str
    stub: str
    lang: str
    priority: int = Field(ge=1)
    requires: list[str] = Field(default_factory=list)
    authority_match: list[str] = Field(default_factory=list)


class _StructuringOut(BaseModel):
    candidates: list[_StructuredCandidateOut]


# --------------------------------------------------------------------------
# Prompts. Frozen text — any edit invalidates the cached prefix, so keep them
# stable and put anything per-call in the user turn.
# --------------------------------------------------------------------------

_CLEANING_SYSTEM = """You clean meeting transcripts for a requirements analyst.

Remove disfluencies (um, uh, false starts, repeated words) and add sentence
punctuation. Correct obvious transcription errors in domain vocabulary.

Never change meaning, never summarise, never merge or drop an utterance.
Return exactly one cleaned line per input utterance, in the same order. A
line that needs no change is returned unchanged."""

_TRANSLATION_SYSTEM = """You translate meeting transcripts for a requirements analyst.

For each utterance, identify the language actually spoken and translate it
into the document language. If the utterance is already in the document
language, return null for the translation rather than restating it.

The original is retained alongside your translation and is authoritative, so
translate literally: preserve hedges, vagueness and ambiguity exactly as
spoken. Do not resolve an ambiguity the speaker left open — that ambiguity is
the signal the analyst is looking for.

Return exactly one entry per input utterance, in the same order."""

_CLASSIFICATION_SYSTEM = """You map meeting utterances onto requirements template sections.

You are given the section list and the transcript. Assign each utterance the
key of the section it belongs to. Use only keys from the supplied list.

Return exactly one key per input utterance, in the same order."""

_ANALYST_SYSTEM = """You are the BMAD Analyst producing planning artifacts from a client
requirements meeting.

Produce: open questions ranked by impact, a decision log, a project brief,
and a follow-up email.

Every claim must cite the utterance ids it rests on — cite ids from the
transcript you were given and never invent one. Mark provenance "stated" only
when the client actually said it; anything you concluded is "inferred". A
reviewer's core need is telling those two apart, so do not blur them."""

_DEBRIEF_CONVERSATION_SYSTEM = """You are Elicta, answering an analyst's questions about a \
requirements meeting that has just finished.

Answer only from the transcript and artifacts in this conversation. Say when
something was never covered rather than filling the gap — the analyst is using
you to find out what is missing, so an invented answer costs them the very
thing they came for. Distinguish what the client stated from what you
inferred, every time. Be brief; this is a working conversation, not a report."""


_EXTRACTION_SYSTEM = """You extract factual claims from client reference documents.

For each claim, quote the exact supporting span and give its character
offsets in the source document. Quote verbatim — the offsets are used to
bind the claim back to the document, so an approximate quote breaks the
citation."""

_STRUCTURING_SYSTEM = """You turn extracted claims into pre-phrased candidate follow-up questions.

Each candidate carries the template section it serves, the trigger types that
should surface it, a full phrasing, and a short stub for the panel. Priority
1 is highest.

The phrasing is read aloud by an operator mid-meeting, so it must be short,
natural, and answerable — not a written survey question."""


def _numbered(lines: list[str]) -> str:
    return "\n".join(f"{index}. {line}" for index, line in enumerate(lines, start=1))


def _retry_after(exc: Any) -> float | None:
    """How long the provider asked us to wait, if it said.

    Only what it actually sent. A guessed number is worse than none: a client
    that trusts it retries straight back into the same limit.
    """

    header = getattr(getattr(exc, "response", None), "headers", None)
    if header is None:
        return None
    try:
        return float(header.get("retry-after"))
    except (TypeError, ValueError):
        return None


def _upstream_failure(stage: str, exc: AnthropicError) -> UpstreamUnavailableError | None:
    """A vendor exception as a neutral one, or `None` when the fault is ours.

    `None` is the load-bearing half. A 400 means this codebase sent the
    provider something it could not accept — a bug here, not a condition out
    there — and a bug that answers 503 is a bug nobody investigates. Only the
    conditions an operator can actually respond to are translated; everything
    else is left to become the 500 it is.
    """

    if isinstance(exc, RateLimitError):
        return UpstreamUnavailableError(
            stage,
            UpstreamFailure.RATE_LIMITED,
            "the model provider is rate limiting this deployment. "
            "The same request should succeed shortly — this is a limit, not a fault.",
            retry_after=_retry_after(exc),
        )
    # Before `APIConnectionError`, which it subclasses.
    if isinstance(exc, APITimeoutError):
        return UpstreamUnavailableError(
            stage, UpstreamFailure.UNAVAILABLE, "the model provider timed out."
        )
    if isinstance(exc, APIConnectionError):
        return UpstreamUnavailableError(
            stage,
            UpstreamFailure.UNAVAILABLE,
            "the model provider could not be reached. Check the network path to it.",
        )
    if isinstance(exc, OverloadedError):
        return UpstreamUnavailableError(
            stage,
            UpstreamFailure.UNAVAILABLE,
            "the model provider is overloaded and asked us to try again.",
            retry_after=_retry_after(exc),
        )
    if isinstance(exc, InternalServerError):
        return UpstreamUnavailableError(
            stage,
            UpstreamFailure.UNAVAILABLE,
            f"the model provider failed with a server error ({exc.status_code}).",
        )
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return UpstreamUnavailableError(
            stage,
            UpstreamFailure.CREDENTIAL_REJECTED,
            "the model provider rejected the configured credential. "
            "Re-enter it on the Settings screen.",
        )
    return None


def _upstream_aware(stage: str) -> Callable[..., Any]:
    """Translate this stage's vendor failures into the neutral ones.

    Here rather than in the composition root, because this is the only module
    that knows which SDK is underneath. Everything above it sees
    `UpstreamUnavailableError` and can answer without importing a vendor.

    The catch is `AnthropicError`, the SDK's own base class, and not
    `Exception`: a stage that divides by zero must still crash like a stage
    that divides by zero.
    """

    def decorate(call: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(call)
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            try:
                return await call(*args, **kwargs)
            except AnthropicError as exc:
                failure = _upstream_failure(stage, exc)
                if failure is None:
                    raise
                raise failure from exc

        return wrapped

    return decorate


def anthropic_debrief_engines(
    client: AsyncAnthropic | None = None,
    *,
    model: str = DEFAULT_MODEL,
    diarize: Any = None,
) -> DebriefEngines:
    """The four text stages of §7, backed by Claude.

    `diarize` is passed through untouched: it is a speech-vendor seam, not a
    model call, so this module neither supplies nor wraps it.
    """

    client = client or AsyncAnthropic()

    async def _parse(system: str, prompt: str, schema: type[BaseModel]) -> Any:
        response = await client.messages.parse(
            model=model,
            max_tokens=MAX_TOKENS,
            system=_cached_system(system),
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
        return response.parsed_output

    @_upstream_aware(STAGE_CLEAN)
    async def clean(session_id: str, utterances: list[Any]) -> list[str]:
        parsed = await _parse(
            _CLEANING_SYSTEM,
            "Clean these utterances:\n\n" + _numbered([u.text for u in utterances]),
            _CleanedTranscript,
        )
        return _same_length(parsed.cleaned_text, utterances, "cleaning")

    @_upstream_aware(STAGE_TRANSLATE)
    async def translate(
        session_id: str, utterances: list[Any], document_language: str
    ) -> list[TranslationOutcome]:
        parsed = await _parse(
            _TRANSLATION_SYSTEM,
            f"Document language: {document_language}\n\nUtterances:\n\n"
            + _numbered([u.cleaned_text for u in utterances]),
            _TranslatedTranscript,
        )
        lines = _same_length(parsed.lines, utterances, "translation")
        return [
            TranslationOutcome(
                original_language=line.original_language,
                translated_text=line.translated_text,
            )
            for line in lines
        ]

    @_upstream_aware(STAGE_CLASSIFY)
    async def classify(
        session_id: str, utterances: list[Any], sections: list[Any]
    ) -> list[str]:
        section_list = "\n".join(f"- {s.key}: {s.title}" for s in sections)
        parsed = await _parse(
            _CLASSIFICATION_SYSTEM,
            f"Sections:\n{section_list}\n\nUtterances:\n\n"
            + _numbered([u.cleaned_text for u in utterances]),
            _ClassifiedTranscript,
        )
        return _same_length(parsed.section_keys, utterances, "classification")

    @_upstream_aware(STAGE_RUN_CHAIN)
    async def run_chain(session_id: str, utterances: list[Any]) -> BmadAnalystChainOutput:
        transcript = "\n".join(
            f"[{u.utterance_id}] ({u.speaker_tag}, {u.section_key}) {u.cleaned_text}"
            for u in utterances
        )
        parsed = await _parse(
            _ANALYST_SYSTEM, f"Transcript:\n\n{transcript}", _AnalystArtifacts
        )
        return BmadAnalystChainOutput(
            open_questions=[
                BmadOpenQuestionDraft(**question.model_dump())
                for question in parsed.open_questions
            ],
            decisions=[
                BmadDecisionDraft(**decision.model_dump()) for decision in parsed.decisions
            ],
            project_brief=BmadProjectBriefDraft(**parsed.project_brief.model_dump()),
            follow_up_email=BmadFollowUpEmailDraft(**parsed.follow_up_email.model_dump()),
        )

    @_upstream_aware(STAGE_CONVERSE)
    async def converse(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """One turn of the FR-7.3 debrief conversation.

        The odd one out in this module: every other stage is a single-shot
        `messages.parse` against a schema, because §14.4 wants schema and not
        prose. A conversation *is* prose, so this is a plain `create` — and
        the assistant's content blocks are returned exactly as the API sent
        them, never flattened to a string, because the caller persists them
        verbatim and replays them back as the next turn's history.
        """

        response = await client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=_cached_system(_DEBRIEF_CONVERSATION_SYSTEM),
            messages=turns,
        )
        return [block.model_dump() for block in response.content]

    return DebriefEngines(
        name=model,
        diarize=diarize if diarize is not None else _no_diarizer,
        clean=clean,
        translate=translate,
        classify=classify,
        run_chain=run_chain,
        converse=converse,
    )


async def _no_diarizer(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError(
        "diarization is a speech-vendor seam, not a model call — supply "
        "`diarize` to anthropic_debrief_engines() from the configured ASR "
        "vendor (architecture §3.3, ADR-011)."
    )


def _same_length(produced: list[Any], expected: list[Any], stage: str) -> list[Any]:
    """Reject a per-utterance result that does not line up with its input.

    Every stage here is positional: entry *n* of the output describes
    utterance *n*. A length mismatch silently shifts every downstream
    citation onto the wrong utterance, which is the one failure mode that
    would corrupt artifacts while still looking well-formed.
    """

    if len(produced) != len(expected):
        raise ValueError(
            f"{stage} returned {len(produced)} entries for {len(expected)} "
            "utterances; results are positional and must line up"
        )
    return produced


def anthropic_compiler_engines(
    client: AsyncAnthropic | None = None, *, model: str = DEFAULT_MODEL
) -> CompilerEngines:
    """The §3.10 compiler chain, backed by Claude.

    The analyst pass goes through the Message Batches API rather than a live
    call: §3.10 describes this work as "batch, offline, minutes not seconds",
    so submission and collection are deliberately separate steps.
    """

    client = client or AsyncAnthropic()

    @_upstream_aware(STAGE_EXTRACT)
    async def extract(engagement_id: str, documents: list[Any]) -> DocumentExtractionOutput:
        corpus = "\n\n".join(
            f"<document id=\"{d.document_id}\">\n{d.text}\n</document>" for d in documents
        )
        response = await client.messages.parse(
            model=model,
            max_tokens=MAX_TOKENS,
            system=_cached_system(_EXTRACTION_SYSTEM),
            messages=[{"role": "user", "content": f"Documents:\n\n{corpus}"}],
            output_format=_ExtractionOut,
        )
        return DocumentExtractionOutput(
            claims=[
                ExtractedClaimDraft(
                    text=claim.text,
                    citation=CitedSpan(
                        document_id=claim.document_id,
                        cited_text=claim.cited_text,
                        start_char_index=claim.start_char_index,
                        end_char_index=claim.end_char_index,
                    ),
                )
                for claim in response.parsed_output.claims
            ]
        )

    @_upstream_aware(STAGE_STRUCTURE)
    async def structure(engagement_id: str, claims: list[Any]) -> ClaimStructuringOutput:
        claim_list = "\n".join(f"[{c.id}] {c.text}" for c in claims)
        response = await client.messages.parse(
            model=model,
            max_tokens=MAX_TOKENS,
            system=_cached_system(_STRUCTURING_SYSTEM),
            messages=[{"role": "user", "content": f"Claims:\n\n{claim_list}"}],
            output_format=_StructuringOut,
        )
        return ClaimStructuringOutput(
            candidates=[
                ClaimStructuringDraft(**candidate.model_dump())
                for candidate in response.parsed_output.candidates
            ]
        )

    @_upstream_aware(STAGE_SUBMIT_BATCH)
    async def submit_batch(engagement_id: str, context_pack: Any) -> str:
        documents = "\n\n".join(
            f"<document id=\"{d.document_id}\" status=\"{d.status.value}\">\n{d.text}\n</document>"
            for d in getattr(context_pack, "documents", [])
        )
        batch = await client.messages.batches.create(
            requests=[
                {
                    "custom_id": engagement_id,
                    "params": {
                        "model": model,
                        "max_tokens": MAX_TOKENS,
                        # Schema-enforced here too (§14.4). A batch result is
                        # collected hours later by a different process, so
                        # prose that "looks parseable" is not recoverable —
                        # the schema has to hold at submission time.
                        "output_config": {
                            "format": {
                                "type": "json_schema",
                                "schema": _BANK_SCHEMA,
                            }
                        },
                        "system": _ANALYST_SYSTEM,
                        "messages": [
                            {
                                "role": "user",
                                "content": (
                                    f"Sector: {context_pack.sector}\n"
                                    f"Project type: {context_pack.project_type}\n\n"
                                    f"Documents:\n\n{documents}"
                                ),
                            }
                        ],
                    },
                }
            ]
        )
        return batch.id

    @_upstream_aware(STAGE_FETCH_BATCH)
    async def fetch_batch(batch_job_id: str) -> list[AnalystBatchResult]:
        """Collect a submitted analyst batch, if it has finished.

        Returns an empty list while the batch is still processing — the
        caller polls rather than blocking, since §3.10 budgets minutes for
        this work and holding a connection open for it would be wrong.
        """

        batch = await client.messages.batches.retrieve(batch_job_id)
        if batch.processing_status != "ended":
            return []

        collected: list[AnalystBatchResult] = []
        async for entry in await client.messages.batches.results(batch_job_id):
            if entry.result.type != "succeeded":
                collected.append(
                    AnalystBatchResult(
                        custom_id=entry.custom_id,
                        output=None,
                        error=_batch_error(entry.result),
                    )
                )
                continue

            text = next(
                (b.text for b in entry.result.message.content if b.type == "text"), ""
            )
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                collected.append(
                    AnalystBatchResult(
                        custom_id=entry.custom_id,
                        output=None,
                        error=f"analyst batch returned unparseable output: {exc}",
                    )
                )
                continue

            collected.append(
                AnalystBatchResult(
                    custom_id=entry.custom_id,
                    output=BmadAnalystPassOutput(
                        candidates=[
                            BmadCandidateDraft(**candidate)
                            for candidate in payload.get("candidates", [])
                        ]
                    ),
                )
            )
        return collected

    return CompilerEngines(
        name=model, extract=extract, structure=structure,
        submit_batch=submit_batch, fetch_batch=fetch_batch,
    )



# `Authorization: Bearer` auth is gated behind this API beta flag. The SDK
# injects it for credentials it manages itself, but explicitly skips that when
# a static credential is already on the request — which is exactly the
# bring-your-own-token case here — so it has to be supplied.
OAUTH_BETA_HEADER = "oauth-2025-04-20"


def build_anthropic_client(
    mode: Any, secret: str, *, base_url: str | None = None
) -> AsyncAnthropic:
    """A direct or compatible-endpoint client for the supplied credential.

    An API key goes on `X-Api-Key`; an OAuth token goes on
    `Authorization: Bearer` and carries the beta flag that unlocks it. Getting
    that pairing wrong fails as a 401 that looks like a bad credential rather
    than a missing header, so the two are built together here and nowhere
    else.
    """

    from app.modules.settings.models import AuthMode

    kwargs: dict[str, Any] = {}
    if base_url:
        kwargs["base_url"] = base_url

    if mode is AuthMode.OAUTH_TOKEN:
        kwargs["auth_token"] = secret
        kwargs["default_headers"] = {"anthropic-beta": OAUTH_BETA_HEADER}
    else:
        kwargs["api_key"] = secret

    return AsyncAnthropic(**kwargs)


def build_llm_client(inference: Any, secret: str | None) -> Any:
    """The client for whichever Messages API surface the operator chose.

    Each cloud reseller has its own client class rather than a `base_url`
    override on the default one: they differ in request signing and in how
    model ids are addressed, and pointing the plain client at their endpoint
    produces authentication failures that read like bad credentials.

    Bedrock and Vertex take no secret from settings on purpose — they
    authenticate through the host's own credential chain (an IAM role, GCP
    application-default credentials), which is a better mechanism than a
    long-lived key pasted into a form.
    """

    from anthropic import (
        AsyncAnthropicBedrockMantle,
        AsyncAnthropicFoundry,
        AsyncAnthropicVertex,
    )

    from app.modules.settings.models import LlmProvider

    provider = inference.provider

    if provider is LlmProvider.BEDROCK:
        return AsyncAnthropicBedrockMantle(aws_region=inference.region)

    if provider is LlmProvider.VERTEX:
        return AsyncAnthropicVertex(
            project_id=inference.project_id, region=inference.region
        )

    if provider is LlmProvider.FOUNDRY:
        if secret is None:
            raise EngineNotConfiguredError("inference (no Foundry key configured)")
        return AsyncAnthropicFoundry(api_key=secret, resource=inference.resource)

    # Anthropic direct, and any compatible gateway — same client, differing
    # only in where it points.
    if secret is None:
        raise EngineNotConfiguredError("inference (no credential configured)")
    return build_anthropic_client(
        inference.auth_mode, secret, base_url=inference.base_url
    )


class SettingsBackedClient:
    """An Anthropic client that re-resolves its credentials on every call.

    An admin screen exists so an operator can fix a wrong or expired key
    without a restart. That only works if the credential is read at call
    time — engines built once at startup would hold the key the service
    booted with and silently ignore every later change.

    The underlying client is cached per (credential, base URL) pair, so
    re-resolving costs a dict lookup rather than a new connection pool per
    request.
    """

    def __init__(self, store: Any) -> None:
        self._store = store
        self._cache: dict[tuple[str, str | None, str], Any] = {}

    def _resolve(self) -> Any:
        inference = self._store.read().inference
        secret = None

        if inference.provider.uses_stored_credential:
            stored = self._store.get_secret(inference.auth_mode.secret_key)
            if stored is None:
                raise EngineNotConfiguredError(
                    f"inference (no {inference.auth_mode.value.replace('_', ' ')} "
                    f"configured for {inference.provider.value})"
                )
            secret = stored.reveal()

        cache_key = (
            secret or "",
            inference.base_url,
            f"{inference.provider.value}:{inference.auth_mode.value}:"
            f"{inference.region}:{inference.project_id}:{inference.resource}",
        )
        client = self._cache.get(cache_key)
        if client is None:
            client = build_llm_client(inference, secret)
            self._cache[cache_key] = client
        return client

    @property
    def messages(self) -> Any:
        return self._resolve().messages

    def current_model(self) -> str:
        return self._store.read().inference.model or DEFAULT_MODEL


def engines_from_settings(
    store: Any, *, diarize: Any = None
) -> tuple[DebriefEngines, CompilerEngines]:
    """Build engines that read their credentials from the settings store.

    Always returns engines — unlike `configured_engines`, which reports
    absence — because with a settings UI the credential can arrive after
    startup. A stage that runs before one is configured raises
    `EngineNotConfiguredError` and is recorded as FAILED, exactly as an
    unconfigured environment does.
    """

    client = SettingsBackedClient(store)
    model = store.read().inference.model or DEFAULT_MODEL
    return (
        anthropic_debrief_engines(client, model=model, diarize=diarize),
        anthropic_compiler_engines(client, model=model),
    )


def configured_engines(
    *, diarize: Any = None, model: str | None = None
) -> tuple[DebriefEngines, CompilerEngines] | None:
    """Build production engines if credentials are present, else `None`.

    Returning `None` rather than a half-configured pair keeps the decision in
    one place: the composition root falls back to the unconfigured engines,
    which fail loudly per stage.
    """

    from .engines import inference_is_configured

    if not inference_is_configured():
        return None

    chosen = model or os.environ.get("ELICTA_INFERENCE_MODEL") or DEFAULT_MODEL
    client = AsyncAnthropic()
    return (
        anthropic_debrief_engines(client, model=chosen, diarize=diarize),
        anthropic_compiler_engines(client, model=chosen),
    )


async def probe_anthropic_credential(
    secret: str, *, base_url: str | None = None, mode: Any = None
) -> None:
    """Verify an Anthropic credential, raising if it does not work.

    Lists models rather than sending a message: it exercises the same
    authentication path, costs no tokens, and cannot be mistaken for product
    traffic in the operator's usage. Raises the SDK's own typed error, which
    the settings surface renders by type and message — never echoing the
    credential back.
    """

    from app.modules.settings.models import AuthMode

    client = build_anthropic_client(mode or AuthMode.API_KEY, secret, base_url=base_url)
    await client.models.list(limit=1)
