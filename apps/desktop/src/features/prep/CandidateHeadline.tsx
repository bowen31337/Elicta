import { stubFor } from '../../services/questionStub';
import type { BankCandidate } from './types';

/**
 * One bank candidate, in the two tiers the meeting will show it in.
 *
 * The bank was reviewed here as full phrasings and asked in the room as a
 * glance, and this screen showed only the first of those. So an operator could
 * read, reorder and approve a whole bank without ever seeing the form they
 * would actually work from — which, for every bank compiled before the stub
 * reached the panel, was empty.
 *
 * Both tiers, not one. The panel shows the glance because an operator there is
 * looking at a client; this screen is where the wording is edited and read for
 * sense, so replacing the phrasing with keywords would remove the thing being
 * reviewed. The headline is here so the reviewer can see what the glance will
 * be — and notice when it is a poor one, which is a thing they can fix before
 * the meeting rather than during it.
 */
export function CandidateHeadline({ candidate }: { readonly candidate: BankCandidate }) {
  const headline = stubFor(candidate);
  // A question already short enough is its own headline. Printing it twice
  // reads as a rendering fault rather than as two tiers.
  const echoes = headline.trim().toLowerCase() === candidate.phrasing.trim().toLowerCase();

  return (
    <>
      <span className="t-headline candidate-headline" data-testid="candidate-headline">
        {headline}
      </span>
      {echoes ? null : (
        <span className="t-body candidate-phrasing">{candidate.phrasing}</span>
      )}
    </>
  );
}
