<div align="center">

# Elicta

**A live requirements-elicitation assistant for client meetings.**

[![CI](https://github.com/bowen31337/Elicta/actions/workflows/test.yml/badge.svg)](https://github.com/bowen31337/Elicta/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Rust](https://img.shields.io/badge/rust-stable-orange.svg)](https://www.rust-lang.org/)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB.svg)](https://www.python.org/)
[![Tauri 2](https://img.shields.io/badge/Tauri-2-24C8DB.svg)](https://tauri.app/)

<img src="docs/journeys/screenshots/panel-nudge-surfaced.png" width="380" alt="The operator panel surfacing a follow-up question mid-meeting: the headline 'How fast is fast?', the full phrasing beneath it, the trigger reason 'unquantified adjective — fast', and four response chips." />

</div>

---

Elicta listens to a requirements meeting, tracks coverage against a template, detects ambiguity in
the moment, surfaces the follow-up question the operator would have wished they asked — while the
client is still in the room — and produces citation-backed planning artifacts afterwards.

The quality of a requirements document is set in the room, by whether the right follow-up question
got asked in the five seconds after a client said something vague. Miss it and the ambiguity
survives into the build, where it resurfaces as a change request at 10–50× the cost. That is not a
knowledge failure — the operator knows what to ask. It is an attention failure: they are
simultaneously listening, maintaining rapport, managing time, taking notes, and tracking coverage.

**Existing meeting AI solves the *recording* problem. Elicta solves the *elicitation* problem.**

---

## The core idea

> **The reasoning happens before the meeting; the meeting only does selection.**

The naive implementation streams the live transcript to a large model and asks for a good
follow-up question. That path costs 3–6 seconds — outside the conversational window — and it
degrades precisely under the conditions where it is most needed, because a stuffed context
inflates prompt processing.

Instead, a batch job runs the expensive analyst reasoning offline and emits a bank of
pre-reasoned, pre-phrased candidate questions. At runtime the system matches conversational state
against that bank. Matching is a retrieval-and-scoring problem measured in tens of milliseconds,
not an inference problem measured in seconds.

The consequence that shapes the whole build: **the highest-value trigger path contains no model
call at all.** Detecting an unquantified adjective is a lexicon scan; responding to it is a
template instantiation against a pre-written candidate.

```
Client stops speaking
  │
  ├─ Turn endpointing (Deepgram Flux, streaming) ─── ⚠ not ours, dominates
  ├─ Final turn emitted
  ├─ Speaker attribution ───────────────────────────  0ms managed / ~15ms fallback
  ├─ Lexicon scan (Aho–Corasick) ───────────────────  <5ms
  ├─ Parse check ───────────────────────────────────  ~10ms
  ├─ Bank retrieval (filtered) ─────────────────────  <20ms
  ├─ Scoring ───────────────────────────────────────  <5ms
  ├─ Slot instantiation ────────────────────────────  <5ms
  ├─ Rate-limit check + render ─────────────────────  ~20ms
  │
  └─ Nudge visible
```

Elicta's controllable contribution is **65–80ms** against a ≤2.0s p50 budget. The pipeline spends
its time almost entirely in speech endpointing, which is where optimisation effort goes — not into
micro-optimising ranking, which is already three orders of magnitude below the noise floor.

That lesson was learned the expensive way. An early build shortened the recognition window to cut
latency and made the transcript *worse* — the same 2.4 seconds of speech came back as
`"How are arrivals" / "Today at the death"` instead of `"How are arrivals booked in today at the
depot"`. A short window does not merely split a sentence, it mis-hears it, because the recogniser
has no context either side of the cut. The fix was not a shorter window but **no window**:
a streaming socket that endpoints on conversational turns.

Model-assisted triggers (contradiction detection, coverage-gap reasoning) run on a slow lane and
are deliberately kept off this path. A contradiction is worth surfacing thirty seconds late; a
vague adjective is not.

---

## What it is not

- **Not a transcription product.** Transcription is commodity input, not a differentiator.
- **Not a note-taker.** Notes are a by-product.
- **Not an autonomous agent.** It never speaks to the client, never joins as a participant that
  talks, and never sends anything on the operator's behalf without review.
- **Not a general-purpose chat assistant during the meeting.**

Precision is gated over recall throughout. A single suggestion that embarrasses the operator in
front of a client costs more than ten good ones earn, so a release candidate with a non-zero
embarrassment rate does not ship. Three excellent nudges per meeting beat twelve adequate ones.

---

## Repository layout

A polyglot monorepo — three toolchains, three package managers.

| Path | Stack | Contents |
|---|---|---|
| `core/crates/*` | Rust | Latency-critical plugin crates: `asr-live`, `bank`, `capture`, `coverage`, `language`, `ranking`, `slow-lane`, `trigger-gate`, `wer` |
| `core/shared/*` | Rust | Cross-cutting concerns: `app` (registry seam), `crypto`, `egress`, `health`, `session`, `telemetry` |
| `apps/desktop` | TypeScript / React 18 / Vite | Operator panel UI, on a hand-built Apple design-token layer |
| `apps/desktop/src-tauri` | Rust (Tauri 2) | Desktop shell — its own Cargo workspace |
| `apps/service` | Python 3.12 / FastAPI / SQLAlchemy | Context compiler, debrief engine, record-path transcription |
| `packages/api-client` | TypeScript | Generated from the service's OpenAPI schema — not hand-edited |
| `tests/e2e` | Rust + Python | Cross-cutting journey tests |
| `migrations/` | Python | Alembic revisions |
| `handbook/` | Python | The user guide, generated — chapters, diagrams and a bound PDF |
| `docs/` | — | PRD, architecture, runbook, journeys, audits |

The service exposes **63 API paths**: `/api/meetings` (21), `/api/engagements` (12),
`/api/sessions` (11), `/api/admin` (6), `/api/replay` (4), `/api/documents` (2), `/api/threads` (2),
plus `/api/artifacts`, `/api/audit`, `/api/bank`, `/api/operator` and `/api/service`.

---

## Getting started

**Prerequisites:** Rust (stable, verified on 1.96.1), Python 3.12 with
[`uv`](https://docs.astral.sh/uv/), Node ≥ 22.13 with pnpm 11.

```bash
cargo build --workspace --locked          # Rust workspace
cd apps/service && uv sync --locked       # Python service
pnpm install --frozen-lockfile            # Desktop
```

Run the service and the desktop app:

```bash
cd apps/service && uv run uvicorn app.main:app --reload   # serves 63 API paths
pnpm dev                                                  # tauri dev
```

Or run the whole system as a web app, reachable from other machines on the network — useful for
trying a build in a browser before packaging it:

```bash
./start.sh                    # service + panel on 0.0.0.0, dev server with hot reload
./start.sh --prod             # build the bundle and serve that instead
./start.sh --https            # serve over TLS, which is what the microphone needs
./start.sh --host 127.0.0.1   # this machine only
```

It prints the URLs to open, including the LAN addresses. The panel reaches the service through a
same-origin `/api` proxy, so nothing has to be reconfigured per host.

> **Microphone capture needs a secure context.** Browsers expose `navigator.mediaDevices` only
> over HTTPS or on `localhost`, so on a plain-HTTP LAN address the API is *absent* rather than
> blocked — there is nothing to permit and no prompt to accept. `--https` generates a self-signed
> certificate covering every address the machine answers on. The Capture screen says so rather
> than failing silently.

**State defaults to SQLite** under `ELICTA_STATE_DIR` (or `~/.elicta`) — no database server
needed. `DATABASE_URL` selects another target; the migration harness wants the `asyncpg` driver.

```bash
uv run --project apps/service alembic upgrade head         # apply
uv run --project apps/service alembic upgrade head --sql   # render SQL, no database needed
```

### Desktop bundle

```bash
./scripts/build-macos.sh              # host architecture
./scripts/build-macos.sh --universal  # arm64 + x86_64, as shipped
```

The bundle carries the service: somebody who opens the `.dmg` has no Python, so the FastAPI
service is frozen into a sidecar binary, declared as an `externalBin`, and started by the shell
when nothing is already answering on port 8000. Requires **Xcode 26+** — `screencapturekit`
vendors a Swift bridge over Metal 4.

---

## Configuration

Vendor credentials live in the **settings store, not the environment**. The desktop Settings
screen writes them over `PUT /api/admin/settings`; environment variables are a headless fallback
that a UI-set value overrides. Credentials are re-read per call, so a key entered in the UI takes
effect without a restart.

Secrets are **write-only** across that API: a read returns `configured` plus a four-character
hint, never the value, and the internal `SecretValue` type refuses to print itself, so a stray log
line cannot leak one. Secrets are encrypted at rest, with the key held outside the database.

- **Reasoning** — bring-your-own Anthropic key or OAuth token, with Bedrock, Vertex and Foundry
  available as routes back to in-tenant inference. The provider list is deliberately closed to
  Anthropic Messages API surfaces: structured outputs, cache-boundary control and the slow lane's
  request shape all assume it.
- **Speech** — a cloud model resolves its vendor key through the credential pool; a **local**
  model needs no key and targets an OpenAI-compatible `/v1/audio/transcriptions` endpoint, so a
  deployment can run Whisper or Parakeet on its own hardware and send no audio anywhere. Elicta
  does not run the model and ships no weights.
- **Documents** — uploaded directly, or linked from OneDrive/SharePoint through Microsoft Graph
  via an Entra ID app registration.

`.env.example` is the source of truth for variable names; [`docs/RUNBOOK.md`](docs/RUNBOOK.md)
carries the full reference table and the startup-validation contract.

Inference is an injected seam rather than an import. The default engine **raises** instead of
returning plausible output, so an unconfigured deployment fails honestly rather than looking
healthy while fabricating requirements.

---

## Testing

Tests live beside the code. The full suite is green:

| Suite | Command | Tests |
|---|---|---|
| Rust workspace | `MACOSX_DEPLOYMENT_TARGET=13.0 cargo test --workspace --locked` | 892 |
| Python service | `cd apps/service && uv run pytest` | 1452 |
| API integration (e2e) | `uv run --project apps/service python -m pytest tests/e2e/api_integration` | 340 |
| Desktop | `pnpm --filter elicta-desktop test` | 1130 |

Lint and type gates:

```bash
cargo clippy --workspace --all-targets -- -D warnings
cd apps/service && uv run ruff check .
pnpm --filter elicta-desktop typecheck
```

CI lives in [`.github/workflows/`](.github/workflows/). `test.yml` gates every language;
`parity.yml` checks cross-platform replay parity; `replay-gate.yml` enforces the precision and
embarrassment gates; `build.yml` produces Tauri artifacts.

The **replay harness** is engineering infrastructure, not a test suite. It replays transcripts
from meetings already run through the pipeline at wall-clock speed and logs every suggestion the
system would have surfaced, which is how precision and embarrassment are measured without ever
risking a client meeting.

Several journey tests exist because a green unit suite can still describe a product that does not
work — `stopSession.ts` was fully unit-tested against a stubbed `fetch` for weeks while the route
it posted to did not exist, because **a stub answers whatever URL it is handed**. The e2e journeys
ask the served schema and the running panel instead.

---

## Security and privacy

The posture is vendor-assurance-based rather than perimeter-based, because client audio
necessarily reaches named processors.

- **Two audited egress chokepoints** — one in the core for device-originated traffic, one in the
  service tier for its fan-out. Every outbound request is logged, and optional PII redaction is
  applied at these boundaries rather than scattered through call sites.
- **Minimal egress by construction.** The slow lane sends a rolling 60–90 second transcript
  window plus a structured state summary, once per minute. The full transcript is never sent.
- **A fully local speech path.** Pointed at a local recogniser, no audio leaves the machine.
- **At rest**, transcripts and artifacts sit in an encrypted database with the key in the platform
  keystore — macOS Keychain (`kSecAttrAccessibleWhenUnlockedThisDeviceOnly`), DPAPI / Credential
  Manager on Windows. Elicta writes no copy of the raw audio anywhere on the device; it is held
  only for as long as it takes to turn it into text.
- **Deletion is soft, everywhere it exists.** Engagements, documents and vocabulary carry
  `deleted_at`; a marked row stops loading and disappears from every list, and nothing erases.
- **Every processor** requires a DPA with no-training-on-customer-data terms, vendor-side
  retention set to zero or the minimum available, and residency pinned per engagement where
  supported.

The primary risk being managed is not exfiltration by an attacker but inadvertent over-collection.
Routing every outbound path through one of two logged chokepoints makes over-collection visible in
code review rather than discoverable in an audit.

---

## Project status

Pre-release and under active development. Delivery is phased, and **each phase carries a kill
criterion** — if a phase fails it, the next does not start:

| Phase | Scope | Kill criterion |
|---|---|---|
| 0 | Replay harness | None — this is the instrument, not the experiment |
| 1 | Prep and synthesis, no real-time | A senior BA rates the generated question tree worse than their own |
| 2 | Live coverage tracking | Operators report the coverage display as distracting in ≥2 of 5 pilots |
| 3 | Live ambiguity triggers (deterministic) | Precision below 70%, or any embarrassing suggestion |
| 4 | Generative suggestion (slow lane) | Same, after two tuning iterations |

Specifications are the source of truth for behaviour, and features cite them by ID
(`FR-5.4`, `NFR-3.1`). [`docs/journeys/`](docs/journeys/) carries one file per user journey, with
screenshots captured from the running app and a status table for each.

---

## Engineering notes

This codebase was produced by an autonomous coding-agent harness — 282 tasks in a single run —
then audited by hand and remediated. Both documents are kept as the record, because the failure
mode they describe is not specific to this project:

- [`docs/code-quality-audit.md`](docs/code-quality-audit.md) — **what** was wrong. The run
  completed 282 of 282 tasks with zero failures and produced a codebase that did not run. Almost
  every unit the specification asked for existed, to a genuinely high standard, and essentially
  none of them were wired together.
- [`docs/claw-forge-process-evaluation.md`](docs/claw-forge-process-evaluation.md) — **why**.
  Every task passed its own acceptance criterion; the criteria were satisfiable without
  integration, so integration never happened. The process did not fail. It succeeded exactly as
  specified, and the specification had a hole in it.

The gaps are closed — the suites above are green against a running process. The documents remain
as an argument about acceptance criteria: **assert quantity and real dispatch, not that a log line
was emitted.** An app serving zero routes passed the original check for months.

[`CLAUDE.md`](CLAUDE.md) carries the contributor-facing conventions and the accumulated gotchas —
the traps that cost somebody an afternoon, written down so they cost nobody a second one.

---

## Documentation

| Document | Purpose |
|---|---|
| [`docs/live-elicitation-assistant-prd.md`](docs/live-elicitation-assistant-prd.md) | Requirements, success metrics, release plan |
| [`docs/live-elicitation-assistant-architecture.md`](docs/live-elicitation-assistant-architecture.md) | Design, critical path, ADRs |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | Environment-variable reference and operations |
| [`docs/journeys/`](docs/journeys/) | One file per user journey, with screenshots and status |
| [`handbook/handbook.pdf`](handbook/handbook.pdf) | The user guide, bound as one document |
| [`docs/code-quality-audit.md`](docs/code-quality-audit.md) | Audit of what was built versus wired |
| [`CLAUDE.md`](CLAUDE.md) | Contributor orientation — conventions and gotchas |

---

## License

[MIT](LICENSE) © Bowen Li
