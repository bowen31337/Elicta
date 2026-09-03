import { useEffect, useState } from 'react';

import './route.css';
import {
  AskedItChip,
  EscapeHatchInput,
  GoDeeperChip,
  ParkItChip,
  WhatAmIMissingChip,
} from './chips';
import type { CoverageSummary, SessionStreamUtterance } from './coverage';
import { CoverageIndicator, useSessionStream, useStopSession } from './coverage';
import type { DetectedLanguage } from './language';
import { LanguageChrome } from './language';
import type { Nudge } from './nudge';
import { QuestionPanel, TranscriptPanel } from './feed';
import { CaptureBar } from './capture';
import { useCapture } from '../capture/useCapture';
import type { BankQuestion } from './bank';
import { BankRail, upcoming, useMeetingBank } from './bank';
import { recordNudgeDisposition } from '../../services/nudgeDisposition';
import { stubFor } from '../../services/questionStub';
import { useCurrentEngagement, useCurrentMeeting } from '../../services/selection';

/**
 * The operator panel — the one screen this product shows during a meeting.
 *
 * Everything here is shaped by a single constraint: the operator is looking at
 * a client, not at this. So the panel is a floating material rather than a
 * page, the nudge is the only thing set at reading size, and every response is
 * one tap. The chrome (coverage, time, language, connection) is deliberately
 * quiet — it is state to glance at, not to read.
 *
 * On a touch screen that constraint gets stronger rather than different: the
 * panel stops being a card floating over something and becomes the screen,
 * with the chrome pinned at the top, the nudge in the middle at reading size,
 * and every control docked at the foot of the display where a thumb already
 * is. The layout adapts; what the screen *is* does not. `route.css` holds the
 * whole of that behind `(pointer: coarse)` — deliberately the pointer and not
 * a width, since a narrow desk window is still driven by a cursor.
 */
export interface PanelState {
  readonly active: Nudge | null;
  readonly history: readonly Nudge[];
  readonly coverage: CoverageSummary | null;
  readonly languages: readonly DetectedLanguage[];
  /** False when the slow lane cannot reach a model (architecture §10). */
  readonly modelReachable?: boolean;
  /**
   * Which of the four problems the lane met — an outage, a throttle, a
   * refused credential or a plan that does not cover the model. They do not
   * share a remedy, so the panel says which rather than collapsing them.
   */
  readonly degradedReason?: string | null;
  readonly meetingId?: string;
  readonly operatorLanguage?: string;
  readonly activeTier?: 'tier-1' | 'tier-2' | 'tier-3' | null;
  /**
   * The meeting so far, for a fixed scene. Live, this comes off the stream.
   *
   * Supplied the same way `coverage` and `languages` are, and for the same
   * reason: the journey screenshots and the accessibility audit render this
   * panel from props with no service behind them, so a region that could only
   * be filled by a live stream would be photographed and audited empty for
   * ever — which is the one state whose colours do not need checking.
   */
  readonly transcript?: readonly SessionStreamUtterance[];
  /** The meeting's bank, for a fixed scene. Live, this is fetched. */
  readonly bankQuestions?: readonly BankQuestion[];
  /**
   * How long capture has been running, in milliseconds, for a fixed scene.
   *
   * A duration rather than an instant, and that is not a detail: a scene is a
   * frozen fixture, so an absolute timestamp in it is measured against a real
   * clock that moves further from it every day. Set as an instant, the
   * recording bar in the journey screenshots read `9098:09:34` — the fixture's
   * age, not a meeting's length.
   */
  readonly capturingForMs?: number;
  /**
   * Whether anything said will be transcribed, for a fixed scene. Live, this
   * comes off the stream's lane frame. Defaults to transcribing, so every
   * other scene renders unchanged.
   */
  readonly liveTranscription?: boolean;
  /** Which recogniser is listening, for a fixed scene. */
  readonly liveModel?: string | null;
  /** Why nothing will be transcribed, for a fixed scene. */
  readonly liveTranscriptionReason?: string | null;
  /**
   * Recent input levels, for a fixed scene. Live, these come off the local
   * capture store.
   *
   * A scene supplies them for the reason it supplies the transcript and the
   * coverage: the journey screenshots and the accessibility audit render this
   * panel from props with no device anywhere near them, so a region that
   * could only be filled by an open microphone would be photographed and
   * audited empty for ever — and the recording bar's controls are the newest
   * colours on the panel.
   */
  readonly waveform?: readonly number[];
  /** Whether that scene's recording is being held. */
  readonly paused?: boolean;
}

