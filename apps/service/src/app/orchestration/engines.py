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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.core.agent_permissions import (
    AgentFilesystemScope,
    FilesystemOperation,
    PermissionDecision,
    evaluate_filesystem_permission,
)


class EngineNotConfiguredError(RuntimeError):
    """Raised when a pipeline stage needs a model and none is configured.

    Names the stage and the setting that would enable it, so the persisted
    `FAILED` record explains itself without a log dive.
    """

    def __init__(self, stage: str) -> None:
        super().__init__(
            f"{stage} needs an inference engine, and none is configured. "
            "Set ANTHROPIC_API_KEY (or CLAUDE_CODE_USE_BEDROCK / "
            "CLAUDE_CODE_USE_VERTEX) and supply a DebriefEngines / "
            "CompilerEngines implementation backed by the Claude Agent SDK "
            "(architecture ADR-012, §3.11)."
        )
        self.stage = stage


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

    @classmethod
    def unconfigured(cls) -> DebriefEngines:
        return cls(
            name=UNCONFIGURED,
            diarize=_unconfigured("diarization (architecture §7 step 2)"),
            clean=_unconfigured("transcript cleanup (§7 step 4)"),
            translate=_unconfigured("transcript translation (§7 step 4)"),
            classify=_unconfigured("section classification (§7 step 5)"),
            run_chain=_unconfigured("BMAD analyst chain (§7 step 6)"),
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

    @classmethod
    def unconfigured(cls) -> CompilerEngines:
        return cls(
            name=UNCONFIGURED,
            extract=_unconfigured("document claim extraction (§3.10)"),
            structure=_unconfigured("claim structuring (§3.10)"),
            submit_batch=_unconfigured("BMAD analyst batch submission (§3.10)"),
            fetch_batch=_unconfigured("BMAD analyst batch collection (§3.10)"),
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
