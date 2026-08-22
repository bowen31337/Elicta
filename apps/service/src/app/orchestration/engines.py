"""The inference seams the post-meeting and compile-time pipelines run on.

Every pipeline stage in this codebase takes its model call as an injected
callable — `clean`, `translate`, `classify`, `run_chain` — so no stage
imports an SDK and each is testable without one. Something still has to
supply those callables. This module defines what "something" looks like.

ADR-012 fixes which harness backs them: the **Agent SDK** for the context
compiler and the debrief engine (multi-step tool use, resumable sessions,
structured artifact output), and the plain **Messages API** for the slow
lane, which is deliberately excluded because an agent loop would abstract
away the cache-boundary control that path's latency budget depends on.

`UnconfiguredEngines` is the default. It is not a stub that fabricates
plausible output — that would make an unconfigured deployment look like a
working one. Every call raises `EngineNotConfiguredError`, and because each
pipeline stage converts an engine exception into a persisted `FAILED` record,
an unconfigured service produces an honest, inspectable failure at exactly
the stage that needed a model, rather than silent success or a crash.
"""

from __future__ import annotations

import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.core.agent_permissions import (
    AgentFilesystemScope,
    FilesystemOperation,
    PermissionDecision,
    evaluate_filesystem_permission,
)

#: The phrase every "nothing is set up here" refusal carries.
#:
#: A stage record persists its failure as text, so by the time anything asks
#: *why* a run stopped, the exception type is gone and a sentence is all that
#: is left. This is the one word-for-word thing a reader may rely on — and it
#: lives here, beside the message that contains it, so rewording the message
#: without moving the marker is a test failure rather than a silent
#: reclassification.
UNCONFIGURED_MARKER = "and none is configured"


class EngineNotConfiguredError(RuntimeError):
    """Raised when a pipeline stage needs something that is not set up.

    Names the stage and the setting that would enable it, so the persisted
    `FAILED` record explains itself without a log dive. `detail` replaces the
    model-shaped advice for a stage whose missing piece is not a model — the
    diarizer wants a speech vendor, and telling its operator to set an
    Anthropic key would send them somewhere useless.
    """

    def __init__(self, stage: str, detail: str | None = None) -> None:
        super().__init__(
            f"{stage} needs {detail or 'an inference engine'}, "
            f"{UNCONFIGURED_MARKER}. "
            + (
                ""
                if detail
                else "Set ANTHROPIC_API_KEY (or CLAUDE_CODE_USE_BEDROCK / "
                "CLAUDE_CODE_USE_VERTEX) and supply a DebriefEngines / "
                "CompilerEngines implementation backed by the Claude Agent SDK "
                "(architecture ADR-012, §3.11)."
            )
        )
        self.stage = stage


class UpstreamFailure(str, Enum):
    """Why the provider did not answer — the part that decides what to do next.

    The distinction is not academic. An operator who reads "rate limited"
    waits a minute; one who reads "internal server error" starts looking for a
    broken deployment. Collapsing the two, which is what an untranslated
    vendor exception does, costs exactly the information that chooses between
    them.
    """

    RATE_LIMITED = "rate_limited"
    """The provider is throttling this deployment. Wait; nothing is wrong."""

    UNAVAILABLE = "unavailable"
    """The provider timed out, could not be reached, or failed its own way."""

    CREDENTIAL_REJECTED = "credential_rejected"
    """The provider was reached and refused the configured credential."""

    NOT_ENTITLED = "not_entitled"
    """Reached, the credential is valid, and this request is not permitted.

    A missing OAuth scope or a model the plan does not include. Distinct from
    `RATE_LIMITED` because waiting achieves nothing, and from
    `CREDENTIAL_REJECTED` because re-entering the credential achieves nothing
    either — the two remedies those imply are both wrong here, and following
    either one wastes an operator's afternoon."""


