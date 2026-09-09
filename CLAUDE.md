# CLAUDE.md

## Project Overview

**Elicta** — a live requirements-elicitation assistant for client meetings. It listens to a
requirements meeting, tracks coverage against a template, detects ambiguity in the moment,
surfaces a follow-up question to the operator within the conversational window, and produces
citation-backed BMAD artifacts afterwards.

The one architectural idea to hold onto: **the reasoning happens before the meeting; the meeting
only does selection.** A batch job pre-reasons a bank of candidate questions; at runtime the
system matches conversational state against that bank (retrieval + scoring, tens of ms) rather
than calling a model (seconds). The highest-value trigger path contains no model call at all.

Specs are the source of truth for behaviour — features cite them by ID (`FR-5.4`, `NFR-3.1`):
- `docs/live-elicitation-assistant-prd.md` — requirements
- `docs/live-elicitation-assistant-architecture.md` — design + ADRs
- `docs/RUNBOOK.md` — env-var reference (`.env.example` is the source of truth for names)
- `docs/code-quality-audit.md` — audit of what is built vs wired, with the integration gaps
- `docs/journeys/` — one file per user journey, with screenshots captured from the running app

UI is built on the Apple design token layer (`apps/desktop/src/tokens.css`): reference
`var(--label)` / `var(--space-5)` and the `.t-*` type roles rather than hardcoding values. The
panel uses the `.glass` material; other screens use the `.group` / `.row` grouped-list idiom.
Both themes and the three `prefers-reduced-*` settings are handled at the token layer — do not
reintroduce hardcoded colors. Text colour comes from `--label` or
`--label-supporting`; `--label-secondary` / `--label-tertiary` fail WCAG AA for small text and are
for non-text use only. Coloured *text* uses `--green-ink` / `--orange-ink` / `--red-ink` /
`--accent-ink`; the vivid system colours are for fills. `tests/e2e/journeys/audit-a11y.mjs` gates
this in CI. Solve a colour against the **worst ground it is used on**
(glass composites darker than a card), and never let element `opacity` dim already-reduced ink —
both produced real AA failures here.
- `docs/claw-forge-process-evaluation.md` — root-cause analysis of why the seams were left empty

## Stack & Layout

Polyglot monorepo — three toolchains, three package managers.

| Path | Stack | What it is |
|---|---|---|
| `core/crates/*` | Rust | Latency-critical plugin crates: `asr-live`, `bank`, `capture`, `coverage`, `language`, `ranking`, `slow-lane`, `trigger-gate`, `wer` |
| `core/shared/*` | Rust | Cross-cutting: `app` (registry seam), `crypto`, `egress`, `health`, `session`, `telemetry` |
| `apps/desktop` | TS / React 18 / Vite | Panel UI (`src/features/panel/*`) |
| `apps/desktop/src-tauri` | Rust (Tauri 2) | Desktop shell — **its own Cargo workspace**, not the root one |
| `apps/service` | Python 3.12 / FastAPI / SQLAlchemy | Context compiler, debrief engine, record-path transcription |
| `packages/api-client` | TS | Generated from the service's OpenAPI schema — **do not hand-edit** |
| `tests/e2e` | Rust + Python | Cross-cutting journey tests (both languages) |
| `migrations/versions/` | Python | Alembic revisions (see gotcha below — not runnable yet) |

Root `Cargo.toml` mounts `core/crates/*` by glob, so a new crate needs no workspace edit.

## Build & Test

Rust (root workspace; toolchain via rustup, stable — verified on 1.96.1):
```bash
cargo build --workspace --locked
MACOSX_DEPLOYMENT_TARGET=13.0 cargo test --workspace --locked   # 892 tests, all green
cargo clippy --workspace --all-targets -- -D warnings
cargo test -p trigger-gate                   # single crate
```
**On macOS that environment variable is not optional.** Without it the `capture`
test binary aborts before running a line — `Library not loaded:
@rpath/libswift_Concurrency.dylib` — because Swift back-deploys the concurrency
runtime to an `@rpath` the binary carries no `LC_RPATH` for. It is the same
fault `bundle.macOS.minimumSystemVersion` prevents in the shipped app, and
`cargo test` has no `tauri.conf.json` to read that from. It fails the run
rather than one crate, so all 892 results are lost to one crate's link.
`cargo test -p capture --no-default-features` is the other way past it and
skips the ScreenCaptureKit backend.

Python service (`uv`, deps in `apps/service/uv.lock`):
```bash
cd apps/service && uv sync --locked
cd apps/service && uv run pytest             # 1385 tests; testpaths = ["src"]
cd apps/service && uv run ruff check .
uv run --project apps/service python -m pytest tests/e2e/api_integration   # 300 tests, from repo root
```

macOS desktop bundle (`.app` + `.dmg`) — **build locally, not in CI**:
```bash
./scripts/build-macos.sh              # host arch only; what you want for testing
./scripts/build-macos.sh --universal  # arm64 + x86_64, as shipped
```
**The bundle carries the service.** Somebody who opens the `.dmg` has no
Python, so `service_main.py` is frozen by `scripts/build-service-sidecar.sh`
into `src-tauri/binaries/elicta-service-<target>`, declared as an `externalBin`,
and started by the shell when nothing is already answering on port 8000. The
build reuses an existing binary; a missing one stops the bundler outright. The
freeze needs a `python3` and takes minutes.

**Every build gives itself a version number.** `scripts/build-macos.sh` runs
`scripts/bump-version.sh` (patch + 1; `--set X.Y.Z`, `--minor`, or `--no-bump`
for a deliberate rebuild of the same code). Before it, every artifact was
`Elicta_0.1.0_aarch64.dmg`, a rebuild overwrote the last one, and nothing on
disk said which build it was — which is how a stale install shadowed an
afternoon of rebuilds. **Three files carry the version and must move
together**: `tauri.conf.json` names the bundle and is what the updater
compares, `src-tauri/Cargo.toml` versions the shell binary, `package.json` is
what `pnpm` reports. Two agreeing and one not is a build whose artifact and
whose binary disagree about what they are; `src/__tests__/version.test.ts`
gates that. The script edits each file by its own anchored rule — a blanket
search-and-replace would move `Cargo.toml`'s dependency versions too.

**Staleness is pruned, not detected at the point of use.**
`scripts/prune-stale-builds.sh` runs first on every build and deletes a frozen
service older than anything it was built from, so the reuse check refreezes
rather than shipping the previous one. Its inputs are every Python file under
`apps/service` **plus** `uv.lock` and the freeze script — the two the old
check missed, either of which changes what is inside the binary with no `.py`
moving. It also clears bundles left from other versions.

Nothing of the operator's is removed. An install in `/Applications` and a
running service from another build are named with the command to deal with
each, behind `--remove-installed` and `--stop-running`; `--dry-run` says what
would go. That matters because a stale install is what shadowed a whole
afternoon of rebuilds: its service held port 8000, the shell adopts whatever
is already answering, and a panel built minutes ago ran against an API from
two days earlier. The shell refuses a service it cannot identify as its own
now (`GET /api/service/identity`), but refusing is not clearing.

