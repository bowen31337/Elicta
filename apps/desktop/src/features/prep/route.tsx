import './screens.css';

import { useCallback, useState } from 'react';

import { ScreenEyebrow } from '../../ui/Mark';
import { ScreenState } from '../../ui/ScreenState';
import {
  addVocabularyTerm,
  compileBank,
  createMeeting,
  deleteDocument,
  deleteVocabularyTerm,
  linkDocument,
  moveCandidate,
  pruneCandidate,
  retagDocument,
  uploadDocument,
} from './prepActions';
import type {
  BankCandidate,
  DocumentStatus,
  PreparedMeeting,
  QuestionBank,
  ReferenceDocument,
  VocabularyEntry,
  VocabularyTermType,
} from './types';
import { CAPTURE_MODES } from './types';
import { usePrep } from './usePrep';

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
 *
 * Every control here writes to an endpoint that already existed. For a while
 * none of them did: `Prune` and `Compile` were rendered as buttons with no
 * handler and there was no control at all for attaching a document, adding a
 * term or creating the engagement, so the only way to prepare an engagement
 * was to call the API by hand. The journey document described the API and read
 * as though it described the screen.
 */
export interface PrepActions {
  readonly prune: (candidateId: string) => Promise<void>;
  readonly move: (candidateId: string, priority: number) => Promise<void>;
  readonly compile: () => Promise<void>;
  readonly addTerm: (term: string, termType: VocabularyTermType) => Promise<void>;
  readonly attach: (url: string, status: DocumentStatus) => Promise<void>;
  readonly upload: (file: File, status: DocumentStatus) => Promise<void>;
  readonly removeDocument: (documentId: string) => Promise<void>;
  readonly removeTerm: (termId: string) => Promise<void>;
  readonly addMeeting: (captureMode: string) => Promise<void>;
  readonly retag: (documentId: string, status: DocumentStatus) => Promise<void>;
}

export interface PrepScreenProps {
  readonly clientOrganisation: string;
  readonly documents: readonly ReferenceDocument[];
  readonly vocabulary: readonly VocabularyEntry[];
  readonly bank: QuestionBank | null;
  /** Why the bank is empty, when it is. See `compileNotice` in `usePrep`. */
  readonly compileNotice?: string | null;
  /** True while a compile is running, which is neither empty nor finished. */
  readonly compileRunning?: boolean;
  readonly meetings: readonly PreparedMeeting[];
  readonly actions: PrepActions;
}

function meetingCaptureLabel(mode: string): string {
  return CAPTURE_MODES.find((known) => known.value === mode)?.label ?? mode;
}

const DOCUMENT_STATUSES: readonly DocumentStatus[] = ['ground truth', 'hypothesis', 'superseded'];

/** The three kinds of word, in the order journey 1 introduces them. */
const TERM_TYPES: readonly { readonly value: VocabularyTermType; readonly label: string }[] = [
  { value: 'product_name', label: 'Product name' },
  { value: 'internal_system', label: 'Internal system' },
  { value: 'acronym', label: 'Acronym or jargon' },
];

/**
 * Runs one write and keeps what happened.
 *
 * A refusal here is usually actionable — a link that is not SharePoint, a term
 * the service will not take — so the service's own sentence is shown rather
 * than a status code, and the control stays disabled only while the call is in
 * flight.
 */
function useWrite() {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = useCallback(async (write: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await write();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'That did not work.');
    } finally {
      setBusy(false);
    }
  }, []);

  return { error, busy, run };
}

