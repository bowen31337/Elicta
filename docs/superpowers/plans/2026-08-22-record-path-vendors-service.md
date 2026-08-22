# Record-Path Speech Vendors (Service Side) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the record path transcribe real audio with two real speech vendors, and fill the diarization seam that currently stops the debrief dead.

**Architecture:** Audio is held in service-tier memory (never on disk), keyed by
`audio_ref = "session:{session_id}"`, and appended by a chunk endpoint. Two vendor
clients — Deepgram (one blocking POST) and AssemblyAI (upload → poll → delete) —
each satisfy the existing `transcribe` seam; Deepgram alone additionally satisfies
the `diarize` seam. Both are injected at `build_app`/`main.py` and wrapped by the
existing `audited()` chokepoint, so every vendor call writes an egress row without
any stage knowing about it.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, httpx, SQLAlchemy, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-08-22-deepgram-record-path-design.md`

**Scope:** This is **plan 1 of 2**. It ends with a record path you can drive with
`curl`: POST audio, get two transcripts, a divergence and a debrief. Plan 2 covers
the desktop capture tap, the AudioWorklet and the uploader (spec §5.1, §5.2, §5.5).

## Global Constraints

- **Audio never touches disk.** NFR-2.4 / FR-1.7. The hold is in-memory and must
  never be a `DurableMapping`. This is enforced by a test, not by intention.
- **Tests live beside the code.** `test_foo.py` next to `foo.py`. `pytest` only
  collects under `apps/service/src`.
- **`composition.py` is the composition root.** Routers are built by
  `build_*_router(...)` factories taking their persistence callables as arguments.
  A router is not picked up automatically — mounting it there is a required step.
- **Inference and vendor access are injected seams, never imports.** A client must
  not reach for `Backend`.
- **Stages fail closed.** A failed stage halts the chain rather than feeding the
  next one. Never return plausible output in place of a failure.
- **Secrets are write-only across the API** and `SecretValue` refuses to print
  itself. Never log a credential, never add one to a test fixture that prints.
- **Credentials are re-read per call**, so a key entered in the UI takes effect
  without a restart.
- **Run the full service suite after adding a test file** — duplicate test
  basenames across modules collide under pytest.
- Commands, from `apps/service` unless stated: `uv run pytest`, `uv run ruff check .`
  API integration suite, from the repo root:
  `uv run --project apps/service python -m pytest tests/e2e/api_integration`

---

### Task 1: A credential per speech vendor

**Files:**
- Modify: `apps/service/src/app/modules/settings/models.py` (`SecretKey`)
- Modify: `apps/service/src/app/modules/settings/store.py` (`_SECRET_ENV`)
- Modify: `.env.example`
- Modify: `docs/RUNBOOK.md`
- Test: `apps/service/src/app/modules/settings/test_vendor_credentials.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `SecretKey.DEEPGRAM_API_KEY`, `SecretKey.ASSEMBLYAI_API_KEY`;
  env fallbacks `ELICTA_DEEPGRAM_API_KEY`, `ELICTA_ASSEMBLYAI_API_KEY`.

**Why:** There is one `ASR_VENDOR_API_KEY` today and two record vendors. One key
cannot authenticate two vendors, and pretending otherwise is how a dead credential
came to read as "configured".

- [ ] **Step 1: Write the failing test**

Create `apps/service/src/app/modules/settings/test_vendor_credentials.py`:

```python
"""Each speech vendor carries its own credential (spec §2, D3).

One `asr_vendor_api_key` served two record vendors, which cannot be right:
the two are chosen precisely because they are independent, and independent
vendors do not share an API key.
"""

from __future__ import annotations

import pytest

from app.modules.settings.models import SecretKey
from app.modules.settings.store import InMemorySettingsStore


@pytest.mark.parametrize(
    "key",
    [SecretKey.DEEPGRAM_API_KEY, SecretKey.ASSEMBLYAI_API_KEY],
)
def test_each_record_vendor_has_its_own_secret(key: SecretKey) -> None:
    store = InMemorySettingsStore()
    store.set_secret(key, "vendor-key-1234")

    stored = store.get_secret(key)

    assert stored is not None
    assert stored.reveal() == "vendor-key-1234"


def test_the_two_vendor_secrets_are_independent() -> None:
    """Setting one must not disturb the other, or a save wipes a key."""

    store = InMemorySettingsStore()
    store.set_secret(SecretKey.DEEPGRAM_API_KEY, "deepgram-key")
    store.set_secret(SecretKey.ASSEMBLYAI_API_KEY, "assemblyai-key")

    assert store.get_secret(SecretKey.DEEPGRAM_API_KEY).reveal() == "deepgram-key"
    assert store.get_secret(SecretKey.ASSEMBLYAI_API_KEY).reveal() == "assemblyai-key"


def test_the_live_path_credential_is_not_orphaned() -> None:
    """`ASR_VENDOR_API_KEY` still serves the live path and must survive."""

    assert SecretKey.ASR_VENDOR_API_KEY.value == "asr_vendor_api_key"


@pytest.mark.parametrize(
    ("key", "variable"),
    [
        (SecretKey.DEEPGRAM_API_KEY, "ELICTA_DEEPGRAM_API_KEY"),
        (SecretKey.ASSEMBLYAI_API_KEY, "ELICTA_ASSEMBLYAI_API_KEY"),
    ],
)
def test_a_headless_deployment_can_supply_the_key_by_environment(
    key: SecretKey, variable: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.settings.store import _SECRET_ENV

    assert variable in _SECRET_ENV[key]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/service && uv run pytest src/app/modules/settings/test_vendor_credentials.py -v`

Expected: FAIL — `AttributeError: DEEPGRAM_API_KEY` on the `SecretKey` enum.

- [ ] **Step 3: Add the two members**

In `apps/service/src/app/modules/settings/models.py`, inside `class SecretKey`,
after `ASR_VENDOR_API_KEY`:

```python
    # The record path runs two independent engines (FR-2.6), and independent
    # vendors do not share an API key. `ASR_VENDOR_API_KEY` above stays for the
    # live path, which this does not touch.
    DEEPGRAM_API_KEY = "deepgram_api_key"
    ASSEMBLYAI_API_KEY = "assemblyai_api_key"
```

In `apps/service/src/app/modules/settings/store.py`, inside `_SECRET_ENV`:

```python
    SecretKey.DEEPGRAM_API_KEY: ("ELICTA_DEEPGRAM_API_KEY",),
    SecretKey.ASSEMBLYAI_API_KEY: ("ELICTA_ASSEMBLYAI_API_KEY",),
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/service && uv run pytest src/app/modules/settings/test_vendor_credentials.py -v`

Expected: PASS (6 tests).

- [ ] **Step 5: Document the two variables**

`.env.example` is the source of truth for env-var names. Append:

```bash
# Record-path speech vendors. Two engines run over every recording (FR-2.6) and
# they are independent vendors, so each needs its own key. A key set on the
# Settings screen overrides the value here.
# ELICTA_DEEPGRAM_API_KEY=
# ELICTA_ASSEMBLYAI_API_KEY=
```

In `docs/RUNBOOK.md`, the sentence at line ~124 says `apps/service` does not yet
have external ASR-vendor credentials in its table. Replace that sentence with a
table entry for both variables, matching the surrounding rows' format.

- [ ] **Step 6: Run the full service suite**

Run: `cd apps/service && uv run pytest -q && uv run ruff check .`

Expected: all pass. A new test file can collide with another module's basename —
this is why the whole suite runs, not just the new file.

- [ ] **Step 7: Commit**

