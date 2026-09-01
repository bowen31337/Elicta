import './screens.css';
import {
  CompileProgress,
  type CompileState,
  type NoticeTone,
} from './CompileProgress';

import { useCallback, useState } from 'react';

import { ScreenEyebrow } from '../../ui/Mark';
import { ConfirmDialog } from '../../ui/ConfirmDialog';
import { ScreenState } from '../../ui/ScreenState';
import {
  addVocabularyTerm,
  compileBank,
  createMeeting,
  deleteDocument,
  deleteMeeting,
  deleteVocabularyTerm,
  linkDocument,
  moveCandidate,
  pruneCandidate,
  renameMeeting,
  retagDocument,
  uploadDocument,
} from './prepActions';
import type {
  BankCandidate,
  DocumentStatus,
  PreparedMeeting,
  QuestionBank,
  QuestionBankSection,
  ReferenceDocument,
  VocabularyEntry,
  VocabularyTermType,
} from './types';
import { CAPTURE_MODES } from './types';
import { SectionIndex } from './SectionIndex';
import type { IndexEntry } from './sectionNavigation';
import { bankSectionId, flattenEntries, jumpBehaviour } from './sectionNavigation';
import { useCurrentSection } from './useCurrentSection';
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
  readonly renameMeeting: (meetingId: string, sessionPurpose: string) => Promise<void>;
  readonly removeMeeting: (meetingId: string) => Promise<void>;
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
  /** Where the compile is, for the meter. See `CompileProgress`. */
  readonly compileState?: CompileState;
  /** Which stages the service says are finished. */
  readonly compileStages?: readonly string[];
  /** How the notice reads: something to wait out, look at, or fix. */
  readonly compileTone?: NoticeTone;
  readonly meetings: readonly PreparedMeeting[];
  readonly actions: PrepActions;
}

function meetingCaptureLabel(mode: string): string {
  return CAPTURE_MODES.find((known) => known.value === mode)?.label ?? mode;
}

/**
 * What to call a meeting in a label a person or a screen reader reads.
 *
 * A meeting created and not yet described has no purpose, and this screen is
 * where several of those accumulate — so the id stands in. Two rows whose
 * buttons both read `Remove` are two buttons a screen reader cannot separate.
 */
