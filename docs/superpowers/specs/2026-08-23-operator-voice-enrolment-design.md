# Operator voice enrolment and speaker verification (FR-1.5, FR-1.6)

Status: approved to implement, 2026-08-23.

## Why

The Capture screen's "Your voice" section is chrome. `features/capture/route.tsx`
hardcodes `operatorEnrolled={false}` and its button carries no handler, so an
operator who presses Enrol gets nothing. Behind it the seam is empty in both
directions: `operator_voiceprints` has an Alembic revision and no SQLAlchemy
model, `core/crates/capture/src/enrol` has an `EnrolmentRecorder` with zero
callers and no non-test `VoiceEmbedder`, and the service has no route.

FR-1.5 asks for a <=60s enrolment sample. FR-1.6 asks that each utterance be
tagged operator or not-operator. Architecture section 3.5 says the gate should
evaluate only utterances whose speaker is not the operator; `UtteranceRequest`
already carries a `speaker` field that nothing ever sets.

## Decisions

1. **The embedding is computed in the service**, not on-device. The panel is
   served to a browser at a LAN address where no Tauri shell exists, so an
   on-device path would leave the button dead exactly where it was pressed.
   One implementation, reachable from both the browser build and the shell.
2. **The embedder is a stdlib baseline**, not the ECAPA-TDNN-class model
   architecture section 3.3 specifies. No numpy, torch or ONNX exists in this
   tree and none is being added. MFCC statistics are enough for one-vs-rest
   verification on a clean feed and materially worse under cross-talk. This is
   stated in the module docstring, in the UI, and in the coverage doc.
3. **Scope is FR-1.5 and FR-1.6**: enrol, persist, and tag live utterances.

## Shape

New module `apps/service/src/app/modules/voiceprint/`:

- `embedding.py` — PCM16 to embedding bytes, and similarity. Pure, stdlib.
- `models.py` — wire and domain shapes.
- `service.py` — enrol and identify, over injected persistence and embedder.
- `router.py` — `build_voiceprint_router(...)`, mounted from `composition.py`.

Routes:

- `GET /api/operator/voiceprint` — status only. Never the embedding bytes.
- `POST /api/operator/voiceprint` — base64 linear16 16kHz mono, upsert, 201.
- `DELETE /api/operator/voiceprint` — un-enrol.

## The threshold errs toward "other"

The consumer is the trigger gate. Tagging the client as the operator
suppresses a nudge, which is a silent failure. Tagging the operator as the
client costs one bad nudge, which is visible and disposable in a tap. The
comparison is tuned toward the error that can be seen. A print whose
`embedding_model` does not match the live embedder refuses to compare rather
than scoring incompatible bytes.

## Degradation

Not enrolled, no live lane, or an unusable print leaves `speaker` as `None`
and the gate behaves exactly as it does today. A deployment that never enrols
sees no change.

## Data protection

FR-1.7: the enrolment PCM is embedded and discarded inside the request
handler. It never reaches `session_audio` and never reaches disk. A test
asserts it.

## Out of scope

Operator authentication. The service has no `operator_id` concept; enrolment
is keyed to a single local operator constant. Multi-operator identity is its
own subsystem.

## Traps

- SQLite takes its schema from `metadata.create_all`, not Alembic, so the
  model must be portable. The existing revision is PostgreSQL-flavoured
  (`postgresql.UUID`, `gen_random_uuid()`) and needs reconciling.
- Three new routes move four recorded counts and the generated API client.
- A new module without `__init__.py` is invisible to `pkgutil`.
- The Rust `enrol` module stays as it is. Porting the DSP there would put the
  same algorithm in two languages that must stay bit-compatible or
  verification silently degrades.
