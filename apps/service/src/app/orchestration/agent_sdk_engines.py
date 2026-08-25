"""The context compiler on the Claude Agent SDK (ADR-012).

ADR-012 fixes the Agent SDK as the compiler's harness and the plain Messages
API as the slow lane's. The compiler shipped on the Messages API for both,
which the code-quality audit records as still open: "no Agent SDK adapter
exists". This is that adapter, and the reason it stopped being a tidiness
matter is a credential.

Settings accept either credential an organisation might issue: an API key, or
an OAuth token from `claude setup-token`. The second authenticates, resolves
an organisation, and lists models — and is then refused for `/v1/messages`
with a 429 that carries no rate-limit headers and a body message of literally
"Error". It is an entitlement decision wearing a rate limit's clothes: that
token is entitled to Claude Code's surface, which is what the Agent SDK runs,
and not to arbitrary Messages API traffic. So the harness ADR-012 asked for is
also the only harness that credential can drive.

Two things this deliberately does not do. It does not touch the slow lane —
ADR-012 excludes it, because an agent loop abstracts away the cache-boundary
control that path's latency budget depends on, and that reasoning is unchanged
by any of the above. And it does not implement the Batch API, which does not
exist on this surface; `submit_batch` refuses as `NOT_ENTITLED` so the
fallback `compiler.py` already runs for batch-refusing credentials carries the
Analyst pass to `run_analyst`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from app.modules.compiler.agent.models import (
    AnalystBatchResult,
    BmadAnalystPassOutput,
)
from app.modules.compiler.citations.models import (
    CitedSpan,
    ClaimStructuringDraft,
    ClaimStructuringOutput,
    DocumentExtractionOutput,
    ExtractedClaimDraft,
)
from app.orchestration.anthropic_engines import (
    _COMPILER_ANALYST_SYSTEM,
    _EXTRACTION_SYSTEM,
    _STRUCTURING_SYSTEM,
    DEFAULT_MODEL,
    _ExtractionOut,
    _StructuringOut,
    _upstream_aware,
    analyst_prompt,
)
from app.orchestration.engines import (
    STAGE_EXTRACT,
    STAGE_FETCH_BATCH,
    STAGE_RUN_ANALYST,
    STAGE_STRUCTURE,
    STAGE_SUBMIT_BATCH,
    CompilerEngines,
    UpstreamFailure,
    UpstreamUnavailableError,
)

#: What this engine set calls itself in an audited seam record.
AGENT_SDK = "claude-agent-sdk"

#: A fenced block, whatever the fence is labelled.
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class AgentSdkUnavailableError(RuntimeError):
    """The agent loop ran and did not produce something this stage can read."""


def json_payload(text: str) -> dict[str, Any]:
    """The object an assistant turn was asked for, read back out of its prose.

    `messages.parse` enforces a schema server-side and hands back a model. The
    agent loop has no equivalent, so the answer arrives as an assistant turn
    and the schema becomes this function's job.

    Raises rather than returning `{}` when there is no object to find. An
    empty result here is indistinguishable downstream from a document set that
    genuinely contained no claims, and would persist as a successful compile
    with an empty bank — which is the failure this whole module exists at the
    end of.
    """

    fenced = _FENCE_RE.search(text)
    if fenced:
        candidate = fenced.group(1).strip()
    else:
        # The first balanced-looking object in the turn. `find`/`rfind` rather
        # than a regex: JSON nests, and a regex that matches nested braces is
        # a worse thing to maintain than this.
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise AgentSdkUnavailableError(
                f"the model answered with no JSON object in it: {text[:200]!r}"
            )
        candidate = text[start : end + 1]

    try:
        loaded = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AgentSdkUnavailableError(
            f"the model's answer was not valid JSON ({exc}): {candidate[:200]!r}"
        ) from exc

    if not isinstance(loaded, dict):
        raise AgentSdkUnavailableError(
            f"expected a JSON object, got {type(loaded).__name__}"
        )
    return loaded


def _default_run(
    *, oauth_token: str | None, model: str
) -> Callable[[str, str], Awaitable[str]]:
    """One turn of the agent loop, as a plain prompt-in/text-out call.

    Injected rather than imported at the call sites so every stage below is
    testable without spawning a CLI — the same reason the pipeline stages take
    their model call as a callable in the first place.
    """

    async def run(system: str, prompt: str) -> str:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            TextBlock,
            query,
        )

        env: dict[str, str] = {}
        if oauth_token:
            # The variable the SDK itself reads. `ANTHROPIC_OAUTH_TOKEN` is
            # this service's own settings name and means nothing to the SDK,
            # which is a difference worth stating once here rather than
            # rediscovering from a silent fall-through to the Keychain.
            env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token

        options = ClaudeAgentOptions(
            system_prompt=system,
            model=model,
            env=env,
            # No tools: every stage here is a single question about text that
            # is already in the prompt. A loop that could read the filesystem
            # would be a wider grant than the work needs.
            allowed_tools=[],
            # Deliberately uncapped. `max_turns=1` looks like the obvious
            # bound for a single question and is not: Claude Code counts its
            # own turns, so a large document set fails with "Reached maximum
            # number of turns (1)" — an opaque refusal that reads like a
            # provider problem and is a setting. With no tools granted there
            # is no loop to bound: the model answers and stops.
            # The operator's own Claude Code settings, skills and MCP servers
            # are not this service's to load: they would change the answer a
            # compile gives depending on whose laptop it ran on.
            setting_sources=None,
        )

        chunks: list[str] = []
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        chunks.append(block.text)
        answer = "".join(chunks).strip()
        if not answer:
            raise AgentSdkUnavailableError(
                "the agent loop ended without an assistant turn"
            )
        return answer

    return run


def agent_sdk_compiler_engines(
    *,
    oauth_token: str | None = None,
    model: str = DEFAULT_MODEL,
    run: Callable[[str, str], Awaitable[str]] | None = None,
) -> CompilerEngines:
    """The §3.10 compiler chain, run through the Claude Agent SDK."""

    call = run or _default_run(oauth_token=oauth_token, model=model)

    @_upstream_aware(STAGE_EXTRACT)
    async def extract(engagement_id: str, documents: list[Any]) -> DocumentExtractionOutput:
        corpus = "\n\n".join(
            f'<document id="{d.document_id}">\n{d.text}\n</document>' for d in documents
        )
        answer = await call(
            _schema_instructed(_EXTRACTION_SYSTEM, _ExtractionOut),
            f"Documents:\n\n{corpus}",
        )
        parsed = _ExtractionOut.model_validate(json_payload(answer))
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
        answer = await call(
            _schema_instructed(_STRUCTURING_SYSTEM, _StructuringOut),
            f"Claims:\n\n{claim_list}",
        )
        parsed = _StructuringOut.model_validate(json_payload(answer))
        return ClaimStructuringOutput(
            candidates=[
                ClaimStructuringDraft(**candidate.model_dump())
                for candidate in parsed.candidates
            ]
        )

    @_upstream_aware(STAGE_RUN_ANALYST)
    async def run_analyst(
        engagement_id: str, context_pack: Any
    ) -> list[AnalystBatchResult]:
        answer = await call(
            _schema_instructed(_COMPILER_ANALYST_SYSTEM, BmadAnalystPassOutput),
            analyst_prompt(context_pack),
        )
        parsed = BmadAnalystPassOutput.model_validate(json_payload(answer))
        return [AnalystBatchResult(custom_id=engagement_id, output=parsed)]

    @_upstream_aware(STAGE_SUBMIT_BATCH)
    async def submit_batch(engagement_id: str, context_pack: Any) -> str:
        raise UpstreamUnavailableError(
            STAGE_SUBMIT_BATCH,
            UpstreamFailure.NOT_ENTITLED,
            "the Claude Agent SDK has no Batch API, so the Analyst pass runs "
            "as an ordinary request instead. This is expected on this "
            "credential, not a fault to act on.",
        )

    @_upstream_aware(STAGE_FETCH_BATCH)
    async def fetch_batch(job_id: str) -> list[AnalystBatchResult]:
        raise UpstreamUnavailableError(
            STAGE_FETCH_BATCH,
            UpstreamFailure.NOT_ENTITLED,
            "the Claude Agent SDK has no Batch API, so there is no batch to "
            "collect; the Analyst pass ran as an ordinary request.",
        )

    return CompilerEngines(
        name=AGENT_SDK,
        extract=extract,
        structure=structure,
        submit_batch=submit_batch,
        fetch_batch=fetch_batch,
        run_analyst=run_analyst,
    )


def _schema_instructed(system: str, model_cls: Any) -> str:
    """The stage's own system prompt, plus the shape its answer has to take.

    The Messages API path pins the shape with `output_format`, which the agent
    loop has no equivalent of. Stating the schema in the prompt is the nearest
    honest substitute — the same instruction, enforced by `json_payload` and
    the model class on the way back in rather than by the server on the way
    out.
    """

    schema = json.dumps(model_cls.model_json_schema(), indent=2)
    return (
        f"{system}\n\n"
        "Answer with a single JSON object and nothing else — no preamble, no "
        "explanation, no prose after it. It must validate against this JSON "
        f"Schema:\n\n{schema}"
    )
