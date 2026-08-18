"""Classifies a reference-document URL as SharePoint or Microsoft Teams (PRD FR-3.2).

FR-3.2 asks specifically for "reference documents ... by SharePoint or Teams
link" — not an arbitrary URL — so this is the one place that decides which
hosts count, shared by `DocumentLinkAttachmentRequest`'s validator and
anything else that later needs to know which platform a link came from.
"""

from __future__ import annotations

from urllib.parse import urlparse


def classify_reference_link_host(url: str) -> str | None:
    """Returns "sharepoint", "teams", or None for an unrecognized host.

    Matches on hostname suffix rather than a full URL regex: SharePoint
    tenants each get their own subdomain (`{tenant}.sharepoint.com`), so a
    suffix match is what "any SharePoint link" actually requires. Teams
    file links resolve through `teams.microsoft.com`. A link with no
    scheme (so `urlparse` can't isolate a hostname) is treated the same as
    an unrecognized host.
    """

    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    if host is None:
        return None
    host = host.lower()
    if host == "sharepoint.com" or host.endswith(".sharepoint.com"):
        return "sharepoint"
    if host == "teams.microsoft.com" or host.endswith(".teams.microsoft.com"):
        return "teams"
    return None
