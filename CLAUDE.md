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

Desktop (`pnpm`, Node >= 20):
```bash
pnpm install --frozen-lockfile
pnpm --filter elicta-desktop test              # 199 tests
pnpm --filter elicta-desktop typecheck
pnpm --filter elicta-desktop build             # tsc --noEmit && vite build
pnpm dev                                       # tauri dev
pnpm generate:api-client                       # regenerate from the live service schema
```

Database migrations (Alembic, run from the repo root):
```bash
uv run --project apps/service alembic upgrade head         # apply
uv run --project apps/service alembic upgrade head --sql   # render SQL, no database needed
```
`DATABASE_URL` selects the target (see `.env.example`); it must use the `asyncpg` driver.

Run the service:
```bash
cd apps/service && uv run uvicorn app.main:app --reload    # serves 42 API paths
```

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
  a static credential.
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