There is no universal2 route: pydantic-core, cryptography, asyncpg, jiter,
rpds-py and cffi publish one wheel per architecture and none for universal2, so
`--universal` freezes each architecture and joins them with `lipo`, building the
second through Rosetta. Where Rosetta is absent the arm64 half ships alone and
says so.

Needs **Xcode 26+**: `screencapturekit` vendors a Swift bridge over Metal 4, and
SDK 15 compiles most of it before failing. The script preflights that, the Node
floor and the Rust targets, then checks the result is loadable by dyld — the
published 0.1.0 passed the arch and signature checks and still could not start,
because Swift had back-deployed `libswift_Concurrency.dylib` to an `@rpath` with
no `LC_RPATH`. `bundle.macOS.minimumSystemVersion` (13.0) is what prevents that;
it also sets `MACOSX_DEPLOYMENT_TARGET`, so lowering it reintroduces the crash.

`build.yml` **does not run on a push to main any more.** The macOS job costs an
hour of `macos-26` time at 10x billing, and one on every commit exhausted the
account's spending limit — after which builds refuse to start at all, with an
error about billing rather than about the build. It is now asked for:
```bash
gh workflow run build.yml                    # macOS only
gh workflow run build.yml -f windows=true    # and the Windows bundles
```
A tag push (`v*`) still builds, and so does a call from the signing workflow.
Restoring the automatic build is one line — `branches: [main]` under `push`.

Because nothing builds a bundle now until someone asks, **a change that only
breaks on macOS will sit unnoticed on main**. Three did in one day: a filename
case collision, and two packages with no universal2 wheel. `pnpm --filter
elicta-desktop test` covers the first (see `src/__tests__/fileCasing.test.ts`);
the others are only found by building.

The nastier version of this is a **Tauri window setting**, because there is no
build failure at all — the bundle is fine and one feature is silently dead.
`dragDropEnabled` defaults to true, which makes Tauri intercept OS file drags
before the page sees them, so the document dropzone worked in `pnpm dev`, in
`start.sh` and in every test, and did nothing in the `.dmg`. Where a setting
like that decides whether a feature works, assert the setting — the effect
cannot be reproduced anywhere the check can run
(`src/__tests__/dragDropConfig.test.ts`).

The macOS job runs on `macos-26` at 10x billing for ~35 min, and
`cancel-in-progress` means a second run kills the first mid-flight. It
uploads an artifact rather than publishing a release; attaching a `.dmg` to a
release is a separate `gh release upload --clobber` step.

The Windows backends are `#[cfg(target_os = "windows")]`, so a Linux
`cargo test --workspace` never compiles them — the same blind spot applies to
the macOS ones. Cross-check them without a runner:
```bash
cargo check -p capture --target x86_64-pc-windows-msvc --all-targets
cargo check -p capture --target aarch64-pc-windows-msvc --all-targets
cargo check -p capture --target aarch64-apple-darwin --no-default-features --all-targets
cargo check -p capture --target x86_64-apple-darwin --no-default-features --all-targets
```
That type-checks the gated code but links nothing, so it catches trait and
signature breakage, not linkage or runtime behaviour.

**macOS needs `--no-default-features`, and that is the whole point of the
`loopback` feature.** `screencapturekit` pulls in `apple-cf`, which vendors a
Swift bridge and shells out to `swiftc` from its build script — so a Linux
`cargo check --target aarch64-apple-darwin` dies before it reaches a line of
this repo. With the `ScreenCaptureKit` backend behind a default-on feature,
turning it off type-checks every other macOS path — the CoreAudio line-in
backend, input-device enumeration, the TCC permission shims — on the real
target, from anywhere. What stays uncheckable is `device/macos.rs` alone.

That is a development affordance, not a product configuration: every shipped
build takes the default and has the loopback backend. `available_kinds` drops
`Loopback` when the feature is off, so a build without it never offers a path
it cannot open.

Desktop (`pnpm`, Node >= 22.13):
```bash
pnpm install --frozen-lockfile
pnpm --filter elicta-desktop test              # 1013 tests
pnpm --filter elicta-desktop typecheck
pnpm --filter elicta-desktop build             # tsc --noEmit && vite build
pnpm dev                                       # tauri dev
pnpm generate:api-client                       # regenerate from the live service schema
```

**Does a recording actually reach the service?** Nothing in CI answers that — the
upload path is unit-tested piece by piece and joined only at runtime. `audio-upload.mjs`
runs the join: Chrome's fake capture device through the real `getUserMedia`, the real
chunk uploader, the real hold. It needs the service and the panel running, makes and
soft-deletes a meeting of its own, and from the moment Stop fires it spends real speech
credentials.
```bash
node tests/e2e/journeys/audio-upload.mjs                    # Chrome's test tone
FAKE_AUDIO=speech.wav EXPECT_WORDS="dashboard,depot" \
  node tests/e2e/journeys/audio-upload.mjs                  # and that words come back
```
A tone proves the bytes arrive and the sequence never gaps; only speech proves a
transcript. The file's header says how to generate a WAV — there is no fixture here.

**Does a nudge reach the panel?** Two tools, in order of what they measure.
`nudge-probe.mjs` posts to the same intake a recogniser posts to and reads the
session stream itself — the gate, the bank, the rate limit, no audio, nothing
billed. `panel-nudge.mjs` adds the last hop, the one the operator sees: it opens
the app in Chrome, picks the meeting through the toolbar, posts one vague line
and waits for *that* nudge's question to appear in the panel's markup on the
connection it already had.
```bash
node tests/e2e/journeys/nudge-probe.mjs --list           # which meetings there are
node tests/e2e/journeys/panel-nudge.mjs 37               # meeting-37, end to end
node tests/e2e/journeys/panel-nudge.mjs 37 --wait --act  # sit out the limit, tap the chips
node tests/e2e/journeys/panel-nudge.mjs 37 --quiet-check # a line that must NOT fire
```
Two things it deliberately does not accept as proof. A nudge already on the
meeting satisfies "is there a nudge?", so the check is bound to the id the POST
returned and to the previous card receding into history — consecutive nudges on
the same trigger can carry identical text. And `performance.getEntriesByType`
does not list an `EventSource`, so "did the panel connect?" is answered from
CDP's network events; asking the page reports a panel that never connected in
the same run in which it visibly received a nudge.

Database migrations (Alembic, run from the repo root):
```bash
uv run --project apps/service alembic upgrade head         # apply
uv run --project apps/service alembic upgrade head --sql   # render SQL, no database needed
```
State defaults to **SQLite** under `ELICTA_STATE_DIR` (or `~/.elicta`) — no database
server needed, and `.env.example` leaves `DATABASE_URL` commented out on purpose so
copying it does not silently opt a laptop onto PostgreSQL. `DATABASE_URL` (or the
`state_database_url` secret, which wins) selects another target; the migration
harness wants the `asyncpg` driver and the service strips that marker.