```bash
git add apps/service/src/app/modules/settings/models.py \
        apps/service/src/app/modules/settings/store.py \
        apps/service/src/app/modules/settings/test_vendor_credentials.py \
        .env.example docs/RUNBOOK.md
git commit -m "feat(settings): a credential per record-path speech vendor"
```

---

### Task 2: Each key is tested against its own vendor

**Files:**
- Modify: `apps/service/src/app/composition.py:1595-1602` (the `probe is None` block)
- Test: `apps/service/src/app/modules/settings/test_vendor_credentials.py` (extend)

**Interfaces:**
- Consumes: `SecretKey.DEEPGRAM_API_KEY`, `SecretKey.ASSEMBLYAI_API_KEY` (Task 1).
- Produces: `_vendor_probe_for(key: SecretKey, settings_store) -> Callable | None`
  in `composition.py`.

**Why:** Today the ASR key's probe is chosen from `connectors.live_vendor`,
whatever key is being tested. A per-vendor key tested against another vendor's
endpoint is a meaningless green tick — and a red one is worse, because it reports
a working key as broken.

- [ ] **Step 1: Write the failing test**

Append to `apps/service/src/app/modules/settings/test_vendor_credentials.py`:

```python
def test_each_vendor_key_is_probed_against_its_own_vendor() -> None:
    """Not against whichever vendor the live path happens to name.

    The single ASR key was probed against `connectors.live_vendor`. With a key
    per vendor that is simply the wrong endpoint: an AssemblyAI key checked
    against Deepgram returns 401 and the screen calls a working key broken.
    """

    from app.composition import _vendor_probe_for
    from app.modules.settings.probes import probe_assemblyai, probe_deepgram
    from app.modules.settings.store import InMemorySettingsStore

    store = InMemorySettingsStore()

    assert _vendor_probe_for(SecretKey.DEEPGRAM_API_KEY, store) is probe_deepgram
    assert _vendor_probe_for(SecretKey.ASSEMBLYAI_API_KEY, store) is probe_assemblyai


def test_the_live_path_key_still_follows_the_live_vendor_setting() -> None:
    """Unchanged behaviour for the credential this task does not own."""

    from app.composition import _vendor_probe_for
    from app.modules.settings.probes import probe_deepgram
    from app.modules.settings.models import SpeechVendor
    from app.modules.settings.store import InMemorySettingsStore

    store = InMemorySettingsStore()
    settings = store.read()
    settings.connectors.live_vendor = SpeechVendor.DEEPGRAM

    assert _vendor_probe_for(SecretKey.ASR_VENDOR_API_KEY, store) is probe_deepgram
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/service && uv run pytest src/app/modules/settings/test_vendor_credentials.py -k vendor_key -v`

Expected: FAIL — `ImportError: cannot import name '_vendor_probe_for'`.

- [ ] **Step 3: Extract the probe choice into a named function**

In `apps/service/src/app/composition.py`, above `build_app`, add:

```python
def _vendor_probe_for(key: SecretKey, settings_store: SettingsStore) -> Any:
    """The probe for one speech credential, chosen by the vendor it belongs to.

    This used to read `connectors.live_vendor` for every speech key, which was
    tolerable while there was one. With a key per record vendor it is simply
    the wrong endpoint, and a working key reported as broken is worse than an
    unverified one — an operator acts on it.

    The live-path key keeps following `live_vendor`, because that setting is
    genuinely what it authenticates against.
    """

    if key is SecretKey.DEEPGRAM_API_KEY:
        return probe_for_vendor("deepgram")
    if key is SecretKey.ASSEMBLYAI_API_KEY:
        return probe_for_vendor("assemblyai")
    if key is SecretKey.ASR_VENDOR_API_KEY:
        return probe_for_vendor(settings_store.read().connectors.live_vendor.value)
    return None
```

Then replace the existing block at `composition.py:1595-1602` with:

```python
        if probe is None:
            vendor_probe = _vendor_probe_for(key, settings_store)
            if vendor_probe is not None:

                async def probe(secret: str, call=vendor_probe) -> None:
                    await call(secret, base_url=settings_store.read().vendors.asr_base_url)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/service && uv run pytest src/app/modules/settings/test_vendor_credentials.py -v`

Expected: PASS (8 tests).

- [ ] **Step 5: Run the full suites**

Run, from `apps/service`: `uv run pytest -q && uv run ruff check .`
Then, from the repo root:
`uv run --project apps/service python -m pytest tests/e2e/api_integration -q`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add apps/service/src/app/composition.py \
        apps/service/src/app/modules/settings/test_vendor_credentials.py
git commit -m "fix(settings): probe each speech key against its own vendor"
```

---

### Task 3: The service-tier audio hold

**Files:**
- Modify: `apps/service/src/app/composition.py` (`Backend`, a new router mount)
- Create: `apps/service/src/app/modules/asr-record/audio_hold.py`
- Create: `apps/service/src/app/modules/asr-record/test_audio_hold.py`
- Modify: `apps/service/src/app/persistence/test_store.py` (the durability guard)
- Modify: `CLAUDE.md` (the "serves 49 API paths" line)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Backend.session_audio: dict[str, bytearray]`
  - `POST /api/sessions/{session_id}/audio-chunk` taking
    `AudioChunkRequest{sequence: int, pcm: str}` and answering
    `AudioChunkAccepted{received_bytes: int, next_sequence: int}`
  - `read_session_audio(backend) -> Callable[[str], bytes]`, the injectable
    `read_audio` every vendor client takes.
  - `audio_ref_for(session_id) -> str`, returning `f"session:{session_id}"`.

**Why:** `retained_audio` holds a reference string and no bytes exist anywhere,
so `audio_ref` has never pointed at anything.

- [ ] **Step 1: Write the failing test**

Create `apps/service/src/app/modules/asr-record/test_audio_hold.py`:

```python
"""The service-tier hold the record path transcribes from (spec §5.3).

`audio_ref` has never had a value: the schema calls it "a storage key or URI"
from a recording store that does not exist. It names this hold now.
"""

from __future__ import annotations

import base64
import importlib

import pytest

audio_hold = importlib.import_module("app.modules.asr-record.audio_hold")


def _pcm(byte: int, count: int) -> str:
    return base64.b64encode(bytes([byte]) * count).decode()


def test_chunks_append_in_order() -> None:
    held: dict[str, audio_hold.SessionAudio] = {}

    first = audio_hold.append_chunk(held, "meeting-1", sequence=0, pcm=_pcm(1, 4))
    second = audio_hold.append_chunk(held, "meeting-1", sequence=1, pcm=_pcm(2, 6))

    assert first.next_sequence == 1
    assert second.received_bytes == 10
    assert bytes(held["meeting-1"].buffer) == bytes([1] * 4 + [2] * 6)


def test_a_gap_is_refused_rather_than_concatenated_across() -> None:
    """Silently joining the two sides of a dropped chunk makes a transcript
    with a seam nobody can see, which is worse than a refusal to retry."""

    held: dict[str, audio_hold.SessionAudio] = {}
    audio_hold.append_chunk(held, "meeting-1", sequence=0, pcm=_pcm(1, 4))

    with pytest.raises(audio_hold.ChunkOutOfOrder) as raised:
        audio_hold.append_chunk(held, "meeting-1", sequence=2, pcm=_pcm(3, 4))

    assert "expected 1" in str(raised.value)
    assert bytes(held["meeting-1"].buffer) == bytes([1] * 4)


def test_a_resent_chunk_is_refused_too() -> None:
    """Retrying an acknowledged chunk would duplicate audio, not repair it."""

    held: dict[str, audio_hold.SessionAudio] = {}
    audio_hold.append_chunk(held, "meeting-1", sequence=0, pcm=_pcm(1, 4))

    with pytest.raises(audio_hold.ChunkOutOfOrder):
        audio_hold.append_chunk(held, "meeting-1", sequence=0, pcm=_pcm(1, 4))


def test_sessions_are_held_separately() -> None:
    held: dict[str, audio_hold.SessionAudio] = {}

    audio_hold.append_chunk(held, "meeting-1", sequence=0, pcm=_pcm(1, 2))
    audio_hold.append_chunk(held, "meeting-2", sequence=0, pcm=_pcm(9, 2))

    assert bytes(held["meeting-1"].buffer) == bytes([1, 1])
    assert bytes(held["meeting-2"].buffer) == bytes([9, 9])


def test_the_audio_ref_names_the_hold() -> None:
    assert audio_hold.audio_ref_for("meeting-1") == "session:meeting-1"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/service && uv run pytest "src/app/modules/asr-record/test_audio_hold.py" -v`

