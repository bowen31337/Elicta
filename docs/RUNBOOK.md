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

## Variable reference

| Variable | Required? | Used by | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | **Required** (unless `CLAUDE_CODE_USE_BEDROCK` or `CLAUDE_CODE_USE_VERTEX` is set instead) | claw-forge CLI; `apps/service` (context compiler, debrief engine — architecture §9 "Deployment") | Anthropic API key used to authenticate Claude Agent SDK / Messages API calls. |
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

`apps/service` does not yet have external ASR-vendor or database
credentials in this table — the managed-capture and ASR vendor selections
are an open decision (architecture D4, Phase 2) and the question bank runs
on local SQLite (architecture §3). This table will grow as those components
land; keep it in sync with `.env.example` when they do.