Run the service:
```bash
cd apps/service && uv run uvicorn app.main:app --reload    # serves 62 API paths
```

Run the whole system as a web app on `0.0.0.0` (service + panel, both processes, network-reachable
— for browser-testing a build before packaging):
```bash
./start.sh                  # dev server on :1420, service on :8000
./start.sh --prod           # build the bundle and serve it via `vite preview`
./start.sh --https          # serve over TLS, which is what the microphone needs
./start.sh --help           # ports, host, --reload, dependency handling
```
**Microphone capture in a browser needs a secure context.** Browsers expose
`navigator.mediaDevices` only over HTTPS or on `localhost`, so on a plain-HTTP
LAN address the API is *absent* rather than blocked — there is nothing to
permit and no prompt to accept, and the Capture screen says so. `--https`
generates a self-signed certificate in `.certs/` (gitignored) whose SAN list
covers every address the machine answers on, because a certificate for
`localhost` alone is rejected on the LAN address. The browser warns once that
it is not trusted. `vite.config.ts` reads `ELICTA_HTTPS_CERT`/`ELICTA_HTTPS_KEY`.
Capture prefers the Tauri commands when the shell is present and falls back to
`features/capture/browserCapture.ts` otherwise.
The panel is served same-origin with an `/api` proxy to the service (`vite.config.ts`), because
parts of the UI request `/api/...` relative to the page and the service mounts no CORS middleware.

CI: `.github/workflows/` — `test.yml` gates every language (cargo test + clippy, ruff + pytest +
the API integration suite, vitest + typecheck + build). `build.yml` produces Tauri artifacts,
`parity.yml` checks cross-platform replay parity, `replay-gate.yml` enforces the precision and
embarrassment gates, plus signing/release workflows.

## Conventions

- **Tests live beside the code.** `test_foo.py` next to `foo.py` in `apps/service`; `__tests__/`
  next to the component in `apps/desktop`. `pytest` only collects under `apps/service/src`.
- **`app/composition.py` is the composition root.** Routers are built by
  `build_*_router(...)` factories that take their persistence callables as arguments, so a
  router never reaches for a global. `composition.build_app` supplies them. **Adding a router
  means mounting it there** — it is not picked up automatically.
- **The API integration suite drives the production composition root.** `tests/e2e/api_integration/conftest.py`
  is a thin shim over `app.composition`, so the assembly the tests exercise is the one that
  ships. Do not re-create a parallel assembly in the suite; that is what drifted before.
- **`Backend` is the persistence surface**, in-memory by default so the API is reachable with no
  database. A SQLAlchemy-backed implementation substitutes at `create_app(backend=...)` and
  nowhere else.
- **`module_loader` is the second, narrower path.** It mounts already-constructed routers
  exposed from `app/modules/<name>/__init__.py`, for features needing no injection. Note the
  trap: `from .router import x` binds the *submodule* to the name `router`, so an `isinstance`
  check rejects it — expose `routers` (a list) if you use this path.
- **Ordered seams, append-only.** `core/shared/app/src/registry.rs` mounts all nine plugin
  crates and re-exports each one; add new crates as an appended block plus a `MOUNTED_CRATES`
  entry, so parallel work lands as independent hunks.
- **Vendor credentials live in the settings store, not the environment.** The desktop
  Settings screen writes them over `PUT /api/admin/settings`; env vars are a headless
  fallback that a UI-set value overrides. Secrets are **write-only** across that API — a read
  returns `configured` plus a four-character hint, never the value — and `SecretValue` refuses
  to print itself, so a stray log line cannot leak one. Credentials are re-read per call, so a
  key entered in the UI takes effect without a restart. Anthropic access is bring-your-own
  **key or OAuth token** — `build_anthropic_client` pairs each with its header, and a bearer
  token additionally needs `anthropic-beta: oauth-2025-04-20`, which the SDK does *not* add for
  a static credential. Settings persist in SQLite (`ELICTA_SETTINGS_DB`) with secrets encrypted
  at rest; the key lives outside the database (`ELICTA_SETTINGS_KEY`, else a `0600` file beside
  it), and an undecryptable secret reads as *not configured* rather than raising. The provider
  list (Anthropic / Bedrock / Vertex / Foundry / compatible gateway) is **closed to Anthropic
  Messages API surfaces** — structured outputs, cache-boundary control and the slow lane's
  request shape all assume it, so an OpenAI-shaped endpoint would fail per stage, not at setup.
- **Documents have two intake paths, and both must end in text.** An upload
  (`POST /engagements/{id}/documents`) carries its own bytes; a link
  (`.../documents/link`) is fetched from Microsoft Graph by
  `documents/graph.py`, whose credentials are an Entra ID app registration
  (`documents.tenant_id` / `documents.client_id` plus the
  `microsoft_graph_client_secret` secret; `ELICTA_GRAPH_*` are the headless
  fallback). `classify_reference_link_host` decides which hosts count and
  separates OneDrive from SharePoint by the `-my` tenant suffix. Both paths run
  `extract_text` and `index_document` — a document that lands in the list and
  in no index is invisible to retrieval depending only on how it arrived, which
  is what happened. **An unreadable link is refused, not attached**: attaching
  one with an empty body is what made `bank/compile` return an empty bank and
  read as a missing model. `extract_text` is stdlib-only (OOXML via `zipfile`,
  PDF via `zlib`) and is best-effort on PDFs — a scanned page yields nothing
  rather than noise.
- **State is SQLite by default, and everything an operator types is in it.**
  `persistence/models.py` owns the seventeen durable tables; `resolve_database_url`
  decides which database: a URL saved in Settings (secret `state_database_url`,
  shown back with the password stripped) beats `DATABASE_URL`, which beats a
  SQLite file under `ELICTA_STATE_DIR`. A change applies **on restart** — the
  collections are opened once and bound into `Backend`. Two traps: a
  `DurableMapping` only persists through `__setitem__`, so
  `x.setdefault(k, []).append(v)` writes to memory and nowhere else — reassign
  the whole list; and adding a column to a model without a matching revision
  fails `test_migrations`, which exists because such a column works on SQLite
  and is missing on PostgreSQL. Five collections have been moved out of the
  "rebuilt on demand" group after that classification turned out to mean "lost
  on restart": documents and vocabulary, because nothing rebuilds what somebody
  typed; consent records, because they describe a moment; and the record path's
  transcripts, alignments and audio-destruction events, because two of them
  *are* the transcript and NFR-2.4 destroys the audio the third describes. Ask
  what would actually rebuild a collection before leaving it off the store.
- **Deletion is soft, everywhere it exists.** Engagements, reference documents
  and vocabulary terms carry `deleted_at`; set, the row stops loading and
  disappears from every list, and nothing erases. Two traps: `_replace_children`
  rewrites a child list whole, so it must exclude marked rows or the mark lasts
  exactly one write; and `StateStore.soft_delete` deliberately does **not** take
  `self._lock`, because it is reached as a `DurableMapping.forget` which already
  holds it and `threading.Lock` is not reentrant — taking it deadlocked the
  process rather than raising. Real erasure is deliberately absent: it would
  have to decide about recordings, consent records and artifacts, and the PRD
  asks for none of it.
