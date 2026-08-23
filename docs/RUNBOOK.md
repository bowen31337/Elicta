# Runbook — Environment Configuration

This page is the operator-facing reference for configuring the repo's
processes via environment variables. The source of truth for which
variables exist is `.env.example` at the repo root; this page explains what
each one does, whether it's required, and what happens if a required one is
missing.

## Setting up your environment

```
cp .env.example .env
```

Fill in the values you need, then start the process (`claw-forge`, or
`apps/service`). Never commit `.env` — it holds live credentials.

## Startup validation contract

Every process that reads environment variables validates its **required**
variables once, at startup, before doing any other work. If one or more
required variables are missing or empty, the process:

1. Does not partially start — it never begins serving requests or running
   agent turns with an incomplete configuration.
2. Prints a single error message naming every missing variable, for example:

   ```
   Missing required environment variable(s): ANTHROPIC_API_KEY
   ```

3. Exits with a non-zero status.

This turns a missing-credential mistake into an immediate, actionable error
at boot instead of a confusing failure the first time that variable would
have been used.

## Settings: the UI is the primary route

Vendor credentials and endpoints are administered in the desktop app's
**Settings** screen, which writes to the service over
`PUT /api/admin/settings`. Environment variables remain supported as a
**fallback** for headless deployments; a value configured in the UI wins over
the environment, and takes effect without restarting the service.

**Bring your own key or token.** Anthropic access is authenticated either with
an API key from the console (`X-Api-Key`) or with an OAuth token from
`claude setup-token` (`Authorization: Bearer`). The operator picks which in
the Settings screen; both can be stored, and the selected mode decides which
is live. The environment fallbacks are `ANTHROPIC_API_KEY` for the first and
`ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_OAUTH_TOKEN` for the second.

A bearer token also needs the `anthropic-beta: oauth-2025-04-20` flag that
unlocks it. The SDK adds that only for credentials it manages itself and skips
it when a static credential is supplied, so the service sets it — without it a
valid token returns a 401 that reads like a bad credential.

Secrets are write-only across that API. A read returns whether a credential is
configured and its last four characters — never the value — so the settings
form starts empty and leaving a field blank means "leave it unchanged".
Clearing a credential is a separate, explicit action.

**Storage.** Settings persist in SQLite at `ELICTA_SETTINGS_DB` (default
`$XDG_DATA_HOME/elicta/settings.db`). Secret values are encrypted at rest with
Fernet (NFR-2.5); the key comes from `ELICTA_SETTINGS_KEY`, or is generated
once into a `0600` file beside the database. Point `ELICTA_SETTINGS_KEY` at a
KMS or mounted secret in a managed deployment — the key file is the thing to
protect, and it is deliberately not kept inside the database it protects. A
secret that cannot be decrypted with the current key reads as *not configured*,
so a rotated key degrades to "re-enter your credentials" rather than a service
that will not start.

**AI provider.** Claude calls route through any of: Anthropic direct, AWS
Bedrock, Google Vertex AI, Microsoft Foundry, or any other endpoint that
speaks the Anthropic Messages API (a self-hosted or third-party gateway).

That list is closed to Messages-API surfaces on purpose. The compiler and
debrief stages depend on schema-enforced structured outputs (§14.4) and
explicit prompt-cache boundary control (§14.3), and `core/crates/slow-lane`
builds a Messages API request shape directly. An OpenAI-shaped endpoint would
not fail at configuration — it would fail per stage, in the middle of a
debrief — so it is not offered.

Bedrock and Vertex take no credential from settings: they authenticate through
the host's own chain (an IAM role, GCP application-default credentials), which
is a better mechanism than a long-lived key pasted into a form. Each provider's
required fields are validated on save, so a misconfiguration is a form error
rather than a stage failure hours later.

**Speech connectors.** The live path and the record path are configured
separately, because they are bought on different things: the live path on
turn-detection latency (§14.2), the record path on two engines diverging
independently (FR-2.6, T3). Any other speech service can be
configured as a custom connector with its own endpoint — it carries no
built-in feature mapping, so keyterm prompting and retention opt-out must be
confirmed against that vendor's API. Configuring the same vendor twice for the
record path is rejected — engines sharing a lineage agree on the same errors, so
reconciliation would manufacture false assurance.

The legacy in-memory store remains for tests. With it, settings do not survive a restart;
the Settings screen says so. A durable store belongs on the platform secret
store (`core/shared/crypto` already reaches the macOS Keychain and Windows
Credential Manager for the database key).

## Variable reference

