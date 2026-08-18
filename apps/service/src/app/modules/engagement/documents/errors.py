"""Errors raised by the engagement documents API layer."""

from __future__ import annotations


class EngagementNotFoundError(Exception):
    """Raised by a listing callback when `engagement_id` has no known engagement."""


class DocumentNotFoundError(Exception):
    """Raised by a status-update callback when `document_id` has no known document."""


class ReferenceDocumentFetchError(Exception):
    """Raised by a link-attachment fetch callback when retrieving the
    linked document's body fails (PRD FR-3.2), e.g. the SharePoint/Teams
    link is unreachable or the caller lacks access to it.
    """