const EMPTY: PanelState = {
  active: null,
  history: [],
  coverage: null,
  languages: [],
  modelReachable: true,
};

function SlotMeter({ summary }: { summary: CoverageSummary | null }) {
  // The segments are a graphic beside CoverageIndicator's own count, not a
  // replacement for it: the count is the accessible reading, the segments are
  // what an operator takes in without reading.
  if (!summary) return null;
  return (
    <div className="meter-track" aria-hidden="true">
      {summary.slots.map((slot) => (
        <span key={slot.id} className={slot.filled ? 'meter-seg is-filled' : 'meter-seg'} />
      ))}
    </div>
  );
}

export function OperatorPanel({
  initial = EMPTY,
  createSource,
  captureStore,
}: {
  initial?: PanelState;
  /** Overridable so a test can drive the stream without a network. */
  createSource?: Parameters<typeof useSessionStream>[1] extends
    | { createSource?: infer F }
    | undefined
    ? F
    : never;
  /**
   * The microphone, injectable for the same reason the stream is.
   *
   * It was not, and that is why nothing here could be tested: the panel
   * reached for the module singleton, so a test could not put it in the one
   * state that mattered — a recording running that this screen had not
   * noticed — which is precisely the state an operator hit.
   */
  captureStore?: Parameters<typeof useCapture>[0];
}) {
  const [state, setState] = useState<PanelState>(initial);
  /**
   * Which bank questions this meeting has finished with.
   *
   * Held on the panel rather than read back off the service, because the rail
   * has to change in the same render pass as the tap. `Asked it` already
   * reports the disposition and deliberately does not wait for the round trip
   * (FR-6.6: the confirmation is the card receding), so a rail that waited for
   * the service to agree would leave a question the operator has just asked
   * sitting there for as long as the network took.
   */
  const [dealtWith, setDealtWith] = useState<ReadonlySet<string>>(() => new Set());
  // The live session drives the panel when there is one. Coverage arrives as
  // the current summary rather than a diff, and each nudge replaces the
  // active one — the previous nudge recedes into history rather than being
  // dropped, so the operator can still see what they just declined.
  const {
    coverage,
    languages: streamLanguages,
    transcript,
    liveTranscription,
    liveModel,
    liveTranscriptionReason,
    receivingAudio,
    capturingSince,
    modelReachable,
    degradedReason,
  } = useSessionStream(state.meetingId ?? null, {
    createSource,
    onNudge: (nudge) =>
      setState((current) => {
        // Already seen. The stream replays its whole backlog on every
        // connect — that is how a panel opened mid-meeting catches up — and
        // `EventSource` reconnects on its own schedule every few minutes.
        // Nothing deduped, so each reconnection appended the meeting's
        // entire history to itself: an operator who had seen three nudges
        // found six, then nine, all of them real and none of them new.
        if (current.active?.id === nudge.id) return current;
        if (current.history.some((held) => held.id === nudge.id)) return current;
        // Already dealt with, so it arrives behind whatever is live rather
        // than in front of it. The backlog replays in full on every connect
        // and after every restart, and a question the operator asked an hour
        // ago handed back as the live card is one they will ask twice —
        // several nudges on one trigger carry near-identical wording, so
        // there is nothing else to tell them apart by.
        if (nudge.disposition) {
          return { ...current, history: [...current.history, nudge] };
        }
        return {
          ...current,
          active: nudge,
          history: current.active ? [current.active, ...current.history] : current.history,
        };
      }),
  });

  /**
   * Ending the meeting, from the panel.
   *
   * `useStopSession` releases the microphone and then closes the session, in
   * that order, which is why the stop lives here rather than inside the bar:
   * the bar knows what the microphone is doing, this knows the meeting it
   * belongs to.
   *
   * Given the empty string when no meeting is selected — the hook is a hook
   * and cannot be called conditionally, and nothing can press the button in
   * that state anyway, because the bar is only handed one when there is a
   * meeting to stop.
   */
  const { status: stopStatus, stop } = useStopSession(state.meetingId ?? '');

  /**
   * The microphone, where it is this window holding it.
   *
   * `services/captureSession` is one store per bundle, so when the operator
   * pressed Capture in this app the panel is already holding the same levels
   * and the same paused-aware clock the Capture screen draws — which is why
   * the bar can show a real waveform rather than none. Where the panel is a
   * genuine second screen the store is simply idle, `waveform` is empty and
   * the bar draws no wave at all: absence, not a flat line.
   */
  const microphone = useCapture(captureStore);
  const holdingTheDevice =
    microphone.status.state === 'capturing' || microphone.status.state === 'paused';

  const onStopCapture = () => {
    // Fire and forget, like every other control on this panel: the operator's
    // confirmation is the bar changing state, not the round trip. What is
    // *not* fire and forget any more is the failure — see `stopFailed` on the
    // bar. This press did nothing at all for as long as the route it posts to
    // did not exist, and the panel had nowhere to say so.
    void stop();
  };

  // What the room has said, from the stream when there is a meeting and from
  // the prop when a fixed scene is standing in for one — the same rule the
  // coverage and the languages above already follow.
  const heard = state.meetingId ? transcript : (state.transcript ?? []);

  /**
   * Two accounts of one microphone, reconciled rather than left to disagree.
   *
   * The panel has the service's word — audio is arriving, from chunks it has
   * actually received — and the local capture store's, which in the desktop
   * shell is a *snapshot* taken when this screen mounted. The store only
   * re-reads the shell's session on mount, so a screen that mounted before
   * the recording started, or whose read raced it, stays wrong for the rest
   * of the meeting. Nothing about that is visible: the panel shows
   * "Listening…" from the service's account while the store believes it holds
   * nothing, so the wave draws empty and the Pause button — which is only
   * offered where there is something local to pause — is simply not there.
   * That is what an operator reported, and there is no state on screen that
   * explains it.
   *
   * So the disagreement is the trigger. When the service says audio is
   * arriving and the store says nothing is open, ask the shell again; it owns
   * the session and can settle it. Only in that direction, and only while the
   * disagreement lasts: the store believing it holds a device the service has
   * heard nothing from is an ordinary few seconds at the start of a
   * recording, not a contradiction.
   */
  // Not after a stop this screen made: the service's account lags by the
  // freshness window, and re-asking the shell about a session we have just
  // closed is asking a settled question.
  const outOfStep = receivingAudio && !holdingTheDevice && stopStatus !== 'stopped';
  // `microphone.refresh`, never `microphone`: the hook returns a fresh object
  // every render, so depending on it would tear down and rebuild the interval
  // on each one — a timer that never fires, which is the same nothing this
  // effect exists to fix.
  const { refresh: refreshMicrophone } = microphone;
  useEffect(() => {
    if (!outOfStep) return;
    void refreshMicrophone();
    // Re-asked on an interval rather than once, because the first answer can
    // be "idle" legitimately — the shell's session is opened a moment after
    // the first chunk is uploaded — and one attempt would then settle on the
    // wrong answer for the rest of the meeting. Four seconds is the
    // transcription window; nothing here changes faster than that.
    const timer = window.setInterval(() => void refreshMicrophone(), 4000);
    return () => window.clearInterval(timer);
  }, [outOfStep, refreshMicrophone]);

  // The meeting's own recompile, not the engagement's compile: it puts the
  // questions the last meeting left open ahead of everything else, which is
  // the ranking an operator wants at the top of a rail (FR-4.8).
  const bank = useMeetingBank(state.meetingId ?? null);

  /**
   * Ask a question the operator chose off the rail.
   *
   * It becomes the active nudge rather than being asked in place, so
   * everything already built around a live question works on it unchanged —
   * `Asked it` ticks its section, `Park it` files it into the next meeting's
   * bank, `Go deeper` follows the thread. FR-6.3 constrains prominence to one
   * question at a time; this changes which one, not how many.
   *
   * The same shape the typed escape hatch produces, and for the same reason:
   * one kind of live question on this panel, with one set of controls, rather
   * than a second machinery per source.
   */
  const onAskFromBank = (question: BankQuestion) => {
    setDealtWith((current) => new Set(current).add(question.id));
    setState((current) => ({
      ...current,
      active: {
        id: `bank-${question.id}`,
        stub: stubFor(question),
        question: question.phrasing,
        // The reason line says why this is on screen, and the honest answer
        // is that the operator picked it — not that anything was heard. A
        // trigger reason invented here would be the panel claiming the gate
        // fired when it did not, which is the one thing FR-5.11's reason line
        // exists to make impossible.
        triggerReason: question.inherited
          ? 'from the bank — carried forward from your last meeting'
          : 'from the bank — chosen by you',
        createdAt: Date.now(),
        templateSection: question.templateSection,
      },
      history: current.active ? [current.active, ...current.history] : current.history,
    }));
  };

  /**
   * Mark the live nudge asked.
   *
   * The meter is deliberately not touched here. It used to be: the tap wrote
   * the slot into `localStorage` and the panel merged that over the stream's
   * coverage, so the count was a record of taps wearing the clothes of a
   * measurement. Worse, the slot it wrote was whichever one happened to be
   * first unfilled — unrelated to the nudge — so eight questions about "a
   * lot" and "some" reported eight of eight covered.
   *
   * The disposition goes to the service, which owns what a section being
   * asked about means and says so on the next coverage frame. One answer, in
   * one place, that a restart and a second screen both see.
   */
  const onAsked = () => {
    // Fire-and-forget: the operator's confirmation is the card receding in
    // the same render pass (FR-6.6), not this round trip. A dropped sync must
    // never hold up a panel mid-meeting.
    if (state.meetingId && state.active) {
      void recordNudgeDisposition({
        meetingId: state.meetingId,
        nudgeId: state.active.id,
        disposition: 'taken',
      });
    }
    retireActive('taken');
  };

  /**
   * Put the active nudge down, into history.
   *
   * Both chips that deal with a question end here. Parking says "not now"
   * and asking says "done"; either way the operator has finished with it,
   * and the panel went on showing it — with the next nudge up to a minute
   * away, that left a card sitting there already dealt with and nothing to
   * press to move past it.
   *
   * Into history rather than gone. That was not safe until history became
   * reachable: putting a nudge down used to lose it for good. It is one
   * press away now, which is what makes retiring it the right behaviour
   * rather than a trade.
   */
  const retireActive = (disposition: 'taken' | 'parked') => {
    setState((current) =>
      current.active === null
        ? current
        : {
            ...current,
            active: null,
            // Marked here as well as recorded on the service. The stream
            // carries the disposition, but only on the next connect — and
            // the row has to change the moment it is pressed, or the
            // operator sees no difference between a question they have just
            // asked and one still waiting.
            history: [{ ...current.active, disposition }, ...current.history],
          },
    );
  };

  /**
   * Bring a nudge that has receded back to the front.
   *
   * A swap, not a reordering: the one being brought back leaves history and
   * the one it displaces takes the front of it, so nothing is lost and the
   * one just put down is a single press away. Exactly one stays prominent,
   * which is what FR-6.3 asks — it constrains prominence, not which nudge
   * the operator is allowed to be looking at.
   *
   * Without this every chip acted on whatever arrived last, and a nudge
   * became unactionable the moment the next one landed. With one arriving
   * as often as a minute apart, that is most of a meeting's worth.
   */
  const onSelectNudge = (nudge: Nudge) => {
    setState((current) => {
      // Already here. Nothing to do, and swapping it with itself would drop
      // it into its own history.
      if (current.active?.id === nudge.id) return current;
      return {
        ...current,
        active: nudge,
        // Nothing to demote when nothing is active — which is the state
        // parking leaves, and the state an operator is in when they reach
        // for a question they put down. A guard that returned early here
        // made the button do nothing at exactly the moment it is for.
        history: [
          ...(current.active === null ? [] : [current.active]),
          ...current.history.filter((held) => held.id !== nudge.id),
        ],
      };
    });
  };

  const onParked = () => {
    if (state.meetingId && state.active) {
      void recordNudgeDisposition({
        meetingId: state.meetingId,
        nudgeId: state.active.id,
        disposition: 'parked',
      });
    }
    retireActive('parked');
  };

  /**
   * A question the operator typed rather than one the gate surfaced.
   *
   * It becomes the active nudge, because that is what they meant by typing
   * it: they intend to ask it, and every chip acts on the active nudge. So
   * the escape hatch produces a question the rest of the panel already knows
   * how to handle — parking files it into the next meeting's bank, asking it
   * ticks a section — rather than needing a second machinery of its own.
   *
   * It said nothing before. The handler was a no-op and the field cleared on
   * Enter, which is the gesture that means "sent" — so it signalled success
   * for work that never happened.
   *
   * Deliberately no model call: typing already costs an order of magnitude
   * more attention than a tap (FR-6.6's rationale), and a wait on top of
   * that is what the chips exist to avoid.
   */
  const onTypedQuestion = (query: { text: string; submittedAt: number }) => {
    setState((current) => ({
      ...current,
      active: {
        id: `typed-${query.submittedAt}`,
        stub: 'Your question',
        question: query.text,
        // The reason line says why this is on screen, and "you typed it" is
        // as true an answer as "somebody said several".
        triggerReason: 'typed by you',
        createdAt: query.submittedAt,
      },
      history: current.active ? [current.active, ...current.history] : current.history,
    }));
  };

  /**
   * What the meter shows: the stream's slots, with the operator's ticks on
   * top.
   *
   * These are two different facts and were one piece of state. The stream
   * knows which sections *exist* — it derives them from the meeting's bank —
   * and re-sends every one of them unfilled on each connect, because nothing
   * server-side marks a section covered. Which are covered is the operator's,
   * recorded when they tap `Asked it`.
   *
   * Read as `coverage ?? state.coverage`, the stream's copy won whenever
   * there was one, so in a live meeting the tick was invisible and the meter
   * sat at 0 of however many for the whole meeting. Merged, it moves and it
   * survives the reconnection that used to wipe it.
   */
  // Whatever the service last said, unedited. The panel used to merge the
  // operator's own taps in over the top; see `onAsked`.
  const liveCoverage = coverage ?? state.coverage;
  // The live stream wins over the initial prop once a meeting is running:
  // the prop is what the panel was handed at mount, the stream is what the
  // service knows now. Without a meeting there is no stream, so the prop is
  // all there is — which is also how the fixed journey scenes stay renderable.
  const degraded = state.meetingId ? !modelReachable : state.modelReachable === false;
  // Same rule as the languages above: the stream is what the service knows
  // now, the prop is what the panel was handed at mount and is all a fixed
  // scene has.
  const reason = (state.meetingId ? degradedReason : state.degradedReason) ?? null;

  return (
    <main className="panel" aria-label="Elicitation panel">
      <header className="panel-chrome glass">
        <div className="meter">
          <SlotMeter summary={liveCoverage} />
          <CoverageIndicator summary={liveCoverage} />
        </div>
        <div className="chrome-right">
          {/* The stream wins when it has said anything: `state.languages` is
              the fixed prop the screenshot harness renders from, and a live
              meeting should show what the service actually sent. */}
          <LanguageChrome
            languages={streamLanguages.length > 0 ? streamLanguages : state.languages}
            activeTier={state.activeTier ?? null}
          />
          {degraded ? (
            <span className="pill pill--warn" role="status">
              Deterministic only
            </span>
          ) : null}
        </div>
      </header>

      {degraded ? (
        <p className="degraded-note t-footnote" role="status">
          {reason ?? 'The model is unreachable.'} Wording and coverage
          triggers still fire; the slow lane is paused and will catch up.
        </p>
      ) : null}

      {/* One region, and that is the point. The proposed question renders
          inside the conversation, under the line it reacted to — which is
          what makes it judgeable, and what makes a question reacting to the
          operator's own sentence visible instead of hidden. */}
      {/* Two panels, because they scale differently. The transcript runs to
          hundreds of lines and needs its own scroll; the question is one
          thing at a time and must never be pushed off the screen by a client
          who is still talking. What the separation would otherwise cost — the
          reason a suggestion is worth trusting — is carried by the question
          quoting the line it reacted to. */}
      {/* `panel-split` is the grid, and it has to be a *descendant* of the
          element carrying `container-type` — a container cannot query itself,
          which is why styling `.panel` inside its own `@container` block did
          nothing at all. Below the threshold it is `display: contents`, so
          these four stay direct flex children of `.panel` and every rule
          already written for them keeps applying, the coarse-pointer layout
          included. */}
      <div className="panel-split">
      {/* Focusable because it scrolls on a touch screen and can hold nothing
          that takes focus — a live question with no earlier ones under it is
          exactly that, and it is the ordinary state. Without this a keyboard
          user can reach every control on the panel and not the question
          itself. Caught by the audit as `scrollable-region-focusable`. */}
      <section
        className="nudge materialize"
        tabIndex={0}
        aria-label="The question to ask"
      >
        <QuestionPanel
          active={state.active}
          history={[...state.history]}
          transcript={heard}
          operatorLanguage={state.operatorLanguage}
          onSelect={onSelectNudge}
        />
      </section>

      {/* The recording, on the screen the operator is already on. In the
          transcript's column rather than the question's: it is about the
          conversation being captured, and the question column is already the
          busiest half of this panel. */}
      <div className="panel-record">
      <TranscriptPanel
        transcript={heard}
        transcribing={
          state.meetingId ? liveTranscription : (state.liveTranscription ?? true)
        }
        // Only a live meeting can report a microphone. A fixed scene has no
        // stream, and a scene that carries lines was plainly being captured
        // when they were said — inferring it from the prop keeps every
        // screenshot honest without a second flag to set.
        receivingAudio={
          state.meetingId ? receivingAudio : (state.transcript ?? []).length > 0
        }
        model={state.meetingId ? liveModel : (state.liveModel ?? null)}
        blockedBecause={
          state.meetingId ? liveTranscriptionReason : (state.liveTranscriptionReason ?? null)
        }
      />

      <CaptureBar
        // The local device wins where there is one: the service's
        // `receiving_audio` is derived from when a chunk last arrived, which
        // lags a pause by the freshness window and would leave the bar
        // claiming to listen for seconds after the operator held it.
        // A stop that has come back is the end of it, whatever the service
        // still says. `receiving_audio` is derived from when a chunk last
        // arrived and stays true for the freshness window after the last one
        // — so for several seconds after a stop that worked, the bar went on
        // reading "Listening…" with the clock running, which is
        // indistinguishable from a Stop that did nothing. This screen knows
        // better than the derivation does: it released the device itself.
        capturing={
          stopStatus === 'stopped'
            ? false
            : holdingTheDevice
              ? true
              : state.meetingId
                ? receivingAudio
                : (state.transcript ?? []).length > 0
        }
        since={
          state.meetingId
            ? capturingSince
            : state.capturingForMs === undefined
              ? null
              : Date.now() - state.capturingForMs
        }
        // Paused time is not recorded time, and only the local store knows
        // the difference. Absent where the capture is somebody else's, and
        // the bar falls back to the wall clock from `since`.
        elapsedSeconds={holdingTheDevice ? microphone.elapsedSeconds : null}
        waveform={state.waveform ?? microphone.waveform}
        paused={state.paused ?? microphone.status.state === 'paused'}
        // Only where something can actually be held: this window holding the
        // device, or a fixed scene standing in for one. A Pause button that
        // cannot reach a microphone is the Stop button's old bug waiting to
        // be written again.
        onPause={
          holdingTheDevice
            ? () => void microphone.pause()
            : state.waveform === undefined
              ? undefined
              : () => {}
        }
        onResume={
          holdingTheDevice
            ? () => void microphone.resume()
            : state.waveform === undefined
              ? undefined
              : () => {}
        }
        transcribing={
          state.meetingId ? liveTranscription : (state.liveTranscription ?? true)
        }
        // Only a live meeting can be stopped. A fixed scene gets the bar
        // without the button rather than a button that does nothing.
        onStop={
          state.meetingId ? onStopCapture : state.waveform === undefined ? undefined : () => {}
        }
        stopping={stopStatus === 'pending'}
        stopFailed={stopStatus === 'error'}
      />
      </div>

      {/* The two supporting regions, between the live question and the
          controls. Both are deliberately quieter than the nudge above them:
          the nudge is the only thing on this screen set at reading size,
          because the operator is looking at a client rather than at this.

          The rail comes first because it is actionable and the transcript is
          reference — a thumb travelling up from the dock reaches the thing it
          can press before the thing it can only read. */}
      <BankRail
        questions={upcoming(
          // Same rule as the languages and the coverage above: the stream — or
          // here the fetch — is what the service knows now, and the prop is
          // what the panel was handed at mount, which is all a fixed scene has.
          state.meetingId ? bank.questions : (state.bankQuestions ?? []),
          { asked: dealtWith },
        )}
        onAsk={onAskFromBank}
      />


      {/* Everything the operator can do, in one region. On a touch screen it
          docks to the foot of the display as a single material (route.css),
          which is the only part of this panel a thumb can reach without the
          hand leaving the device. Source order matters and is not arbitrary:
          the four chips are laid out two to a row in named grid cells, and
          read row by row that is exactly this order — so the reading order and
          the visual order never come apart. */}
      <footer className="panel-dock">
        <div className="panel-chips">
          {/* Gated on the nudge as well as the slot. Bound to the slot
              alone it rendered permanently, whether anything had been
              suggested or not — so it sat beside "No active nudge" saying
              "Asked it" about nothing, and stayed after the question it
              referred to had been dealt with. FR-6.7 settles which it is:
              it suppresses re-suggestion, and there is nothing to
              re-suggest without a question that was suggested. */}
          {/* Gated on the live nudge alone. It used to be gated on there
              being an unfilled section left as well, which made it remove
              itself the moment the operator had marked them all — and with
              no chip there was no way to record another disposition, so
              nothing was ever marked "Asked" again. The chip is about the
              nudge; the meter is the service's business. */}
          {state.active ? (
            <AskedItChip section={state.active.templateSection ?? null} onAsked={onAsked} />
          ) : null}
          {state.active ? (
            <ParkItChip
              thread={{
                id: state.active.id,
                question: state.active.question,
                operatorAskedAt: null,
              }}
              onParked={onParked}
            />
          ) : null}
          {liveCoverage ? <WhatAmIMissingChip summary={liveCoverage} /> : null}
          {state.active ? (
            <GoDeeperChip
              thread={{
                id: state.active.id,
                question: state.active.question,
                operatorAskedAt: null,
              }}
            />
          ) : null}
        </div>

        {/* FR-6.9: present, but deliberately the quietest thing here — it is an
            escape hatch, not the primary way to work. It stays last so the
            keyboard reaches it in source order after the chips, which are the
            primary input, and because the foot of the dock is where a thumb
            expects a field it has decided to type in. */}
        <EscapeHatchInput onSubmit={onTypedQuestion} />
      </footer>
      </div>
    </main>
  );
}

