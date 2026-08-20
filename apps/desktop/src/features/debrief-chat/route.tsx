import { useState } from 'react';

import '../prep/screens.css';
import './debriefChat.css';

import {
  meetingTitle,
  selectionStatus,
  useCurrentEngagement,
  useCurrentMeeting,
} from '../../services/selection';
import { combineStatus } from '../../services/useResource';
import { ScreenEyebrow } from '../../ui/Mark';
import { ScreenState } from '../../ui/ScreenState';
import type { DebriefTurn } from './useDebriefChat';
import { useDebriefChat } from './useDebriefChat';

/**
 * Journey 7, second half — asking about the meeting in your own words (FR-7.3).
 *
 * The fixed artifacts answer the questions somebody anticipated. This screen is
 * for the ones nobody did: "what did they actually say about the March
 * deadline", "draft the follow-up paragraph about integrations". The service
 * has been able to do this for a long time; there was simply nowhere to type.
 *
 * **It is deliberately not the live panel.** The panel is one glanceable
 * question and one-tap answers, because the operator is looking at a client.
 * Here they are at a desk with the meeting behind them, so this is a document:
 * full sentences, the whole thread visible, and no time pressure anywhere in
 * the design.
 */
export interface DebriefChatScreenProps {
  readonly meetingTitle: string;
  readonly turns: readonly DebriefTurn[];
  readonly busy: boolean;
  readonly error: string | null;
  readonly started: boolean;
  readonly onStart?: () => void;
  readonly onAsk?: (question: string) => void;
}

/** Openers that get someone past the blank-page problem. */
const SUGGESTIONS = [
  'What did they say about the March deadline?',
  'Which requirements are still only inferred?',
  'Draft the follow-up paragraph about integrations.',
];

export function DebriefChatScreen({
  meetingTitle,
  turns,
  busy,
  error,
  started,
  onStart,
  onAsk,
}: DebriefChatScreenProps) {
  const [draft, setDraft] = useState('');

  const submit = (question: string) => {
    const trimmed = question.trim();
    if (trimmed.length === 0 || busy) return;
    onAsk?.(trimmed);
    setDraft('');
  };

  return (
    <main className="screen" aria-labelledby="debrief-chat-title">
      <header className="screen-head">
        <ScreenEyebrow>Debrief</ScreenEyebrow>
        <h1 className="t-large-title" id="debrief-chat-title">
          Ask about this meeting
        </h1>
        <p className="t-footnote">{meetingTitle}</p>
      </header>

      {!started ? (
        <section aria-labelledby="open-title">
          <h2 className="t-section" id="open-title">
            Open the conversation
          </h2>
          <p className="t-body">
            Answers are drawn from the transcript and the documents you attached,
            and every one cites the utterance it rests on — so you can check it
            rather than take it on trust.
          </p>
          <button type="button" className="btn btn--filled" onClick={onStart} disabled={busy}>
            {busy ? 'Opening…' : 'Start'}
          </button>
        </section>
      ) : null}

      {turns.length > 0 ? (
        <section aria-labelledby="thread-title">
          <h2 className="t-section" id="thread-title">
            Conversation
          </h2>
          {/* A log, not a live region: the operator is reading at their own
              pace, and announcing every arriving turn would interrupt that. */}
          <ol className="debrief-thread" aria-label="Debrief conversation">
            {turns.map((turn, index) => (
              <li
                className={`debrief-turn debrief-turn--${turn.role}`}
                key={`${turn.role}-${index}`}
              >
                <span className="t-caption debrief-speaker">
                  {turn.role === 'user' ? 'You' : 'Elicta'}
                </span>
                <p className="t-body">{turn.text}</p>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {started ? (
        <section aria-labelledby="ask-title">
          <h2 className="t-section" id="ask-title">
            Your question
          </h2>
          <form
            className="debrief-ask"
            onSubmit={(event) => {
              event.preventDefault();
              submit(draft);
            }}
          >
            <label className="t-footnote" htmlFor="debrief-question">
              Ask anything about what was said
            </label>
            <textarea
              className="debrief-input t-body"
              id="debrief-question"
              rows={3}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="What did they say about the March deadline?"
            />
            <button type="submit" className="btn btn--filled" disabled={busy || draft.trim() === ''}>
              {busy ? 'Thinking…' : 'Ask'}
            </button>
          </form>

          {turns.length === 0 ? (
            <div className="debrief-suggestions">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  type="button"
                  className="btn"
                  key={suggestion}
                  onClick={() => submit(suggestion)}
                  disabled={busy}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {error ? (
        <p className="debrief-error t-footnote" role="alert">
          {error} Nothing was lost — ask again when it is back.
        </p>
      ) : null}
    </main>
  );
}

/**
 * The mounted screen.
 *
 * It used to open a conversation against the literal meeting id `'meeting-1'`
 * under a hardcoded client name — the id the first meeting on a fresh service
 * happens to get, and nothing else. Asking questions about somebody else's
 * meeting is a worse failure than asking about none, so the id now comes from
 * the same selection every other screen reads, and there is no fallback: with
 * no meeting selected the screen says so rather than guessing one.
 */
export default function DebriefChatRoute() {
  const engagement = useCurrentEngagement();
  const meeting = useCurrentMeeting(engagement.engagementId);
  const chat = useDebriefChat(meeting.meetingId ?? '');

  const status = selectionStatus(
    combineStatus(engagement.status, meeting.status),
    meeting.meetingId,
  );

  if (meeting.meetingId === null || (status !== 'ready' && status !== 'missing')) {
    return (
      <ScreenState
        eyebrow="Debrief"
        status={status === 'ready' || status === 'missing' ? 'idle' : status}
        error={engagement.error ?? meeting.error}
        idleHint="No meeting exists yet. There is nothing to ask about until one has been captured."
      />
    );
  }

  return (
    <DebriefChatScreen
      meetingTitle={meetingTitle(engagement.engagement, meeting.meeting)}
      turns={chat.turns}
      busy={chat.busy}
      error={chat.error}
      started={chat.started}
      onStart={() => void chat.start()}
      onAsk={(question) => void chat.ask(question)}
    />
  );
}