- **A citation is grounded by its quote, not by its offsets.**
  `citations/extraction.py` re-derives `start/end_char_index` from where
  `cited_text` actually occurs (nearest to the model's guess; whitespace runs
  match each other, because `extract_text` joins paragraphs with `\n` and models
  quote across them with a space), and stores the document's own text for that
  span. A quote the document does not contain still fails the whole run — that
  is the fabrication check and must stay. What no longer fails a run is model
  arithmetic: a pass of ~150 questions was lost live because a model quoted
  `…cross-dock.` and gave a span one character short of the full stop.
- **The compile an operator is waiting on sends no batch.**
  `submit_engagement_compile` takes a `route` and `composition.py` passes
  `"direct"`. Measured against the provider, every batch that *succeeded* took
  202s / 307s / 501s against a `BATCH_PATIENCE_SECONDS` window of 180 — so
  waiting first and drafting directly anyway was the slowest *and* dearest of
  the three routes: dead time, then a second pass, and the batch billed anyway
  when it finished. The batch route is untouched and stays the **library's**
  default; it is right for work nobody is waiting on, and a deployment with no
  `run_analyst` engine falls back to it. Two traps if you touch the wait:
  `batch_patience` is resolved at the call, never a default argument (as a
  default it made every test that submits a batch block for three minutes), and
  the poll must not sleep past its own deadline or the window is quietly longer
  than it says.
- **A batch compile finishes in two visits, and something has to make the second.**
  `fetch_batch` returns `[]` while the batch is still processing. `BankCollector`
  (`orchestration/bank_collector.py`) sweeps every 30s, and `main`'s lifespan is
  what starts it — deliberately not `build_app`, or every `TestClient` would
  poll a provider. It stops asking about a batch that ended, failed or expired,
  because the expensive mistake is polling for ever, not missing one. Traps that
  each made the bank silently empty: the submission guard once asked
  `_completed()` of a record whose only states are `SUBMITTED`/`FAILED`;
  collected candidates land in `analyst_passes` and the bank endpoint reads
  `compiled_candidates`, so `_store_compiled_candidates` joins them; a stopped
  compile writes its reason to a stage record that nothing read until
  `log_compile_outcome`, and `batch-collection` must read that reason off the
  *pass*, not off the submission that succeeded. **A batch has ended if anything
  came back at all, error or not** — but a pass that came back and does not meet
  the bank's contract is not an *answer*, so the caller redrafts directly and
  clears the passes first. And `_visit` must swallow its own exceptions: a
  restored batch whose `submitted_at` came back naive from SQLite raised
  `TypeError` out of `_expired` and stopped **every** engagement's bank from
  ever being collected. `composition.py` re-attaches UTC on the way out of the
  store; everything here is written aware.
- **Extended thinking spends the same budget the answer comes out of.** Every
  stage runs with it off (`NO_THINKING`): a 28k-character document reported
  `'NoneType' object has no attribute 'claims'` because the model thought for
  all 32,000 output tokens and the JSON came back cut mid-string. Extraction,
  structuring and the Analyst pass **stream** with `ANALYST_MAX_TOKENS =
  128_000` — measured, not chosen: the provider accepts it and refuses 200,000
  — and streaming is not a style choice, because the SDK refuses a
  non-streaming request whose budget implies more than ten minutes. A cap is
  not a spend, so sitting at the ceiling costs nothing. `MAX_TOKENS = 16000`
  remains for the short stages. And `parsed_output` is `None` when the answer
  does not fit the schema; reading straight through it is what produced that
  `AttributeError`, so it is named as an upstream failure instead.
- **What a compile did outlives the process that did it.** `compile_runs` and
  `bank_compiles` are in memory, so `compile_outcomes` (what the outcome
  endpoint reads) and `compile_batches` (the obligation the collector goes back
  for) are the durable halves. The third state is the one worth naming: a row
  whose `finished_at` is still null at the next launch was *running* when the
  process died, and is reported stopped, saying so. Reported running it is a
  spinner nobody can stop; reported never-run it is a lie about work that was
  done and billed. Find the latest by `started_at`, never by id — ids are
  sequential within a process and a restart resets the counter.
- **The Preparation screen polls, and its meter is an estimate that must not
  lie.** A compile takes minutes and the service reports only stage
  *boundaries*, about 25s / 20s / 2s / 210s apart — so `usePrep` re-asks every
  4s (a settled screen makes no requests) and `compileFraction.ts` weights the
  stages by how long they actually take and creeps within the current one
  against `started_at`. Reading it once at mount is what made a finished
  compile show 13% for five minutes; counting *stages* is what made the bar
  leap then sit. Three properties keep it honest, and a change that breaks one
  is a regression even if the tests pass: it never completes a stage the
  service has not reported (the creep is asymptotic), it never goes backwards,
  and it does not creep at all while `awaiting` — the job is with the provider
  and a bar advancing through a wait invents work. `awaiting` is deliberately
  **not** a stage for the same reason. The segments and the percentage must read
  the same value, not two kept in step; they were not, once. Notices carry three
  tones from `ui/notices.css` — red plus `role="alert"` for a stopped run,
  orange for one that drafted nothing, blue for work in progress.
- **The panel carries the meeting, not only the questions about it.** Three
  regions ride the one SSE stream now: `coverage`, `nudge` and `utterance`.
  The transcript needed nothing produced for it — `LiveUtterances` already
  recognises every window server-side and hands over the text with whoever the
  verifier believed said it, and both were read for the gate and dropped.
  `observe_utterance` records **before** the gate is consulted, because every
  early return below it (the operator's own speech, an utterance that fires
  nothing, a hit the rate limit refuses) is a line the panel must still show —
  and those are most of a meeting. Two traps: each line carries a `seq`,
  because the stream replays its whole backlog on every connect and two people
  can say the same short sentence an hour apart, so nothing in the text tells a
  replay from a repetition; and the stream follows the transcript on its own
  index beside the nudges', since a shared one would advance on every line
  spoken and skip the nudge that arrived while it did.
