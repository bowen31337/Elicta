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
    DEFAULT_TEMPLATE_SECTIONS,
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
    UNCLASSIFIED_SECTION_KEY,
    BmadAnalystChainOutput,
    BmadDecisionDraft,
    BmadFollowUpEmailDraft,
    BmadOpenQuestionDraft,
    BmadProjectBriefDraft,
    TranslationOutcome,
)
from app.modules.trigger.lexicon import GATE_TRIGGER_TYPES

from .engines import (
    STAGE_CLASSIFY,
    STAGE_CLEAN,
    STAGE_CONVERSE,
    STAGE_DIARIZE,
    STAGE_EXTRACT,
    STAGE_FETCH_BATCH,
    STAGE_RUN_ANALYST,
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

# The Analyst pass is the one stage that emits a whole bank, and it needs its
# own budget. Every stage shared `MAX_TOKENS`, which suits a handful of claims
# and does not suit up to `MAX_CANDIDATES` candidates each carrying a section,
# a trigger list, a phrasing, a stub, a language and a priority.
#
# The failure is not a smaller bank. Truncation lands mid-token, so what comes
# back is unparseable and the whole pass is lost — observed live as
# "Unterminated string starting at: line 1 column 15243", with the batch
# reported as succeeded by the provider and the bank empty.
# Measured against the provider rather than chosen: 128,000 is accepted and
# 200,000 is refused — "max_tokens: 200000 > 128000, which is the maximum
# allowed number of output tokens for claude-opus-5". So this is the ceiling,
# not a guess at one.
#
# A cap is not a spend. The bill is for tokens produced, so sitting at the
# maximum costs nothing until an answer actually needs the room — and one
# twenty-eight thousand character document already draws fourteen thousand
# output tokens, so a handful of them walks past anything smaller.
#
# What this does *not* fix is many documents. That pressure is on the input
# side — the context window — and no output budget touches it. Extraction
# sends the whole corpus in one request; the way past that is a request per
# document, not a bigger answer.
ANALYST_MAX_TOKENS = 128_000


#: Extended thinking, off, for every stage that asks for a schema-shaped
#: answer about text already in the prompt.
#:
#: Thinking spends the same budget the answer comes out of. Measured on a
#: twenty-eight thousand character document: `stop_reason: max_tokens`,
#: `output_tokens: 32000`, `thinking_tokens: 32000` — all of it. The answer
#: stopped a few hundred characters in, the JSON would not parse, and the
#: compile reported an `AttributeError` about a `NoneType`.
#:
#: Raising the budget only bought more thinking: the truncation point moved
#: and stayed random. With this off the same call ends `end_turn` on 14,820
#: tokens and parses.
NO_THINKING: dict[str, str] = {"type": "disabled"}


def _parsed_or_refuse(response: Any, stage: str) -> Any:
    """The parsed answer, or a failure that says what happened.

    `parsed_output` is `None` when the model's answer did not fit the schema,
    and the commonest reason is that it was truncated. Read straight through,
    that surfaced as `'NoneType' object has no attribute 'claims'` on the
    operator's screen — an `AttributeError` about a type they have never heard
    of, for a document that was simply too long.

    `UNAVAILABLE` rather than a bug, because that is what it is: the provider
    was reached and did not give a usable answer. The remedy is the same one
    that kind always has — try again, with less.
    """

    if getattr(response, "parsed_output", None) is None:
        raise UpstreamUnavailableError(
            stage,
            UpstreamFailure.UNAVAILABLE,
            "the answer could not be read against the schema, which usually "
            "means it was cut short. A shorter document set is the way past it.",
        )
    return response.parsed_output




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
                    # A closed vocabulary, and the gate's own. Free strings
                    # were accepted here and nothing could consume them: the
                    # runtime matches a hit's category against this list, and
                    # a model writing "vague quantity" where the gate says
                    # `unquantified_amount` records a fact no one can use.
                    "trigger_types": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(GATE_TRIGGER_TYPES)},
                    },
                    "phrasing": {"type": "string"},
                    "stub": {"type": "string"},
                    "lang": {"type": "string"},
                    # No `minimum`. The provider refuses numeric bounds on an
                    # integer outright — "For 'integer' type, property
                    # 'minimum' is not supported" — and refuses them in the
                    # batch *result* rather than at submission, so every
                    # compile was accepted, ended forty-six seconds later with
                    # one errored request, and left the screen saying the
                    # drafting job was still with the provider. The bound
                    # bought nothing that `BankCandidate` does not already
                    # enforce where the result is parsed.
                    "priority": {"type": "integer"},
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


