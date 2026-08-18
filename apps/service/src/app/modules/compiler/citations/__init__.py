"""The offline document-extraction pass that grounds every extracted claim in a citation (architecture §3.11)."""

from __future__ import annotations

from app.modules.compiler.citations.extraction import (
    RunDocumentExtractionPass,
    SaveEngagementDocumentExtractionPass,
    build_extracted_claims,
    run_document_extraction_pass,
)
from app.modules.compiler.citations.models import (
    CitedSpan,
    DocumentExtractionOutput,
    EngagementDocumentExtractionPass,
    ExtractedClaim,
    ExtractedClaimDraft,
    ExtractionPassStatus,
    ExtractionSourceDocument,
)

__all__ = [
    "CitedSpan",
    "DocumentExtractionOutput",
    "EngagementDocumentExtractionPass",
    "ExtractedClaim",
    "ExtractedClaimDraft",
    "ExtractionPassStatus",
    "ExtractionSourceDocument",
    "RunDocumentExtractionPass",
    "SaveEngagementDocumentExtractionPass",
    "build_extracted_claims",
    "run_document_extraction_pass",
]
