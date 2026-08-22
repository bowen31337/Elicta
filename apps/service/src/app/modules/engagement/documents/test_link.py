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


@pytest.mark.parametrize(
    "url",
    [
        "https://onedrive.live.com/?cid=ABC&id=DEF",
        "https://1drv.ms/w/s!AkX3",
        "https://acme-my.sharepoint.com/personal/rw_acme_com/Documents/scoping.docx",
        "https://ONEDRIVE.LIVE.COM/download?resid=1",
    ],
)
def test_onedrive_links_classify_as_onedrive(url: str):
    """OneDrive is where a consultant's own working copies live, and FR-3.2's
    intake is useless if it takes the team site but not the drive beside it.

    `{tenant}-my.sharepoint.com` is OneDrive for Business: it is served from a
    SharePoint host, so matching on the suffix alone called it "sharepoint" and
    it was only ever the *personal* drive.
    """
    assert classify_reference_link_host(url) == "onedrive"


def test_a_team_site_is_still_sharepoint_not_onedrive():
    assert (
        classify_reference_link_host("https://acme.sharepoint.com/sites/proj/x.docx")
        == "sharepoint"
    )


def test_a_url_whose_host_cannot_be_isolated_is_not_a_recognised_source():
    # An unbracketed IPv6 literal makes urlparse raise rather than return a
    # hostname. Anything the classifier cannot read the host of is refused,
    # not guessed at.
    assert classify_reference_link_host("https://[::1/sites/proj/scoping.docx") is None