function meetingName(meeting: PreparedMeeting): string {
  const purpose = meeting.purpose?.trim();
  return purpose === undefined || purpose === '' ? meeting.id : purpose;
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
  compileState = 'idle',
  compileStages = [],
  compileTone,
}: PrepScreenProps) {
  const write = useWrite();
  const [link, setLink] = useState('');
  const [linkStatus, setLinkStatus] = useState<DocumentStatus>('ground truth');
  const [term, setTerm] = useState('');
  const [termType, setTermType] = useState<VocabularyTermType>('product_name');
  const [dragging, setDragging] = useState(false);
  const [captureMode, setCaptureMode] = useState<string>(CAPTURE_MODES[0].value);
  /**
   * Which meeting is being renamed, or `null` for none.
   *
   * One id rather than a flag per row: only one row is ever being edited, and
   * a set would let two rows hold two drafts of the same field.
   */
  const [renaming, setRenaming] = useState<string | null>(null);
  /**
   * The meeting the dialog is asking about, or none.
   *
   * The whole meeting rather than its id, so the question can name it. An id
   * would make the dialog read "Remove meeting-2?", which is the label on the
   * button that opened it and tells the operator nothing they did not have.
   */
  const [removingMeeting, setRemovingMeeting] = useState<PreparedMeeting | null>(null);
  /**
   * Whether the recompile question is open.
   *
   * `Compile` used to live only in the branch that renders when there is no
   * bank, so an engagement could be compiled exactly once — and the moment
   * that matters most was the unreachable one: documents get added, the bank
   * goes stale, and nothing offered to draft it again.
   */
  const [confirmingRecompile, setConfirmingRecompile] = useState(false);
  const [purposeDraft, setPurposeDraft] = useState('');
  /**
   * Which bank sections are open, or `null` for "the operator has not said".
   *
   * `null` rather than seeding a set on mount, because the bank is not
   * necessarily there on mount: an engagement compiles later, and a set seeded
   * from a bank that was still `null` would open nothing and look broken. This
   * way the default is a rule — the first section — evaluated whenever the
   * sections actually arrive.
   */
  const [openSections, setOpenSections] = useState<ReadonlySet<string> | null>(null);
  const [bankQuery, setBankQuery] = useState('');

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

  /* --- The bank, as something short enough to read -------------------------
     A compiled bank is around seventy questions in eight template sections.
     Rendered flat that was nine thousand pixels — eleven screens — with no
     section heading in view to say which one you were in, and it pushed the
     Meetings section below all of it. Two things fix that without hiding the
     deliverable: the sections are disclosures, and there is one box to search
     them. */
  const query = bankQuery.trim().toLowerCase();
  const filtering = query !== '';

  const sections = bank?.sections ?? [];
  /** Every section, paired with the candidates the filter leaves in it. */
  const shownSections = sections
    .map((section) => ({
      section,
      shown: filtering
        ? section.candidates.filter((candidate) =>
            candidate.phrasing.toLowerCase().includes(query),
          )
        : section.candidates,
    }))
    .filter((entry) => entry.shown.length > 0);

  const total = sections.reduce((count, section) => count + section.candidates.length, 0);
  const matched = shownSections.reduce((count, entry) => count + entry.shown.length, 0);

  const bankSummary = filtering
    ? `${matched} of ${total} ${total === 1 ? 'question' : 'questions'} contain that. `
      + 'Reordering is off while the filter is on — a question can only be moved '
      + 'past one you can see.'
    : `${total} ${total === 1 ? 'question' : 'questions'} across `
      + `${sections.length} ${sections.length === 1 ? 'section' : 'sections'}. `
      + 'Open a section to review it.';

  /**
   * The default is the first section open and the rest closed. Open, because a
   * screen whose whole point is the question tree should not arrive as eight
   * closed rows that could be read as an empty bank; the rest closed, because
   * that is the length problem.
   */
  const isOpen = (name: string): boolean =>
    openSections === null ? name === sections[0]?.templateSection : openSections.has(name);

  const allOpen = sections.length > 0 && sections.every((s) => isOpen(s.templateSection));

  const toggleSection = (name: string) => {
    setOpenSections((current) => {
      const next = new Set(
        current ?? (sections[0] === undefined ? [] : [sections[0].templateSection]),
      );
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  /* --- Getting to the bottom of twelve viewports ---------------------------
     Measured on the running app with a real compiled bank — 73 questions in
     eight sections — this screen is 3,452px with one section open and
     11,021px with all of them open, and Meetings starts at 10,235px. The
     disclosures and the filter made the bank readable; they did nothing about
     the page, which still had to be crossed by wheel. The index below is the
     route across it, and it lists the bank's own sections too, because that
     is where the length is. */
  const indexEntries: readonly IndexEntry[] = [
    { id: 'prep-documents', label: 'Reference documents' },
    { id: 'prep-vocabulary', label: 'Engagement vocabulary' },
    {
      id: 'prep-bank',
      label: 'Question bank',
      childrenLabel: 'Question bank sections',
      // From the sections the screen renders, not from the filtered view: an
      // index that shrinks as you type is a map redrawing itself while you
      // read it. The filter already says what it matched, in words.
      children: sections.map((section) => ({
        id: bankSectionId(section.templateSection),
        label: section.templateSection,
        count: section.candidates.length,
      })),
    },
    { id: 'prep-meetings', label: 'Meetings' },
  ];

  const index = useCurrentSection(flattenEntries(indexEntries).map((entry) => entry.id));

  const jump = (entry: IndexEntry) => {
    // A closed section jumped to and left closed is a jump that did nothing:
    // the operator asked for Constraints and got a shut header. Opening it is
    // the whole point of having asked.
    const section = sections.find((s) => bankSectionId(s.templateSection) === entry.id);
    if (section !== undefined && !isOpen(section.templateSection)) {
      toggleSection(section.templateSection);
    }

    const target = document.getElementById(entry.id);
    if (target === null) return;

    // Focus first and without scrolling, so the keyboard lands where the eye
    // is about to; then the scroll, which is the part that is animated.
    // Focusing after would fight the animation, and focusing *with* scroll
    // would jump to the destination and then animate from it.
    target.focus?.({ preventScroll: true });

    const box = target.getBoundingClientRect?.();
    target.scrollIntoView?.({
      behavior: jumpBehaviour(
        box === undefined ? 0 : box.top,
        window.innerHeight,
        window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true,
      ),
      block: 'start',
    });
  };

  return (
    /* The index is a sibling of the document rather than its first child, and
       that is a layout decision, not a tidiness one: as a grid item beside
       `.screen` its area is the full height of the page, which is the distance
       a sticky rail has to be free to travel. Nested inside the column it
       could only travel within its own row, which is no distance at all. */
    <div className="screen-layout">
      <ConfirmDialog
        open={confirmingRecompile}
        title="Draft this bank again?"
        body="It reads the documents as they are now and replaces every question in the bank — including the pruning you have done, which is stored on the questions being replaced. It takes minutes, and it costs a model pass."
        confirmLabel="Recompile"
        cancelLabel="Keep this bank"
        onCancel={() => setConfirmingRecompile(false)}
        onConfirm={() => {
          setConfirmingRecompile(false);
          void write.run(() => actions.compile());
        }}
      />
      <ConfirmDialog
        open={removingMeeting !== null}
        title={`Remove ${removingMeeting === null ? '' : meetingName(removingMeeting)}?`}
        body="It comes off this list. If the meeting happened, its consent record and its recording stay exactly where they are — nothing is erased."
        confirmLabel="Remove"
        onCancel={() => setRemovingMeeting(null)}
        onConfirm={() => {
          const going = removingMeeting;
          setRemovingMeeting(null);
          if (going !== null) void write.run(() => actions.removeMeeting(going.id));
        }}
      />
      <SectionIndex entries={indexEntries} currentId={index.currentId} onJump={jump} />

      <main className="screen screen--indexed" aria-labelledby="prep-title" ref={index.attach}>
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

      <section id="prep-documents" tabIndex={-1} aria-labelledby="docs-title">
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

      <section id="prep-vocabulary" tabIndex={-1} aria-labelledby="vocab-title">
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

      <section id="prep-bank" tabIndex={-1} aria-labelledby="bank-title">
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
                {compileState === 'idle' ? (
                  <span className="t-footnote">
                    Compiling reads the documents and drafts candidates. Minutes,
                    not seconds.
                  </span>
                ) : null}
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
            {/* Under the row, spanning the card. It carries both what the
                compile is doing and whatever it has to say about itself: one
                word — "Compiling" — read the same at ten seconds and at six
                minutes, which is how working became indistinguishable from
                stuck. */}
            <CompileProgress
              state={compileState}
              stagesCompleted={compileStages}
              notice={
                compileNotice
                ?? (compileState === 'complete'
                  ? 'The compile finished and drafted no candidates. Nothing was refused; there was nothing in the documents to draft from.'
                  : null)
              }
              tone={
                compileNotice === null && compileState === 'complete'
                  ? 'warning'
                  : compileTone
              }
            />
          </div>
        ) : (
          <>
            <div className="group">
              <div className="row">
                <div className="row-main">
                  <span className="t-body">
                    {compileRunning ? 'Compiling…' : 'Draft this bank again'}
                  </span>
                  {/* Stated here rather than in the dialog alone: an operator
                      deciding whether to bother needs to know it is not free
                      before they press anything. */}
                  <span className="t-footnote">
                    Reads the documents as they are now and replaces the bank.
                    Minutes, not seconds.
                  </span>

                </div>
                <button
                  type="button"
                  className="btn"
                  disabled={write.busy || compileRunning}
                  onClick={() => setConfirmingRecompile(true)}
                >
                  Recompile
                </button>
              </div>
              {/* A recompile is the same minutes-long job as a first compile
                  and had no meter at all — the bank on screen is the *old* one
                  throughout, so without this there is nothing to tell a
                  recompile in progress from one that never started. */}
              <CompileProgress
                state={compileState}
                stagesCompleted={compileStages}
                notice={compileNotice}
                tone={compileTone}
              />
              <div className="row row--form">
                <div className="row-main">
                  <label className="t-footnote" htmlFor="bank-filter">
                    Find a question
                  </label>
                  <input
                    id="bank-filter"
                    className="field"
                    type="search"
                    value={bankQuery}
                    placeholder="A word the question would contain"
                    aria-describedby="bank-filter-note"
                    onChange={(event) => setBankQuery(event.target.value)}
                  />
                </div>
                <button
                  type="button"
                  className="btn"
                  onClick={() =>
                    setOpenSections(
                      allOpen
                        ? new Set()
                        : new Set(bank.sections.map((section) => section.templateSection)),
                    )
                  }
                >
                  {allOpen ? 'Collapse all' : 'Expand all'}
                </button>
              </div>
            </div>

            <p className="t-footnote hint" id="bank-filter-note">
              {bankSummary}
            </p>

            {shownSections.length === 0 ? (
              <div className="group">
                <div className="row">
                  <div className="row-main">
                    <span className="t-body">No question contains that</span>
                    <span className="t-footnote">
                      The filter reads the question as it would be asked out
                      loud, which is the only text a candidate has.
                    </span>
                  </div>
                </div>
              </div>
            ) : (
              shownSections.map(({ section, shown }) => (
                <BankSection
                  key={section.templateSection}
                  section={section}
                  shown={shown}
                  open={filtering || isOpen(section.templateSection)}
                  // A filter decides what is open while it is on: a section
                  // that matched is worth opening, and one that did not is
                  // gone rather than sitting there as a header to scroll past.
                  toggleable={!filtering}
                  reorderable={!filtering}
                  onToggle={() => toggleSection(section.templateSection)}
                  busy={write.busy}
                  actions={actions}
                  run={write.run}
                />
              ))
            )}
          </>
        )}
      </section>

      <section id="prep-meetings" tabIndex={-1} aria-labelledby="meetings-title">
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
            meetings.map((meeting) =>
              renaming === meeting.id ? (
                <div className="row row--form" key={meeting.id}>
                  <div className="row-main">
                    <label className="t-footnote" htmlFor={`meeting-purpose-${meeting.id}`}>
                      What this meeting is for
                    </label>
                    <input
                      id={`meeting-purpose-${meeting.id}`}
                      type="text"
                      className="field"
                      placeholder="Discovery 2 — depot volumes"
                      value={purposeDraft}
                      disabled={write.busy}
                      onChange={(event) => setPurposeDraft(event.target.value)}
                    />
                  </div>
                  <button
                    type="button"
                    className="btn"
                    disabled={write.busy}
                    aria-label="Save meeting purpose"
                    onClick={() =>
                      void write.run(async () => {
                        await actions.renameMeeting(meeting.id, purposeDraft);
                        setRenaming(null);
                      })
                    }
                  >
                    Save
                  </button>
                  <button
                    type="button"
                    className="btn"
                    disabled={write.busy}
                    aria-label="Cancel rename"
                    onClick={() => setRenaming(null)}
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="row" key={meeting.id}>
                  <div className="row-main">
                    <span className="t-body">{meetingName(meeting)}</span>
                    <span className="t-footnote">
                      {meetingCaptureLabel(meeting.captureMode)} · {meeting.state}
                    </span>
                  </div>
                  <button
                    type="button"
                    className="btn"
                    disabled={write.busy}
                    aria-label={`Rename ${meetingName(meeting)}`}
                    onClick={() => {
                      // Opened with the current purpose in it: renaming is
                      // usually amending, and retyping a sentence to change one
                      // word is how two meetings end up called almost the same.
                      setPurposeDraft(meeting.purpose ?? '');
                      setRenaming(meeting.id);
                    }}
                  >
                    Rename
                  </button>
                  <button
                    type="button"
                    className="btn btn--danger"
                    disabled={write.busy}
                    aria-label={`Remove ${meetingName(meeting)}`}
                    onClick={() => setRemovingMeeting(meeting)}
                  >
                    Remove
                  </button>
                </div>
              ),
            )
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
          engagement. Removing one takes it off this list — nothing is erased,
          and the consent record and recording of a meeting that happened stay
          where they are.
        </p>
      </section>

      </main>
    </div>
  );
}

/**
 * One template section of the bank, as a disclosure.
 *
 * The header carries the count because that is what a closed section has to
 * answer: an operator deciding where to spend the next ten minutes wants to
 * know that Constraints has twelve questions in it and Volumes has eight.
 * Under a filter it counts both ways — "3 of 11" — so a section is never
 * silently showing a subset of itself.
 *
 * Wrapped in an `h3` so the closed bank is a list of headings to a screen
 * reader, which is the same thing it is to the eye.
 */
function BankSection({
  section,
  shown,
  open,
  toggleable,
  reorderable,
  onToggle,
  busy,
  actions,
  run,
}: {
  readonly section: QuestionBankSection;
  readonly shown: readonly BankCandidate[];
  readonly open: boolean;
  readonly toggleable: boolean;
  readonly reorderable: boolean;
  readonly onToggle: () => void;
  readonly busy: boolean;
  readonly actions: PrepActions;
  readonly run: (write: () => Promise<void>) => Promise<void>;
}) {
  const bodyId = `bank-body-${section.templateSection.replace(/\W+/g, '-').toLowerCase()}`;
  // The index points here, and the disclosure header is what it points *at* —
  // so the id sits on the group rather than on the body, or a jump would land
  // below the heading that names where it landed.
  const count =
    shown.length === section.candidates.length
      ? `${section.candidates.length}`
      : `${shown.length} of ${section.candidates.length}`;

  return (
    <div className="group bank-section" id={bankSectionId(section.templateSection)} tabIndex={-1}>
      <h3 className="bank-section-heading">
        <button
          type="button"
          className="row row--header bank-disclosure"
          aria-expanded={open}
          aria-controls={bodyId}
          disabled={!toggleable}
          onClick={onToggle}
        >
          <span className={`bank-caret${open ? ' is-open' : ''}`} aria-hidden="true">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
                 strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" focusable="false">
              <path d="M9 5l7 7-7 7" />
            </svg>
          </span>
          <span className="t-headline bank-section-name">{section.templateSection}</span>
          <span className="t-caption tabular">{count}</span>
        </button>
      </h3>
      {open ? (
        <div id={bodyId}>
          {shown.map((candidate, at) => (
            <CandidateRow
              key={candidate.id}
              candidate={candidate}
              // Only ever the question directly above this one in the list the
              // operator can see. Under a filter there is no such thing —
              // promoting past a hidden neighbour would reorder the bank in a
              // way the screen never showed — so reordering is off instead.
              above={reorderable && at > 0 ? shown[at - 1] : null}
              busy={busy}
              actions={actions}
              run={run}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

/**
 * Where this question came from, in the reviewer's terms.
 *
 * Stated on every row rather than only where there is a document, because
 * silence would be ambiguous exactly where it matters: a row saying nothing
 * about its source reads the same as a row whose source failed to load, and
 * that is the bug this replaced rather than a new way to have it.
 */
function provenanceOf(candidate: BankCandidate): string {
  if (candidate.sourceDoc === null) return 'Reasoned from the engagement';
  const authority = candidate.authorityMatch.join(', ');
  return authority ? `${candidate.sourceDoc} (${authority})` : candidate.sourceDoc;
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
        <span className="t-footnote">
          Priority {candidate.priority} · {provenanceOf(candidate)}
        </span>
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
    renameMeeting: (meetingId, sessionPurpose) =>
      after(renameMeeting(meetingId, sessionPurpose).then(() => undefined)),
    removeMeeting: (meetingId) => after(deleteMeeting(meetingId)),
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
      compileState={prep.compileState}
      compileStages={prep.compileStages}
      compileTone={prep.compileTone}
      meetings={prep.meetings}
      actions={actions}
    />
  );
}