def upstream_failure_in(text: str) -> UpstreamFailure | None:
    """The failure kind a recorded stage error was raised with, if it was one.

    The counterpart to the bracketed marker `UpstreamUnavailableError` writes.
    Returns `None` for anything else — a bug in this codebase is not a provider
    problem and must never be reported as one.
    """

    found = re.search(r"\[([a-z_]+)\]:", text)
    if found is None:
        return None
    try:
        return UpstreamFailure(found.group(1))
    except ValueError:
        return None

class UpstreamUnavailableError(RuntimeError):
    """A stage reached its provider and did not get an answer.

    The sibling of `EngineNotConfiguredError`, and deliberately a separate
    type: that one means *nothing is configured*, this one means something is
    and the provider said no. Both are honest failures the operator can act
    on, and neither is a bug in this codebase — which is why neither may
    surface as a bare 500.

    `failure` is a vendor-neutral reason rather than an HTTP status, because
    this module sits under the API and must not decide what the API answers.
    `composition.py` makes that call.
    """

    def __init__(
        self,
        stage: str,
        failure: UpstreamFailure,
        detail: str,
        *,
        retry_after: float | None = None,
    ) -> None:
        # The kind travels in the text, in brackets, because the text is all
        # that survives. A stage persists its failure as `str(exc)`, so by the
        # time a screen asks why a run stopped the exception is gone — and
        # without this every provider problem reads the same, which sends an
        # operator to the wrong remedy. `upstream_failure_in` reads it back.
        super().__init__(f"{stage} [{failure.value}]: {detail}")
        self.stage = stage
        self.failure = failure
        self.detail = detail
        # Only ever what the provider itself said to wait. Guessing a number
        # here would be worse than saying nothing: a client that trusts it
        # would retry into the same limit.
        self.retry_after = retry_after


# The stage names both halves use. Shared constants rather than two sets of
# string literals, so the name in an unconfigured refusal and the name in a
# rate-limit refusal cannot drift apart.
STAGE_DIARIZE = "diarization (architecture §7 step 2)"
STAGE_CLEAN = "transcript cleanup (§7 step 4)"
STAGE_TRANSLATE = "transcript translation (§7 step 4)"
STAGE_CLASSIFY = "section classification (§7 step 5)"
STAGE_RUN_CHAIN = "BMAD analyst chain (§7 step 6)"
STAGE_CONVERSE = "the debrief conversation (FR-7.3)"
STAGE_EXTRACT = "document claim extraction (§3.10)"
STAGE_STRUCTURE = "claim structuring (§3.10)"
STAGE_SUBMIT_BATCH = "BMAD analyst batch submission (§3.10)"
STAGE_FETCH_BATCH = "BMAD analyst batch collection (§3.10)"
STAGE_RUN_ANALYST = "BMAD analyst pass, direct (§3.10)"


def inference_is_configured() -> bool:
    """Whether credentials for the Agent SDK are present in the environment.

    Mirrors the three authentication routes §3.11 names — a direct API key,
    Bedrock, or Vertex — rather than assuming the key path.
    """

    return any(
        os.environ.get(name)
        for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
    )


UNCONFIGURED = "unconfigured"


def _unconfigured(stage: str) -> Callable[..., Awaitable[Any]]:
    async def call(*_args: Any, **_kwargs: Any) -> Any:
        raise EngineNotConfiguredError(stage)

    return call