Expected: FAIL — `ModuleNotFoundError: app.modules.asr-record.audio_hold`.

Note the module directory is hyphenated, so it is only reachable through
`importlib.import_module`. A literal `import` of it is a syntax error.

- [ ] **Step 3: Write the hold**

Create `apps/service/src/app/modules/asr-record/audio_hold.py`:

```python
"""The session's audio, held in the service tier and nowhere else (NFR-2.4).

Architecture §7 orders transcription and diarization before the discard because
they are the only steps that need audio, and NFR-2.4 revises FR-1.7 to "retained
only until the record path completes". This is that retention: in memory, for the
length of one debrief, and never written down.

Chunks arrive during the meeting rather than in one upload at the end, so a
crashed browser costs the tail rather than the recording.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

from pydantic import BaseModel, Field


class ChunkOutOfOrder(Exception):
    """A chunk arrived that is not the next one expected.

    Raised rather than tolerated: appending across a gap produces a transcript
    with a join nobody can see, and appending a duplicate produces one with a
    stutter. Both read as a bad engine rather than a lost packet.
    """


@dataclass
class SessionAudio:
    """One session's bytes, and the next chunk expected for it.

    The counter lives beside the buffer rather than in a module global: a
    global is shared by every `Backend` in a process, so two tests — or two
    services — would see each other's sequences.
    """

    buffer: bytearray = field(default_factory=bytearray)
    next_sequence: int = 0


class AudioChunkRequest(BaseModel):
    """One slice of a session's recording, on its way to the hold."""

    sequence: int = Field(ge=0)
    pcm: str = Field(min_length=1, description="base64 linear16, 16 kHz mono")


class AudioChunkAccepted(BaseModel):
    """What the uploader needs to send the next one."""

    received_bytes: int
    next_sequence: int


def audio_ref_for(session_id: str) -> str:
    """The `audio_ref` naming this session's hold.

    The field has only ever been documented as "a storage key or URI"; this is
    the first value it has had.
    """

    return f"session:{session_id}"


def append_chunk(
    held: dict[str, SessionAudio], session_id: str, *, sequence: int, pcm: str
) -> AudioChunkAccepted:
    """Append one chunk, or refuse it for being out of order."""

    entry = held.setdefault(session_id, SessionAudio())
    if sequence != entry.next_sequence:
        raise ChunkOutOfOrder(
            f"chunk {sequence} for {session_id}: expected {entry.next_sequence}"
        )

    entry.buffer.extend(base64.b64decode(pcm))
    entry.next_sequence = sequence + 1
    return AudioChunkAccepted(
        received_bytes=len(entry.buffer), next_sequence=entry.next_sequence
    )


def discard(held: dict[str, SessionAudio], session_id: str) -> None:
    """Forget a session's audio, after the record path has finished with it."""

    held.pop(session_id, None)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/service && uv run pytest "src/app/modules/asr-record/test_audio_hold.py" -v`

Expected: PASS (5 tests).

- [ ] **Step 5: Write the failing test for the endpoint and the durability guard**

Append to `apps/service/src/app/modules/asr-record/test_audio_hold.py`:

```python
def test_the_endpoint_accepts_a_chunk_and_refuses_a_gap() -> None:
    from fastapi.testclient import TestClient

    from app.composition import Backend, build_app

    client = TestClient(build_app(Backend()))

    accepted = client.post(
        "/api/sessions/meeting-1/audio-chunk",
        json={"sequence": 0, "pcm": _pcm(1, 4)},
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json() == {"received_bytes": 4, "next_sequence": 1}

    gap = client.post(
        "/api/sessions/meeting-1/audio-chunk",
        json={"sequence": 5, "pcm": _pcm(1, 4)},
    )
    assert gap.status_code == 409, gap.text
    assert "expected 1" in gap.json()["detail"]


def test_the_first_chunk_marks_the_audio_retained() -> None:
    """So the existing NFR-2.4 destruction gate sees this session at all."""

    from fastapi.testclient import TestClient

    from app.composition import Backend, build_app

    backend = Backend()
    client = TestClient(build_app(backend))
    client.post(
        "/api/sessions/meeting-1/audio-chunk",
        json={"sequence": 0, "pcm": _pcm(1, 4)},
    )

    assert backend.retained_audio["meeting-1"] == "session:meeting-1"
```

Append to `apps/service/src/app/persistence/test_store.py`:

```python
def test_session_audio_is_never_made_durable() -> None:
    """FR-1.7 as a test, not as an intention.

    Raw audio is never written to disk. `session_audio` holding bytes makes
    that a live risk rather than a theoretical one, so the guard is here
    beside the other durability decisions.
    """

    backend = attach_state_store(Backend(), open_state_store("sqlite://"))

    assert isinstance(backend.session_audio, dict)
    assert not isinstance(backend.session_audio, DurableMapping)
```

- [ ] **Step 6: Run both to verify they fail**

Run: `cd apps/service && uv run pytest "src/app/modules/asr-record/test_audio_hold.py" src/app/persistence/test_store.py -k "endpoint or retained or session_audio" -v`

Expected: FAIL — 404 for the endpoint, `AttributeError: session_audio` for the guard.

- [ ] **Step 7: Add the field, the router and the mount**

In `apps/service/src/app/composition.py`, in `Backend`, beside `retained_audio`:

```python
    #: The session's audio, in memory only (FR-1.7, NFR-2.4). Deliberately a
    #: plain dict: `attach_state_store` must never make this durable, and
    #: `test_session_audio_is_never_made_durable` is what keeps it that way.
    session_audio: dict[str, Any] = field(default_factory=dict)  # str -> SessionAudio
```

Add the router factory in `audio_hold.py`:

```python
def build_audio_chunk_router(
    held: dict[str, SessionAudio], on_audio_retained: Any
) -> APIRouter:
    """`POST /api/sessions/{id}/audio-chunk` — one slice of a live recording."""

    router = APIRouter(prefix="/api/sessions", tags=["record-path-transcription"])

    @router.post(
        "/{session_id}/audio-chunk",
        response_model=AudioChunkAccepted,
        status_code=202,
    )
    async def accept_audio_chunk(
        session_id: str, payload: AudioChunkRequest
    ) -> AudioChunkAccepted:
        first = session_id not in held
        try:
            accepted = append_chunk(
                held, session_id, sequence=payload.sequence, pcm=payload.pcm
            )
        except ChunkOutOfOrder as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        # The destruction gate is keyed off `retained_audio`; a session that
        # never lands there is never destroyed and never noticed.
        if first:
            await on_audio_retained(session_id, audio_ref_for(session_id))
        return accepted

    return router
```

Add its imports to `audio_hold.py`: `from typing import Any`, and
`from fastapi import APIRouter, HTTPException`.

Mount it in `composition.py` beside the other record-path routers, inside
`_include_operational_routers`:

