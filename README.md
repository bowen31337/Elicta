# Elicta

**A live requirements-elicitation assistant for client meetings.**

Elicta listens to a requirements meeting, tracks coverage against a template, detects ambiguity
in the moment, surfaces the follow-up question the operator would have wished they asked — while
the client is still in the room — and produces citation-backed BMAD planning artifacts afterwards.

The quality of a requirements document is set in the room, by whether the right follow-up question
got asked in the five seconds after a client said something vague. Miss it and the ambiguity
survives into the build, where it resurfaces as a change request at 10–50× the cost. That is not a
knowledge failure — the operator knows what to ask. It is an attention failure: they are
simultaneously listening, maintaining rapport, managing time, taking notes, and tracking coverage.

Existing meeting AI solves the *recording* problem. Elicta solves the *elicitation* problem.

---

## The core idea

**The reasoning happens before the meeting; the meeting only does selection.**

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
  ├─ VAD silence detection ──────────────────── 0ms   (already running)
  ├─ ASR endpoint wait ──────────────────────── 500–800ms   ⚠ not ours
  ├─ Final transcript emitted
  ├─ Speaker attribution ───────────────────── 0ms managed / ~15ms fallback
  ├─ Lexicon scan (Aho–Corasick) ────────────── <5ms
  ├─ Parse check ────────────────────────────── ~10ms
  ├─ Bank retrieval (filtered) ──────────────── <20ms
  ├─ Scoring ────────────────────────────────── <5ms
  ├─ Slot instantiation ─────────────────────── <5ms
  ├─ Rate-limit check + render ──────────────── ~20ms
  │
  └─ Nudge visible ──────────────────────────── ~565–880ms total
```

Elicta's controllable contribution is **65–80ms** against a ≤2.0s p50 budget. The pipeline spends
its time almost entirely in ASR endpointing, which is where optimisation effort goes — not into
micro-optimising ranking, which is already three orders of magnitude below the noise floor.

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
| `apps/desktop` | TypeScript / React 18 / Vite / Tailwind | Operator panel UI |
| `apps/desktop/src-tauri` | Rust (Tauri 2) | Desktop shell — its own Cargo workspace |
| `apps/service` | Python 3.12 / FastAPI / SQLAlchemy | Context compiler, debrief engine, record-path transcription |
| `packages/api-client` | TypeScript | Generated from the service's OpenAPI schema — not hand-edited |
| `tests/e2e` | Rust + Python | Cross-cutting journey tests |
| `migrations/` | Python | Alembic revisions |
| `docs/` | — | PRD, architecture, runbook, audits |

The service exposes 42 API paths across nine groups — `/api/meetings` (15), `/api/engagements`
(10), `/api/sessions` (7), `/api/replay` (4), `/api/admin` (2), plus `/api/artifacts`,
`/api/audit`, `/api/bank`, and `/api/documents`.

---

## Getting started

**Prerequisites:** Rust (stable, via rustup — verified on 1.96.1), Python 3.12 with
[`uv`](https://docs.astral.sh/uv/), Node ≥ 20 with pnpm 11.

```bash
# Rust workspace
cargo build --workspace --locked

# Python service
cd apps/service && uv sync --locked

