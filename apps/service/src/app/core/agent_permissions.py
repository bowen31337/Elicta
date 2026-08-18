"""Scopes the compiler agent's filesystem tools to its own engagement's data (architecture §3.11, "Permissions").

Architecture §3.11 hands the context compiler real filesystem tools -- it
reads the engagement's document set, then writes the compiled candidate bank
-- and names the risk in the same breath: "an agent that can read arbitrary
paths on a service tier holding multiple clients' requirements data is an
incident waiting to be written up." This module is the guard that makes the
required scoping ("read access to the engagement document set, write access
only to the bank ... directories") a structural check rather than a
prompt-level convention, mirroring how `EgressChokepoint`
(`core/egress/chokepoint.py`) makes "every outbound call is audited" a
guarantee instead of a call-site habit.

This module stays decoupled from the Claude Agent SDK itself, the same way
`compiler/agent/bmad_analyst.py` takes its chain as an injected callable
rather than importing the SDK directly: whoever wires the app factory calls
`evaluate_filesystem_permission` from the SDK's tool-permission callback for
every filesystem tool invocation and translates its `FilesystemPermissionResult`
into that callback's own allow/deny shape.

The tenancy model this scoping depends on is unresolved (architecture T8), so
`AgentFilesystemScope` takes its roots as plain paths supplied by the caller
rather than deriving them from an engagement-id convention -- it isn't
coupled to whichever tenancy model T8 eventually settles on.
"""

from __future__ import annotations

import posixpath
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class FilesystemOperation(str, Enum):
    """Which side of the compiler agent's filesystem access a tool call is on (architecture §3.11)."""

    READ = "read"
    WRITE = "write"


class PermissionDecision(str, Enum):
    """The outcome `evaluate_filesystem_permission` reaches for one filesystem tool call."""

    ALLOW = "allow"
    DENY = "deny"


def _normalize(path: str) -> str:
    """Collapse `.` and `..` segments before any containment check.

    Checking containment against the raw path would let a request like
    `<read_root>/../other-engagement/doc.txt` pass a naive prefix check --
    `posixpath.normpath` resolves the traversal first, so containment is
    checked against where the path actually points rather than how it is
    spelled.
    """

    return posixpath.normpath(path)


def _is_within(path: str, roots: list[str]) -> bool:
    normalized_path = _normalize(path)
    for root in roots:
        normalized_root = _normalize(root).rstrip("/") or "/"
        if normalized_path == normalized_root or normalized_path.startswith(
            normalized_root + "/"
        ):
            return True
    return False


class AgentFilesystemScope(BaseModel):
    """The paths one compiler agent run may read from and write to (architecture §3.11).

    `read_roots` is the engagement's own document set and nothing else --
    never a shared directory or another engagement's, since the same service
    tier holds every client's requirements data. `write_roots` is the bank
    directory alone. Construction fails if any root in one list falls inside
    a root in the other: an agent whose write access reached the document
    set it read from could tamper with its own source material, which is
    exactly the incident §3.11 scopes read and write apart to prevent.
    """

    engagement_id: str = Field(min_length=1)
    read_roots: list[str] = Field(min_length=1)
    write_roots: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _read_and_write_roots_must_not_overlap(self) -> AgentFilesystemScope:
        for write_root in self.write_roots:
            if _is_within(write_root, self.read_roots):
                raise ValueError(
                    f"write root {write_root!r} overlaps a read root -- "
                    "read and write access must stay disjoint (architecture §3.11)"
                )
        for read_root in self.read_roots:
            if _is_within(read_root, self.write_roots):
                raise ValueError(
                    f"read root {read_root!r} overlaps a write root -- "
                    "read and write access must stay disjoint (architecture §3.11)"
                )
        return self


class FilesystemPermissionResult(BaseModel):
    """The verdict `evaluate_filesystem_permission` returns for one filesystem tool call."""

    decision: PermissionDecision
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision is PermissionDecision.ALLOW


def evaluate_filesystem_permission(
    scope: AgentFilesystemScope,
    operation: FilesystemOperation,
    path: str,
) -> FilesystemPermissionResult:
    """Decide whether `scope`'s agent may perform `operation` on `path` (architecture §3.11).

    A `READ` is allowed only under one of `scope.read_roots`; a `WRITE` only
    under one of `scope.write_roots`. Everything else -- a read reaching
    outside the engagement's document set, a write landing anywhere but the
    bank directory, a `..` segment engineered to escape a scoped root -- is
    denied. There is no default-allow path: a path matching neither an
    explicit root is out of scope and denies the same way an explicitly
    forbidden path would.
    """

    roots = (
        scope.read_roots if operation is FilesystemOperation.READ else scope.write_roots
    )

    if _is_within(path, roots):
        return FilesystemPermissionResult(
            decision=PermissionDecision.ALLOW,
            reason=f"{path!r} is within engagement {scope.engagement_id!r}'s {operation.value} scope",
        )

    return FilesystemPermissionResult(
        decision=PermissionDecision.DENY,
        reason=(
            f"engagement {scope.engagement_id!r} agent may not {operation.value} {path!r}: "
            f"outside its scoped {operation.value} roots"
        ),
    )