```python
    _audio_hold = importlib.import_module("app.modules.asr-record.audio_hold")
    app.include_router(
        _audio_hold.build_audio_chunk_router(backend.session_audio, on_audio_retained)
    )
```

Extend `delete_audio` in `composition.py` so the bytes go when the ref does:

```python
        _audio_hold.discard(backend.session_audio, session_id)
```

- [ ] **Step 8: Run to verify they pass**

Run: `cd apps/service && uv run pytest "src/app/modules/asr-record/test_audio_hold.py" src/app/persistence/test_store.py -v`

Expected: PASS.

- [ ] **Step 9: Update the recorded route count and regenerate the client**

`CLAUDE.md` says the service "serves 49 API paths". It now serves 50. Update that
line. Then regenerate the typed client, which is generated and never hand-edited:

```bash
cd apps/service && uv run uvicorn app.main:app --port 8000 &
pnpm generate:api-client
```

Stop the server afterwards.

- [ ] **Step 10: Run the full suites**

Run, from `apps/service`: `uv run pytest -q && uv run ruff check .`
From the repo root: `uv run --project apps/service python -m pytest tests/e2e/api_integration -q`
And: `pnpm --filter elicta-desktop typecheck`

Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add apps/service/src/app/modules/asr-record/audio_hold.py \
        apps/service/src/app/modules/asr-record/test_audio_hold.py \
        apps/service/src/app/composition.py \
        apps/service/src/app/persistence/test_store.py \
        packages/api-client/src CLAUDE.md
git commit -m "feat(asr-record): hold the session's audio in the service tier"
```

---

### Task 4: Deepgram fills the transcribe seam

**Files:**
- Create: `apps/service/src/app/orchestration/deepgram_engines.py`
- Create: `apps/service/src/app/orchestration/test_deepgram_engines.py`

**Interfaces:**
- Consumes: `read_audio: Callable[[str], bytes]` (Task 3), `SecretKey.DEEPGRAM_API_KEY` (Task 1).
- Produces:
  `deepgram_record_engine(read_audio, store, *, model="nova-3", name="deepgram", timeout=600.0)`
  returning `async (session_id, audio_ref, keyterms) -> BatchTranscriptionOutput`.
  Also `deepgram_listen_url(model, keyterms) -> str` and
  `to_batch_transcription(payload, name) -> BatchTranscriptionOutput`.

**Why:** the record path runs two `stub_engine`s returning `"hello there"`.

Response shape is **observed**, from a real 90-minute run: `results.utterances[]`
carries `['channel','confidence','end','id','speaker','start','transcript','words']`.

- [ ] **Step 1: Write the failing test**

Create `apps/service/src/app/orchestration/test_deepgram_engines.py`:

```python
"""Deepgram on the record path (spec §5.4a).

The response fixture below is the shape a real 90-minute run returned, trimmed
to two utterances. No test here makes a live call.
"""

from __future__ import annotations

import pytest

from app.orchestration.deepgram_engines import (
    deepgram_listen_url,
    to_batch_transcription,
)

RESPONSE = {
    "results": {
        "channels": [
            {"alternatives": [{"transcript": "Yeah, the dock rule is fifteen minutes."}]}
        ],
        "utterances": [
            {
                "start": 0.0,
                "end": 3.84,
                "speaker": 0,
                "transcript": "Yeah, the dock rule is fifteen minutes.",
                "confidence": 0.99,
            },
            {
                "start": 3.9,
                "end": 6.2,
                "speaker": 1,
                "transcript": "Is that written down anywhere?",
                "confidence": 0.98,
            },
        ],
    }
}


def test_every_utterance_becomes_a_timed_segment() -> None:
    output = to_batch_transcription(RESPONSE, "deepgram")

    assert output.engine == "deepgram"
    assert [(s.start_seconds, s.end_seconds) for s in output.segments] == [
        (0.0, 3.84),
        (3.9, 6.2),
    ]
    assert output.segments[1].text == "Is that written down anywhere?"


def test_the_speaker_travels_with_the_segment() -> None:
    """`TranscriptSegment.speaker` exists and the record path shows it."""

    output = to_batch_transcription(RESPONSE, "deepgram")

    assert [s.speaker for s in output.segments] == ["0", "1"]


def test_the_full_transcript_comes_from_the_alternative() -> None:
    """Not from joining the utterances, which drops the vendor's punctuation
    and spacing decisions."""

    output = to_batch_transcription(RESPONSE, "deepgram")

    assert output.text == "Yeah, the dock rule is fifteen minutes."


def test_a_response_with_no_utterances_is_a_failure_not_an_empty_transcript() -> None:
    """An empty transcript reads as a meeting where nobody spoke."""

    with pytest.raises(ValueError, match="no utterances"):
        to_batch_transcription({"results": {"channels": [], "utterances": []}}, "deepgram")


def test_the_request_carries_the_engagement_vocabulary() -> None:
    url = deepgram_listen_url("nova-3", ["FROSTLINE", "cross dock"])

    assert "keyterm=FROSTLINE" in url
    assert "keyterm=cross+dock" in url or "keyterm=cross%20dock" in url


def test_the_request_opts_out_of_vendor_retention() -> None:
    """NFR-2.3: retention is a request parameter, not only a contract clause."""

    assert "mip_opt_out=true" in deepgram_listen_url("nova-3", [])