- **The transcript and the question are two columns, and the gate that splits
  them lives in a different file from the width it measures.** They cannot
  share a stream — an hour of speech is hundreds of lines and every one of them
  pushed the question further up the scroll, so they were merged for exactly
  one build. Split, what is lost is the reason to trust a suggestion, and that
  is carried by the question quoting the line it reacted to (`provokedBy`),
  not by adjacency. The layout is `@container panel (min-width: 52rem)` in
  `panel/route.css`, and **it had never once applied**: `shell.css` stages the
  panel as a card at `width: min(420px, 100%)`, so the container it asks about
  was 420px on every display ever built and the columns stacked on a 27-inch
  monitor exactly as they stacked on a phone. Nothing failed — no test went
  red, and the screenshots read as a deliberate one-column design. A container
  query is only as true as the box upstream lets that box be. So the stage is
  now a container too (`@container stage (min-width: 54rem)` — 52rem plus the
  panel's own `--panel-inset` on both edges), and
  `panel/__tests__/panelSplitReachable.test.ts` reads both numbers back out of
  the stylesheets and checks they still agree. Two traps, and they are the same
  trap: **a container cannot query itself.** A rule for `.panel` inside
  `@container panel` does nothing whatsoever, silently, which is how the
  columns shipped stacked once before; and `align-items` on `.pane-body--stage`
  inside `@container stage` did nothing either, which is why the panel's height
  is set with `align-self` on the *panel*. Both read as rules a browser had
  ignored for some other reason.
- **A client with tests is not a route.** The panel's Stop button posted to
  `POST /api/meetings/{id}/session/stop` from the day the recording bar
  shipped, and the service **never served that path** — the live-session router
  carried `session/start` and nothing else. Every press was a 404, which
  `useStopSession` turned into an `error` status that no part of the panel
  rendered, so the bar stayed on "Recording" with the clock running and the
  operator's only signal was the absence of one. `stopSession.ts` was fully
  unit-tested throughout, against a stubbed `fetch` — **a stub answers whatever
  URL it is handed**, so a green suite says nothing about whether a route
  exists. Two doc comments described the endpoint in the present tense,
  including one reasoning about what it does to a meeting. Written about
  nothing. The guards now are `tests/e2e/api_integration/test_stopping_a_meeting_from_the_panel.py`
  (which asks the served schema, not a stub) and the path inventory in
  `test_assembled_app.py` — note that inventory is maintained from the
  service's side only, so it agreed with itself about a route the desktop was
  already calling. **Ending a meeting is also two things and was one**: the
  session closes in the service, and the microphone is `services/captureSession`
  in this bundle. A stop that only posts leaves the device open and the chunks
  uploading, which is the identical symptom from a different cause. The device
  is released **first**, and released even when the post then fails — a session
  left open is recoverable by the next start; a recording nobody consented to
  continuing is not.
- **The live path's recogniser is one setting, and local models are a
  provider.** `ConnectorSettings.live_model` (`modules/settings/models.py`) is
  the live path's single selector: a cloud model resolves its Deepgram key
  through the credential pool, a local model needs no key and resolves
  `local_asr_base_url` instead. Model, then provider, then credential — one
  direction, which is what keeps this from re-opening the `live_vendor` bug
  where two places selected a vendor and disagreed. It was `model: str =
  "nova-3"` in `deepgram_live_recogniser`'s signature, a keyword default
  nothing passed, so the choice existed in Python and nowhere an operator
  could reach. Three traps. **Read it per call**, never bind it at assembly —
  the model is what somebody reaches for *because* the current one is failing,
  mid-meeting. **`.value`, never the enum member** — `LiveSpeechModel.NOVA_3`
  formats as `LiveSpeechModel.NOVA_3` in a query string, and the vendor 400
  reads as a broken credential. **`_live_transcription_ready` has to ask the
  right question**: a deployment running Whisper locally has no Deepgram key
  and never will, so gating the panel's lane frame on one reports the lane
  down while it works. Local transcription targets the **OpenAI-compatible**
  `/v1/audio/transcriptions` (`orchestration/local_transcription.py`) rather
  than whisper.cpp's native server, because that is the one surface taking a
  real `model` name and serving both Whisper and Parakeet — against a server
  that loads one model at startup the dropdown would be decoration, and the
  Settings screen says so. Elicta does not run the model and must not imply it
  does: no weights ship, and there is no download. And `keyterm` is Nova-3
  only, so the vocabulary is **dropped rather than sent to be ignored**, with
  the screen saying which models take it — a silently-inert setting is worse
  than one that is off.
  **Being unready has two remedies now, so the lane reports which.**
  `_live_transcription_blocker()` returns the reason and
  `_live_transcription_ready()` is `blocker() is None`, from the one branch —
  a reason computed separately from the flag is the gate-and-report drift that
  cost an evening, wearing a different hat. The panel prints what the service
  says. It used to carry one hardcoded sentence written when there was only
  one way to be unready, so an operator running Parakeet on their own machine
  was told *"No speech credential is configured"*: true, irrelevant, and
  pointing at the single action that would cost them money and change nothing.
  A misreported remedy is worse than no message.
  `tools/local-asr/` is a **development affordance, not a product feature**: a
  small OpenAI-compatible server around `parakeet-mlx`, so a Mac can run
  Parakeet on the Neural Engine rather than on CPU inside a container. Nothing
  in the bundle knows it exists. Two things it records: HuggingFace's chunked
  transfer stalls (`HF_HUB_DISABLE_XET=1` is the way past, and the failure
  looks like a slow network rather than a stuck one), and a one-model server
  **refuses** a model it has not loaded rather than substituting — silent
  substitution is what makes a model dropdown decoration.
- **The recording bar begins the meeting as well as ending it.** The panel
  could report a recording and stop one and not start one, and its own empty
  state said "Start the meeting on the Capture screen" — a navigation away
  from a client's face to press a button that could be in front of you.
  `useRecordingStart` is the same hook the Capture screen uses, so the consent
  gate is read the same way and `goLive` opens the device *before* it books a
  session. Start replaces Pause and Stop rather than joining them; a greyed
  Stop beside a Start is two controls saying one thing. And where consent is
  outstanding the reason **replaces** the button — a control that takes the
  press and then explains is worse than one that is not offered, especially
  the press made while somebody waits to start talking.
  **An optional argument in TypeScript is not optional to Tauri.**
  `openDevice(sourceId?)` passed `undefined` to `start_capture`, whose
  `source_id` is a bare `String`, and Tauri refuses the call before it runs —
  ``invalid args `sourceId` for command `start_capture` ``. Nothing caught it
  because every caller happened to hold a source: the Capture screen
  preselects `sources[0]` and passes it, and the panel's bar is the first
  caller with no picker. The store now resolves the default itself, to
  `sources[0].id ?? label` — the same rule the screen shows selected, so one
  press cannot open a different device from the one an operator would have
  seen chosen. Four store tests had faked a shell that listed **no** inputs
  and accepted a start anyway, which is a shell that does not exist and is
  what let the hole through.
  **The bar must also show `uploadNote`.** The store diagnoses three ways a
  recording runs and uploads nothing — the event channel refused, no way to
  read the samples, and the device open but delivering silence — each as a
  sentence with its remedy. The Capture screen has always shown them; the
  panel's bar showed none, which was survivable while the panel only reported
  somebody else's recording and is not now that it starts them. A meeting can
  otherwise run its full hour uploading nothing, with "Listening…" over a
  moving clock, and **the empty transcript is not a signal** — a quiet room
  looks identical.
- **Nothing checks the macOS Microphone permission.** `macos_line_in.rs` opens
  CoreAudio without consulting TCC, while the ScreenCaptureKit path checks
  Screen Recording via `screen_recording_permission()`. There is no
  microphone probe in `macos_permission.rs` at all — it would need an
  AVFoundation bridge (`AVCaptureDevice.authorizationStatus`). Denied or
  undetermined, CoreAudio starts and delivers silence with no error, which is
  a session booked, a clock running and `last_audio_at` staying null for ever.
  It matters more than it looks: the shipped bundle is **ad-hoc signed**
  (`TeamIdentifier=not set`), so a TCC grant is not reliably carried across
  rebuilds — a working build can stop hearing anything for a reason nothing
  in the product can currently report.
  **The failure it produces is silence, not an error, and the silence watch
  cannot see it.** `startSilenceWatch` counts *arrivals*; a muted input, a
  wrong input, or a refused permission still delivers buffers on schedule,
  full of zeros. Every count is met, the chunks upload, `receiving_audio` goes
  true, the lane reports it is transcribing, and the recogniser returns "" for
  every window — so `feed` skips them and no `utterance` frame is ever
  produced. Nothing anywhere is wrong. An operator watched "Listening…" over a
  moving clock beside an empty transcript for eight minutes. `startDeafWatch`
  is the second question — has any sample been **above zero** in the last 20s
  — and `ALL_SILENCE` names all three causes, because they are
  indistinguishable from the client. Two traps: the test is `peak > 0` and not
  a loudness floor, since a real microphone in a silent room always carries a
  noise floor and only a *digital* zero is diagnostic; and the two watches
  share one lifecycle (`startSilenceWatch` starts both) because **pause is
  supposed to be digitally silent** — separate lifecycles would have raised a
  false alarm on every pause.
- **One question about the microphone gets one answer for the whole panel.**
  The recording bar read "Listening…" over a running clock while the
  transcript header beside it read "Not capturing", at the same moment, about
  the same microphone. Neither reading was wrong — the bar preferred the local
  capture store, the header took the service's `receiving_audio`, and those
  disagree constantly and legitimately, since the service's is derived from
  when a chunk last arrived and lags both edges. The mistake was two
  expressions where one belonged. `listening` in `panel/route.tsx` resolves it
  once (a stop this screen made wins; then holding the device; then the
  service) and every region is handed the result. Tested as a **property** over
  every combination of the two inputs rather than as another example: the bug
  was not any one combination, so a case-by-case test would only have caught
  the case somebody thought of.
- **Coverage is measurable here**, `@vitest/coverage-v8`:
  `pnpm --filter elicta-desktop exec vitest run --coverage
  --coverage.provider=v8 --coverage.include='<glob>'`. It is worth running on
  a seam that has just gained a second caller. `useRecordingStart` sat at 81%
  branch with its *failure* paths uncovered, because the capture screen always
  had a picker, a source and a selected meeting in front of it; the panel's
  recording bar has none of those and walks exactly those branches. High
  coverage of the paths that work says nothing about the paths that report.
- **The live path's latency was the buffering, not the model.** Measured on a
  real machine: recognising a window costs ~0.2s, and the buffers either side
  cost five to nine seconds — the model was about four per cent of the wait,
  so no model swap could have fixed it. Two changes, in order. The **window**
  (`trigger/listener.py`) is 1s and the **upload chunk**
  (`chunkUploader.ts`) is 1s, and *equal lengths are the property*: at 5s
  chunks against a 4s window the remainder grew a second per chunk until two
  windows fired at once, so the lag oscillated instead of staying flat.
  `ELICTA_LIVE_WINDOW_SECONDS` tunes it without a rebuild, floored at one
  whole sample — a window shorter than one would spin the drain loop for ever.
  Then **Flux** (`orchestration/deepgram_flux.py`): a socket on `/v2/listen`
  that endpoints on turns, so a sentence arrives once, whole, instead of cut
  wherever the clock landed. Traps. The **model decides the transport** and it
  is not a preference — Flux is `/v2/listen`-only and a Nova model there never
  produces a turn — so `is_streamed` holds the mapping and
  `_live_lane_for` picks one lane, never both. An **injected `live_recogniser`
  outranks the setting**, or every test that supplies its own engine silently
  reaches Deepgram. Only `event: "EndOfTurn"` is a sentence somebody
  finished; `EagerEndOfTurn` and friends are guesses for a voice agent. And
  the transport is the one live-path setting that **cannot** be re-read per
  chunk: a socket carries a meeting, so it takes effect on the next one.
  What remains is the chunk — Deepgram wants 80ms and we post 1s to our own
  service.
  service.
  **The window went to 1s and came back.** Shortening it is the obvious move
  against latency and it was measured afterwards rather than before, which was
  the mistake — the same 2.4s of speech through Nova-3 came back as
  `'How are arrivals' / 'Today at the death'` at 1s and
  `'How are arrivals booked in today at the'` at 2s. A short window does not
  merely split a sentence, it **mis-hears** it ("depot" → "death"), because
  the recogniser has no context either side of the cut, and a gate reading
  that is worse than a gate reading nothing. So the window is 4s again and the
  latency is **not solved there**: it is solved by not having a window, which
  is what Flux does.
  **The recogniser sits inside the audio-chunk request**, and that is a known
  cost rather than a fixed one. Measured: chunk median 4ms, p95 over a second
  when a window completes. A `BackgroundLane` (queue + worker per meeting) was
  built to decouple it and **reverted** — under it, `_identify_speaker`'s
  `asyncio.to_thread` never resumed, so an enrolled deployment recorded no
  transcript at all, silently, with nothing logged. It is not needed at the
  current sizes: against Flux `on_chunk` is a socket send, and against a
  windowed model the recogniser fires once per 4s. Anyone re-attempting it
  must check `test_operator_enrolment.py` first — it is the only test that
  exercises identify-then-observe end to end, and it is the one that caught it.
  Finally, `LIVE_POLL_SECONDS` is a ceiling rather than a floor now:
  `_wake_watchers` signals every open panel the moment a line exists, and the
  timeout only catches a missed signal — the event is an accelerator, never a
  correctness requirement.
  **`_wake_watchers` must iterate a copy.** The set it walks is added to and
  removed from by every stream that opens or closes, so a panel disconnecting
  as a line is produced raises `Set changed size during iteration` — inside
  `observe_utterance`, inside the chunk handler, which swallows it. The
  visible symptom is a transcript that simply stops with nothing anywhere
  saying why: the exact failure the signal was added to make *faster*.- **A stream whose reader ends must be dropped, or it goes deaf in silence.**
  `FluxUtterances._read` said it left a failed stream "closed" for the next
  chunk to reopen and **nothing closed it**. When the vendor closed the socket
  — the ordinary case — the reader task ended, the entry stayed in
  `_streams`, `feed` went on sending into it happily, and not a word came
  back. A meeting transcribed two or three turns and then stopped for good,
  with audio still arriving and every part of the chain reporting success. The
  `finally` now drops it for *any* end, not only an exception, and checks
  `stream.reader is asyncio.current_task()` so it cannot race `close()`, which
  cancels the reader and has already taken the entry.
- **The delay an operator feels is when Flux decides a turn ended**, not the
  recognising, which is milliseconds. `eot_timeout_ms` defaults to **5000** at
  the vendor: whenever confidence does not cross `eot_threshold` the sentence
  sits unsent until five seconds of silence, and nobody in a meeting stops
  talking for five seconds. Elicta sends the vendor's **defaults** —
  `eot_threshold=0.7`, `eot_timeout_ms=5000` — tunable by env and **clamped
  to the documented ranges** — an out-of-range value is a 400 on the
  socket, which this lane reports as the vendor being unreachable and an
  operator reads as a broken credential. They were 0.6 and 1500ms for one build, tuned
  down for speed, and **that was the wrong lever**: a meeting came back as a
  column of one- and two-word lines — "two", "All", "Car", "Does", "So" —
  because almost every pause for breath was read as somebody finishing. The
  vendor's own words for the lower range are "faster responses, more false
  positives", and a false positive here is a turn ending mid-sentence; it also
  costs accuracy twice, since each fragment is then recognised with no context
  from the words before it. **The speed came from interim turns instead**, so
  there is nothing left to buy by ending a turn early and only coherence to
  lose. Measured after restoring them: hesitant speech with 1.8s and 1.6s
  pauses came back as three whole clauses rather than fragments.
- **A socket opened on demand needs a backoff, or one refusal becomes
  permanent.** `FluxUtterances` opens its socket from `feed`, a chunk arrives
  every 100ms, and a failed open raised into a handler that swallows it — so
  a single throttle, network blink or rotated key meant **ten connection
  attempts a second** at the vendor for the rest of the meeting, and the
  retries are what kept it refused. Now: 2s doubling to 30s, reset on a
  successful open, audio during the wait **dropped rather than queued**
  (there is nowhere for it to go, and the recording is banked before this lane
  sees a byte). And `backing_off()` reaches the panel's lane frame through
  `_lane_not_answering`, because a recogniser that has stopped answering is
  otherwise indistinguishable from a quiet room — ready credential, audio
  arriving, no line ever appearing.
- **The transcript renders as the room speaks, not a sentence at a time.**
  Flux narrates a turn as it forms (`Update`) and then confirms it
  (`EndOfTurn`); reading only the confirmation meant the screen sat blank
  through every sentence and printed it whole about a second after it ended.
  `turn_of` returns both, keyed on the vendor's `turn_index`. Three rules hold
  the design together. **Interim lines never reach the gate** — a question
  raised from half a sentence is worse than one raised a moment later — so
  `_observe_text` writes them straight to the transcript and only a final turn
  becomes an utterance. **A sentence is one line that grows**: `_hold_interim`
  rewrites the tail in place and `_drop_interim` takes it away for the final
  to land on the same `seq`, or a five-word sentence would arrive as five
  ever-longer lines. And **the panel is told which is which** (`final` on the
  frame), because showing unsettled text as settled quotes somebody on words
  they have not said yet; it is also why an interim line is not attributed —
  verification runs on the finished turn, against the audio the words came
  from. Trap: the stream must re-send a line when its *`final` flag* changes
  and not only its text. The final replaces the interim in place, so the
  length is unchanged and so is the text — comparing text alone emitted every
  interim and no settled line at all, and the transcript filled with sentences
  that never stopped claiming to be in progress.
  **And the panel has to accept a line it has already seen.** Its filing rule
  was `current[seq] !== undefined` — keep the first, ignore the rest — which
  was right for as long as a line could only arrive once: the stream replays
  the whole meeting on every connect, and ignoring a repeat is what makes a
  reconnect idempotent. A streaming recogniser broke that assumption without
  changing its shape. Keeping the first meant keeping the first *fragment*:
  the service held `"Hey. What's up?"` and the screen showed `"Hey, what's"`
  for the rest of the meeting, with every part of the chain working. The
  question is no longer "have I seen this index" but "is this newer" —
  `supersedes` takes a growing line and a settled one, and never lets a
  finished line be un-finished by a replayed interim.

- **The panel has two accounts of one microphone, and a snapshot is not an
  account.** The service's comes from audio it has received; the local
  `captureSession`'s, in the shell, is read **once, on mount** (`refresh()`
  adopts the Rust session) and never again. A panel that mounted before the
  recording started stays wrong for the rest of the meeting, and nothing says
  so: the bar reads "Listening…" from the service while the store believes it
  holds nothing, so the wave draws empty and Pause — offered only where there
  is something local to pause — is simply absent. That is what an operator
  reported, with no state on screen to explain it. The disagreement is now the
  trigger: `receivingAudio && !holdingTheDevice` re-asks the shell every 4s
  until they agree, and **only in that direction** — a store holding a device
  the service has not heard from yet is the ordinary first seconds of a
  recording. Two traps. `useCapture` returns a fresh object each render, so
  the effect depends on `microphone.refresh` (a `useCallback`) and never on
  `microphone`, or the interval is rebuilt every render and never fires. And
  `receiving_audio` **lags a stop by the freshness window**, so a stop that
  worked left the bar listening with the clock running for seconds — the exact
  appearance of one that did nothing; `stopStatus === 'stopped'` now wins over
  the derivation, because this screen released the device itself and knows
  better. `OperatorPanel` takes `captureStore` for the same reason it takes
  `createSource`: reaching for the module singleton is why the one state that
  mattered was the one no test could set up.
