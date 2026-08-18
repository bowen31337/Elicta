# PRD — Live Requirements Elicitation Assistant

**Status:** Draft for review
**Owner:** [PM]
**Last updated:** 18 August 2026
**Reviewers required:** Infosec, Legal/Contracts, IT Endpoint, Delivery Lead

---

## 1. Problem

Client requirements meetings are the highest-leverage and least-supported moment in our delivery process. The quality of a PRD is set in the room, by whether the right follow-up question got asked in the five seconds after a client said something vague. Miss it and the ambiguity survives into the build, where it surfaces as a change request at 10–50x the cost.

The failure is not a knowledge failure. It is an attention failure. A person running a client meeting is simultaneously listening, maintaining rapport, managing time, taking notes, and tracking coverage against a requirements template. Under that load, "they said *fast* and I never got a number" is the normal outcome, not the exceptional one.

Existing meeting AI (Otter, Fireflies, Teams Copilot, Zoom AI Companion) solves the *recording* problem, which is not our problem. None of them track coverage against a requirements template, none of them detect ambiguity in the moment, and none of them produce structured requirements artifacts. They produce a transcript and a summary — after the meeting, when the client has already left.

## 2. Goals

| # | Goal |
|---|---|
| G1 | Surface, during the meeting, the follow-up question the operator would have wished they asked |
| G2 | Maintain live coverage state against a requirements template so nothing is silently skipped |
| G3 | Produce reviewable BMAD planning artifacts from the meeting, with every claim traceable to a timestamped utterance |
| G4 | Carry requirements state across a multi-meeting arc, not just within one session |
| G5 | Keep client audio and transcripts confined to named processors under contract, with vendor retention disabled and every egress path audited (NFR-2) |

## 3. Non-goals

- **Not a transcription product.** Transcription is commodity input, not a differentiator. We buy or self-host it.
- **Not a note-taker.** Notes are a by-product.
- **Not an autonomous agent.** It never speaks to the client, never joins as a participant that talks, never sends anything on the operator's behalf without review.
- **Not a scheduling tool.** Calendar integration is out of scope; the follow-up email draft covers the loop-closing need.
- **Not a general-purpose chat assistant during the meeting.** See FR-6.1 on length caps.

## 4. Users

**Primary — the operator.** The person running the client requirements meeting. Runs the app on a second machine, glances at it, taps it, and uses it heavily after the meeting.

**Secondary — the reviewer.** Delivery lead or architect who receives the artifacts and needs to see what the client actually said versus what the system inferred.

> **OPEN DECISION D1 — this shapes the product and is not yet resolved.** Is the primary user an experienced PM/BA, or a junior one being levelled up?
> - *Experienced:* they already know what to ask. Live value is mostly coverage tracking and contradiction detection; the bulk of value is prep and synthesis. Build phases 0–2, possibly stop.
> - *Junior:* live question generation earns its keep, but credibility risk rises sharply and phase 3 becomes mandatory.
>
> **This decision must be made before phase 2 scoping.**

## 5. Success metrics

| Metric | Target | Measured |
|---|---|---|
| M1 — Precision@surfaced | ≥70% of surfaced nudges rated *useful* by a senior BA | Replay harness + post-meeting rating |
| M2 — Embarrassment rate | **0** nudges rated *would have embarrassed me in front of the client* | Same |
| M3 — Template coverage | ≥80% of applicable template sections have ≥1 sourced client statement after meeting 1 | Automated from artifact |
| M4 — Ambiguity capture | ≥60% of unquantified requirements resolved in-meeting rather than by follow-up email | Compare open-questions list at meeting end vs. trigger log |
| M5 — Time to signed brief | Baseline first, then reduce | Delivery records |
| M6 — Requirements-origin rework | Change requests traceable to a requirements gap, per project | Delivery records, trailing indicator |

**M2 is a gate, not a target.** A single embarrassing suggestion in front of a client costs more than ten good ones earn. Any release candidate with a non-zero M2 does not ship.

**Explicitly not a metric:** number of questions suggested. Volume is an anti-signal.

## 6. Constraints

These are fixed inputs, not design choices.

| # | Constraint | Consequence |
|---|---|---|
| ~~C1~~ | ~~No third-party SaaS may receive client meeting audio~~ **WITHDRAWN — see revision note** | Managed capture and cloud ASR are available |
| C2 | No software may be installed on the machine hosting the client meeting | Capture must not require an agent on the meeting host |
| C3 | LLM inference uses the **Claude Agent SDK** where the workload is agentic, and the Messages API where it is single-shot (§7.1) | Python/TypeScript service tier required; app cannot call the SDK directly |
| C4 | Operator is in NSW, Australia | Surveillance Devices Act applies to recording private conversations; see §11 |
| C5 | Client requirements content may be contractually restricted | MSA/NDA terms govern processing of client information; see §11 |
| C6 | STT must meet both a latency and an accuracy bar (NFR-5) | Dual-path transcription; single-engine designs do not satisfy both |

**Revision note on C1.** The perimeter constraint is withdrawn as a deliberate product decision, trading data-residency posture for capability. The immediate gains are managed per-participant capture (§10) and access to the current generation of cloud ASR.

**C4 and C5 are unaffected by that decision.** They are external legal and contractual constraints, not internal policy, and cannot be relaxed by product choice. §11 stands in full.

## 7. Solution overview