/**
 * The mounted panel, over the service.
 *
 * This was the last of the six screens that shipped bound to nothing. It
 * rendered `<OperatorPanel />` with no props at all, so `meetingId` was
 * `undefined`, `useSessionStream` took its `meetingId === null` early return,
 * and the panel never opened a stream for any meeting. Everything downstream
 * followed from that one omission: coverage stayed at its "— / —" placeholder,
 * no nudge ever arrived, all four one-tap responses stayed unrendered because
 * each is gated on coverage or an active nudge, and `recordNudgeDisposition`
 * never fired because it is guarded on `state.meetingId`. A live run recorded
 * the result on a meeting whose session was running.
 *
 * The meeting comes from the same selection the toolbar picker writes, which
 * is where every other screen reads it.
 */
export default function PanelRoute() {
  const engagement = useCurrentEngagement();
  const meeting = useCurrentMeeting(engagement.engagementId);
  const meetingId = meeting.meetingId ?? undefined;

  // Keyed on the meeting for two reasons. `initial` is read once by
  // `useState`, so a meeting id that resolves after the first render would
  // otherwise never reach the stream. And the active nudge and its history
  // belong to the meeting they were raised in — carrying them across a
  // change of meeting would put one client's question on another's panel.
  return <OperatorPanel key={meetingId ?? 'no-meeting'} initial={{ ...EMPTY, meetingId }} />;
}