- **A question is two tiers everywhere it appears, and the short one is the
  point.** `stub` is the glance — at most five words, no verb, no question mark
  — and `phrasing` is what gets read aloud. The panel leads with the stub, the
  bank rail *is* stubs, and the Preparation screen shows both so a reviewer
  sees the form the room will get. A bank compiled before this carries no stub;
  `services/questionStub.ts` derives keywords from the phrasing on the client
  rather than the service defaulting one, deliberately — a server-side default
  would make a bank that would genuinely read better recompiled
  indistinguishable from one that would not. `stubFor` prefers a supplied stub
  whole and never re-derives it: a model-written stub reads better than
  anything lifted mechanically out of a sentence.
- **`app/orchestration/` owns pipeline order.** `debrief.py` runs architecture §7 steps 2–8,
  `compiler.py` runs §3.10; `composition.py` decides *when* they run. Stages fail closed — a
  failed stage halts the chain rather than feeding the next one. Add a stage to the orchestrator,
  not to a caller somewhere else.
- **Inference is an injected seam, never an import.** Stages take `clean`/`translate`/`classify`
  callables; `orchestration/engines.py` supplies them. The default raises rather than returning
  plausible output, so an unconfigured deployment fails honestly instead of looking healthy.
- **The startup log is the route table.** There is no hand-maintained route list.
- **Acceptance criteria must fail on the empty case.** `test_main.py` asserts route *counts* and
  real dispatch, not that a log line was emitted — an app serving zero routes passed the old
  check for months. Assert quantity, not mechanism.