A desktop application on a second machine — macOS and Windows at v1 (NFR-3.1) — that listens to the meeting, maintains live requirements state, surfaces one short nudge at a time in a chat-shaped panel, and after the meeting becomes a full conversational interface for producing BMAD artifacts.

The load-bearing architectural idea: **the expensive reasoning happens before the meeting, not during it.** A BMAD Analyst pass runs offline over the context pack and emits a bank of pre-reasoned candidate questions. At runtime the system is doing retrieval and selection against that bank — a sub-second operation — not reasoning from a cold start. This is what makes real-time viable inside the conversational window.

Three surfaces, one continuous thread:

1. **Prep** — before the meeting. Context pack in, question bank out.
2. **Live** — during. Terse, tap-driven, one nudge at a time.
3. **Debrief** — after. Unconstrained conversation, artifact generation.

---

## 8. Functional requirements

### 8.1 Capture (FR-1)

| # | Requirement | Priority |
|---|---|---|
| FR-1.1 | Capture audio from a configurable input device; support USB audio interface (line-in from meeting machine), loopback from a silent local join, and built-in/external microphone | P0 |
| FR-1.2 | Default to and actively recommend wired or loopback capture over acoustic capture; warn the operator when acoustic capture is selected | P0 |
| FR-1.3 | Provide a single-tap, unmissable **pause capture** control that halts audio ingestion immediately | P0 |
| FR-1.4 | Display an unambiguous capture-state indicator (capturing / paused) visible at a glance | P0 |
| FR-1.5 | Support enrolment of the operator's voice (≤60s sample) for speaker verification | P1 |
| FR-1.6 | Tag each utterance as *operator* or *not operator* using on-device speaker verification | P1 |
| FR-1.7 | Never write raw audio to persistent storage. Audio exists in memory for the duration of transcription and is discarded | P0 |

**Rationale for FR-1.2.** Acoustic capture degrades exactly the signal we most need. The audio has already been through a lossy codec with noise suppression and AGC, then loudspeaker reproduction, then a reverberant room, then a far-field mic. The first casualties are proper nouns, client jargon, and numbers — and numbers are the payload of our highest-value trigger. Additionally, the MacBook's internal mic array beamforms toward the presumed talker (the operator) and macOS voice processing actively attenuates off-axis sound, working directly against us. Acoustic capture is retained only as the in-person-meeting fallback.

**Rationale for FR-1.6.** Full open-set diarization across multiple client stakeholders is hard and unnecessary in real time. The trigger gate needs one binary: *the client just finished a thought and I am not talking.* Single-speaker verification against an enrolled voiceprint is a much easier problem. Full attribution runs offline in the debrief pass, where latency is irrelevant.

### 8.2 Transcription (FR-2)

Two paths, because the trigger engine and the transcript of record have incompatible requirements. Attempting to satisfy both with one engine produces a system that is either too slow to nudge or too unreliable to cite.

| # | Requirement | Priority |
|---|---|---|
| **Live path — optimised for latency** | | |
| FR-2.1 | Streaming ASR producing interim hypotheses within 400ms and finalised utterances on endpoint | P0 |
| FR-2.2 | Configurable endpointing silence threshold, default 600ms, tunable per capture mode | P0 |
| FR-2.3 | Emit every utterance with start timestamp, end timestamp, speaker identity, and **per-word confidence** | P0 |
| FR-2.4 | Prefer engines with immutable streaming output — revised partials break speculative drafting (FR-5.9) | P1 |
| **Record path — optimised for accuracy** | | |
| FR-2.5 | Batch re-transcription of the full session at the highest available accuracy, with no latency constraint | P0 |
| FR-2.6 | Run two independent engines on the record path and reconcile. Agreement raises confidence; divergence is flagged | P1 |
| FR-2.7 | All artifacts, citations and coverage decisions derive from the record path, never from the live path | P0 |
| FR-2.8 | Surface divergent or low-confidence spans to the operator for review during debrief | P1 |
| **Both paths** | | |
| FR-2.9 | Per-engagement custom vocabulary / keyterm prompting: client name, product names, internal systems, acronyms | P0 |
| FR-2.10 | Consume per-participant audio streams where the capture mode provides them (§10) | P0 |
| **Multilingual — automatic** | | |
| FR-2.11 | **No per-meeting language selection.** Language is detected automatically; the operator never chooses before a meeting | P0 |
| FR-2.12 | Handle intra-sentential code-switching without language-ID routing — an end-to-end multilingual model, not a detect-then-route pipeline | P0 |
| FR-2.13 | Emit **per-token language tags** with confidence, not a single utterance-level language | P0 |
| FR-2.14 | Constrain detection to an engagement-scoped expected-language set, derived from client context (FR-3). Languages outside the set still transcribe, but rank lower | P1 |
| FR-2.15 | Tag language per participant stream where the capture mode provides separated streams | P1 |
| FR-2.16 | Learn per-attendee language preference across meetings in an engagement and bias that stream accordingly | P2 |
| FR-2.17 | Per-language number normalisation, including Chinese 万/亿 grouping | P0 |
| FR-2.18 | Language-appropriate tokenisation — word segmentation for languages without orthographic word boundaries | P0 |
| FR-2.19 | Retain the original-language utterance alongside any translation, permanently and inseparably | P0 |
| **Detection must be visible** | | |
| FR-2.20 | Display detected language(s) live in the panel | P0 |
| FR-2.21 | Allow single-tap operator override of the detected language | P0 |
| FR-2.22 | Suppress deterministic triggers when token-level language tag confidence is low | P0 |
| FR-2.23 | Announce tier changes explicitly when the meeting drifts into a lower-tier language (§8.2a) | P0 |

