/**
 * One requirements-template section tracked by the live coverage tracker
 * (PRD FR-6.5, FR-6.7). `filled` reflects whether at least one sourced
 * client statement has landed against it; that decision is made by the
 * coverage tracker in the core, this panel only ever renders it.
 */
export interface CoverageSlot {
  readonly id: string;
  readonly label: string;
  readonly filled: boolean;
}

/**
 * The persistent coverage indicator's full state (PRD FR-6.5): every
 * tracked section plus time remaining in the meeting. `timeRemainingMs`
 * travels as a duration rather than a deadline timestamp, so the panel
 * never has to reason about clock skew between the service and the device
 * it renders on -- the second-screen client included.
 */
export interface CoverageSummary {
  readonly slots: readonly CoverageSlot[];
  readonly timeRemainingMs: number | null;
}

/**
 * A nudge as it arrives on the session stream. Defined independently of
 * `panel/nudge`'s `Nudge` type rather than imported, because this feature
 * owns the stream's wire contract, not the nudge domain -- a caller that
 * wants to feed these into the nudge queue converts at the composition
 * root, not here.
 */
export interface SessionStreamNudge {
  readonly id: string;
  readonly stub: string;
  readonly question: string;
  readonly triggerReason: string;
  readonly createdAt: number;
  /**
   * What the operator already did with it, when they have. Carried on the
   * wire so a reconnect — or a restart — does not present a question they
   * have asked as one still waiting.
   */
  readonly disposition?: 'taken' | 'parked' | null;
  /**
   * The template section this nudge belongs to, or `null` when it belongs to
   * none. Resolved by the service from the candidate the nudge was drawn
   * from; a template fallback fires on a phrase and names nothing.
   */
  readonly templateSection?: string | null;
}

/**
 * One finalised utterance as it arrives on the session stream.
 *
 * The panel could show a question and never the sentence that provoked it.
 * Since most of a meeting earns no question at all (FR-5.7), a quiet panel
 * meant both "nothing worth asking" and "nothing heard", and an operator had
 * no way to tell those apart while a client was talking.
 */
export interface SessionStreamUtterance {
  /**
   * Its place in the meeting's transcript, assigned by the service.
   *
   * The panel's identity for the line, and the only thing it can dedupe on:
   * the stream replays the whole meeting on every connect, and two people can
   * say the same short sentence an hour apart, so nothing in the text tells a
   * replay from a repetition.
   */
  readonly seq: number;
  readonly text: string;
  /**
   * Whoever the voiceprint verifier believed said it, or `null` when the
   * question could not be answered — which is every deployment where nobody
   * has enrolled (FR-1.6). Kept as absence: a line attributed to the wrong
   * person is worse than one attributed to nobody.
   */
  readonly speaker: string | null;
  /** Milliseconds since the epoch, matching a nudge's `createdAt`. */
  readonly at: number | null;
  /**
   * Whether the speaker has finished this line.
   *
   * A streaming recogniser sends the words so far while somebody is still
   * talking, and the same `seq` arrives again, longer, until they stop. That
   * is what lets the transcript keep up with the room instead of printing
   * each sentence whole a second after it ended.
   *
   * Marked rather than merged silently, because the difference matters on
   * screen: an unfinished line may still change, and showing it as settled
   * would be quoting somebody on words they have not said yet. Nothing
   * downstream reasons about one — the gate only ever sees finished lines.
   */
  readonly final: boolean;
}

/**
 * The event shapes carried on `GET /api/meetings/{id}/session/stream`
 * (architecture §7: "desktop captures; phone renders nudges", carried over
 * a service-tier sync channel to the second screen).
 */
export type SessionStreamEvent =
  | { readonly type: 'lane'; readonly lane: SessionStreamLane }
  | { readonly type: 'coverage'; readonly coverage: CoverageSummary }
  | { readonly type: 'nudge'; readonly nudge: SessionStreamNudge }
  // One line of the meeting, whether or not it earned a nudge.
  | { readonly type: 'utterance'; readonly utterance: SessionStreamUtterance }
  // The languages this room is expected to use (FR-2.14), sent before
  // anything is transcribed. `expected` is what keeps the strip from
  // reporting a derivation as a detection.
  | { readonly type: 'language'; readonly language: string; readonly expected: boolean };

