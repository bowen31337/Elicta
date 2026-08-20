import { useMemo } from 'react';

import {
  selectionStatus,
  useCurrentEngagement,
  type EngagementSummary,
} from '../../services/selection';
import { combineStatus, useResource, type ResourceStatus } from '../../services/useResource';
import type { QuestionBank, ReferenceDocument } from './types';

/**
 * What the preparation screen shows, read from the service (PRD FR-3.1, FR-3.6, FR-4.8).
 *
 * Three reads against one engagement, deliberately not one: the documents, the
 * vocabulary and the compiled bank are written by three different routes at
 * three different times, and an engagement mid-setup has some and not others.
 * Collapsing them into a single call would make "documents attached, bank not
 * compiled yet" — the normal state of a real engagement — indistinguishable
 * from a failure.
 */
interface WireDocument {
  readonly document_id: string;
  readonly name: string;
  readonly status: string;
}

interface WireDocumentList {
  readonly documents: readonly WireDocument[];
}

interface WireVocabulary {
  readonly terms: readonly { term: string }[];
}

interface WireBankCandidate {
  readonly id: string;
  readonly phrasing: string;
  readonly priority: number;
  readonly pruned: boolean;
}

interface WireBank {
  readonly sections: readonly {
    readonly template_section: string;
    readonly candidates: readonly WireBankCandidate[];
  }[];
}

/** The three statuses the screen's own props recognise. */
const DOCUMENT_STATUSES: readonly ReferenceDocument['status'][] = [
  'ground truth',
  'hypothesis',
  'superseded',
];

function toDocumentStatus(status: string): ReferenceDocument['status'] {
  // The service's enum values carry a space ('ground truth'), and a value it
  // grows later must not be rendered as one of the three that already mean
  // something — an unknown tag reads as a hypothesis, the weakest claim,
  // rather than being promoted to ground truth by accident.
  const known = DOCUMENT_STATUSES.find((candidate) => candidate === status);
  return known ?? 'hypothesis';
}

export interface PrepData {
  readonly clientOrganisation: string;
  readonly documents: readonly ReferenceDocument[];
  readonly vocabulary: readonly string[];
  readonly bank: QuestionBank | null;
  readonly status: ResourceStatus;
  readonly error: string | null;
  readonly engagement: EngagementSummary | null;
}

export function usePrep(): PrepData {
  const current = useCurrentEngagement();
  const id = current.engagementId;
  const scoped = (suffix: string) =>
    id === null ? null : `/api/engagements/${encodeURIComponent(id)}/${suffix}`;

  const documents = useResource<WireDocumentList>(scoped('documents'));
  const vocabulary = useResource<WireVocabulary>(scoped('vocabulary'));
  const bank = useResource<WireBank>(scoped('bank'));

  const sections = bank.data?.sections ?? [];

  return {
    clientOrganisation: current.engagement?.client_organisation ?? 'No engagement yet',
    documents: useMemo(
      () =>
        (documents.data?.documents ?? []).map((document) => ({
          id: document.document_id,
          name: document.name,
          status: toDocumentStatus(document.status),
        })),
      [documents.data],
    ),
    vocabulary: useMemo(
      () => (vocabulary.data?.terms ?? []).map((entry) => entry.term),
      [vocabulary.data],
    ),
    // `null` is the screen's "not compiled yet" branch, and a compile that has
    // not run returns 200 with no sections rather than a 404 — so emptiness,
    // not the status code, is what decides it.
    bank: sections.length === 0 ? null : { sections: sections.map(toSection) },
    status:
      id === null
        ? selectionStatus(current.status, id)
        : combineStatus(current.status, documents.status, vocabulary.status, bank.status),
    error: current.error ?? documents.error ?? vocabulary.error ?? bank.error,
    engagement: current.engagement,
  };
}

function toSection(section: WireBank['sections'][number]) {
  return {
    templateSection: section.template_section,
    // A pruned candidate was explicitly excluded by a reviewer; showing it
    // again would undo the only editing action this screen offers.
    candidates: section.candidates
      .filter((candidate) => !candidate.pruned)
      .map((candidate) => ({
        id: candidate.id,
        phrasing: candidate.phrasing,
        priority: candidate.priority,
      })),
  };
}
