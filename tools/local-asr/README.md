# A local Parakeet transcription server

**Not part of Elicta, and not shipped.** The product deliberately does not run a
speech model: no weights are in the bundle, there is no download, and the
Settings screen says so. What the live path does when `live_model` names a local
model is post each four-second window to an OpenAI-compatible transcription API
that somebody else is running. This is one of those, for a machine that wants
Parakeet and does not already have a server.

## Why this and not `speaches` or LocalAI

Those are the general answer and are the right one on Linux with a GPU. On an
Apple Silicon laptop they run Parakeet on CPU inside a Linux VM — the one
arrangement where the model is slowest, on the one path whose entire budget is
the conversational window. `parakeet-mlx` runs the same model on the Neural
Engine natively and ships no server, so the missing piece is exactly
`server.py`.

Measured on this host: 2.3 s of speech transcribed in **0.86 s**, first token to
last, against a four-second window budget.

## Running it

```bash
uv run --with parakeet-mlx --with fastapi --with uvicorn --with python-multipart \
  python tools/local-asr/server.py
```

Then in Elicta: **Settings → Speech → Live transcription model** → any Parakeet
entry, and **Local transcription server** → `http://127.0.0.1:8178/v1`. The lane
reports itself ready as soon as the address is saved; the model is read per
window, so neither setting needs a restart.

Options: `--model` (default `parakeet-tdt-0.6b-v2`), `--host`, `--port`
(default 8178).

## The first run downloads about 2.3 GB

Weights land in the HuggingFace cache (`~/.cache/huggingface/hub`), and later
runs start from disk in roughly two minutes.

**If the download stalls,** set `HF_HUB_DISABLE_XET=1`. HuggingFace's chunked
transfer hung at 2.2 GB of 2.3 GB on this host with the process at 0% CPU and
nothing in the log; plain HTTP resumed from the partial file and finished in
128 s. It is worth knowing because the failure looks exactly like a slow
network rather than a stuck one.

## What it will not do

- **It serves one model.** A request naming a different one is **refused**, not
  quietly transcribed with the loaded one. A server that substitutes silently is
  a server whose model dropdown is decoration, and an operator who switched
  models to fix a bad transcript would get the same bad transcript with nothing
  to explain why. Restart with `--model` to change it.
- **A failed transcription is an error, never an empty string.** Read as
  silence, a broken recogniser is a meeting that transcribes to nothing while
  every screen shows a working lane.
- **It does not authenticate and binds to loopback.** Client audio goes to it;
  that is the whole point of choosing a local model, and it should not be
  reachable from the network without thinking about it first.