## The Handbook

`handbook/` is the **user guide** — for the people who use Elicta, not the people who
build it. It carries no description of the internals, and that is enforced: a prose
chapter may contain no links and no requirement identifiers, and technical content
belongs in this file or `docs/` instead. Chapters show real screens from
`docs/journeys/screenshots/`, embedded in the PDF.

It is still generated code. One chapter (*What Works Today*) is derived from the status
tables in `docs/journeys/*.md`; the rest are hand-written and each declares, in
`handbook/book.toml`, the paths it describes — mostly the screens it shows.

```bash
python3 handbook/tools/gen.py build     # chapters, index, footers and the PDF
python3 handbook/tools/gen.py check     # errors block CI, warnings ask a human
python3 handbook/tools/gen.py status
python3 handbook/tools/gen.py pdf       # rebuild handbook/handbook.pdf alone
python3 handbook/tools/gen.py accept --chapter <id>
cd handbook/tools && python3 -m unittest   # pytest does not collect these
```

- **A change to a screen puts the chapter that shows it into drift**, and a change to a
  journey's status table makes the generated chapter stale. `check` fails on the latter
  until `build` is re-run — the `handbook` job in `test.yml` enforces it, and a `Stop`
  hook in `.claude/settings.json` enforces it per session.
- **Drift on a screen usually means the screenshot is out of date**, which no check can
  see. Look at the picture, not just the words.