def test_the_request_describes_the_audio_the_capture_path_produces() -> None:
    url = deepgram_listen_url("nova-3", [])

    for expected in ("encoding=linear16", "sample_rate=16000", "channels=1"):
        assert expected in url

    for expected in ("diarize=true", "utterances=true", "model=nova-3"):
        assert expected in url
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/service && uv run pytest src/app/orchestration/test_deepgram_engines.py -v`

Expected: FAIL — `ModuleNotFoundError: app.orchestration.deepgram_engines`.

- [ ] **Step 3: Write the client**

Create `apps/service/src/app/orchestration/deepgram_engines.py`:

```python
"""Deepgram as a record-path batch engine (PRD FR-2.5/2.6, spec §5.4a).

One blocking request per session. Measured rather than assumed: 90 minutes of
speech returns in 71 seconds against Deepgram's 600-second processing ceiling,
and the cost per audio-minute did not change between a 10-minute and a
90-minute file.

The seam this fills is `transcribe(session_id, audio_ref, keyterms)`, and
`read_audio` is injected so this module never reaches for `Backend`.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

import httpx

from app.modules.settings.models import SecretKey

_models = importlib.import_module("app.modules.asr-record.models")
BatchTranscriptionOutput = _models.BatchTranscriptionOutput
TranscriptSegment = _models.TranscriptSegment

LISTEN_URL = "https://api.deepgram.com/v1/listen"

#: A 90-minute meeting holds the connection open for over a minute. httpx's
#: default would abort a transcription that was proceeding perfectly well.
DEFAULT_TIMEOUT_SECONDS = 600.0


class DeepgramUnavailable(Exception):
    """Deepgram could not be reached, or refused the request."""


def deepgram_listen_url(model: str, keyterms: list[str]) -> str:
    """The request URL, including the vocabulary and the retention opt-out.

    `keyterm` is repeated once per term and is Nova-3 only; multi-word phrases
    are encoded by `urlencode`. This is the path the engagement's vocabulary
    travels, which is the single most effective preparation an operator does.
    """

    params = [
        ("model", model),
        ("diarize", "true"),
        ("utterances", "true"),
        ("smart_format", "true"),
        ("encoding", "linear16"),
        ("sample_rate", "16000"),
        ("channels", "1"),
        # NFR-2.3: vendor-side retention is set per request, not left to the
        # contract alone, so an audit can see it on the wire.
        ("mip_opt_out", "true"),
        *(("keyterm", term) for term in keyterms),
    ]
    return f"{LISTEN_URL}?{urlencode(params)}"


def to_batch_transcription(payload: Any, name: str) -> BatchTranscriptionOutput:
    """Deepgram's response, as the record path's own shape."""

    results = payload.get("results") or {}
    utterances = results.get("utterances") or []
    if not utterances:
        raise ValueError(
            "no utterances in the Deepgram response — refusing to report an "
            "empty transcript, which reads as a meeting where nobody spoke"
        )

    channels = results.get("channels") or [{}]
    alternatives = channels[0].get("alternatives") or [{}]

    return BatchTranscriptionOutput(
        engine=name,
        segments=[
            TranscriptSegment(
                start_seconds=float(utterance["start"]),
                end_seconds=float(utterance["end"]),
                text=utterance["transcript"],
                speaker=str(utterance["speaker"]),
            )
            for utterance in utterances
        ],
        text=alternatives[0].get("transcript", ""),
    )


def deepgram_record_engine(
    read_audio: Callable[[str], bytes],
    store: Any,
    *,
    model: str = "nova-3",
    name: str = "deepgram",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Callable[[str, str, list[str]], Awaitable[BatchTranscriptionOutput]]:
    """One record-path batch engine, backed by Deepgram."""

    async def transcribe(
        session_id: str, audio_ref: str, keyterms: list[str]
    ) -> BatchTranscriptionOutput:
        payload = await _listen(read_audio, store, session_id, model, keyterms, timeout)
        return to_batch_transcription(payload, name)

    return transcribe


async def _listen(
    read_audio: Callable[[str], bytes],
    store: Any,
    session_id: str,
    model: str,
    keyterms: list[str],
    timeout: float,
) -> Any:
    """One `/v1/listen` call. Shared by both seams so there is one request shape.

    A second copy would be a second place for the retention opt-out to be
    forgotten.
    """

    audio = read_audio(session_id)
    if not audio:
        raise DeepgramUnavailable(f"no audio held for {session_id}: nothing to transcribe")

    # Read per call, so a key entered on the Settings screen takes effect
    # without a restart.
    secret = store.get_secret(SecretKey.DEEPGRAM_API_KEY)
    if secret is None:
        raise DeepgramUnavailable("no Deepgram credential is configured")

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            deepgram_listen_url(model, keyterms),
            headers={
                "Authorization": f"Token {secret.reveal()}",
                "Content-Type": "application/octet-stream",
            },
            content=bytes(audio),
        )

    if response.status_code == 504:
        raise DeepgramUnavailable(
            "Deepgram timed out processing this recording — its own cause, "
            "not a network failure, and the remedies differ"
        )
    if response.status_code != 200:
        raise DeepgramUnavailable(f"Deepgram answered {response.status_code}")

    return response.json()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/service && uv run pytest src/app/orchestration/test_deepgram_engines.py -v`

Expected: PASS (7 tests).

- [ ] **Step 5: Run the full service suite**

Run: `cd apps/service && uv run pytest -q && uv run ruff check .`

- [ ] **Step 6: Commit**

```bash
git add apps/service/src/app/orchestration/deepgram_engines.py \
        apps/service/src/app/orchestration/test_deepgram_engines.py
git commit -m "feat(orchestration): a Deepgram record-path batch engine"
```

---

### Task 5: Deepgram fills the diarize seam

**Files:**
- Modify: `apps/service/src/app/orchestration/deepgram_engines.py`
- Modify: `apps/service/src/app/orchestration/test_deepgram_engines.py`

**Interfaces:**
- Consumes: `to_batch_transcription`, `deepgram_listen_url` (Task 4).
- Produces: `deepgram_diarizer(read_audio, store, *, model, name, timeout)`
  returning `async (session_id, audio_ref) -> DiarizationOutput`, and
  `to_speaker_turns(payload, name) -> DiarizationOutput`.

**Why:** the debrief stops at `_no_diarizer`. This is the step that unblocks it.

Note D3a: **only Deepgram diarizes.** `run_diarization` takes exactly one
`diarize`, and two engines would give two conflicting speaker maps with nothing
to arbitrate between them.

- [ ] **Step 1: Write the failing test**

Append to `apps/service/src/app/orchestration/test_deepgram_engines.py`:

```python
def test_consecutive_utterances_by_one_speaker_become_one_turn() -> None:
    """A `SpeakerTurn` is a continuous stretch attributed to one speaker, so
    two adjacent utterances from the same person are one turn, not two."""

    from app.orchestration.deepgram_engines import to_speaker_turns

    payload = {
        "results": {
            "channels": [{"alternatives": [{"transcript": "..."}]}],
            "utterances": [
                {"start": 0.0, "end": 2.0, "speaker": 0, "transcript": "a"},
                {"start": 2.0, "end": 4.0, "speaker": 0, "transcript": "b"},
                {"start": 4.0, "end": 6.0, "speaker": 1, "transcript": "c"},
            ],
        }
    }

    output = to_speaker_turns(payload, "deepgram")

    assert output.engine == "deepgram"
    assert [(t.start_seconds, t.end_seconds, t.speaker_tag) for t in output.turns] == [
        (0.0, 4.0, "0"),
        (4.0, 6.0, "1"),
    ]


def test_a_speaker_returning_later_starts_a_new_turn() -> None:
    """Merging by speaker alone would collapse a conversation into two turns."""

    from app.orchestration.deepgram_engines import to_speaker_turns

    payload = {
        "results": {
            "channels": [{"alternatives": [{"transcript": "..."}]}],
            "utterances": [
                {"start": 0.0, "end": 1.0, "speaker": 0, "transcript": "a"},
                {"start": 1.0, "end": 2.0, "speaker": 1, "transcript": "b"},
                {"start": 2.0, "end": 3.0, "speaker": 0, "transcript": "c"},
            ],
        }
    }

    output = to_speaker_turns(payload, "deepgram")

    assert [t.speaker_tag for t in output.turns] == ["0", "1", "0"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/service && uv run pytest src/app/orchestration/test_deepgram_engines.py -k turn -v`

Expected: FAIL — `ImportError: cannot import name 'to_speaker_turns'`.

- [ ] **Step 3: Add the diarizer**

Append to `apps/service/src/app/orchestration/deepgram_engines.py`:

```python
_pipeline_models = importlib.import_module("app.modules.debrief.pipeline.models")
DiarizationOutput = _pipeline_models.DiarizationOutput
SpeakerTurn = _pipeline_models.SpeakerTurn


def to_speaker_turns(payload: Any, name: str) -> DiarizationOutput:
    """Deepgram's per-utterance speakers, merged into continuous turns.

    `run_diarization` wants turns, not utterances: it builds `Utterance`s from
    the record-path spans itself and calls `tag_span_speaker(span, turns)`.
    Returning utterances would bypass the rule that makes `speaker_tag` never
    null.
    """

    utterances = (payload.get("results") or {}).get("utterances") or []
    if not utterances:
        raise ValueError("no utterances in the Deepgram response — nothing to diarize")

    turns: list[SpeakerTurn] = []
    for utterance in utterances:
        speaker = str(utterance["speaker"])
        start = float(utterance["start"])
        end = float(utterance["end"])
        # Merge only with the immediately preceding turn: a speaker returning
        # after somebody else is a new turn, not a continuation of their last.
        if turns and turns[-1].speaker_tag == speaker:
            turns[-1] = SpeakerTurn(
                start_seconds=turns[-1].start_seconds,
                end_seconds=end,
                speaker_tag=speaker,
            )
        else:
            turns.append(
                SpeakerTurn(start_seconds=start, end_seconds=end, speaker_tag=speaker)
            )

    return DiarizationOutput(engine=name, turns=turns)


def deepgram_diarizer(
    read_audio: Callable[[str], bytes],
    store: Any,
    *,
    model: str = "nova-3",
    name: str = "deepgram",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Callable[[str, str], Awaitable[DiarizationOutput]]:
    """The `diarize` seam, from the same call shape as the transcript.

    Only one engine diarizes (spec D3a): `run_diarization` takes exactly one,
    and two would produce two conflicting speaker maps for the same audio.

    This maps through `to_speaker_turns` — the function the tests cover. A
    second copy of the merge that happened to be the one production used would
    be tested by nothing.
    """

    async def diarize(session_id: str, audio_ref: str) -> DiarizationOutput:
        # Its own call rather than one shared with the transcribe seam: the two
        # are invoked by different stages at different times, and threading one
        # response between them would couple the record path to the debrief.
        payload = await _listen(read_audio, store, session_id, model, [], timeout)
        return to_speaker_turns(payload, name)

    return diarize
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/service && uv run pytest src/app/orchestration/test_deepgram_engines.py -v`

Expected: PASS (9 tests).

- [ ] **Step 5: Run the full service suite**

Run: `cd apps/service && uv run pytest -q && uv run ruff check .`

- [ ] **Step 6: Commit**

```bash
git add apps/service/src/app/orchestration/deepgram_engines.py \
        apps/service/src/app/orchestration/test_deepgram_engines.py
git commit -m "feat(orchestration): fill the diarize seam from Deepgram"
```

---

### Task 6: AssemblyAI fills the transcribe seam

**Files:**
- Create: `apps/service/src/app/orchestration/assemblyai_engines.py`
- Create: `apps/service/src/app/orchestration/test_assemblyai_engines.py`

**Interfaces:**
- Consumes: `read_audio` (Task 3), `SecretKey.ASSEMBLYAI_API_KEY` (Task 1).
- Produces: `assemblyai_record_engine(read_audio, store, *, name="assemblyai", poll_seconds=3.0, poll_ceiling_seconds=1800.0)`
  returning `async (session_id, audio_ref, keyterms) -> BatchTranscriptionOutput`,
  and `to_batch_transcription(payload, name)`.

**Why:** two independent engines are what FR-2.6 and T3 ask for; one engine
produces no divergence to review.

**Before writing any mapping code, resolve R6.** AssemblyAI's utterance shape was
only ever proven on synthetic tone, which has no speech and therefore no
`utterances`. Run one real-speech transcription against the key and record the
actual response shape. If it differs from the fixture below, the fixture is wrong
and the fixture is what to change.

- [ ] **Step 1: Write the failing test**

Create `apps/service/src/app/orchestration/test_assemblyai_engines.py`:

```python
"""AssemblyAI on the record path (spec §5.4b).