# Desktop
pnpm install --frozen-lockfile
```

Run the service and the desktop app:

```bash
cd apps/service && uv run uvicorn app.main:app --reload   # serves 42 API paths
pnpm dev                                                  # tauri dev
```

Or run the whole system as a web app, reachable from other machines on the network — useful for
trying a build in a browser before packaging it for macOS, Windows or Linux:

```bash
./start.sh                    # service + panel on 0.0.0.0, dev server with hot reload
./start.sh --prod             # build the bundle and serve that instead
./start.sh --host 127.0.0.1   # this machine only
```

It prints the URLs to open, including the LAN addresses. The panel reaches the service through a
same-origin `/api` proxy on the web port, so nothing has to be reconfigured per host. Capture,
signature verification and update checks come from the desktop shell and are unavailable in a
browser; those screens say so rather than failing.

Apply database migrations from the repository root:

```bash
uv run --project apps/service alembic upgrade head         # apply
uv run --project apps/service alembic upgrade head --sql   # render SQL, no database needed
```

`DATABASE_URL` selects the target and must use the `asyncpg` driver. The service starts without a
database — persistence defaults to an in-memory backend so the full API is reachable — and a
SQLAlchemy-backed implementation substitutes at the composition root.

---

## Configuration

Vendor credentials live in the **settings store, not the environment**. The desktop Settings
screen writes them over `PUT /api/admin/settings`; environment variables are a headless fallback
that a UI-set value overrides. Credentials are re-read per call, so a key entered in the UI takes
effect without a restart.

Secrets are **write-only** across that API: a read returns `configured` plus a four-character
hint, never the value, and the internal `SecretValue` type refuses to print itself, so a stray log
line cannot leak one.

`.env.example` is the source of truth for variable names; `docs/RUNBOOK.md` carries the full
reference table and the startup-validation contract. Anthropic access is bring-your-own key or
OAuth token, with Bedrock and Vertex available as routes back to in-tenant inference.

Inference is an injected seam rather than an import. The default engine **raises** instead of
returning plausible output, so an unconfigured deployment fails honestly rather than looking
healthy while fabricating requirements.

---

## Testing

Tests live beside the code. The full suite is green:

| Suite | Command | Tests |
|---|---|---|
| Rust workspace | `cargo test --workspace --locked` | 839 |
| Python service | `cd apps/service && uv run pytest` | 706 |
| API integration (e2e) | `uv run --project apps/service python -m pytest tests/e2e/api_integration` | 45 |
| Desktop | `pnpm --filter elicta-desktop test` | 199 |

Lint and type gates:

```bash
cargo clippy --workspace --all-targets -- -D warnings
cd apps/service && uv run ruff check .
pnpm --filter elicta-desktop typecheck
```

CI lives in `.github/workflows/`. `test.yml` gates every language; `parity.yml` checks
cross-platform replay parity; `replay-gate.yml` enforces the precision and embarrassment gates;
`build.yml` produces Tauri artifacts.

The **replay harness** is engineering infrastructure, not a test suite. It replays transcripts
from meetings already run through the pipeline at wall-clock speed and logs every suggestion the
system would have surfaced, which is how precision and embarrassment are measured without ever
risking a client meeting.

---

## Security and privacy

The posture is vendor-assurance-based rather than perimeter-based, because client audio
necessarily reaches named processors.

- **Two audited egress chokepoints** — one in the core for device-originated traffic, one in the
  service tier for its fan-out. Every outbound request is logged, and optional PII redaction is
  applied at these boundaries rather than scattered through call sites.
- **Minimal egress by construction.** The slow lane sends a rolling 60–90 second transcript
  window plus a structured state summary, once per minute. The full transcript is never sent.
- **At rest**, transcripts and artifacts sit in an encrypted database with the key in the platform
  keystore — macOS Keychain (`kSecAttrAccessibleWhenUnlockedThisDeviceOnly`), DPAPI / Credential
  Manager on Windows. Raw audio is never written to disk on the device.
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
(`FR-5.4`, `NFR-3.1`).

---

## Documentation

| Document | Purpose |
|---|---|
| [`docs/live-elicitation-assistant-prd.md`](docs/live-elicitation-assistant-prd.md) | Requirements, success metrics, release plan |
| [`docs/live-elicitation-assistant-architecture.md`](docs/live-elicitation-assistant-architecture.md) | Design, critical path, ADRs |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | Environment-variable reference and operations |
| [`docs/code-quality-audit.md`](docs/code-quality-audit.md) | Audit of what is built versus wired |
| [`CLAUDE.md`](CLAUDE.md) | Contributor orientation — conventions and gotchas |

---

## License

This repository is private and carries no open-source licence. All rights reserved.