@dataclass(frozen=True)
class DebriefEngines:
    """The five inference seams of the post-meeting pipeline (architecture §7).

    `name` labels every record the pipeline persists, so a transcript can be
    traced back to the engine that produced it.
    """

    name: str
    diarize: Callable[..., Awaitable[Any]]
    clean: Callable[..., Awaitable[Any]]
    translate: Callable[..., Awaitable[Any]]
    classify: Callable[..., Awaitable[Any]]
    run_chain: Callable[..., Awaitable[Any]]
    # FR-7.3's free-form half. The other five stages run once over a finished
    # transcript; this one answers an operator mid-conversation, so it takes
    # the turns so far and returns the assistant's content blocks verbatim —
    # the shape `debrief/session/service.py` persists without interpreting.
    converse: Callable[..., Awaitable[Any]]

    @classmethod
    def unconfigured(cls) -> DebriefEngines:
        return cls(
            name=UNCONFIGURED,
            diarize=_unconfigured(STAGE_DIARIZE),
            clean=_unconfigured(STAGE_CLEAN),
            translate=_unconfigured(STAGE_TRANSLATE),
            classify=_unconfigured(STAGE_CLASSIFY),
            run_chain=_unconfigured(STAGE_RUN_CHAIN),
            converse=_unconfigured(STAGE_CONVERSE),
        )

    @property
    def is_configured(self) -> bool:
        """Whether these engines can actually reach a model.

        An explicit property rather than a `name == "unconfigured"` check at
        each call site: the name is a label for records, and a caller that
        matched on it would silently start answering "configured" the day
        someone renamed it.
        """

        return self.name != UNCONFIGURED


@dataclass(frozen=True)
class CompilerEngines:
    """The inference seams of the context compiler (architecture §3.10)."""

    name: str
    extract: Callable[..., Awaitable[Any]]
    structure: Callable[..., Awaitable[Any]]
    submit_batch: Callable[..., Awaitable[Any]]
    fetch_batch: Callable[..., Awaitable[Any]]
    #: The Analyst pass as an ordinary request rather than a batch job, for a
    #: credential the Batch API will not accept. Optional because the batch is
    #: the right default — it is cheaper and nobody is waiting on it — and this
    #: costs more; it exists so that "cannot submit a batch" stops meaning
    #: "cannot draft a bank at all". Returns the same `AnalystBatchResult`
    #: shape a collected batch does, so everything downstream is shared.
    run_analyst: Callable[..., Awaitable[Any]] | None = None

    @classmethod
    def unconfigured(cls) -> CompilerEngines:
        return cls(
            name=UNCONFIGURED,
            extract=_unconfigured(STAGE_EXTRACT),
            structure=_unconfigured(STAGE_STRUCTURE),
            submit_batch=_unconfigured(STAGE_SUBMIT_BATCH),
            fetch_batch=_unconfigured(STAGE_FETCH_BATCH),
        )

    @property
    def is_configured(self) -> bool:
        """Whether these engines can actually reach a model. See `DebriefEngines`."""

        return self.name != UNCONFIGURED


def engagement_filesystem_scope(engagement_id: str) -> AgentFilesystemScope:
    """The filesystem scope §3.11 requires for one engagement's agents.

    "Read access to the engagement document set, write access only to the
    bank and artifact directories." Scoping per engagement is what keeps one
    client's requirements data out of another's agent context on a shared
    service tier — the tenancy model that ultimately governs this is still
    open (T8), so the scope is derived per engagement rather than per tenant.
    """

    return AgentFilesystemScope(
        engagement_id=engagement_id,
        read_roots=[f"engagements/{engagement_id}/documents"],
        write_roots=[
            f"engagements/{engagement_id}/bank",
            f"engagements/{engagement_id}/artifacts",
        ],
    )


class AgentPathDenied(PermissionError):
    """A filesystem path the agent scope does not allow."""


def enforce_filesystem_permission(
    scope: AgentFilesystemScope, operation: FilesystemOperation, path: str
) -> None:
    """Gate one agent filesystem access, raising if the scope denies it.

    §3.11 asks for this to be a structural check rather than a prompt-level
    convention, so callers get an exception rather than a boolean they might
    forget to read. Wire this into the SDK's tool-permission callback and
    translate `AgentPathDenied` into that callback's deny shape.
    """

    result = evaluate_filesystem_permission(scope, operation, path)
    if result.decision is not PermissionDecision.ALLOW:
        raise AgentPathDenied(result.reason)