A different shape from Deepgram's: audio is uploaded to the vendor first, then
polled, then deleted. The delete is not optional — it is the only reason this
vendor's flow sits inside the audio promise.
"""

from __future__ import annotations

import pytest

from app.orchestration.assemblyai_engines import to_batch_transcription

RESPONSE = {
    "status": "completed",
    "text": "Yeah, the dock rule is fifteen minutes.",
    "utterances": [
        {"start": 0, "end": 3840, "speaker": "A", "text": "Yeah, the dock rule is fifteen minutes."},
        {"start": 3900, "end": 6200, "speaker": "B", "text": "Is that written down anywhere?"},
    ],
}


def test_milliseconds_become_seconds() -> None:
    """AssemblyAI reports milliseconds and the record path stores seconds.
    Storing one as the other silently misplaces every citation in the debrief."""

    output = to_batch_transcription(RESPONSE, "assemblyai")

    assert [(s.start_seconds, s.end_seconds) for s in output.segments] == [
        (0.0, 3.84),
        (3.9, 6.2),
    ]


def test_the_speaker_travels_with_the_segment() -> None:
    output = to_batch_transcription(RESPONSE, "assemblyai")

    assert [s.speaker for s in output.segments] == ["A", "B"]


def test_the_engine_names_itself() -> None:
    """`engine` plus `session_id` identify a transcript, so this must differ
    from Deepgram's or the two engines overwrite each other."""

    assert to_batch_transcription(RESPONSE, "assemblyai").engine == "assemblyai"


def test_a_response_with_no_utterances_is_a_failure() -> None:
    with pytest.raises(ValueError, match="no utterances"):
        to_batch_transcription({"status": "completed", "utterances": []}, "assemblyai")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/service && uv run pytest src/app/orchestration/test_assemblyai_engines.py -v`

Expected: FAIL — `ModuleNotFoundError: app.orchestration.assemblyai_engines`.

- [ ] **Step 3: Write the client**

Create `apps/service/src/app/orchestration/assemblyai_engines.py`:

```python
"""AssemblyAI as the second record-path batch engine (PRD FR-2.6, spec §5.4b).

Upload, poll, delete. The shape differs from Deepgram's in a way that matters
beyond code: this vendor *stores* the audio until we remove it, where Deepgram
takes it in the transcription request and keeps nothing. The delete is what
makes that acceptable, and it is mandatory.

Limits are far outside a meeting: 10 hours of audio, 2.2 GB via upload. There is
no synchronous processing ceiling, because it is a polling API by construction.
"""

from __future__ import annotations

import asyncio
import importlib
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.modules.settings.models import SecretKey

_models = importlib.import_module("app.modules.asr-record.models")
BatchTranscriptionOutput = _models.BatchTranscriptionOutput
TranscriptSegment = _models.TranscriptSegment

BASE_URL = "https://api.assemblyai.com"


class AssemblyAIUnavailable(Exception):
    """AssemblyAI could not be reached, refused the request, or never finished."""


def to_batch_transcription(payload: Any, name: str) -> BatchTranscriptionOutput:
    """AssemblyAI's response, as the record path's own shape.

    Timestamps arrive in milliseconds; everything downstream — citations,
    divergence spans, the debrief's quotes — is in seconds.
    """

    utterances = payload.get("utterances") or []
    if not utterances:
        raise ValueError(
            "no utterances in the AssemblyAI response — refusing to report an "
            "empty transcript, which reads as a meeting where nobody spoke"
        )

    return BatchTranscriptionOutput(
        engine=name,
        segments=[
            TranscriptSegment(
                start_seconds=float(utterance["start"]) / 1000.0,
                end_seconds=float(utterance["end"]) / 1000.0,
                text=utterance["text"],
                speaker=str(utterance["speaker"]),
            )
            for utterance in utterances
        ],
        text=payload.get("text", ""),
    )


