"""Compiles one verification-question candidate per hypothesis-document claim (PRD FR-4.9).

Reference documents tagged `hypothesis` have their claims treated as
something to confirm rather than settled fact (PRD §8.3 rationale for
FR-3.4, narrated in `engagement/documents/models.py`): "hypothesis documents
generate verification questions instead" of being trusted outright. This
technique is that pass — it turns each `HYPOTHESIS`-tagged claim into its
own `BankCandidate` phrased as a question, mirroring how
`compiler/bank/recompile.py` turns each inherited open question into its
own candidate. Claims from `GROUND_TRUTH` or `SUPERSEDED` documents are
skipped: this technique only ever fires for `HYPOTHESIS`.
"""

from __future__ import annotations

from app.modules.engagement.documents.models import DocumentStatus

from ..bank.models import BankCandidate
from .models import HypothesisDocumentClaim

VERIFICATION_TEMPLATE_SECTION = "hypothesis-verification"


def generate_verification_questions(claims: list[HypothesisDocumentClaim]) -> list[BankCandidate]:
    """Compile one verification-question `BankCandidate` per hypothesis claim (PRD FR-4.9).

    Claims from non-`HYPOTHESIS` documents are dropped rather than
    rejected: a caller can safely pass every claim from every reference
    document regardless of status and rely on this pass to filter down to
    the ones that actually need verifying. Candidates are produced in the
    order hypothesis claims are given, with `priority` assigned 1..N in
    that order.
    """

    hypothesis_claims = [claim for claim in claims if claim.document_status == DocumentStatus.HYPOTHESIS]

    return [
        BankCandidate(
            id=f"hypothesis-verification-{claim.claim_id}",
            template_section=VERIFICATION_TEMPLATE_SECTION,
            phrasing=f'Can you confirm: "{claim.text}"?',
            priority=index + 1,
        )
        for index, claim in enumerate(hypothesis_claims)
    ]
