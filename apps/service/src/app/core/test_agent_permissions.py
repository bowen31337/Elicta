"""Tests for the compiler agent's filesystem permission scoping (architecture §3.11)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.agent_permissions import (
    AgentFilesystemScope,
    FilesystemOperation,
    PermissionDecision,
    evaluate_filesystem_permission,
)


def make_scope(**overrides) -> AgentFilesystemScope:
    defaults = {
        "engagement_id": "engagement-1",
        "read_roots": ["/data/engagements/engagement-1/documents"],
        "write_roots": ["/data/engagements/engagement-1/bank"],
    }
    defaults.update(overrides)
    return AgentFilesystemScope(**defaults)


def test_a_read_within_the_document_root_is_allowed():
    result = evaluate_filesystem_permission(
        make_scope(),
        FilesystemOperation.READ,
        "/data/engagements/engagement-1/documents/statement-of-work.pdf",
    )

    assert result.decision == PermissionDecision.ALLOW
    assert result.allowed is True


def test_a_read_outside_the_document_root_is_denied():
    result = evaluate_filesystem_permission(
        make_scope(),
        FilesystemOperation.READ,
        "/data/engagements/engagement-2/documents/statement-of-work.pdf",
    )

    assert result.decision == PermissionDecision.DENY
    assert result.allowed is False
    assert "engagement-1" in result.reason
    assert "engagement-2/documents/statement-of-work.pdf" in result.reason


def test_a_read_of_the_bank_directory_is_denied():
    result = evaluate_filesystem_permission(
        make_scope(),
        FilesystemOperation.READ,
        "/data/engagements/engagement-1/bank/candidates.json",
    )

    assert result.decision == PermissionDecision.DENY


def test_a_write_within_the_bank_root_is_allowed():
    result = evaluate_filesystem_permission(
        make_scope(),
        FilesystemOperation.WRITE,
        "/data/engagements/engagement-1/bank/candidates.json",
    )

    assert result.decision == PermissionDecision.ALLOW


def test_a_write_to_the_document_root_is_denied():
    result = evaluate_filesystem_permission(
        make_scope(),
        FilesystemOperation.WRITE,
        "/data/engagements/engagement-1/documents/statement-of-work.pdf",
    )

    assert result.decision == PermissionDecision.DENY


def test_a_write_outside_the_bank_root_is_denied():
    result = evaluate_filesystem_permission(
        make_scope(),
        FilesystemOperation.WRITE,
        "/data/engagements/engagement-1/artifacts/summary.json",
    )

    assert result.decision == PermissionDecision.DENY


def test_a_path_traversal_out_of_the_document_root_is_denied():
    result = evaluate_filesystem_permission(
        make_scope(),
        FilesystemOperation.READ,
        "/data/engagements/engagement-1/documents/../../engagement-2/documents/secret.pdf",
    )

    assert result.decision == PermissionDecision.DENY


def test_a_lookalike_sibling_directory_is_not_treated_as_within_scope():
    result = evaluate_filesystem_permission(
        make_scope(),
        FilesystemOperation.READ,
        "/data/engagements/engagement-1/documents-archive/statement-of-work.pdf",
    )

    assert result.decision == PermissionDecision.DENY


def test_the_read_root_itself_is_allowed():
    result = evaluate_filesystem_permission(
        make_scope(),
        FilesystemOperation.READ,
        "/data/engagements/engagement-1/documents",
    )

    assert result.decision == PermissionDecision.ALLOW


def test_a_scope_with_overlapping_read_and_write_roots_fails_construction():
    with pytest.raises(ValidationError):
        make_scope(
            read_roots=["/data/engagements/engagement-1/shared"],
            write_roots=["/data/engagements/engagement-1/shared/bank"],
        )


def test_a_scope_with_a_read_root_nested_inside_a_write_root_fails_construction():
    with pytest.raises(ValidationError):
        make_scope(
            read_roots=["/data/engagements/engagement-1/bank/inputs"],
            write_roots=["/data/engagements/engagement-1/bank"],
        )