def assemblyai_record_engine(
    read_audio: Callable[[str], bytes],
    store: Any,
    *,
    name: str = "assemblyai",
    poll_seconds: float = 3.0,
    poll_ceiling_seconds: float = 1800.0,
) -> Callable[[str, str, list[str]], Awaitable[BatchTranscriptionOutput]]:
    """The second record-path batch engine."""

    async def transcribe(
        session_id: str, audio_ref: str, keyterms: list[str]
    ) -> BatchTranscriptionOutput:
        audio = read_audio(session_id)
        if not audio:
            raise AssemblyAIUnavailable(
                f"no audio held for {session_id}: nothing to transcribe"
            )

        secret = store.get_secret(SecretKey.ASSEMBLYAI_API_KEY)
        if secret is None:
            raise AssemblyAIUnavailable("no AssemblyAI credential is configured")

        headers = {"authorization": secret.reveal()}
        transcript_id: str | None = None

        async with httpx.AsyncClient(timeout=600.0) as client:
            try:
                uploaded = await client.post(
                    f"{BASE_URL}/v2/upload", headers=headers, content=bytes(audio)
                )
                if uploaded.status_code != 200:
                    raise AssemblyAIUnavailable(
                        f"AssemblyAI upload answered {uploaded.status_code}"
                    )

                submitted = await client.post(
                    f"{BASE_URL}/v2/transcript",
                    headers=headers,
                    json={
                        "audio_url": uploaded.json()["upload_url"],
                        "speaker_labels": True,
                        "word_boost": keyterms,
                    },
                )
                if submitted.status_code != 200:
                    raise AssemblyAIUnavailable(
                        f"AssemblyAI submit answered {submitted.status_code}"
                    )

                transcript_id = submitted.json()["id"]
                payload = await _poll(
                    client, headers, transcript_id, poll_seconds, poll_ceiling_seconds
                )
                return to_batch_transcription(payload, name)
            finally:
                # The vendor is holding a copy of a client's meeting. Removing
                # it is the point, so it runs even when the run failed.
                if transcript_id is not None:
                    await _delete(client, headers, transcript_id)

    return transcribe


async def _poll(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    transcript_id: str,
    interval: float,
    ceiling: float,
) -> Any:
    """Wait for the transcript, but not for ever.

    A transcript stuck in `processing` must fail the stage with that reason
    rather than hang the debrief behind it.
    """

    deadline = time.monotonic() + ceiling
    while time.monotonic() < deadline:
        response = await client.get(
            f"{BASE_URL}/v2/transcript/{transcript_id}", headers=headers
        )
        payload = response.json()
        status = payload.get("status")
        if status == "completed":
            return payload
        if status == "error":
            raise AssemblyAIUnavailable(
                f"AssemblyAI failed: {payload.get('error')}"
            )
        await asyncio.sleep(interval)

    raise AssemblyAIUnavailable(
        f"AssemblyAI still processing after {ceiling:.0f}s"
    )


