"""Classifies a reference-document URL as SharePoint or Microsoft Teams (PRD FR-3.2).

FR-3.2 asks specifically for "reference documents ... by SharePoint or Teams
link" — not an arbitrary URL — so this is the one place that decides which
hosts count, shared by `DocumentLinkAttachmentRequest`'s validator and
anything else that later needs to know which platform a link came from.
"""

from __future__ import annotations

from urllib.parse import urlparse


def classify_reference_link_host(url: str) -> str | None:
    """Returns "sharepoint", "onedrive", "teams", or None for an unrecognized host.

    Matches on hostname suffix rather than a full URL regex: SharePoint
    tenants each get their own subdomain (`{tenant}.sharepoint.com`), so a
    suffix match is what "any SharePoint link" actually requires. Teams
    file links resolve through `teams.microsoft.com`. A link with no
    scheme (so `urlparse` can't isolate a hostname) is treated the same as
    an unrecognized host.

    OneDrive is separated from SharePoint rather than folded into it, even
    though OneDrive for Business is served from a SharePoint host. The tell is
    the `-my` suffix on the tenant subdomain: `{tenant}-my.sharepoint.com` is
    somebody's personal drive, `{tenant}.sharepoint.com` is a team site. They
    are the same API and very different places — the working copy on one
    consultant's drive versus the document the whole engagement shares — and a
    connector that cannot say which it read cannot explain itself later.
    """

    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    if host is None:
        return None
    host = host.lower()
    if host == "onedrive.live.com" or host.endswith(".onedrive.live.com"):
        return "onedrive"
    # 1drv.ms is OneDrive's own shortener; it resolves to a sharing URL, which
    # is exactly what the connector hands to Graph anyway.
    if host == "1drv.ms" or host.endswith(".1drv.ms"):
        return "onedrive"
    if host == "sharepoint.com" or host.endswith(".sharepoint.com"):
        # Checked before the plain SharePoint answer, or every personal drive
        # reports as a team site.
        tenant = host.rsplit(".sharepoint.com", 1)[0]
        return "onedrive" if tenant.endswith("-my") else "sharepoint"
    if host == "teams.microsoft.com" or host.endswith(".teams.microsoft.com"):
        return "teams"
    return None
