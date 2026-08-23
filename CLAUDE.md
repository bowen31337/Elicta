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
| `apps/desktop` | TS / React 18 / Vite / Tailwind | Panel UI (`src/features/panel/*`) |
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
cargo test --workspace --locked              # 839 tests, all green
cargo clippy --workspace --all-targets -- -D warnings
cargo test -p trigger-gate                   # single crate
```

Python service (`uv`, deps in `apps/service/uv.lock`):
```bash
cd apps/service && uv sync --locked
cd apps/service && uv run pytest             # 706 tests; testpaths = ["src"]
cd apps/service && uv run ruff check .
uv run --project apps/service python -m pytest tests/e2e/api_integration   # 45 tests, from repo root
```

macOS desktop bundle (`.app` + `.dmg`) — **build locally, not in CI**:
```bash
./scripts/build-macos.sh              # host arch only; what you want for testing
./scripts/build-macos.sh --universal  # arm64 + x86_64, as shipped
```
Needs **Xcode 26+**: `screencapturekit` vendors a Swift bridge over Metal 4, and
SDK 15 compiles most of it before failing. The script preflights that, the Node
floor and the Rust targets, then checks the result is loadable by dyld — the
published 0.1.0 passed the arch and signature checks and still could not start,
because Swift had back-deployed `libswift_Concurrency.dylib` to an `@rpath` with
no `LC_RPATH`. `bundle.macOS.minimumSystemVersion` (13.0) is what prevents that;
it also sets `MACOSX_DEPLOYMENT_TARGET`, so lowering it reintroduces the crash.

`build.yml` builds **macOS only** on push; the Windows jobs are gated behind
`if: inputs.windows` and are asked for explicitly:
```bash
gh workflow run build.yml -f windows=true
```
The macOS job runs on `macos-26` at 10x billing for ~35 min, and
`cancel-in-progress` means a second push kills the first run mid-flight. It
uploads an artifact rather than publishing a release; attaching a `.dmg` to a
release is a separate `gh release upload --clobber` step.

The Windows backends are `#[cfg(target_os = "windows")]`, so a Linux
`cargo test --workspace` never compiles them — the same blind spot applies to
the macOS ones. Cross-check them without a runner:
```bash
cargo check -p capture --target x86_64-pc-windows-msvc --all-targets
cargo check -p capture --target aarch64-pc-windows-msvc --all-targets
```
That type-checks the gated code but links nothing, so it catches trait and
signature breakage, not linkage or runtime behaviour.

Desktop (`pnpm`, Node >= 22.13):
```bash
pnpm install --frozen-lockfile
pnpm --filter elicta-desktop test              # 199 tests
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
cd apps/service && uv run uvicorn app.main:app --reload    # serves 50 API paths
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
  `persistence/models.py` owns the seven durable tables; `resolve_database_url`
  decides which database: a URL saved in Settings (secret `state_database_url`,
  shown back with the password stripped) beats `DATABASE_URL`, which beats a
  SQLite file under `ELICTA_STATE_DIR`. A change applies **on restart** — the
  collections are opened once and bound into `Backend`. Two traps: a
  `DurableMapping` only persists through `__setitem__`, so
  `x.setdefault(k, []).append(v)` writes to memory and nowhere else — reassign
  the whole list; and adding a column to a model without a matching revision
  fails `test_migrations`, which exists because such a column works on SQLite
  and is missing on PostgreSQL. Documents and vocabulary were classified as
  "rebuilt on demand" and were not — nothing rebuilds what somebody typed, and
  a live restart came back with zero of both.
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
- **A compile finishes in two visits, and something has to make the second.**
  The Analyst pass is submitted as a batch and collected minutes later;
  `fetch_batch` returns `[]` while it is still processing. `BankCollector`
  (`orchestration/bank_collector.py`) sweeps every 30s, and `main`'s lifespan is
  what starts it — deliberately not `build_app`, or every `TestClient` would
  poll a provider. It stops asking about a batch that ended, failed or expired,
  because the expensive mistake is polling for ever, not missing one. Watch for
  three traps that each made the bank silently empty: the submission guard once
  asked `_completed()` of a record whose only states are `SUBMITTED`/`FAILED`;
  collected candidates land in `analyst_passes` and the bank endpoint reads
  `compiled_candidates`, so `_store_compiled_candidates` joins them; and a
  stopped compile writes its reason to a stage record that nothing read until
  `log_compile_outcome`.
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
- **Formatting is not gated yet.** `cargo fmt --all --check` reports 328 hunks across 65 files
  and `ruff format --check` 94 files, all pre-existing. Both are deferred to their own
  mechanical commits; `test.yml` says where to re-enable the check.

## claw-forge Agent Notes

- State service: `http://localhost:8420` (per `claw-forge.yaml`)
- Report task complete: `PATCH /features/{id}` with `status=done`
- Request human input: `POST /features/{id}/human-input`
- Repo slash-commands live in `.claude/commands/`
- Feature agents leave a `HANDOFF.md` at the root when a task's footprint required touching
  shared scaffolding — read it before assuming a crate or module is unowned.
