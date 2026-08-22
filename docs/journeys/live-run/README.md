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

**72 checks passed, 17 failed** — 21 August 2026, against a clean state
database, a real Anthropic OAuth token, no Deepgram key, and
`claude-haiku-4-5-20251001` saved in Settings. Journeys 2, 5, 6 and 10 pass
completely; journey 1 passes 16 of 17.

Earlier runs scored 52/34, 61/22, 56/28, 65/19 and 70/19. They are not
comparable without reading what was configured each time — which is what this
section is for, and the count of *questions asked* has moved too. Journey 5
went from 4 checks to 8, because the four it had never exercised degraded mode
at all; journey 6 and journey 9 each gained one, for reasons worth stating:

* Journey 6 asked only that the agreement figure was not the string `0%`. That
  would have gone green the moment the screen started rendering an em dash,
  which is not "reporting how far the engines agreed" either. It now accepts a
  figure *or* an explicit "nothing was compared", and rejects everything else.
* Journey 9 never looked at how much evidence the two release gates rest on. It
  had photographed "100%" in green, over one rating, and passed.

Both are the same lesson the repository already had written down: an acceptance
criterion has to fail on the empty case.

**Two things about *running* it, both of which cost a run to learn:**

* **The model is read from Settings, and Settings wins.** `ELICTA_INFERENCE_MODEL`
  is the headless fallback; a value saved through the API or the UI overrides it
  and persists in the settings database. A run against a *fresh* settings
  database with no model saved falls back to the default, `claude-opus-5`, which
  this credential may not use — it answers 429 with no `retry-after`. That
  dropped journey 7 from 8/6 to 4/10 and looked exactly like a code regression
  in the debrief conversation. Save the model before the run, and check
  `GET /api/admin/settings` says what you think it does.
* **The browser profile used to persist between runs.** Chrome was launched with
  no `--user-data-dir`, so it kept its default profile — and the toolbar keeps
  the chosen engagement and meeting in `localStorage`. Against a fresh state
  database the picker opened holding an id the service had never heard of, and
  journey 1 failed on "the engagement can be chosen from the toolbar" with the
  *previous* run's id in the failure message. Each run now gets a throwaway
  profile that is deleted with it.

**What is left, and why none of it is a broken build:**

* **The question bank cannot be drafted on this credential.** The token reaches
  `POST /v1/messages` (200) and is refused on `POST /v1/messages/batches` with
  `permission_error: OAuth token does not meet scope requirement
  any_of(user:batch, user:developer, workspace:developer, workspace:inference)`.
  The Analyst pass is a batch job, so it cannot be submitted at all. Everything
  either side of it — reading documents, extracting claims, structuring them,
  and the collector that goes back for a finished batch — is built and tested,
  and none of it can be shown live here. That is journey 1's one failure.
* **That refusal is now also journey 5's best evidence.** It is a real upstream
  failure across a real seam, on a credential that is otherwise fine, so it is
  the one honest way to exercise the degraded path live. Journey 5 asserts it
  does *not* move the panel: drafting the bank is a batch workload on a
  different entitlement from the slow lane the badge speaks for. It did move it
  the first time this ran, which is how that was found.
* **No speech vendor client exists** on either path, so nothing is transcribed;
  `deepgram-proof.json` shows the credential was never the constraint. Journey 4
  additionally had no Deepgram key configured in this run.
* **Consent is not asked for in this build.** `DEFAULT_CONSENT_MODEL` is
  `ENGAGEMENT_LEVEL`, so the gate answers `not_required`, capture is admitted
  with nothing confirmed, and no `ConsentRecord` is written. Journey 2 passes
  10/10 because it now asserts that behaviour rather than the asking one. The
  decision is deliberate and documented at the constant; a reader should not
  mistake a green journey 2 for consent being on the record.
* **Journeys 11 and 12 ask the desktop shell questions a browser cannot answer.**
  The audio sources and the OS permission list come from the Tauri side, and
  headless Chrome has neither. Journey 11 scored better in an earlier run only
  because that run inherited a browser profile with a microphone permission
  already granted — the hermetic profile above makes the answer honest and
  stable rather than dependent on what a previous run left behind.

**`report.json` and `report.md` are the record of one run, and the media beside
them may be from a different one.** They are versioned; the screenshots and
video are not (see below), so a working copy can hold one run's pictures next
to another's numbers. Each journey's entry records `frames`, which is the
cheapest way to tell: it is the frame count of the `journey.mp4` that run
produced. For this run, journey 1 records 250 frames and its video has 250.

## Reproducing

```bash
# 1. Save the model into Settings first — see the note above about why the
#    env fallback is not enough once a settings database exists.
curl -X PUT http://<host>:8000/api/admin/settings -H 'content-type: application/json' \
  -d '{"inference":{"provider":"anthropic","auth_mode":"oauth_token",
       "model":"claude-haiku-4-5-20251001"},
       "secrets":[{"key":"anthropic_oauth_token","value":"…"}]}'

# 2. Run it.
ELICTA_ANTHROPIC_TOKEN=… ELICTA_DEEPGRAM_KEY=… \
  node tests/e2e/journeys/live-run.mjs \
    --app http://<host>:1420 --api http://<host>:8000 --out <dir>
node tests/e2e/journeys/live-report.mjs <dir>
```

`--only 01,05` runs a subset. Point `--out` somewhere else when you do, or the
partial run overwrites `report.json` with just those journeys.

Secrets are redacted from every log line, report and filename; the run asserts
that a stored credential is never returned by the API.
