import './screens.css';

import { ScreenEyebrow } from '../../ui/Mark';
import type { QuestionBank, ReferenceDocument } from './types';

/**
 * Journey 1 — prepare an engagement.
 *
 * The reviewable question tree is the point of this screen. The PRD calls it
 * the phase 0 deliverable: "if the tree is good, the operator is better
 * prepared even if the live layer never ships." So the tree gets the space,
 * and setup is compressed into rows above it.
 *
 * Each candidate shows its phrasing, not an id — a reviewer prunes on whether
 * they would actually ask the question out loud.
 */
export interface PrepScreenProps {
  readonly clientOrganisation: string;
  readonly documents: readonly ReferenceDocument[];
  readonly vocabulary: readonly string[];
  readonly bank: QuestionBank | null;
}

const STATUS_PILL: Record<string, string> = {
  'ground truth': 'pill pill--ok',
  hypothesis: 'pill',
  superseded: 'pill pill--warn',
};

export function PrepScreen({
  clientOrganisation,
  documents,
  vocabulary,
  bank,
}: PrepScreenProps) {
  return (
    <main className="screen" aria-labelledby="prep-title">
      <header className="screen-head">
        <ScreenEyebrow>Engagement</ScreenEyebrow>
        <h1 className="t-large-title" id="prep-title">
          {clientOrganisation}
        </h1>
      </header>

      <section aria-labelledby="docs-title">
        <h2 className="t-section" id="docs-title">
          Reference documents
        </h2>
        <div className="group">
          {documents.map((document) => (
            <div className="row" key={document.id}>
              <div className="row-main">
                <span className="t-body">{document.name}</span>
                <span className="t-footnote">Indexed for retrieval</span>
              </div>
              <span className={STATUS_PILL[document.status] ?? 'pill'}>
                {document.status}
              </span>
            </div>
          ))}
        </div>
        <p className="t-footnote hint">
          A document tagged <strong>ground truth</strong> is the only kind a
          contradiction can fire against.
        </p>
      </section>

      <section aria-labelledby="vocab-title">
        <h2 className="t-section" id="vocab-title">
          Engagement vocabulary
        </h2>
        <div className="chips-row">
          {vocabulary.map((term) => (
            <span className="pill" key={term}>
              {term}
            </span>
          ))}
        </div>
        <p className="t-footnote hint">
          Sent to the transcriber as keyterms. Client and product names are the
          words most often misheard, and a misheard product name fires a
          trigger about nothing.
        </p>
      </section>

      <section aria-labelledby="bank-title">
        <h2 className="t-section" id="bank-title">
          Question bank
        </h2>
        {bank === null ? (
          <div className="group">
            <div className="row">
              <div className="row-main">
                <span className="t-body">Not compiled yet</span>
                <span className="t-footnote">
                  Compiling reads the documents and drafts candidates. Minutes,
                  not seconds.
                </span>
              </div>
              <button type="button" className="btn btn--filled">
                Compile
              </button>
            </div>
          </div>
        ) : (
          bank.sections.map((section) => (
            <div className="group bank-section" key={section.templateSection}>
              <div className="row row--header">
                <span className="t-headline">{section.templateSection}</span>
                <span className="t-caption tabular">
                  {section.candidates.length}
                </span>
              </div>
              {section.candidates.map((candidate) => (
                <div className="row" key={candidate.id}>
                  <div className="row-main">
                    <span className="t-body">{candidate.phrasing}</span>
                    <span className="t-footnote">Priority {candidate.priority}</span>
                  </div>
                  <button type="button" className="btn btn--danger">
                    Prune
                  </button>
                </div>
              ))}
            </div>
          ))
        )}
      </section>
    </main>
  );
}

export default function PrepRoute() {
  return (
    <PrepScreen clientOrganisation="—" documents={[]} vocabulary={[]} bank={null} />
  );
}