/**
 * Confirmation that `POST /api/meetings/{id}/session/stop` closed the session.
 *
 * `stoppedAt` travels as the ISO timestamp the service assigned when it closed
 * the session, mirroring how `session/start` hands back `started_at` -- the
 * panel does not stamp its own clock for either edge.
 *
 * `sessionId` is `null` when the service had nothing open to close. That is a
 * success: the operator asked for the recording to be over and it is over.
 * The two are kept apart rather than smoothed together because they say
 * different things about what this call did.
 *
 * This type described a flush of the panel's final coverage summary for as
 * long as the endpoint it describes did not exist. Coverage is derived in the
 * service now, from the meeting's own nudge dispositions, so that there is one
 * answer in one place -- the panel counting it here is the arrangement that
 * once read eight of eight sections covered on evidence of nothing.
 */
export interface SessionStopResult {
  readonly sessionId: string | null;
  readonly meetingId: string;
  readonly stoppedAt: string;
}

/**
 * Whether the slow lane can currently reach a model (architecture §10).
 *
 * Carried on the session stream rather than polled, because the connection
 * that would tell the panel the answer is the same one that goes quiet when
 * the answer is "no" — a poll would have to guess at a timeout, and guess
 * differently from whatever the service already knows.
 */
export interface SessionStreamLane {
  readonly modelReachable: boolean;
  /** Plain-language cause, shown to the operator when degraded. */
  readonly reason: string | null;
  /**
   * Whether a chunk of audio would actually be transcribed — a different
   * question from `modelReachable`, with a different remedy.
   *
   * The slow lane needs a model; the live lane needs a speech credential, and
   * a deployment can have either without the other. Carried because the
   * panel's transcript region cannot otherwise tell a quiet room from a
   * stopped microphone from a deployment that never bought speech: all three
   * render as no lines, and only the third is something the operator can go
   * and fix.
   */
  readonly liveTranscription: boolean;
  /**
   * Which recogniser is listening, as its wire name, or `null` where the
   * service is driven by an injected one.
   *
   * On screen because the setting is read per window: an operator who has
   * just changed the model — which they do *because* the transcript is poor,
   * mid-meeting — has no other evidence that the change took. It is also the
   * one place the local/vendor distinction becomes visible in the room, which
   * is a thing some engagements need to be able to see.
   */
  readonly liveModel: string | null;
  /**
   * Why nothing said here will be written down, or `null` when it will.
   *
   * Carried rather than derived, because there are two ways to be unready and
   * they have opposite remedies — a vendor model wants a key, a local model
   * wants the address of a server the operator is running. The panel had one
   * hardcoded sentence for both and told an operator running Parakeet on
   * their own machine to go and configure a credential.
   */
  readonly liveTranscriptionReason: string | null;
  /**
   * Why no line can be attributed to a speaker, or `null` when they can.
   *
   * With nothing enrolled, verification answers "cannot tell" for every
   * window — correctly, and by design. What was not correct was the screen:
   * every row read "Unattributed" with nothing anywhere saying why or what
   * would change it, which is a transcript that looks broken rather than one
   * being careful.
   */
  readonly speakerAttributionReason: string | null;
  /**
   * Whether audio is arriving right now — a different question again from
   * `liveTranscription`, which only says a credential exists.
   *
   * A credential is not a microphone. Before Capture is pressed the panel has
   * a configured recogniser and no audio, and reporting that as "Transcribing"
   * asserts the room is being written down when nothing is being captured at
   * all. Audio arriving is the only evidence that separates a meeting being
   * recorded from one opened and walked away from.
   */
  readonly receivingAudio: boolean;
  /**
   * When this run of capture began, in milliseconds since the epoch, or
   * `null` when nothing is being captured.
   *
   * The recording's clock, not the meeting's: a session is opened and never
   * ended, so counting from its start would keep running through a meeting
   * nobody is recording — the same lie as a "Transcribing" label with no
   * audio behind it, told in numbers.
   */
  readonly capturingSince: number | null;
}