export function PrepScreen({
  clientOrganisation,
  documents,
  vocabulary,
  bank,
  meetings,
  actions,
  compileNotice = null,
  compileRunning = false,
}: PrepScreenProps) {
  const write = useWrite();
  const [link, setLink] = useState('');
  const [linkStatus, setLinkStatus] = useState<DocumentStatus>('ground truth');
  const [term, setTerm] = useState('');
  const [termType, setTermType] = useState<VocabularyTermType>('product_name');
  const [dragging, setDragging] = useState(false);
  const [captureMode, setCaptureMode] = useState<string>(CAPTURE_MODES[0].value);

  /**
   * Uploads a dropped or chosen batch, one at a time and in the order given.
   *
   * Sequential rather than concurrent: the service mints document ids as it
   * goes, and a list that comes back in a different order than the operator
   * dropped things reads as though something went wrong.
   */
  const upload = (files: FileList | null | undefined) => {
    const chosen = [...(files ?? [])];
    if (chosen.length === 0) return;
    void write.run(async () => {
      for (const file of chosen) {
        await actions.upload(file, linkStatus);
      }
    });
  };

  const attach = () => {
    if (link.trim() === '') return;
    void write.run(async () => {
      await actions.attach(link.trim(), linkStatus);
      setLink('');
    });
  };

  const addTerm = () => {
    if (term.trim() === '') return;
    void write.run(async () => {
      await actions.addTerm(term.trim(), termType);
      setTerm('');
    });
  };

  return (
    <main className="screen" aria-labelledby="prep-title">
      <header className="screen-head">
        <ScreenEyebrow>Engagement</ScreenEyebrow>
        <h1 className="t-large-title" id="prep-title">
          {clientOrganisation}
        </h1>
      </header>

      {write.error === null ? null : (
        <p className="t-footnote prep-error" role="alert">
          {write.error}
        </p>
      )}

      <section aria-labelledby="docs-title">
        <h2 className="t-section" id="docs-title">
          Reference documents
        </h2>
        <div className="group">
          {documents.map((document) => (
            <div className="row" key={document.id}>
              <div className="row-main">
                <span className="t-body">{document.name}</span>
              </div>
              <label className="sr-only" htmlFor={`tag-${document.id}`}>
                Tag for {document.name}
              </label>
              <select
                id={`tag-${document.id}`}
                className="field field--inline"
                value={document.status}
                disabled={write.busy}
                onChange={(event) =>
                  void write.run(() =>
                    actions.retag(document.id, event.target.value as DocumentStatus),
                  )
                }
              >
                {DOCUMENT_STATUSES.map((status) => (
                  <option key={status} value={status}>
                    {status}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="btn btn--danger"
                disabled={write.busy}
                aria-label={`Remove ${document.name}`}
                onClick={() => void write.run(() => actions.removeDocument(document.id))}
              >
                Remove
              </button>
            </div>
          ))}

          <div className="row row--form">
            <div className="row-main">
              <label className="t-footnote" htmlFor="doc-link">
                SharePoint, OneDrive or Teams link
              </label>
              <input
                id="doc-link"
                type="url"
                className="field"
                placeholder="https://…sharepoint.com/… or https://1drv.ms/…"
                value={link}
                onChange={(event) => setLink(event.target.value)}
              />
            </div>
            <label className="sr-only" htmlFor="doc-link-status">
              How to treat it
            </label>
            <select
              id="doc-link-status"
              className="field field--inline"
              value={linkStatus}
              onChange={(event) => setLinkStatus(event.target.value as DocumentStatus)}
            >
              {DOCUMENT_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
            <button type="button" className="btn" disabled={write.busy} onClick={attach}>
              Attach
            </button>
          </div>
        </div>

        <div
          data-testid="document-dropzone"
          className={`dropzone${dragging ? ' dropzone--over' : ''}`}
          onDragOver={(event) => {
            // Without preventDefault the browser navigates to the dropped file
            // and the operator loses the screen they were preparing.
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            upload(event.dataTransfer?.files);
          }}
        >
          <p className="t-body">Drop documents here</p>
          <p className="t-footnote">
            Tagged as <strong>{linkStatus}</strong>. Uploaded documents are read
            straight away and need no connector configured.
          </p>
          <label className="btn dropzone-pick" htmlFor="doc-files">
            Choose files
          </label>
          <input
            id="doc-files"
            className="sr-only"
            type="file"
            multiple
            disabled={write.busy}
            onChange={(event) => {
              upload(event.target.files);
              // Cleared so choosing the same file twice fires a change both
              // times — re-uploading a corrected document is a normal thing
              // to want.
              event.target.value = '';
            }}
          />
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
          {vocabulary.map((entry) => (
            <span className="pill pill--removable" key={entry.id}>
              {entry.term}
              <button
                type="button"
                className="pill-remove"
                disabled={write.busy}
                aria-label={`Remove ${entry.term}`}
                onClick={() => void write.run(() => actions.removeTerm(entry.id))}
              >
                ×
              </button>
            </span>
          ))}
        </div>
        <div className="group">
          <div className="row row--form">
            <div className="row-main">
              <label className="t-footnote" htmlFor="vocab-term">
                A word the client uses
              </label>
              <input
                id="vocab-term"
                type="text"
                className="field"
                placeholder="Zephyr WMS"
                value={term}
                onChange={(event) => setTerm(event.target.value)}
              />
            </div>
            <label className="sr-only" htmlFor="vocab-type">
              What kind of word it is
            </label>
            <select
              id="vocab-type"
              className="field field--inline"
              value={termType}
              onChange={(event) => setTermType(event.target.value as VocabularyTermType)}
            >
              {TERM_TYPES.map((kind) => (
                <option key={kind.value} value={kind.value}>
                  {kind.label}
                </option>
              ))}
            </select>
            <button type="button" className="btn" disabled={write.busy} onClick={addTerm}>
              Add term
            </button>
          </div>
        </div>
        <p className="t-footnote hint">
          Anything removed here is kept and can be brought back; nothing is
          erased. Sent to the transcriber as keyterms. Client and product names are the
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
                {/* "Not compiled yet" was shown after four compiles had run
                    and failed, because an empty bank looks the same either
                    way. It is only true when nothing has been attempted. */}
                <span className="t-body">
                  {compileRunning
                    ? 'Compiling'
                    : compileNotice === null
                      ? 'Not compiled yet'
                      : 'The bank is empty'}
                </span>
                {compileNotice === null ? (
                  <span className="t-footnote">
                    Compiling reads the documents and drafts candidates. Minutes,
                    not seconds.
                  </span>
                ) : (
                  <span className="t-footnote" role="status">
                    {compileNotice}
                  </span>
                )}
              </div>
              <button
                type="button"
                className="btn btn--filled"
                disabled={write.busy || compileRunning}
                onClick={() => void write.run(() => actions.compile())}
              >
                Compile
              </button>
            </div>
          </div>
        ) : (
          bank.sections.map((section) => (
            <div className="group bank-section" key={section.templateSection}>
              <div className="row row--header">
                <span className="t-headline">{section.templateSection}</span>
                <span className="t-caption tabular">{section.candidates.length}</span>
              </div>
              {section.candidates.map((candidate, at) => (
                <CandidateRow
                  key={candidate.id}
                  candidate={candidate}
                  above={at === 0 ? null : section.candidates[at - 1]}
                  busy={write.busy}
                  actions={actions}
                  run={write.run}
                />
              ))}
            </div>
          ))
        )}
      </section>

      <section aria-labelledby="meetings-title">
        <h2 className="t-section" id="meetings-title">
          Meetings
        </h2>
        <div className="group">
          {meetings.length === 0 ? (
            <div className="row">
              <div className="row-main">
                <span className="t-body">No meetings yet</span>
                <span className="t-footnote">
                  Everything after this page is about a meeting — consent, the
                  live panel, the recording and the write-up. Add the first one
                  here.
                </span>
              </div>
            </div>
          ) : (
            meetings.map((meeting) => (
              <div className="row" key={meeting.id}>
                <div className="row-main">
                  <span className="t-body">{meeting.purpose ?? meeting.id}</span>
                  <span className="t-footnote">
                    {meetingCaptureLabel(meeting.captureMode)} · {meeting.state}
                  </span>
                </div>
              </div>
            ))
          )}

          <div className="row row--form">
            <div className="row-main">
              <label className="t-footnote" htmlFor="meeting-capture">
                How the audio is captured
              </label>
              <select
                id="meeting-capture"
                className="field"
                value={captureMode}
                onChange={(event) => setCaptureMode(event.target.value)}
              >
                {CAPTURE_MODES.map((mode) => (
                  <option key={mode.value} value={mode.value}>
                    {mode.label}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="button"
              className="btn"
              disabled={write.busy}
              onClick={() => void write.run(() => actions.addMeeting(captureMode))}
            >
              Add meeting
            </button>
          </div>
        </div>
        <p className="t-footnote hint">
          Which one you are working on is chosen in the toolbar, beside the
          engagement.
        </p>
      </section>

    </main>
  );
}

/**
 * One candidate, with the two edits a reviewer makes: move it earlier, or take
 * it out. Promotion takes the priority of the question above it rather than
 * `priority - 1`, so a bank whose priorities are not contiguous still reorders
 * the way the list reads.
 */
function CandidateRow({
  candidate,
  above,
  busy,
  actions,
  run,
}: {
  readonly candidate: BankCandidate;
  readonly above: BankCandidate | null;
  readonly busy: boolean;
  readonly actions: PrepActions;
  readonly run: (write: () => Promise<void>) => Promise<void>;
}) {
  return (
    <div className="row">
      <div className="row-main">
        <span className="t-body">{candidate.phrasing}</span>
        <span className="t-footnote">Priority {candidate.priority}</span>
      </div>
      <button
        type="button"
        className="btn"
        disabled={busy || above === null}
        aria-label={`Move “${candidate.phrasing}” earlier`}
        onClick={() => {
          if (above === null) return;
          void run(() => actions.move(candidate.id, above.priority));
        }}
      >
        Move up
      </button>
      <button
        type="button"
        className="btn btn--danger"
        disabled={busy}
        aria-label={`Prune “${candidate.phrasing}”`}
        onClick={() => void run(() => actions.prune(candidate.id))}
      >
        Prune
      </button>
    </div>
  );
}

/**
 * The mounted screen: the same component, over the service instead of over
 * four hardcoded empty values. What it showed before — an em dash and three
 * empty lists — was indistinguishable from a working screen for an engagement
 * with nothing in it, and from a service that was not running at all. Those
 * are now three different pictures.
 */
export default function PrepRoute() {
  const prep = usePrep();
  const engagementId = prep.engagementId;
  const { reload } = prep;

  // Every write re-reads, so what the screen shows after an edit is what the
  // service stored, not what this component hoped it stored.
  const after = useCallback(
    async (write: Promise<unknown>) => {
      await write;
      reload();
    },
    [reload],
  );

  const actions: PrepActions = {
    prune: (candidateId) => after(pruneCandidate(candidateId)),
    move: (candidateId, priority) => after(moveCandidate(candidateId, priority)),
    compile: () => after(engagementId === null ? Promise.resolve() : compileBank(engagementId)),
    addTerm: (term, termType) =>
      after(
        engagementId === null
          ? Promise.resolve()
          : addVocabularyTerm(engagementId, { term, termType }),
      ),
    attach: (url, status) =>
      after(engagementId === null ? Promise.resolve() : linkDocument(engagementId, { url, status })),
    upload: (file, status) =>
      after(engagementId === null ? Promise.resolve() : uploadDocument(engagementId, file, status)),
    removeDocument: (documentId) => after(deleteDocument(documentId)),
    removeTerm: (termId) =>
      after(
        engagementId === null
          ? Promise.resolve()
          : deleteVocabularyTerm(engagementId, termId),
      ),
    addMeeting: (captureMode) =>
      after(
        engagementId === null
          ? Promise.resolve()
          : createMeeting({ engagementId, captureMode }),
      ),
    retag: (documentId, status) => after(retagDocument(documentId, status)),
  };

  if (prep.status !== 'ready' && prep.status !== 'missing') {
    return (
      <ScreenState
        eyebrow="Engagement"
        status={prep.status}
        error={prep.error}
        idleHint="No engagement is selected. Choose one on the Engagements screen, or make the first one there."
      />
    );
  }

  return (
    <PrepScreen
      clientOrganisation={prep.clientOrganisation}
      documents={prep.documents}
      vocabulary={prep.vocabulary}
      bank={prep.bank}
      compileNotice={prep.compileNotice}
      compileRunning={prep.compileRunning}
      meetings={prep.meetings}
      actions={actions}
    />
  );
}