- **Never edit a file carrying `<!-- HANDBOOK-GENERATED -->`.** Change the source or the
  renderer; the next `build` reverts anything else.
- **Prose chapters own everything above `<!-- HANDBOOK-NAV -->`;** `build` owns the rest.
- **`accept` is a claim that a human re-read the chapter.** `build` deliberately never
  writes `handbook/drift.lock.json`. Baselining to clear warnings empties the mechanism.
- **`BANNED_CLAIMS` in `handbook/tools/lint.py`** lists statements known false here (the
  `run.sh` commands, formatting being gated, counting routes off `app.routes`, literal
  imports of hyphenated modules). A chapter warning readers about one adds
  `<!-- lint-allow: <tag> -->`; nobody deletes the entry to go green.
- **`build` also writes `handbook/handbook.pdf`** — the whole handbook bound as one
  document, typeset by `mdread.py` / `typeset.py` / `pdf.py`, which write the PDF
  format directly because nothing else here can (no pandoc, no browser, no LaTeX,
  and CI installs only Python). The file records a digest of its sources in its
  own metadata, so `build` rewrites it only when the content or the layout code
  changed; `check` reports `stale-pdf` when it did not. Mermaid diagrams appear as
  captioned source, not pictures.
- **The handbook is written for readers outside the team**, and the PDF is how they
  read it. Two rules are gated, not merely advised: a prose chapter may contain **no
  links** (`cross-reference`) and **no requirement identifiers, architecture section
  numbers or decision-record numbers** (`spec-reference`). Say the thing in words
  where the reader is. The one chapter that must show an identifier marks itself with
  `<!-- lint-allow: spec-reference -->`. Citations in doc comments are stripped from
  generated chapters by `render.plain_summary`.
- **Diagrams are drawn, not printed as source.** Use a ` ```diagram ` block —
  `steps`, `flow`, `timeline`, `compare` or `stack` — which `diagrams.py` renders as
  a real picture. Mermaid still renders as a source panel and should not be used in
  new chapters.
- **Screenshots are embedded, not linked.** `images.py` reads PNGs with stdlib zlib
  only; `pdf.py` embeds them. Blank space at the foot of a screenshot is cropped with
  a clipping path, so the file is never modified.
- **Generators that describe the internals still exist but are unmounted**, listed in
  `generators.UNMOUNTED` with a reason. A test asserts every generator is either
  mounted in `book.toml` or declared there, so nothing is silently wired to nothing.
- `/handbook-sync` walks the whole post-feature pass.

## Gotchas

- **`run.sh` is boilerplate from another project.** It references `frontend/`, `backend/`,
  `main.py` and a trading daemon — none exist here. Only the secrets/no-secrets split is
  instructive (package managers and linters must never run under `op run`). Don't trust its
  commands; use the ones above.
- **Service module dirs are hyphenated** (`asr-record`, `live-session`, `slow-lane`) and are
  only reachable via `importlib.import_module()`. A literal `import` of them is a syntax error.
  `composition.py` imports those three that way.
- **A new module needs `__init__.py`** — without it `pkgutil` does not report it as a package
  and `module_loader` never sees it. `engagement` and `replay` were invisible this way.
- **A DTO between a write and a read drops what it does not declare, silently.**
  Pydantic's default `extra` policy is `ignore`, so `BankCandidate(..., stub=x)`
  against a model with no `stub` field raises nothing, type-checks, and loses
  the value. That is how the panel's glanceable tier stayed empty for every
  candidate ever compiled: `_store_compiled_candidates` wrote `stub`, the store
  read `row.stub`, and the model between them never mentioned it — 554
  candidates on a real state file, 554 empty stubs. It is the documented
  write-path/read-path split one level subtler, because here both paths agree
  on the name. When adding a field to a compiled candidate, add it to **both**
  `compiler/api/models.py` and `compiler/bank/models.py` and to
  `get_base_candidates` in `composition.py`, which rebuilds each candidate
  field by field across the package boundary.
- **Duplicate test basenames across modules** (`test_router.py`, `test_service.py`,
  `test_recompile.py`, …) collide under pytest if a package is missing `__init__.py`. Run the
  **full** service suite after adding one, not just your own directory.
- **`FastAPI.routes` under-reports.** This version wraps included routers in `_IncludedRouter`
  objects carrying no `.path`, so walking `app.routes` reports zero however many are mounted.
  Count from `app.openapi()["paths"]` instead.
- **Two `BankCandidate` / `InheritedOpenQuestion` types exist** — one under `compiler/api`, one
  under `compiler/bank`. They are different models; `composition.py` imports the `api` pair
  under aliases. Check which package a router belongs to before importing.
- **`apps/desktop/src-tauri` has `[workspace]` with no members** on purpose, to stop Cargo's
  upward manifest search. Keep it; removing it breaks the build.
- **`.gitignore` un-ignores two paths** (`apps/desktop/src/features/panel/coverage/`,
  `core/crates/coverage/`) that the generic `coverage/` rule would swallow. New `coverage`-named
  paths need the same treatment.
- **Formatting is not gated yet.** `cargo fmt --all --check` reports 352 hunks
  and `ruff format --check` 145 files, all pre-existing. Both are deferred to their own
  mechanical commits; `test.yml` says where to re-enable the check.

## claw-forge Agent Notes

- State service: `http://localhost:8420` (per `claw-forge.yaml`)
- Report task complete: `PATCH /features/{id}` with `status=done`
- Request human input: `POST /features/{id}/human-input`
- Repo slash-commands live in `.claude/commands/`