**Rationale for FR-2.11 / 2.12.** Explicit language identification requires 1–3 seconds of speech before it can decide, which would breach the latency budget on every first utterance, and it fails at exactly the code-switch points that dominate APAC meetings. An end-to-end multilingual model makes no language decision at all — identity falls out of the transcription rather than gating it. Auto-awareness is therefore simpler *and* faster than manual selection, not a feature bolted on top of it.

**Rationale for FR-2.13.** A code-switched utterance has no single language. 这个 API 的 latency 要求是什么 cannot be assigned to Mandarin or English without discarding half of it. The trigger gate runs each language's lexicon over the tokens tagged as that language, which is only possible with token-level granularity. This is a genuine differentiator between engines and is easily missed when evaluating on headline WER alone.

**Rationale for FR-2.14.** Unconstrained detection searches every supported language; constraining the candidate set measurably improves accuracy. The engagement context already knows the client, so the constraint can be derived rather than asked for — preserving FR-2.11 while avoiding a ninety-nine-way guess.

**Rationale for FR-2.20 through 2.23 — the silent misdetection failure.** If Cantonese is mislabelled as Mandarin, the ASR still emits plausible, well-formed Chinese text. The gate then runs the wrong lexicon and every downstream artifact degrades with no error raised anywhere. This is the worst class of failure in the system: invisible, uncorrected, and only discovered when the artifacts turn out to be wrong. Detection must always be visible and always overridable. An operator who reads nudge silence as "nothing worth asking" — when the real cause is an unannounced tier drop — has been actively misled by the product.

**Output language is not auto-detected.** Meeting language is inferred; artifact language is an explicit engagement setting. A meeting conducted in mixed Mandarin and English still produces artifacts in one language for the delivery team, and that choice is made deliberately, not guessed.

### 8.2a Language support tiers

Accuracy is not uniform across languages and cannot be made so by vendor selection. Published figures for Mandarin-English intra-sentential code-switching sit around 15% WER for production approaches and ~6.5% CER for research-best systems — against a live-path bar of 8% entity-weighted WER. **A single global accuracy target is not achievable and should not be committed to.**

| Tier | Capability | Requirements to add a language |
|---|---|---|
| **Tier 1** | Full: deterministic live triggers (FR-5.2, 5.3), model triggers, coverage, artifacts | Ambiguity lexicon, tokeniser/parser, compiled bank, annotated WER reference set |
| **Tier 2** | Model-path triggers only (FR-5.4–5.6), coverage, artifacts. No sub-second nudges | ASR support meeting Tier 2 accuracy; compiled bank |
| **Tier 3** | Transcript and artifacts only | ASR support |

**Launch tiering:** English and Mandarin at Tier 1. All other ASR-supported languages at Tier 2 by default.

**Why Tier 2 remains genuinely useful.** The deterministic triggers are language-specific; the model-assisted triggers are not. Contradiction, novel-entity and coverage-gap detection operate on semantic understanding in the slow lane and generalise across languages without additional work. A Tier 2 language loses the ~800ms path and retains the 60s path — fewer nudges, arriving later, but real ones.

**Why Tier 1 is expensive.** Adding a Tier 1 language is linguistics work, not engineering work, and requires a native-speaker BA:

- The ambiguity lexicon must be **rebuilt, not translated**. 差不多, 应该, 尽快, 大概 are Mandarin vagueness markers with no clean English correspondence, and Chinese hedges through constructions (aspect particles, reduplication) absent from English entirely.
- The unnamed-actor trigger (FR-5.3) **does not transfer to pro-drop languages**. Chinese omits subjects constantly and grammatically. An English-derived detector fires on a large fraction of ordinary sentences, destroying precision and breaching FR-5.7 immediately. Each language needs its own evasion-detection strategy, or none.
- Languages without orthographic word boundaries require segmentation before lexicon matching is possible at all.

Budget 4–6 weeks of native-speaker linguistic work per Tier 1 language. This is not parallelisable with engineering and is the binding constraint on language rollout.

### 8.2b Nudge language

Meeting language and nudge language are independent axes.

| # | Requirement | Priority |
|---|---|---|
| FR-2.24 | Suggested question phrasing rendered in the **meeting language** | P0 |
| FR-2.25 | Stub, trigger reason and interface chrome rendered in the **operator's language** | P0 |
| FR-2.26 | Operator language configurable independently of meeting language | P1 |

**Rationale.** The operator must say the question aloud. Handing them a question in a language they then translate under time pressure defeats the entire latency architecture. The trigger reason, by contrast, exists for their comprehension and belongs in whichever language they read fastest.

**Rationale for the split.** The live path tolerates error: a wrong nudge is rate-limited, low-cost, and the operator simply ignores it. The record path does not: a transcription error there becomes a wrong requirement in a signed PRD. Separating them lets each be optimised without compromise, and the record path costs nothing in latency because it runs after the meeting.

**Rationale for FR-2.10.** Per-participant streams remove cross-talk and far-field pickup, which are the dominant WER contributors in multi-party meetings — a larger effect than the difference between any two current engines. They also eliminate runtime diarization entirely.

Stock Whisper remains excluded from the live path — not streaming-native, endpointing not controllable. It is a legitimate candidate for the record path.