#: Every per-utterance schema below carries the number of the utterance it
#: describes. That is the whole mechanism: results are matched by what they
#: say they are for, not by where they happen to land, so a model that returns
#: one entry too few or too many can no longer shift a citation onto the wrong
#: utterance — and no longer costs a finished meeting its documents either.
class _UtteranceLine(BaseModel):
    utterance: int = Field(
        description="The number of the utterance this entry is for, exactly as numbered in the input."
    )


class _CleanedLine(_UtteranceLine):
    cleaned_text: str = Field(description="The cleaned text of that utterance.")


class _CleanedTranscript(BaseModel):
    lines: list[_CleanedLine]


class _TranslatedLine(_UtteranceLine):
    original_language: str = Field(description="BCP-47 code of the language actually spoken.")
    translated_text: str | None = Field(
        default=None,
        description="Translation into the document language, or null if already in it.",
    )


class _TranslatedTranscript(BaseModel):
    lines: list[_TranslatedLine]


class _ClassifiedLine(_UtteranceLine):
    section_key: str = Field(description="Key of the section that utterance belongs to.")


class _ClassifiedTranscript(BaseModel):
    lines: list[_ClassifiedLine]


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
A line that needs no change is returned unchanged.

Each input utterance is numbered. Give every line the number of the utterance
it is for. Cover every utterance."""

_TRANSLATION_SYSTEM = """You translate meeting transcripts for a requirements analyst.

For each utterance, identify the language actually spoken and translate it
into the document language. If the utterance is already in the document
language, return null for the translation rather than restating it.

The original is retained alongside your translation and is authoritative, so
translate literally: preserve hedges, vagueness and ambiguity exactly as
spoken. Do not resolve an ambiguity the speaker left open — that ambiguity is
the signal the analyst is looking for.

Each input utterance is numbered. Give every entry the number of the utterance
it is for. Cover every utterance."""

_CLASSIFICATION_SYSTEM = """You map meeting utterances onto requirements template sections.

You are given the section list and the transcript. Assign each utterance the
key of the section it belongs to. Use only keys from the supplied list.

Each input utterance is numbered. Give every entry the number of the utterance
it is for. Cover every utterance."""

_ANALYST_SYSTEM = """You are the BMAD Analyst producing planning artifacts from a client
requirements meeting.

Produce: open questions ranked by impact, a decision log, a project brief,
and a follow-up email.

Every claim must cite the utterance ids it rests on — cite ids from the
transcript you were given and never invent one. Mark provenance "stated" only
when the client actually said it; anything you concluded is "inferred". A
reviewer's core need is telling those two apart, so do not blur them."""

_COMPILER_ANALYST_SYSTEM = """You are the BMAD Analyst preparing for a requirements
meeting that has not happened yet.

You are given an engagement's reference documents and the sections of the
requirements template the answers have to fill. Produce a bank of candidate
questions an analyst could ask in the room — as many as the material genuinely
supports, up to 300. Breadth matters: a thin bank leaves gaps nobody notices
until the meeting is over.

Work through every section in turn and draft for each one before going back to
deepen any of them. A section the documents say little about is exactly where
the meeting has most to find out, so it needs questions rather than fewer of
them; a section carrying most of the bank means the others were skipped.

Tag every candidate:

- `template_section`: the section of the requirements template the answer
  belongs in. Use **only** the sections listed in the request, spelled exactly
  as they are given. Do not invent one, and do not add a general or
  miscellaneous section to hold whatever did not fit — a section that holds
  most of the bank is a bin rather than a section, and it makes the bank
  unreviewable. If a question genuinely fits none of the listed sections, it is
  not a question for this template; leave it out. Never file a candidate under
  a meeting artifact such as an open-questions list or a decision log; those
  are written after a meeting, and this is a bank for going into one.
- `trigger_types`: which conversational conditions should surface it, from
  this exact list and no other wording:
  `unquantified_amount` (a quantity nobody put a number on — "many", "a few"),
  `unquantified_property` (a quality nobody measured — "fast", "flexible"),
  `unquantified_time` (a date nobody fixed — "soon", "shortly"),
  `qualified_agreement` (an answer that agreed with conditions — "typically",
  "if possible").
  Name every one the question would genuinely answer; a question that answers
  none of them belongs to no trigger and will only ever be read on the
  preparation screen.
- `stub`: the question reduced to its keywords — **at most five words**, and
  three is better. Not a shortened sentence: no verb is needed, no question
  mark, no leading article. "Monthly arrivals, peak vs trough". "Late vessel:
  slot holds?". "Who owns the exception". This is the only part an operator
  reads while looking at a client, so a stub they have to *read* rather than
  glance at has failed at the one thing it is for. If the keywords do not fit
  in five words, the question is asking two things and belongs as two
  candidates.
- `phrasing`: the exact wording, ready to be read aloud.
- `priority`: 1 is highest.

Every candidate is a question. A statement of fact belongs in the documents it
came from, not in a bank of things to ask.

Ground each candidate in what the documents actually say, and set `source_doc`
to the document id it came from where one applies. A document tagged
`superseded` is background only: never draft a question that challenges anybody
using it. A `hypothesis` document is our own assumption rather than the
client's, so it yields questions that verify rather than questions that assert.

Stay in problem space. Do not ask questions shaped like a solution, or like an
implementation plan, before the template calls for them."""


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
should surface it, a full phrasing, and a stub for the panel. Priority 1 is
highest.

