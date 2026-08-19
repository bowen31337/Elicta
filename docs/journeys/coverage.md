# Requirement coverage

Every requirement in the PRD, and the journey that carries it. Generated
from the PRD by `scripts/coverage.py`, so a requirement added there and
not placed in a journey shows up as a gap rather than being quietly
missed.

**117 of 117 requirements are covered by a journey.**

## 1. [Prepare an engagement](01-prepare-an-engagement.md) — 19 requirements

| Req | |
|---|---|
| `FR-2.14` | Constrain detection to an engagement-scoped expected-language set, derived… |
| `FR-3.1` | Accept client background: organisation, sector, commercial context, delive… |
| `FR-3.2` | Accept reference documents by upload and by SharePoint/Teams link |
| `FR-3.3` | Extract, structure, and index reference document content for retrieval and… |
| `FR-3.4` | Require a status tag on every reference document: ground truth, hypothesis… |
| `FR-3.5` | Accept engagement purpose, scope boundary, and target requirements template |
| `FR-3.6` | Maintain a client-specific vocabulary list (product names, internal system… |
| `FR-3.12` | Allow the operator to mark specific reference claims as assertions to veri… |
| `FR-3.13` | Operate with an engagement that has no reference documents, falling back t… |
| `FR-3.14` | Display a context-completeness indicator so the operator knows what qualit… |
| `FR-4.1` | Run a BMAD Analyst pass over the context pack and emit 150–300 candidate q… |
| `FR-4.2` | Tag each candidate with: target template section, trigger conditions, prio… |
| `FR-4.3` | Embed candidates for sub-300ms retrieval at runtime |
| `FR-4.4` | Draw question strategies from an explicit elicitation technique set, not f… |
| `FR-4.5` | Present the compiled bank to the operator pre-meeting as a reviewable ques… |
| `FR-4.6` | Keep discovery-stage banks in problem space; suppress solution-shaped and … |
| `FR-4.7` | Weight candidate ranking by attendee decision authority and domain — surfa… |
| `FR-4.8` | Recompile the bank per meeting, weighting toward the inherited open-questi… |
| `FR-4.9` | Generate verification questions from hypothesis-tagged documents rather th… |

## 2. [Start a meeting with consent](02-start-a-meeting-with-consent.md) — 9 requirements

| Req | |
|---|---|
| `FR-1.1` | Capture audio from a configurable input device; support USB audio interfac… |
| `FR-1.7` | Never write raw audio to persistent storage. Audio exists in memory for th… |
| `FR-3.8` | Accept this session's purpose and target template sections |
| `FR-3.9` | Accept this session's attendees, pre-populated from the calendar invite wh… |
| `FR-3.10` | Capture attendee profiles as structured fields only: role, business functi… |
| `NFR-2.1` | Every processor touching client audio or transcripts must hold a DPA with … |
| `NFR-2.2` | Data residency pinned to an agreed region per engagement where the vendor … |
| `NFR-2.3` | Vendor-side retention set to zero or the minimum available on every ASR an… |
| `NFR-2.4` | Raw audio retained only until the record path completes, then discarded (r… |

## 3. [Catch a vague answer live](03-catch-a-vague-answer-live.md) — 25 requirements

| Req | |
|---|---|
| `FR-2.1` | Streaming ASR producing interim hypotheses within 400ms and finalised utte… |
| `FR-2.2` | Configurable endpointing silence threshold, default 600ms, tunable per cap… |
| `FR-2.3` | Emit every utterance with start timestamp, end timestamp, speaker identity… |
| `FR-2.4` | Prefer engines with immutable streaming output — revised partials break sp… |
| `FR-5.1` | Evaluate every finalised utterance against the trigger gate |
| `FR-5.2` | Trigger on unquantified adjectives and vague quantifiers ("fast", "scalabl… |
| `FR-5.3` | Trigger on unnamed actors — passive constructions and "the system does X" … |
| `FR-5.4` | Trigger on contradiction with an earlier utterance in the engagement or wi… |
| `FR-5.5` | Trigger on novel entity — a system, role, or process not present in the co… |
| `FR-5.6` | Trigger on coverage gap combined with topic drift away from an unfilled se… |
| `FR-5.7` | Gate pass rate must not exceed ~10% of utterances |
| `FR-5.8` | Surface at most one nudge per 60 seconds regardless of how many pass the g… |
| `FR-5.9` | Begin speculative drafting on interim ASR hypotheses; commit or discard at… |
| `FR-5.10` | Slow lane: full-context pass at 60s cadence, injecting novel candidates in… |
| `FR-5.11` | Every surfaced nudge must carry its trigger reason |
| `FR-6.1` | Nudge text hard-capped at 25 words, enforced as max_tokens in the request,… |
| `FR-6.2` | Two-tier rendering: a 3–5 word glanceable stub, with the full question at … |
| `FR-6.3` | One nudge displayed prominently at a time; prior nudges recede into dimmed… |
| `FR-6.4` | Streaming disabled in live mode. Nudges render complete or not at all |
| `FR-6.5` | Persistent coverage indicator: sections filled / total, and time remaining |
| `FR-6.6` | Tap-only primary input. Chips: Asked it, Park it, Go deeper, What am I mis… |
| `FR-6.7` | Asked it marks the coverage slot satisfied and suppresses re-suggestion |
| `FR-6.8` | Park it defers the thread to the open-questions list without dismissing it |
| `FR-6.9` | Text input present but visually de-emphasised as an escape hatch |
| `FR-6.10` | Treat operator speech as implicit input — when the operator asks the clien… |

## 4. [Run a code-switched meeting](04-run-a-code-switched-meeting.md) — 15 requirements

| Req | |
|---|---|
| `FR-2.11` | No per-meeting language selection. Language is detected automatically; the… |
| `FR-2.12` | Handle intra-sentential code-switching without language-ID routing — an en… |
| `FR-2.13` | Emit per-token language tags with confidence, not a single utterance-level… |
| `FR-2.15` | Tag language per participant stream where the capture mode provides separa… |
| `FR-2.16` | Learn per-attendee language preference across meetings in an engagement an… |
| `FR-2.17` | Per-language number normalisation, including Chinese 万/亿 grouping |
| `FR-2.18` | Language-appropriate tokenisation — word segmentation for languages withou… |
| `FR-2.19` | Retain the original-language utterance alongside any translation, permanen… |
| `FR-2.20` | Display detected language(s) live in the panel |
| `FR-2.21` | Allow single-tap operator override of the detected language |
| `FR-2.22` | Suppress deterministic triggers when token-level language tag confidence i… |
| `FR-2.23` | Announce tier changes explicitly when the meeting drifts into a lower-tier… |
| `FR-2.24` | Suggested question phrasing rendered in the meeting language |
| `FR-2.25` | Stub, trigger reason and interface chrome rendered in the operator's langu… |
| `FR-2.26` | Operator language configurable independently of meeting language |

## 5. [Keep working when the model is unreachable](05-degraded-mode.md) — 3 requirements

| Req | |
|---|---|
| `NFR-4.1` | Loss of the LLM endpoint degrades gracefully: lexicon triggers and coverag… |
| `NFR-4.2` | ASR failure surfaces visibly rather than silently producing an empty trans… |
| `NFR-4.3` | Meeting state persists locally; app crash does not lose the session |

## 6. [Reconcile the recording](06-reconcile-the-recording.md) — 7 requirements

| Req | |
|---|---|
| `FR-2.5` | Batch re-transcription of the full session at the highest available accura… |
| `FR-2.6` | Run two independent engines on the record path and reconcile. Agreement ra… |
| `FR-2.7` | All artifacts, citations and coverage decisions derive from the record pat… |
| `FR-2.8` | Surface divergent or low-confidence spans to the operator for review durin… |
| `FR-7.2` | Full offline pass over the recording: complete diarization, speaker attrib… |
| `NFR-5.1` | Measure entity-weighted WER, not overall WER. Weighting toward numerals, p… |
| `NFR-5.2` | Live path, Tier 1 monolingual: entity-weighted WER ≤8% |

## 7. [Produce the debrief artifacts](07-produce-the-debrief.md) — 12 requirements

| Req | |
|---|---|
| `FR-7.1` | Same thread, same context, no length cap, no latency budget, streaming ena… |
| `FR-7.3` | Conversational interface over the meeting content — free-form querying, dr… |
| `FR-7.4` | Inherit live-mode signal: which nudges fired, which were taken, which were… |
| `FR-8.1` | Transcript with speaker attribution and timestamps |
| `FR-8.2` | Requirements coverage matrix against the BMAD template section taxonomy |
| `FR-8.3` | Open questions list, ranked by impact on the build |
| `FR-8.4` | Decision and commitment log — what was agreed, by whom |
| `FR-8.5` | Draft project brief |
| `FR-8.6` | Draft follow-up email: what we heard, what we still need from you |
| `FR-8.7` | Every requirement claim carries a timestamp and speaker citation |
| `FR-8.8` | Anything the system inferred rather than heard is visually flagged as infe… |
| `FR-8.10` | Full PRD generation — only once sufficient coverage exists across meetings… |

## 8. [Carry state to the next meeting](08-carry-state-forward.md) — 3 requirements

| Req | |
|---|---|
| `FR-3.7` | Inherit all engagement context automatically; the operator confirms rather… |
| `FR-3.11` | Inherit the standing open-questions list and requirements state from prior… |
| `FR-8.9` | Updated standing requirements state, carried into the next meeting in the … |

## 9. [Tune ranking with the replay harness](09-replay-and-tune-ranking.md) — 6 requirements

| Req | |
|---|---|
| `NFR-5.3` | Live path, code-switched: entity-weighted WER ≤15%. Deterministic triggers… |
| `NFR-5.4` | Record path, Tier 1: entity-weighted WER ≤3%; residual divergences surface… |
| `NFR-5.5` | Record path, Tier 2: entity-weighted WER ≤6% |
| `NFR-5.6` | Triggers suppressed when the trigger span itself falls below a confidence … |
| `NFR-5.7` | WER measured and published per language and per capture mode. No global fi… |
| `NFR-5.8` | Language falls back to a lower tier automatically when measured accuracy d… |

## 10. [Configure providers and connectors](10-configure-providers.md) — 4 requirements

| Req | |
|---|---|
| `FR-2.9` | Per-engagement custom vocabulary / keyterm prompting: client name, product… |
| `NFR-2.5` | Transcripts and artifacts encrypted at rest; retention set by data classif… |
| `NFR-2.6` | PII redaction available on outbound paths, configurable per engagement |
| `NFR-2.7` | All egress passes through a single audited chokepoint with request logging |

## 11. [Control capture during the meeting](11-control-capture.md) — 6 requirements

| Req | |
|---|---|
| `FR-1.2` | Default to and actively recommend wired or loopback capture over acoustic … |
| `FR-1.3` | Provide a single-tap, unmissable pause capture control that halts audio in… |
| `FR-1.4` | Display an unambiguous capture-state indicator (capturing / paused) visibl… |
| `FR-1.5` | Support enrolment of the operator's voice (≤60s sample) for speaker verifi… |
| `FR-1.6` | Tag each utterance as *operator* or *not operator* using on-device speaker… |
| `FR-2.10` | Consume per-participant audio streams where the capture mode provides them… |

## 12. [Install and roll out](12-install-and-roll-out.md) — 8 requirements

| Req | |
|---|---|
| `NFR-3.1` | Ship to Windows (x64, arm64) and macOS (universal) at v1; iOS and Android … |
| `NFR-3.2` | Trigger engine, bank retrieval, ranking and session state implemented once… |
| `NFR-3.3` | macOS: Developer ID signed and notarised. Unnotarised builds are Gatekeepe… |
| `NFR-3.4` | Windows: Authenticode signed with an EV certificate. Without SmartScreen r… |
| `NFR-3.5` | MDM distribution preferred on both desktop platforms — Jamf/Intune on macO… |
| `NFR-3.6` | .dmg and MSI available as fallback distribution |
| `NFR-3.7` | EDR whitelisting agreed with IT on both platforms before pilot — an unknow… |
| `NFR-3.8` | Behaviour verified identical across platforms via the replay harness. M1 a… |
