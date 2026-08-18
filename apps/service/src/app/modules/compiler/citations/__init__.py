"""The offline document-extraction and claim-structuring passes (architecture §3.11, §14.4).

Citations cannot be combined with a constrained output format in one
request, so this package runs two calls: `extraction.py`'s citations-enabled
pass grounds every claim in a document span, then `structuring.py`'s
schema-constrained pass turns those grounded claims into schema-valid
candidate records.
"""

from __future__ import annotations

from app.modules.compiler.citations.extraction import (
    RunDocumentExtractionPass,
    SaveEngagementDocumentExtractionPass,
    build_extracted_claims,
    format_source_doc,
    run_document_extraction_pass,
)
from app.modules.compiler.citations.models import (
    CitedSpan,
    ClaimStructuringDraft,
    ClaimStructuringOutput,
    ClaimStructuringPassStatus,
    DocumentExtractionOutput,
    EngagementClaimStructuringPass,
    EngagementDocumentExtractionPass,
    ExtractedClaim,
    ExtractedClaimDraft,
    ExtractionPassStatus,
    ExtractionSourceDocument,
    StructuredCitationCandidate,
)
from app.modules.compiler.citations.structuring import (
    RunClaimStructuringPass,
    SaveEngagementClaimStructuringPass,
    build_structured_candidates,
    run_claim_structuring_pass,
)

__all__ = [
    "CitedSpan",
    "ClaimStructuringDraft",
    "ClaimStructuringOutput",
    "ClaimStructuringPassStatus",
    "DocumentExtractionOutput",
    "EngagementClaimStructuringPass",
    "EngagementDocumentExtractionPass",
    "ExtractedClaim",
    "ExtractedClaimDraft",
    "ExtractionPassStatus",
    "ExtractionSourceDocument",
    "RunClaimStructuringPass",
    "RunDocumentExtractionPass",
    "SaveEngagementClaimStructuringPass",
    "SaveEngagementDocumentExtractionPass",
    "StructuredCitationCandidate",
    "build_extracted_claims",
    "build_structured_candidates",
    "format_source_doc",
    "run_claim_structuring_pass",
    "run_document_extraction_pass",
]