The phrasing is read aloud by an operator mid-meeting, so it must be short,
natural, and answerable — not a written survey question.

The stub is not a shorter phrasing. It is the question reduced to keywords, at
most five words, with no verb, article or question mark required — "Monthly
arrivals, peak vs trough". It is the only tier an operator reads without
breaking eye contact, so anything that has to be read rather than glanced at
has failed at the one thing it is for."""


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


def _vendor_message(exc: AnthropicError) -> str:
    """The provider's own sentence, when it sent one worth repeating."""

    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    return str(exc)


def _upstream_failure(stage: str, exc: AnthropicError) -> UpstreamUnavailableError | None:
    """A vendor exception as a neutral one, or `None` when the fault is ours.

    `None` is the load-bearing half. A 400 means this codebase sent the
    provider something it could not accept — a bug here, not a condition out
    there — and a bug that answers 503 is a bug nobody investigates. Only the
    conditions an operator can actually respond to are translated; everything
    else is left to become the 500 it is.
    """

    if isinstance(exc, RateLimitError):
        retry_after = _retry_after(exc)
        if retry_after is None:
            # A 429 with no `retry-after` and no rate-limit headers is what
            # Anthropic returns when the credential is not entitled to make
            # this request: the body says `rate_limit_error`, and the same
            # request a second later is refused identically. Promising it
            # "should succeed shortly" sends an operator away to wait for
            # something that never happens — which is exactly what it did.
            #
            # This named the model as the cause and only the model, which sent
            # the next operator to check a setting that was already right: the
            # engagement had `claude-opus-5` chosen and `models.list` returned
            # `claude-opus-5`. What was refused was an OAuth token's right to
            # call `/v1/messages` at all. The credential is the first thing to
            # look at, and the model the second.
            #
            # `NOT_ENTITLED` rather than `RATE_LIMITED`, because that kind is
            # documented as "a missing OAuth scope or a model the plan does not
            # include" and this is the second of those. The wording said as
            # much while the kind still said "throttled", so anything reading
            # the kind — which is what a screen has to do — repeated the advice
            # this sentence exists to rule out.
            return UpstreamUnavailableError(
                stage,
                UpstreamFailure.NOT_ENTITLED,
                "the model provider refused this request as rate limited but "
                "gave no time to retry after, so waiting will not clear it. "
                "That is how a request the credential is not entitled to make "
                "is refused: most often an OAuth token used where an API key "
                "is required, and sometimes a model the plan does not include. "
                "Check the credential first and the model second, in Settings.",
            )
        return UpstreamUnavailableError(
            stage,
            UpstreamFailure.RATE_LIMITED,
            "the model provider is rate limiting this deployment. "
            "The same request should succeed shortly — this is a limit, not a fault.",
            retry_after=retry_after,
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
    if isinstance(exc, PermissionDeniedError):
        # The credential is good and the request is not allowed — a missing
        # OAuth scope, most often. The provider names the scopes it wanted, and
        # that sentence is the only thing here that tells an operator what to
        # change, so it is carried through verbatim rather than replaced with
        # "re-enter the credential", which cannot help and was what this said.
        return UpstreamUnavailableError(
            stage,
            UpstreamFailure.NOT_ENTITLED,
            "the model provider accepted the credential and refused this "
            f"request: {_vendor_message(exc)}",
        )
    if isinstance(exc, AuthenticationError):
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
    parse: Any = None,
    converse_raw: Any = None,
) -> DebriefEngines:
    """The four text stages of §7, backed by Claude.

    `diarize` is passed through untouched: it is a speech-vendor seam, not a
    model call, so this module neither supplies nor wraps it.

    `parse` and `converse_raw` are the two model calls the stages make, and
    they are injectable so another harness can supply them without a second
    copy of the stages. ADR-012 puts the debrief engine on the Agent SDK, and
    everything that makes these stages worth trusting is *after* the model
    call — the per-utterance alignment, the gap handling FR-2.19 asks for, the
    strict zips. Writing those twice is how one harness quietly stops matching
    the other on the failure that corrupts artifacts while still looking
    well-formed.
    """

    async def _parse(system: str, prompt: str, schema: type[BaseModel]) -> Any:
        if parse is not None:
            return await parse(system, prompt, schema)
        nonlocal client
        client = client or AsyncAnthropic()
        response = await client.messages.parse(
            model=model,
            max_tokens=MAX_TOKENS,
            system=_cached_system(system),
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
            thinking=NO_THINKING,
        )
        return response.parsed_output

    @_upstream_aware(STAGE_CLEAN)
    async def clean(session_id: str, utterances: list[Any]) -> list[str]:
        parsed = await _parse(
            _CLEANING_SYSTEM,
            "Clean these utterances:\n\n" + _numbered([u.text for u in utterances]),
            _CleanedTranscript,
        )
        # An utterance the model skipped keeps its own words: not cleaned,
        # rather than cleaned into somebody else's.
        return [
            line.cleaned_text if line is not None else utterance.text
            for line, utterance in zip(
                _by_utterance(parsed.lines, len(utterances), "cleaning"),
                utterances,
                strict=True,
            )
        ]

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
        # A gap retains the original untranslated, which is what FR-2.19 asks
        # for anyway: the original is authoritative, and claiming a language
        # nobody identified would be worse than claiming none.
        return [
            TranslationOutcome(
                original_language=(
                    line.original_language if line is not None else document_language
                ),
                translated_text=line.translated_text if line is not None else None,
            )
            for line in _by_utterance(parsed.lines, len(utterances), "translation")
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
        # A gap is marked unclassified rather than borrowing its neighbour's
        # section: an utterance in the wrong slot fills a coverage slot that
        # nothing was actually said about.
        return [
            line.section_key if line is not None else UNCLASSIFIED_SECTION_KEY
            for line in _by_utterance(parsed.lines, len(utterances), "classification")
        ]

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

        if converse_raw is not None:
            return await converse_raw(_DEBRIEF_CONVERSATION_SYSTEM, turns)
        nonlocal client
        client = client or AsyncAnthropic()
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
    """The same refusal as any other unset seam, and typed like one.

    This raised a bare `RuntimeError` for a condition that is neither a bug nor
    a surprise: diarization is a speech-vendor seam, and no speech vendor is
    wired. Anything asking why a run stopped then had to tell this apart from a
    genuine crash by reading its prose, which is how the operator's screen came
    to show the words "supply `diarize` to anthropic_debrief_engines()".
    """

    raise EngineNotConfiguredError(
        STAGE_DIARIZE, "a speech vendor to tell the voices apart"
    )


def _by_utterance(lines: list[Any], count: int, stage: str) -> list[Any | None]:
    """One slot per utterance, filled from whichever line claims it.

    Entry *n* of a per-utterance result describes utterance *n*, and getting
    that wrong is the one failure that corrupts artifacts while still looking
    well-formed: every later claim binds to the wrong words. The old guard
    protected against it by refusing any result whose length did not match,
    which was correct and expensive — measured against a live model over a
    37-utterance meeting, two runs in three came back one entry out and the
    whole finished meeting's documents were discarded.

    Matching on the number each line carries keeps the safety property and
    drops the cost. A line for an utterance that does not exist is ignored
    rather than appended; two lines for the same utterance keep the first;
    an utterance no line claims comes back `None`, for the caller to fill
    with something honest.

    A result that claims *nothing* is still refused. Filling every slot would
    report a stage that did no work as a success, which is the failure this
    whole module exists to avoid.
    """

    slots: list[Any | None] = [None] * count
    matched = 0
    for line in lines:
        index = getattr(line, "utterance", 0) - 1
        if 0 <= index < count and slots[index] is None:
            slots[index] = line
            matched += 1
    if matched == 0 and count > 0:
        raise ValueError(
            f"{stage} returned nothing for any of {count} utterances"
        )
    return slots


def analyst_prompt(context_pack: Any) -> str:
    """The one place the Analyst request is written.

    Every route to the same pass reads this — the batch, the direct request,
    and the Agent SDK adapter. Written more than once they would drift, and a
    bank drafted by one route would quietly stop matching one drafted by
    another: the kind of difference nobody notices until two engagements
    disagree for no reason anyone can find.

    Module-level rather than a closure because it is now shared across
    modules, not just across the two routes in this one.
    """

    documents = "\n\n".join(
        f"<document id=\"{d.document_id}\" status=\"{d.status.value}\">\n{d.text}\n</document>"
        for d in getattr(context_pack, "documents", [])
    )
    # In the request rather than the system prompt: the system prompt is
    # cached across every engagement, and these vary per engagement.
    sections = list(getattr(context_pack, "template_sections", None) or ())
    if not sections:
        sections = list(DEFAULT_TEMPLATE_SECTIONS)
    listed = "\n".join(f"- {section}" for section in sections)
    return (
        f"Sector: {context_pack.sector}\n"
        f"Project type: {context_pack.project_type}\n\n"
        f"Template sections — file every candidate under exactly one of "
        f"these, and cover all of them:\n{listed}\n\n"
        f"Documents:\n\n{documents}"
    )


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
        # Streamed with the long-output budget, for the reason the Analyst
        # pass is: a claim per fact in the corpus grows with the corpus, and
        # sixteen thousand tokens is a cap a real document set walks past. The
        # failure is not a shorter list — truncation lands mid-token, the
        # answer will not parse, and the whole pass is lost.
        async with client.messages.stream(
            model=model,
            max_tokens=ANALYST_MAX_TOKENS,
            system=_cached_system(_EXTRACTION_SYSTEM),
            messages=[{"role": "user", "content": f"Documents:\n\n{corpus}"}],
            output_format=_ExtractionOut,
            thinking=NO_THINKING,
        ) as stream:
            response = await stream.get_final_message()
        parsed = _parsed_or_refuse(response, STAGE_EXTRACT)
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
                for claim in parsed.claims
            ]
        )

    @_upstream_aware(STAGE_STRUCTURE)
    async def structure(engagement_id: str, claims: list[Any]) -> ClaimStructuringOutput:
        claim_list = "\n".join(f"[{c.id}] {c.text}" for c in claims)
        # A candidate per claim, so this grows with extraction's output the
        # same way extraction grows with the corpus.
        async with client.messages.stream(
            model=model,
            max_tokens=ANALYST_MAX_TOKENS,
            system=_cached_system(_STRUCTURING_SYSTEM),
            messages=[{"role": "user", "content": f"Claims:\n\n{claim_list}"}],
            output_format=_StructuringOut,
            thinking=NO_THINKING,
        ) as stream:
            response = await stream.get_final_message()
        parsed = _parsed_or_refuse(response, STAGE_STRUCTURE)
        return ClaimStructuringOutput(
            candidates=[
                ClaimStructuringDraft(**candidate.model_dump())
                for candidate in parsed.candidates
            ]
        )

    _analyst_prompt = analyst_prompt

    @_upstream_aware(STAGE_RUN_ANALYST)
    async def run_analyst(engagement_id: str, context_pack: Any) -> list[AnalystBatchResult]:
        """The Analyst pass as an ordinary request, for a credential the Batch API refuses.

        The batch is the right default: it is cheaper, and §3.10 budgets
        minutes for work nobody is waiting on. It is not the only way to ask
        the question, and a token with no batch scope could otherwise never
        produce a bank at all — which is what happened.

        Returns the same shape a collected batch does, under the same
        `custom_id` convention, so the collection that enforces the 150-300
        candidate contract is shared rather than reimplemented. That contract
        is also why this is not free: a hundred and fifty drafted questions is
        a large answer to ask for in one request.
        """

        # Streamed, and that is what lets it ask for a whole bank. The SDK
        # refuses a *non-streaming* request whose budget implies more than ten
        # minutes of generation — "Streaming is required for operations that
        # may take longer than 10 minutes" — so this call was capped at the
        # shared sixteen thousand, and a bank that did not fit came back
        # truncated mid-token and failed to parse. Neither a smaller bank nor
        # an error: a whole pass lost.
        #
        # Schema-enforced from the pass's own model rather than the
        # hand-written batch schema beside it: this route parses its answer
        # immediately, so the model that has to hold is the one the collection
        # will read.
        async with client.messages.stream(
            model=model,
            max_tokens=ANALYST_MAX_TOKENS,
            system=_cached_system(_COMPILER_ANALYST_SYSTEM),
            messages=[{"role": "user", "content": _analyst_prompt(context_pack)}],
            output_format=BmadAnalystPassOutput,
            thinking=NO_THINKING,
        ) as stream:
            response = await stream.get_final_message()
        return [
            AnalystBatchResult(
                custom_id=engagement_id,
                output=_parsed_or_refuse(response, STAGE_RUN_ANALYST),
            )
        ]

    @_upstream_aware(STAGE_SUBMIT_BATCH)
    async def submit_batch(engagement_id: str, context_pack: Any) -> str:
        batch = await client.messages.batches.create(
            requests=[
                {
                    "custom_id": engagement_id,
                    "params": {
                        "model": model,
                        "max_tokens": ANALYST_MAX_TOKENS,
                        # See `NO_THINKING`. A batch is collected hours later,
                        # so a budget spent thinking is found late.
                        "thinking": NO_THINKING,
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
                        "system": _COMPILER_ANALYST_SYSTEM,
                        "messages": [
                            {
                                "role": "user",
                                "content": _analyst_prompt(context_pack),
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
        run_analyst=run_analyst,
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

    from app.modules.settings.models import AuthMode, SecretKey

    # The client re-reads the secret's value per request; `harness` below
    # re-reads which harness to send it to. Neither is captured here.
    client = SettingsBackedClient(store)

    # ADR-012 names the Agent SDK as the compiler's harness; the compiler
    # shipped on the Messages API for both. With an API key that difference is
    # a tidiness matter and the Messages API is the better of the two here —
    # it has the Batch API, which §3.10 wants and the agent loop has not.
    #
    # With an OAuth token it stops being a preference. `claude setup-token`
    # issues a credential entitled to Claude Code's surface, which is what the
    # Agent SDK runs; `/v1/messages` refuses it with a 429 carrying no
    # rate-limit headers, so on that credential the Messages API compiler
    # cannot draft a bank at all. The credential decides the harness because
    # only one harness will accept it.
    def harness() -> tuple[DebriefEngines, CompilerEngines]:
        """The engines the settings ask for *now*.

        Resolved per call rather than once, because the settings screen
        promises a credential takes effect without a restart and this was the
        half that did not keep it. `SettingsBackedClient` re-reads the secret's
        value on every request; the choice of harness was made in `create_app`
        and never revisited, so a deployment that booted on an OAuth token
        stayed on Claude Code's surface after the admin switched it to an API
        key — and went on spending a weekly Claude Code allowance the operator
        had stopped meaning to use.

        Cheap enough to do per stage: one settings read, and the Agent SDK
        import is already lazy. A stage is a model call taking seconds.
        """

        now = store.read()
        chosen_model = now.inference.model or DEFAULT_MODEL
        if now.inference.auth_mode is AuthMode.OAUTH_TOKEN:
            from .agent_sdk_engines import (
                agent_sdk_compiler_engines,
                agent_sdk_debrief_engines,
            )

            token = store.get_secret(SecretKey.ANTHROPIC_OAUTH_TOKEN)
            revealed = token.reveal() if token else None
            # Both halves, or the credential drafts a bank and then cannot
            # write up the meeting the bank was drafted for. ADR-012 puts the
            # debrief engine on the Agent SDK anyway; with this credential it
            # is the only harness that will take it.
            return (
                agent_sdk_debrief_engines(
                    oauth_token=revealed, model=chosen_model, diarize=diarize
                ),
                agent_sdk_compiler_engines(oauth_token=revealed, model=chosen_model),
            )
        return (
            anthropic_debrief_engines(client, model=chosen_model, diarize=diarize),
            anthropic_compiler_engines(client, model=chosen_model),
        )

    # `name` labels every record the pipeline persists, and `DebriefEngines`
    # is frozen, so it cannot follow a mid-session change of harness the way
    # the stages now do. Resolved once here, from the settings as they stand —
    # which is what it did before, and is right except in the window between
    # an operator changing the mode and the app next starting. A stale label
    # on an otherwise correct run is a far smaller thing than the run itself
    # going to the wrong provider, which is what this is fixing.
    at_startup = harness()
    return (
        _dispatching_debrief(harness, name=at_startup[0].name),
        _dispatching_compiler(harness, name=at_startup[1].name),
    )


#: The §3.10 chain's stages. `run_analyst` is included: it is optional on the
#: dataclass, and the fallback path `compiler.py` runs for batch-refusing
#: credentials reaches for it, so a dispatcher that dropped it would send that
#: path to `None` on exactly the credential that needs it.
_COMPILER_STAGES = ("extract", "structure", "submit_batch", "fetch_batch", "run_analyst")


def _dispatching(
    harness: Callable[[], tuple[DebriefEngines, CompilerEngines]], half: int, stage: str
) -> Callable[..., Any]:
    """One stage, sent to whichever harness the settings name at the time."""

    async def call(*args: Any, **kwargs: Any) -> Any:
        return await getattr(harness()[half], stage)(*args, **kwargs)

    return call


def _dispatching_debrief(
    harness: Callable[[], tuple[DebriefEngines, CompilerEngines]], *, name: str
) -> DebriefEngines:
    """A real `DebriefEngines` whose stages resolve the harness per call.

    A dataclass rather than a duck-typed stand-in on purpose:
    `dataclasses.replace` is used on these — the debrief substitutes a
    transcript-derived diarizer when the audio is gone — and that requires
    one.
    """

    return DebriefEngines(
        name=name,
        **{
            stage: _dispatching(harness, 0, stage)
            for stage in ("diarize", "clean", "translate", "classify", "run_chain", "converse")
        },
    )


def _dispatching_compiler(
    harness: Callable[[], tuple[DebriefEngines, CompilerEngines]], *, name: str
) -> CompilerEngines:
    """The same, for the §3.10 compiler chain."""

    return CompilerEngines(
        name=name,
        **{
            stage: _dispatching(harness, 1, stage)
            for stage in _COMPILER_STAGES
        },
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
    secret: str,
    *,
    base_url: str | None = None,
    mode: Any = None,
    model: str | None = None,
    run: Any = None,
) -> None:
    """Verify an Anthropic credential, raising if it does not work.

    Sends the smallest possible message on the configured model — one token,
    no cache, no tools — because that is the request the product makes and the
    only one whose success means anything.

    This used to call `models.list`, on the reasoning that listing exercises
    the same authentication path while costing no tokens. It does not. An
    OAuth token authenticates, lists models, and includes the configured model
    in what it lists, and is then refused for `/v1/messages`. So the Settings
    screen said "Verified (…TAAA)" while every bank compile stopped at the
    first model call, and the credential was the last thing anybody suspected.
    A probe whose pass does not imply the product works is worse than no probe,
    because it is read as evidence.

    Raises the SDK's own typed error, which the settings surface renders by
    type and message — never echoing the credential back.
    """

    from app.modules.settings.models import AuthMode

    chosen = model or DEFAULT_MODEL

    # The probe follows the harness, because the harness follows the
    # credential. `engines_from_settings` runs the compiler on the Agent SDK
    # for an OAuth token, so probing that credential against `/v1/messages`
    # reports the 429 it is refused with there — for a token that drafts a
    # bank perfectly well through the agent loop. That is the `models.list`
    # mistake inverted: it passed a credential that could not work, this would
    # fail one that does.
    if (mode or AuthMode.API_KEY) is AuthMode.OAUTH_TOKEN:
        from .agent_sdk_engines import probe_agent_sdk_credential

        await probe_agent_sdk_credential(secret, model=chosen, run=run)
        return

    client = build_anthropic_client(mode or AuthMode.API_KEY, secret, base_url=base_url)
    await client.messages.create(
        model=chosen,
        max_tokens=1,
        messages=[{"role": "user", "content": "."}],
    )