### 8.3 Context pack (FR-3)

**Object model.** Context is split across two levels. `Engagement` is created once per client project and holds everything stable. `Meeting` is created per session and holds only what changes. This split exists to protect adoption — see rationale below.

| # | Requirement | Priority |
|---|---|---|
| **Engagement level — created once** | | |
| FR-3.1 | Accept client background: organisation, sector, commercial context, delivery history | P0 |
| FR-3.2 | Accept reference documents by upload and by SharePoint/Teams link | P0 |
| FR-3.3 | Extract, structure, and index reference document content for retrieval and contradiction detection | P0 |
| FR-3.4 | Require a **status tag** on every reference document: `ground truth`, `hypothesis`, or `superseded` | P0 |
| FR-3.5 | Accept engagement purpose, scope boundary, and target requirements template | P0 |
| FR-3.6 | Maintain a client-specific vocabulary list (product names, internal systems, acronyms) feeding FR-2.3 | P1 |
| **Meeting level — created per session, ≤2 minutes** | | |
| FR-3.7 | Inherit all engagement context automatically; the operator confirms rather than re-enters | P0 |
| FR-3.8 | Accept this session's purpose and target template sections | P0 |
| FR-3.9 | Accept this session's attendees, pre-populated from the calendar invite where available | P0 |
| FR-3.10 | Capture attendee profiles as **structured fields only**: role, business function, decision authority, domain expertise. No free-text personal assessment field | P0 |
| FR-3.11 | Inherit the standing open-questions list and requirements state from prior meetings | P0 |
| FR-3.12 | Allow the operator to mark specific reference claims as assertions to verify with the client this session | P2 |
| **Degraded operation** | | |
| FR-3.13 | Operate with an engagement that has no reference documents, falling back to a generic elicitation bank keyed to sector and project type | P1 |
| FR-3.14 | Display a context-completeness indicator so the operator knows what quality of support to expect | P2 |

**Rationale for the engagement/meeting split.** This is the single largest adoption risk in the product. Value scales with context quality, context quality scales with operator effort, and that is a bad dependency. If per-meeting setup takes forty minutes it happens once and never again. Everything stable lives at engagement level; per-meeting setup reduces to confirming attendees, stating the session purpose, and reviewing inherited open questions.

**Rationale for FR-3.4 (document status).** The contradiction trigger (FR-5.4) fires when a client statement conflicts with a reference document. Fired against a superseded scoping deck, it produces: *"you said X but the scoping document says Y"* → *"yes, we changed that three weeks ago."* That is exactly the M2 embarrassment failure, and its cause is the context pack rather than the model. Contradiction triggers fire only against `ground truth`. `hypothesis` documents generate verification questions instead — a different and safer move. `superseded` documents remain indexed for background but never trigger.

**Rationale for FR-3.10 (structured attendee fields).** Role-aware routing is high-value: asking a CFO about API latency or a warehouse supervisor about capex approval wastes a turn, and surfacing a question because the person who owns that decision is in the room is genuinely differentiating. But a free-text profile field invites assessments of named individuals ("defensive", "blocks everything") which the model would then act on and which would sit in a discoverable system. Structured fields only. Cheap now, expensive to retrofit.

