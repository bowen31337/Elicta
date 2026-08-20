# Live run — 20 August 2026

Screenshots and video of all twelve journeys **driven against a running
system**: the panel on `:1420`, the service on `:8000`, and real Anthropic and
Deepgram credentials.

**These are not the handbook's screenshots.** `../screenshots/` holds images
captured from `journeys.html`, which renders the real components against frozen
fixture state — right for documentation, because a screenshot that moves with
the clock makes every diff noise. The images here are the opposite: the live
app with nothing staged, which is why so many of them show empty screens.
Nothing in the handbook references this directory, and nothing should.

## What is here

| File | What it is |
|---|---|
| `report.md` | Every check, per journey, with the detail behind each failure |
| `report.json` | The same, machine-readable |
| `FINDINGS.md` | What the run found, and the root cause behind most of it |
| `deepgram-proof.json` | A live Deepgram transcript, captured outside Elicta |

**The video and screenshots are deliberately not committed.** A run produces
one directory per journey holding `journey.mp4` and the screenshots taken at
each labelled step — around 7 MB — and `.gitignore` excludes both under this
directory. They are evidence of one run against one machine, regenerable in a
few minutes, and git cannot prune them later without rewriting history. The
reports above are small enough to diff, so those are what is versioned.

If you have run the harness locally, the media sits beside these files. If you
have only cloned, it is not here; regenerate it as below. The caption bar along
the bottom of every frame is harness chrome, drawn over the app so a recording
explains itself.

## Result

52 checks passed, 34 failed. Journey 10 (setting up the services) was the only
one to pass completely.

Two defects account for nearly all of the failures. Writes and reads in the
service's composition root are bound to different fields, so most of what a
journey writes cannot be read back. And no speech-vendor client exists on
either path, so nothing is ever transcribed — `deepgram-proof.json` is there to
show the credential was not the constraint. `FINDINGS.md` has the detail.

## Reproducing

```bash
ELICTA_ANTHROPIC_TOKEN=… ELICTA_DEEPGRAM_KEY=… \
  node tests/e2e/journeys/live-run.mjs \
    --app http://<host>:1420 --api http://<host>:8000 --out <dir>
node tests/e2e/journeys/live-report.mjs <dir>
```

Secrets are redacted from every log line, report and filename; the run asserts
that a stored credential is never returned by the API.