async def _delete(
    client: httpx.AsyncClient, headers: dict[str, str], transcript_id: str
) -> None:
    """Remove the vendor-side copy, and say so if it did not go.

    Swallowing this would leave a client's meeting on a third party's disk with
    nobody aware of it.
    """

    try:
        response = await client.delete(
            f"{BASE_URL}/v2/transcript/{transcript_id}", headers=headers
        )
    except httpx.HTTPError as exc:
        raise AssemblyAIUnavailable(
            f"could not delete the vendor-side copy of {transcript_id}: {exc}"
        ) from exc

    if response.status_code != 200:
        raise AssemblyAIUnavailable(
            f"AssemblyAI refused to delete {transcript_id}: {response.status_code}"
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/service && uv run pytest src/app/orchestration/test_assemblyai_engines.py -v`

Expected: PASS (4 tests).

- [ ] **Step 5: Run the full service suite**

Run: `cd apps/service && uv run pytest -q && uv run ruff check .`

Note both new engine modules define `to_batch_transcription`. They are separate
modules and never imported together unqualified, but run the whole suite: the
repository has had duplicate-basename collisions before.

- [ ] **Step 6: Commit**

```bash
git add apps/service/src/app/orchestration/assemblyai_engines.py \
        apps/service/src/app/orchestration/test_assemblyai_engines.py
git commit -m "feat(orchestration): an AssemblyAI record-path batch engine"
```

---

### Task 7: Build the engine list from the settings, and wire it

**Files:**
- Create: `apps/service/src/app/orchestration/record_engines.py`
- Create: `apps/service/src/app/orchestration/test_record_engines.py`
- Modify: `apps/service/src/app/main.py:84-106`
- Modify: `apps/service/src/app/composition.py` (`read_session_audio`)

**Interfaces:**
- Consumes: `deepgram_record_engine` (Task 4), `deepgram_diarizer` (Task 5),
  `assemblyai_record_engine` (Task 6), `Backend.session_audio` (Task 3).
- Produces: `build_record_engines(store, read_audio) -> list[tuple[str, Any]]`
  and `UnconfiguredVendor`.

**Why:** the engine list must come from `connectors.record_vendors`, not be
hardcoded, or the setting describes engines that are not running.

- [ ] **Step 1: Write the failing test**

Create `apps/service/src/app/orchestration/test_record_engines.py`:

```python
"""The record path's engines come from the settings (spec §5.6)."""

from __future__ import annotations

import pytest

from app.modules.settings.models import SecretKey, SpeechVendor
from app.modules.settings.store import InMemorySettingsStore
from app.orchestration.record_engines import UnconfiguredVendor, build_record_engines


def _store(*vendors: SpeechVendor) -> InMemorySettingsStore:
    store = InMemorySettingsStore()
    store.read().connectors.record_vendors = list(vendors)
    return store


def test_one_engine_is_built_per_selected_vendor() -> None:
    store = _store(SpeechVendor.DEEPGRAM, SpeechVendor.ASSEMBLYAI)
    store.set_secret(SecretKey.DEEPGRAM_API_KEY, "dg")
    store.set_secret(SecretKey.ASSEMBLYAI_API_KEY, "aai")

    engines = build_record_engines(store, lambda _session: b"pcm")

    assert [name for name, _ in engines] == ["deepgram", "assemblyai"]


def test_a_selected_vendor_with_no_credential_is_refused_by_name() -> None:
    """Never skipped silently: the setting would then claim an engine that is
    not running, and the operator would read one transcript as two."""

    store = _store(SpeechVendor.DEEPGRAM, SpeechVendor.ASSEMBLYAI)
    store.set_secret(SecretKey.DEEPGRAM_API_KEY, "dg")

    with pytest.raises(UnconfiguredVendor, match="assemblyai"):
        build_record_engines(store, lambda _session: b"pcm")


def test_a_vendor_with_no_client_is_refused_by_name() -> None:
    """A custom endpoint has no batch client here, and pretending otherwise
    produces a session with fewer transcripts than engines."""

    store = _store(SpeechVendor.CUSTOM)

    with pytest.raises(UnconfiguredVendor, match="custom"):
        build_record_engines(store, lambda _session: b"pcm")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/service && uv run pytest src/app/orchestration/test_record_engines.py -v`

Expected: FAIL — `ModuleNotFoundError: app.orchestration.record_engines`.

- [ ] **Step 3: Write the builder**

Create `apps/service/src/app/orchestration/record_engines.py`:

```python
"""Which batch engines the record path runs, read from the settings.

FR-2.6 runs two engines and T3 requires that they diverge independently, which
is why the vendor list is a setting rather than a constant. Building it from
that setting is what keeps the screen and the behaviour the same thing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.modules.settings.models import SecretKey, SpeechVendor
from app.orchestration.assemblyai_engines import assemblyai_record_engine
from app.orchestration.deepgram_engines import deepgram_record_engine


class UnconfiguredVendor(Exception):
    """A selected record vendor cannot run.

    Raised at startup rather than skipped, because a silently-dropped engine
    leaves the settings claiming a pair and the recording screen showing one
    transcript with nothing to compare it against — which reads as an engine
    that failed rather than one that was never built.
    """


_FACTORIES: dict[SpeechVendor, tuple[str, SecretKey, Any]] = {
    SpeechVendor.DEEPGRAM: ("deepgram", SecretKey.DEEPGRAM_API_KEY, deepgram_record_engine),
    SpeechVendor.ASSEMBLYAI: (
        "assemblyai",
        SecretKey.ASSEMBLYAI_API_KEY,
        assemblyai_record_engine,
    ),
}


def build_record_engines(
    store: Any, read_audio: Callable[[str], bytes]
) -> list[tuple[str, Any]]:
    """One `(name, transcribe)` pair per selected vendor, in the configured order."""

    engines: list[tuple[str, Any]] = []
    for vendor in store.read().connectors.record_vendors:
        factory = _FACTORIES.get(vendor)
        if factory is None:
            raise UnconfiguredVendor(
                f"{vendor.value}: selected as a record engine, but no batch "
                "client exists for it"
            )
        name, key, build = factory
        if store.get_secret(key) is None:
            raise UnconfiguredVendor(
                f"{name}: selected as a record engine, but {key.value} is not "
                "configured"
            )
        engines.append((name, build(read_audio, store, name=name)))
    return engines
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/service && uv run pytest src/app/orchestration/test_record_engines.py -v`

Expected: PASS (3 tests).

- [ ] **Step 5: Expose the audio reader and wire `main.py`**

In `apps/service/src/app/composition.py`, beside the other seam helpers:

```python
def read_session_audio(backend: Backend) -> Callable[[str], bytes]:
    """The `read_audio` every vendor client takes, bound to one backend.

    Injected rather than imported so a client never reaches for `Backend` —
    the same discipline `orchestration/engines.py` follows for inference.
    """

    def read(session_id: str) -> bytes:
        entry = backend.session_audio.get(session_id)
        return bytes(entry.buffer) if entry is not None else b""

    return read
```

In `apps/service/src/app/main.py`, replace the engine wiring:

```python
    read_audio = read_session_audio(backend)
    debrief_engines, compiler_engines = engines_from_settings(
        store, diarize=deepgram_diarizer(read_audio, store)
    )

    # A selected vendor that cannot run is a refusal at startup, not a silent
    # omission that shows up as a missing transcript hours later.
    record_engines = build_record_engines(store, read_audio)
    logger.info(
        "startup: record path engines: %s",
        ", ".join(name for name, _ in record_engines),
    )

    app = build_app(
        backend,
        debrief_engines=debrief_engines,
        compiler_engines=compiler_engines,
        settings_store=store,
        record_path_engines=record_engines,
    )
```

Add the imports `from app.composition import read_session_audio`,
`from app.orchestration.deepgram_engines import deepgram_diarizer`, and
`from app.orchestration.record_engines import build_record_engines`.

Note `build_record_engines` raises when a vendor is unconfigured. `main.py` must
let that stop startup — a service that starts with no engines serves a record
path that silently produces nothing.

- [ ] **Step 6: Run the full suites**

Run, from `apps/service`: `uv run pytest -q && uv run ruff check .`
From the repo root: `uv run --project apps/service python -m pytest tests/e2e/api_integration -q`

Expected: all pass. Tests constructing `build_app` without `record_path_engines`
still get the two stubs, which is what keeps `TestClient` off the network.

- [ ] **Step 7: Commit**

```bash
git add apps/service/src/app/orchestration/record_engines.py \
        apps/service/src/app/orchestration/test_record_engines.py \
        apps/service/src/app/main.py apps/service/src/app/composition.py
git commit -m "feat(service): run the record path on the configured vendors"
```

---

### Task 8: Prove it against the real vendors

**Files:**
- Modify: `docs/journeys/06-reconcile-the-recording.md` (status table)
- Modify: `docs/journeys/07-produce-the-debrief.md` (status table)
- Modify: `handbook/` — via `python3 handbook/tools/gen.py build`

**Interfaces:**
- Consumes: everything above.
- Produces: no code. Evidence, and the documentation that follows from it.

**Why:** every claim in this plan so far rests on fixtures. Two risks are
explicitly unresolved until this task runs: **R6**, AssemblyAI's utterance shape
was proven on synthetic tone which contains no speech; and **R7**, both spikes
used a single-narrator sample, so speaker *separation* is unproven for either
vendor.

- [ ] **Step 1: Configure both credentials**

On the Settings screen, enter the Deepgram key and the AssemblyAI key in their own
fields, and press **Test** on each. Both must report reachable. The old
`asr_vendor_api_key` reads as not configured and is not reused — it is dead, and
guessing which vendor it belonged to is exactly what this design removed.

- [ ] **Step 2: Feed a real two-person recording**

Use a recording with at least two distinct speakers — this is what resolves R7.
Chunk it and post it:

```bash
# 16 kHz mono linear16, split into ~5 second chunks
python3 - <<'EOF'
import base64, httpx, wave
w = wave.open("two-speakers.wav")
assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 16000, 2)
pcm = w.readframes(w.getnframes())
step = 16000 * 2 * 5
for i, off in enumerate(range(0, len(pcm), step)):
    r = httpx.post(
        "http://127.0.0.1:8000/api/sessions/meeting-1/audio-chunk",
        json={"sequence": i, "pcm": base64.b64encode(pcm[off:off+step]).decode()},
        timeout=60,
    )
    assert r.status_code == 202, r.text
print("uploaded")
EOF

curl -s -X POST http://127.0.0.1:8000/api/sessions/meeting-1/record-path-transcript \
  -H 'Content-Type: application/json' \
  -d '{"audio_ref":"session:meeting-1"}' | python3 -m json.tool
```

- [ ] **Step 3: Confirm each item of the definition of done**

- Two `RecordPathTranscript`s come back, one per engine, both `COMPLETE`.
- A `SessionAlignment` exists and shows measured divergence — not "nothing was
  compared".
- `GET /api/sessions/meeting-1/record-path-transcript` shows both.
- The `SessionDiarization` carries **more than one** speaker tag. One tag means
  R7 is still open; investigate before claiming diarization works.
- A known product name from the engagement vocabulary is transcribed correctly
  (R4).
- The debrief runs past its diarization step and produces the four documents.
- `GET /api/audit/egress?engagement_id=<id>&start_ms=0&end_ms=9999999999999`
  shows rows for both vendors.
- `backend.session_audio` no longer holds the session, and the audio-destruction
  record exists.
- No AssemblyAI transcript remains: re-requesting the transcript id returns 404.

- [ ] **Step 4: Record what is true now, and what still is not**

Update the status tables in `docs/journeys/06-reconcile-the-recording.md` and
`docs/journeys/07-produce-the-debrief.md`. Say what now works **and** that the
live path still does not — the panel still sits at rest for a whole meeting, and
nothing about that changed here.

Then rebuild the handbook, which derives its *What Works Today* chapter from
those tables:

```bash
python3 handbook/tools/gen.py build
python3 handbook/tools/gen.py check
```

`check` must report 0 errors. Drift warnings ask a human to re-read the chapter
and are not cleared by `accept` unless somebody actually did.

- [ ] **Step 5: Commit**

```bash
git add docs/journeys/06-reconcile-the-recording.md \
        docs/journeys/07-produce-the-debrief.md handbook/
git commit -m "docs(journeys): the record path transcribes against real vendors"
```

---

## What this plan does not do

Carried to plan 2 (desktop side): the Rust capture tap (spec §5.1), the browser
AudioWorklet, the chunk uploader (§5.2), and the Stop trigger that starts a
transcription (§5.5). Until those land, audio reaches the hold only by `curl`.

Also untouched, and stated so nobody reads this as more than it is: **the live
path**. `asr-live` keeps its three scripted fakes, no nudge fires, and the panel
sits at its resting state for the whole meeting. This plan unblocks the
after-the-meeting half.

R2 (unbounded memory) has no task here because the ceiling belongs with the
uploader that fills the buffer, in plan 2. On the service side today, a caller
can post chunks until the process dies.

R9 (the Settings screen is mid-rewrite into tabs) touches Task 1 and Task 2 only
in so far as the new credentials need fields on that screen. Nothing in this plan
edits `SettingsPanel.tsx`; the two keys are reachable over the API and by
environment variable, so the screen work can land whenever the tabs rewrite does.
