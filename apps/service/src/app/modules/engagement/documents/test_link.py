"""Tests for classifying a reference-document link's host (PRD FR-3.2)."""

from __future__ import annotations

import pytest

from .link import classify_reference_link_host


@pytest.mark.parametrize(
    "url",
    [
        "https://acme.sharepoint.com/sites/proj/scoping.docx",
        "https://sharepoint.com/sites/proj/scoping.docx",
        "https://ACME.SHAREPOINT.COM/sites/proj/scoping.docx",
    ],
)
def test_sharepoint_links_classify_as_sharepoint(url: str):
    assert classify_reference_link_host(url) == "sharepoint"


@pytest.mark.parametrize(
    "url",
    [
        "https://teams.microsoft.com/l/file/abc123",
        "https://TEAMS.MICROSOFT.COM/l/file/abc123",
    ],
)
def test_teams_links_classify_as_teams(url: str):
    assert classify_reference_link_host(url) == "teams"


@pytest.mark.parametrize(
    "url",
    [
        "https://dropbox.com/s/abc/scoping.docx",
        "https://sharepoint.com.evil.example/scoping.docx",
        "not-a-url",
        "sharepoint.com/no-scheme",
        "",
    ],
)
def test_unrecognized_links_return_none(url: str):
    assert classify_reference_link_host(url) is None