**Rationale for FR-3.3 (compile, don't dump).** The context pack must be compiled down, not accumulated. Large raw document sets inflate the cached prefix and consume a latency budget with no slack in it (NFR-1). The question bank is the compiled artifact; raw documents remain in the retrieval index for slow-lane use only.

### 8.4 Question bank compilation (FR-4)

Runs offline, pre-meeting. This is where the Analyst reasoning lives.

| # | Requirement | Priority |
|---|---|---|
| FR-4.1 | Run a BMAD Analyst pass over the context pack and emit 150–300 candidate questions | P0 |
| FR-4.2 | Tag each candidate with: target template section, trigger conditions, priority, and prerequisite knowledge | P0 |
| FR-4.3 | Embed candidates for sub-300ms retrieval at runtime | P0 |
| FR-4.4 | Draw question strategies from an explicit elicitation technique set, not from persona prompting alone | P0 |
| FR-4.5 | Present the compiled bank to the operator pre-meeting as a reviewable question tree they can edit, reorder, and prune | P0 |
| FR-4.6 | Keep discovery-stage banks in problem space; suppress solution-shaped and epic-shaped questions before the requirements template calls for them | P1 |
| FR-4.7 | Weight candidate ranking by attendee decision authority and domain — surface questions the people actually in the room can answer | P1 |
| FR-4.8 | Recompile the bank per meeting, weighting toward the inherited open-questions list | P0 |
| FR-4.9 | Generate verification questions from `hypothesis`-tagged documents rather than treating them as fact | P1 |

**Rationale for FR-4.4.** A persona is roughly 5% of what produces a good question. A persona alone yields a generic BA that does not know the client, the reference docs, what was agreed last meeting, or which sections are still empty — it produces plausible, textbook, slightly obvious questions. The output *looks* fine, which makes this a quiet failure mode. The technique set, context pack, coverage state, and retrieval are what actually carry the quality.

**Rationale for FR-4.5.** The reviewable question tree is independently valuable and is the phase 0 deliverable. If the tree is good, the operator is better prepared even if the live layer never ships.

### 8.5 Live trigger and selection (FR-5)

| # | Requirement | Priority |
|---|---|---|
| FR-5.1 | Evaluate every finalised utterance against the trigger gate | P0 |
| FR-5.2 | Trigger on unquantified adjectives and vague quantifiers ("fast", "scalable", "user-friendly", "a lot", "soon") via lexicon match | P0 |
| FR-5.3 | Trigger on unnamed actors — passive constructions and "the system does X" with no owner | P0 |
| FR-5.4 | Trigger on contradiction with an earlier utterance in the engagement or with a reference document | P1 |
| FR-5.5 | Trigger on novel entity — a system, role, or process not present in the context pack | P1 |
| FR-5.6 | Trigger on coverage gap combined with topic drift away from an unfilled section | P1 |
| FR-5.7 | Gate pass rate must not exceed ~10% of utterances | P0 |
| FR-5.8 | Surface at most one nudge per 60 seconds regardless of how many pass the gate | P0 |
| FR-5.9 | Begin speculative drafting on interim ASR hypotheses; commit or discard at endpoint | P1 |
| FR-5.10 | Slow lane: full-context pass at 60s cadence, injecting novel candidates into the bank mid-meeting | P1 |
| FR-5.11 | Every surfaced nudge must carry its trigger reason | P0 |

FR-5.2 and FR-5.3 require no model at all — they are lexicon and parse-level rules, running locally with near-perfect precision. Build these first; they will carry more weight than expected.

FR-5.11 is not decoration. Without a visible reason the operator cannot calibrate trust, and uncalibrated suggestions get ignored within two meetings.

### 8.6 Live interface (FR-6)

| # | Requirement | Priority |
|---|---|---|
| FR-6.1 | Nudge text hard-capped at 25 words, enforced as `max_tokens` in the request, not as a prompt instruction | P0 |
| FR-6.2 | Two-tier rendering: a 3–5 word glanceable stub, with the full question at smaller weight beneath | P0 |
| FR-6.3 | One nudge displayed prominently at a time; prior nudges recede into dimmed history | P0 |
| FR-6.4 | **Streaming disabled in live mode.** Nudges render complete or not at all | P0 |
| FR-6.5 | Persistent coverage indicator: sections filled / total, and time remaining | P0 |
| FR-6.6 | Tap-only primary input. Chips: `Asked it`, `Park it`, `Go deeper`, `What am I missing?` | P0 |
| FR-6.7 | `Asked it` marks the coverage slot satisfied and suppresses re-suggestion | P0 |
| FR-6.8 | `Park it` defers the thread to the open-questions list without dismissing it | P0 |
| FR-6.9 | Text input present but visually de-emphasised as an escape hatch | P1 |
| FR-6.10 | Treat operator speech as implicit input — when the operator asks the client a question, mark that thread live and adjust ranking | P1 |

**Rationale for FR-6.4.** Streaming exists to hold attention while a response renders. That is precisely the wrong behaviour in a live meeting. A message that materialises complete costs one glance; a message typing itself out pulls at the operator for several seconds, during which they are not listening to the client.

**Rationale for FR-6.6.** Typing is an order of magnitude more attention than glancing — it requires composition, and composition is not compatible with listening. If consulting the assistant requires typing, the tool is worse than a printed question tree.

**Rationale for FR-6.7 / 6.8.** These chips are the feedback loop, not just dismissals. Without them the coverage state drifts within ten minutes and the assistant starts repeating itself. Obtaining that signal for one tap at near-zero attention cost is the main reason to prefer this shape over a pure heads-up display.

**Rationale for FR-6.10.** The meeting itself is the input channel. The operator is already talking; the app is already transcribing them. Most consultation intents are expressed by talking to the client, not to the app. The chips cover only the residual intents that cannot be — *why did you say that*, *another angle*, *what am I not covering*.

### 8.7 Debrief mode (FR-7)

| # | Requirement | Priority |
|---|---|---|
| FR-7.1 | Same thread, same context, no length cap, no latency budget, streaming enabled | P0 |
| FR-7.2 | Full offline pass over the recording: complete diarization, speaker attribution, cleanup | P0 |
| FR-7.3 | Conversational interface over the meeting content — free-form querying, drafting, challenge | P0 |
| FR-7.4 | Inherit live-mode signal: which nudges fired, which were taken, which were parked | P1 |

### 8.8 Artifacts (FR-8)

| # | Requirement | Priority |
|---|---|---|
| FR-8.1 | Transcript with speaker attribution and timestamps | P0 |
| FR-8.2 | Requirements coverage matrix against the BMAD template section taxonomy | P0 |
| FR-8.3 | **Open questions list**, ranked by impact on the build | P0 |
| FR-8.4 | Decision and commitment log — what was agreed, by whom | P0 |
| FR-8.5 | Draft project brief | P0 |
| FR-8.6 | Draft follow-up email: what we heard, what we still need from you | P0 |
| FR-8.7 | Every requirement claim carries a timestamp and speaker citation | P0 |
| FR-8.7a | Where the meeting language differs from the artifact language, citations carry **both** the original-language utterance and its translation. The original renders on expand | P0 |
| FR-8.8 | Anything the system inferred rather than heard is visually flagged as inference | P0 |
| FR-8.9 | Updated standing requirements state, carried into the next meeting in the engagement | P0 |
| FR-8.10 | Full PRD generation — only once sufficient coverage exists across meetings, never from a single discovery call | P2 |

**Rationale for FR-8.3.** The open-questions list is the most valuable artifact in this set and almost nobody builds it. It is also what converts into client homework via FR-8.6.

**Rationale for FR-8.10.** One discovery meeting does not contain a PRD. Generating one produces a confident, hallucinated document the operator then has to un-believe, which is worse than no document. Coverage gates artifact depth.

**Rationale for FR-8.7 / 8.8.** Traceability is what makes the artifacts defensible in client sign-off and in later disputes about scope. It is also the only practical defence against fluent fabrication.

---

## 9. Non-functional requirements

### 9.1 Latency (NFR-1)

The window in which a follow-up question still reads as natural is approximately 1–4 seconds after the client stops speaking, extending to ~7s if the operator covers it ("let me make sure I've got that"). Beyond that, asking signals that you were not listening.

| Stage | Budget |
|---|---|
| ASR endpoint to finalised text | 500–800ms |
| Trigger gate evaluation | ≤150ms |
| Retrieval, ranking, phrasing | 300–800ms |
| Render | ≤50ms |
| **Total, speech-end to nudge visible** | **≤2.0s p50, ≤3.5s p95** |

Two techniques are required to hold this budget: speculative drafting on interim hypotheses (FR-5.9), reclaiming most of the endpointing wait; and prompt caching on a stable prefix — context pack, template, meeting purpose — with only a rolling 60–90 second transcript window appended. The full transcript is never resent. Get the caching wrong and time-to-first-token alone consumes the budget.

Endpointing dominates this budget: at a 600ms default (FR-2.2) it is roughly eight times the rest of the local pipeline combined. Tuning it is the highest-leverage latency work available and must be measured before any other optimisation.

### 9.1a Transcription assurance (NFR-5)

| # | Requirement |
|---|---|
| NFR-5.1 | Measure **entity-weighted WER**, not overall WER. Weighting toward numerals, proper nouns, negations, and engagement vocabulary |
| NFR-5.2 | Live path, Tier 1 monolingual: entity-weighted WER ≤8% |
| NFR-5.3 | Live path, code-switched: entity-weighted WER ≤15%. **Deterministic triggers gate on span confidence and will fire less often** — this is correct behaviour, not a defect |
| NFR-5.4 | Record path, Tier 1: entity-weighted WER ≤3%; residual divergences surfaced, never silently resolved |
| NFR-5.5 | Record path, Tier 2: entity-weighted WER ≤6% |
| NFR-5.6 | Triggers suppressed when the trigger span itself falls below a confidence threshold |
| NFR-5.7 | WER measured and published **per language and per capture mode**. No global figure is quoted |
| NFR-5.8 | Language falls back to a lower tier automatically when measured accuracy does not meet its bar, with the operator notified |

**Rationale for NFR-5.1.** Overall WER is close to useless for this product. A 4% WER that fails on every number is worse than an 8% WER that gets numbers right, because numerals are the payload of the highest-value trigger — the whole point of `quantify "fast"` is capturing the answer.

**Rationale for NFR-5.3.** Code-switched accuracy is materially worse than monolingual and no vendor selection changes that. Rather than pretend otherwise, the system fires fewer triggers when confidence is low. Fewer correct nudges beats more wrong ones — M2 is the gate, not M1.

**Rationale for NFR-5.6.** Firing a nudge on a misheard trigger span — `quantify "fast"` when the client said "vast" — is an M2 event, and it is entirely preventable at near-zero cost.

**Rationale for NFR-5.8.** Silent degradation is the failure mode to avoid. An operator who believes they have Tier 1 support in a language where accuracy has dropped will trust nudges they should not.

### 9.2 Security and data (NFR-2)

Revised following the withdrawal of C1. The posture is now vendor-assurance-based rather than perimeter-based.

| # | Requirement |
|---|---|
| NFR-2.1 | Every processor touching client audio or transcripts must hold a DPA with no-training-on-customer-data terms and a defined retention window |
| NFR-2.2 | Data residency pinned to an agreed region per engagement where the vendor supports it |
| NFR-2.3 | Vendor-side retention set to zero or the minimum available on every ASR and inference path |
| NFR-2.4 | Raw audio retained only until the record path completes, then discarded (revises FR-1.7) |
| NFR-2.5 | Transcripts and artifacts encrypted at rest; retention set by data classification outcome (§13, D2) |
| NFR-2.6 | PII redaction available on outbound paths, configurable per engagement |
| NFR-2.7 | All egress passes through a single audited chokepoint with request logging |

**What changed and why it still matters.** The old proposition was *nothing leaves the machine*, which made the infosec review trivial. The new proposition is *client audio and transcripts leave the machine, to named processors under contract, with retention disabled.* That is a materially larger review and a real conversation with Legal about sub-processors under client MSAs (L3) — but it is a normal enterprise SaaS posture, not an exotic one.

NFR-2.7 is retained from the original design and becomes **more** important, not less: with multiple external processors in the path, a single audited egress point is the only practical way to know what actually left.

### 9.3 Platform and distribution (NFR-3)

| # | Requirement |
|---|---|
| NFR-3.1 | Ship to Windows (x64, arm64) and macOS (universal) at v1; iOS and Android as companion clients thereafter |
| NFR-3.2 | Trigger engine, bank retrieval, ranking and session state implemented **once** in a shared core. No per-platform reimplementation |
| NFR-3.3 | macOS: Developer ID signed and notarised. Unnotarised builds are Gatekeeper-blocked |
| NFR-3.4 | Windows: Authenticode signed with an **EV certificate**. Without SmartScreen reputation, every early install shows a warning |
| NFR-3.5 | MDM distribution preferred on both desktop platforms — Jamf/Intune on macOS with a PPPC profile pre-granting microphone and screen-recording entitlements; Intune on Windows |
| NFR-3.6 | `.dmg` and MSI available as fallback distribution |
| NFR-3.7 | EDR whitelisting agreed with IT on both platforms before pilot — an unknown binary opening a loopback audio stream will be flagged |
| NFR-3.8 | Behaviour verified identical across platforms via the replay harness. M1 and M2 are product metrics, never per-platform metrics |

**Rationale for NFR-3.2 and 3.8.** The trigger engine is the product. Three implementations means three behaviours, and a replay harness that validates one of them while two ship unvalidated.

**Mobile scope note.** Mobile clients cannot capture meeting audio — iOS offers no system-audio loopback, and Android's equivalent is opt-out by the captured application. Mobile ships as a second-screen nudge display and a debrief client, both of which are genuinely valuable and neither of which requires capture. See architecture §11.2.

### 9.4 Reliability (NFR-4)

| # | Requirement |
|---|---|
| NFR-4.1 | Loss of the LLM endpoint degrades gracefully: lexicon triggers and coverage tracking continue to function |
| NFR-4.2 | ASR failure surfaces visibly rather than silently producing an empty transcript |
| NFR-4.3 | Meeting state persists locally; app crash does not lose the session |

---

## 10. Architecture

```
PRE-MEETING (offline)
  Context pack ──▶ BMAD Analyst pass ──▶ Question bank (~200 candidates, embedded)
                                              │
LIVE                                          │
  Audio in ──▶ Streaming ASR ──▶ Trigger gate ─┴──▶ Rank + phrase ──▶ Nudge
  (managed        (live path,     (local rules,        (local retrieval,
   per-participant  hosted)        ~150ms)              300–800ms)
   streams)                                                  ▲
                                       Slow lane (60s cadence, Messages API,
                                       cached prefix) ───────┘

POST-MEETING
  Retained audio ──▶ Batch ASR ×2, reconciled ──▶ Diarization + cleanup
                     (record path, FR-2.5/2.6)          │
                                                        ▼
                     Debrief thread ──▶ BMAD artifacts + updated state
```

Capture options in priority order, all supported as input devices:

1. **Managed capture.** A capture vendor joins the meeting and returns one audio stream per participant (FR-2.10), removing cross-talk and eliminating runtime diarization. Preferred wherever the meeting platform is supported. Vendor unselected — see D4.
2. **Silent join.** The operator's second machine joins the meeting muted, camera off, speakers off, operator on headphones. Loopback — ScreenCaptureKit or the CoreAudio process tap on macOS, WASAPI on Windows — gives clean digital audio. Cost: an extra name in the participant roster — which, given §11, may be an advantage.
3. **Line-in.** Meeting machine line-out into a USB audio interface on the second machine. Clean analog, no roster entry, works with dial-in and any platform.
4. **Acoustic.** External omnidirectional USB conference mic near the speakers, voice isolation disabled. In-person fallback and degraded mode only.

**Rejected: Teams application-hosted media bot.** Technically in-perimeter and gives per-participant streams, but production bots must run on Windows Server in Azure, are C#/.NET only, and the Real-time Media Platform remains in developer preview with guidance subject to change. Microsoft's own documentation now describes real-time media bots as specialist integrations delivered via managed partners and explicitly does not recommend them for AI agent scenarios, pointing instead at Copilot Studio or post-hoc Graph transcripts. Building on a preview surface the vendor is steering people away from, for an internal tool, is not a defensible use of the team. Graph meeting transcripts remain useful as a post-meeting input.

---

## 11. Legal and compliance

**Blocking. Resolve before the capture layer is written.**

| # | Item | Owner |
|---|---|---|
| L1 | NSW Surveillance Devices Act position on recording client conversations. A laptop mic in a room is a listening device, and internal-tool framing does not change that. Determine whether all-party consent must be obtained and logged per meeting | Legal |
| L2 | If consent must be captured, that is a v1 UI requirement, not a policy footnote — spec the consent flow into FR-6 | Legal + PM |
| L3 | Client MSA/NDA terms governing processing of client information by automated systems. Review the standard template plus any client-specific deviations | Contracts |
| L4 | Data classification for client requirements conversations, which determines retention, egress, and encryption obligations | Infosec |
| L5 | Client-side policy: some enterprise clients prohibit recording or bots in their meetings outright | Delivery leads |

**Behavioural risk, not legal but worth stating.** A visible AI notetaker changes how candidly people speak. This risks degrading the very elicitation we are trying to improve. Conversely, a laptop listening silently in the room is invisible in a way a roster entry is not, which cuts against us on L1. The silent-join capture option is preferred partly because it makes our presence legible.

---

## 12. Release plan

Each phase has a kill criterion. If a phase fails it, the next phase does not start.

### Phase 0 — Replay harness (1 week)

Not user-facing. Take transcripts from meetings already run. Replay through the pipeline at wall-clock speed. Log every suggestion it would have surfaced, with timestamps. Two senior BAs rate each on *useful*, *timely*, *would this have embarrassed me*.

This yields M1 and M2 without ever risking a client meeting, and lets the gate threshold be tuned offline. It also reveals whether the question bank is any good — which is the actual determinant of whether the product works.

> **Kill criterion:** none. This is the instrument, not the experiment.

### Phase 1 — Prep and synthesis, no real-time (2 weeks)

Question tree generation from the context pack. Post-meeting synthesis from an uploaded recording. Artifacts FR-8.1 through FR-8.6.

> **Kill criterion:** if a senior BA rates the generated question tree as worse than what they would write themselves, stop. Real-time can only be worse than batch — it has less time and less context.

### Phase 2 — Live coverage (2 weeks)

Capture, streaming ASR, coverage indicator. No generation. The panel shows what is filled and what is not, plus time remaining.

> **Kill criterion:** operator reports the coverage display was distracting rather than useful in ≥2 of 5 pilot meetings.

### Phase 3 — Live ambiguity triggers (3 weeks)

Lexicon triggers, FR-5.2 and FR-5.3, feeding the nudge panel. Deterministic, high precision, no model in the hot path. This is where most of the realisable real-time value lives.

> **Kill criterion:** M1 below 70% or M2 non-zero on the replay harness.

### Phase 4 — Generative suggestion (4 weeks+)

Model-driven triggers FR-5.4 through FR-5.6, slow lane, speculative drafting.

Gate on **precision, not recall**. A 60%-precision suggester is worse than nothing, because the operator learns to ignore the panel and the product is dead. Prefer surfacing three excellent nudges per meeting over twelve adequate ones.

> **Kill criterion:** M1 below 70% or M2 non-zero after two tuning iterations.

---

## 13. Open decisions

| # | Decision | Blocks | Owner |
|---|---|---|---|
| D1 | Primary user: experienced PM or junior BA? (§4) | Phase 2 scoping | PM |
| D2 | Data classification for client requirements content | NFR-2.5, all retention | Infosec |
| D3 | Consent model — announce and log per meeting, or engagement-level? | FR-6 UI scope | Legal |
| D4 | Capture and ASR vendor selection — which managed capture vendor, which live-path engine, which two independent record-path engines — assessed on DPA, residency and retention terms as much as on accuracy | Phase 2, ADR-011 | Eng + Infosec + Legal |
| D5 | Requirements template taxonomy — BMAD PRD sections as-is, or an internal variant? | FR-4.2, FR-8.2 | Delivery |
| D6 | Which BMAD version and module set do we standardise on? | FR-4.1 | Eng |

---

## 14. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | Low precision trains the operator to ignore the panel; product dies quietly | Precision gates at every phase; rate limiting FR-5.8; kill criteria |
| R2 | Anchoring — the operator asks the suggested question instead of the better one they would have found | Rate limiting; framing nudges as prompts not scripts; monitor in pilot |
| R3 | Deskilling over time | Watch in pilot; consider a coverage-only mode for experienced operators |
| R4 | Legal position (§11) turns out to prohibit capture | Resolve L1–L5 before phase 2. Phases 0–1 are unaffected — they work on already-recorded material |
| R5 | Acoustic capture WER makes numbers unreliable, undermining the core trigger | FR-1.2 device hierarchy; measure WER per capture mode in phase 2 |
| R6 | Scope estimated as "ChatGPT plus a persona", underestimating the build by ~5x | This document. Persona and prompt is one day; the context pipeline and question bank is where the weeks go |
| R7 | Client refuses recording, product unusable on the accounts that matter most | Establish per-client position early via L5; prep and debrief phases retain value without live capture |
| R8 | Setup friction — value depends on context quality, context quality depends on operator effort. High per-meeting setup cost means it is done once and abandoned | Engagement/meeting split (FR-3); calendar pre-population; degraded operation (FR-3.13); position the question tree as the prep deliverable rather than as form-filling |
| R9 | Stale reference documents generate false contradiction triggers in front of the client | Mandatory document status tagging (FR-3.4); triggers restricted to `ground truth` |
| R10 | Multilingual scoped as an ASR vendor decision, underestimating it by an order of magnitude. The transcription is purchasable; the trigger gate is per-language linguistics work | §8.2a tiering; T10–T13; native-speaker BA resourcing in the rollout plan |
| R11 | Code-switched accuracy fails to meet the live-path bar, and the product is quietly useless in exactly the APAC meetings it was built for | Measure early (T12); NFR-5.3 sets a realistic separate bar; confidence gating means fewer nudges rather than wrong ones; automatic tier fallback (NFR-5.8) |
| R12 | Translated citations used as evidence in a scope dispute, and the original wording is gone | FR-2.19 and FR-8.7a make original retention structural, not optional |

---

## 15. Appendix — what we are deliberately not building, and why

**Transcription.** Commodity. Otter, Fireflies, Granola, Circleback, Teams Copilot and Zoom AI Companion all do transcript, notes, and action items, effectively free. Building it consumes the effort that should go to the elicitation layer, which is the only defensible part.

**A meeting bot of our own.** Managed capture is bought, not built — the C1 constraint that previously excluded hosted capture vendors is withdrawn, and per-participant streams are now a design dependency (FR-2.10, architecture ADR-011). What stays excluded is a *self-built* platform bot: per-platform maintenance forever, breaking on every vendor update. See also the rejected Teams media bot in §10.

**Scheduling and calendar integration.** No differentiation. The follow-up email draft (FR-8.6) covers the actual need, which is converting open questions into client homework.

**Voice interaction with the assistant during the meeting.** The operator cannot speak to the app in front of a client. FR-6.10 covers this properly: the operator talks to the client, and the assistant listens in.