| Variable | Required? | Used by | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | **Required** (unless `CLAUDE_CODE_USE_BEDROCK` or `CLAUDE_CODE_USE_VERTEX` is set instead) | claw-forge CLI; `apps/service` (context compiler, debrief engine — architecture §9 "Deployment") | Anthropic API key used to authenticate Claude Agent SDK / Messages API calls. |
| `ELICTA_INFERENCE_MODEL` | Optional — defaults to `claude-opus-5` | `apps/service` (context compiler, debrief pipeline) | Model used for the compiler and debrief stages (architecture ADR-012, §3.10). Only takes effect when one of the Anthropic auth routes above is configured; with none set those stages fail closed and name the missing setting. It fills the model until one is saved on the Settings screen, which then wins. Set it deliberately: a credential whose plan does not include the chosen model is refused with a 429 that carries no `retry-after` and never clears, which is reported as such rather than as ordinary throttling. |
| `ELICTA_GRAPH_TENANT_ID`, `ELICTA_GRAPH_CLIENT_ID`, `ELICTA_GRAPH_CLIENT_SECRET` | Optional — headless fallback; the Settings screen is the normal way in and a UI-set value overrides these | `apps/service` (reference-document connector, PRD FR-3.2) | An Entra ID app registration Elicta reads linked SharePoint, OneDrive and Teams documents as, needing `Files.Read.All` and `Sites.Read.All`. All three are required together: with any of them missing, attaching a link is refused with a 502 naming the missing setting rather than recording a document nothing can read. Uploading a file needs none of them. |
| `ELICTA_SESSION_STREAM_HOLD_SECONDS` | Optional — defaults to `300` | `apps/service` (`GET /api/meetings/{id}/session/stream`) | How long one live-session connection is held open before it is closed and the panel opens another. The stream used to close the moment it had nothing left to send, which `EventSource` reads as a dropped connection and retries after about three seconds — roughly twelve hundred reconnections in an hour-long meeting, each re-sending the frames the panel already had. Lower it below the idle timeout of whatever sits in front of the service (nginx's `proxy_read_timeout` defaults to 60s); a quiet connection sends a comment frame every 15s so an intermediary can tell it apart from a dead one. A value that is not a positive number is ignored in favour of the default. |
| `DATABASE_URL` | Optional — defaults to a SQLite file under `ELICTA_STATE_DIR` (or `~/.elicta`) | `apps/service`; `alembic upgrade` | Where engagement state is kept. Unset, the service uses a local SQLite file and needs no database server, which is what the desktop product ships with. Set it to opt onto PostgreSQL; the migration harness wants the `asyncpg` driver and the service strips that marker for its own synchronous access. A URL saved on the Settings screen (secret `state_database_url`) overrides this. Either way the change applies on restart — the collections are opened once at startup. Offline SQL rendering (`alembic upgrade head --sql`) needs no reachable database. |
| `CLAUDE_CODE_USE_BEDROCK` | Optional — alternate auth path for `apps/service` | `apps/service` | Routes Claude Agent SDK authentication through AWS Bedrock instead of a direct API key (architecture §9). Requires the usual AWS credentials in the environment. |
| `CLAUDE_CODE_USE_VERTEX` | Optional — alternate auth path for `apps/service` | `apps/service` | Routes Claude Agent SDK authentication through GCP Vertex instead of a direct API key (architecture §9). Requires the usual GCP credentials in the environment. |
| `MODEL_DEFAULT`, `MODEL_OPUS`, `MODEL_SONNET`, `MODEL_HAIKU`, `MODEL_FAST` | Optional | claw-forge CLI | Override the model aliases used by `claw-forge.yaml` without editing that file. Each falls back to a built-in default when unset. |
| `ANTHROPIC_OAUTH_TOKEN`, `ANTHROPIC_OAUTH_MODEL` | Optional | claw-forge CLI | Alternate to `ANTHROPIC_API_KEY` using a `claude setup-token` OAuth token. |
| `PROXY_API_KEY`, `PROXY_BASE_URL`, `PROXY_MODEL` | Optional | claw-forge CLI | Configures an Anthropic-Messages-API-compatible proxy provider. |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Optional | claw-forge CLI | Configures the OpenAI provider. |
| `OPENAI_COMPAT_API_KEY`, `OPENAI_COMPAT_BASE_URL`, `OPENAI_COMPAT_MODEL` | Optional | claw-forge CLI | Configures an OpenAI-compatible provider (Azure, Together, Fireworks, etc). |
| `GROQ_API_KEY`, `GROQ_MODEL` | Optional | claw-forge CLI | Configures the Groq provider. |
| `CEREBRAS_API_KEY`, `CEREBRAS_MODEL` | Optional | claw-forge CLI | Configures the Cerebras provider. |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | Optional | claw-forge CLI | Configures a local Ollama provider. |
| `ELICTA_DEEPGRAM_API_KEY` | Optional — one of the two ways in | `apps/service` (record-path ASR, FR-2.6) | API key for Deepgram, one of the two independent batch speech engines the record path runs (architecture §14.1-14.2). The Settings screen has no field for this key yet — it offers the live path's single ASR key only — so this variable and `PUT /api/admin/settings` are the two ways to supply it. A value saved through that endpoint overrides this one, and is re-read per call, so it takes effect without a restart. |
| `ELICTA_ASSEMBLYAI_API_KEY` | Optional — one of the two ways in | `apps/service` (record-path ASR, FR-2.6) | API key for AssemblyAI, one of the two independent batch speech engines the record path runs (architecture §14.1-14.2). The Settings screen has no field for this key yet — it offers the live path's single ASR key only — so this variable and `PUT /api/admin/settings` are the two ways to supply it. A value saved through that endpoint overrides this one, and is re-read per call, so it takes effect without a restart. |
