"""The enrolment API, including the promise that the sample is not kept."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from .embedding import MODEL_NAME, SAMPLE_RATE
from .models import OperatorVoiceprint
from .router import build_voiceprint_router
from .test_embedding import TRACT_A, voice

FIXED_NOW = datetime(2026, 8, 23, 10, 30, tzinfo=UTC)


class Store:
    """A voiceprint store that also notices anything else written to it.

    `written` exists for one test: FR-1.7 says raw audio never reaches
    persistent storage, and the only way to assert a negative is to give the
    route somewhere it *could* put the sample and show it did not.
    """

    def __init__(self) -> None:
        self.prints: dict[str, OperatorVoiceprint] = {}
        self.written: list[object] = []

    async def get(self, operator_id: str) -> OperatorVoiceprint | None:
        return self.prints.get(operator_id)

    async def save(self, voiceprint: OperatorVoiceprint) -> None:
        self.written.append(voiceprint)
        self.prints[voiceprint.operator_id] = voiceprint

    async def forget(self, operator_id: str) -> bool:
        return self.prints.pop(operator_id, None) is not None


@pytest.fixture
def store() -> Store:
    return Store()


@pytest.fixture
def client(store: Store) -> TestClient:
    app = FastAPI()
    app.include_router(
        build_voiceprint_router(store.get, store.save, store.forget, now=lambda: FIXED_NOW)
    )
    return TestClient(app)


def sample(seconds: float = 6.0) -> str:
    return base64.b64encode(voice(TRACT_A, seconds=seconds).tobytes()).decode("ascii")


def test_an_operator_who_has_not_enrolled_gets_an_answer_not_a_404(client: TestClient) -> None:
    """Not enrolled is a state of the screen, not a missing resource. A 404
    would be indistinguishable from the service being unreachable."""

    response = client.get("/api/operator/voiceprint")

    assert response.status_code == 200
    assert response.json()["enrolled"] is False


def test_the_screen_is_told_the_cap_it_should_count_down_to(client: TestClient) -> None:
    body = client.get("/api/operator/voiceprint").json()

    assert body["max_sample_seconds"] == 60
    assert body["min_sample_seconds"] == 3


def test_enrolling_reports_the_sample_it_actually_kept(client: TestClient) -> None:
    response = client.post("/api/operator/voiceprint", json={"pcm": sample(8.0)})

    assert response.status_code == 201
    body = response.json()
    assert body["enrolled"] is True
    assert body["sample_seconds"] == 8.0
    assert body["embedding_model"] == MODEL_NAME
    assert body["usable"] is True


def test_the_status_never_returns_the_voiceprint_itself(client: TestClient) -> None:
    """Biometric material, on a read anyone reaching the API can make, that
    nothing on the screen has any use for."""

    client.post("/api/operator/voiceprint", json={"pcm": sample()})

    body = client.get("/api/operator/voiceprint").json()

    assert "embedding" not in body
    assert MODEL_NAME in str(body)  # the model is named; the bytes are not there


def test_the_recording_is_never_written_anywhere(client: TestClient, store: Store) -> None:
    """FR-1.7. The sample becomes an embedding inside the handler and goes out
    of scope; nothing persists the audio, here or anywhere downstream."""

    pcm = sample()
    client.post("/api/operator/voiceprint", json={"pcm": pcm})

    assert len(store.written) == 1
    saved = store.written[0]
    assert isinstance(saved, OperatorVoiceprint)
    # The embedding is 24 float32s regardless of how long the sample was, so a
    # print can never be a recording however this is later changed.
    assert len(base64.b64decode(saved.embedding)) == 96
    assert pcm not in str(saved.model_dump())


def test_re_enrolling_replaces_rather_than_accumulates(
    client: TestClient, store: Store
) -> None:
    client.post("/api/operator/voiceprint", json={"pcm": sample(6.0)})
    client.post("/api/operator/voiceprint", json={"pcm": sample(10.0)})

    assert len(store.prints) == 1
    assert client.get("/api/operator/voiceprint").json()["sample_seconds"] == 10.0


def test_a_silent_recording_is_refused_with_something_an_operator_can_act_on(
    client: TestClient,
) -> None:
    silence = base64.b64encode(bytes(SAMPLE_RATE * 2 * 6)).decode("ascii")

    response = client.post("/api/operator/voiceprint", json={"pcm": silence})

    assert response.status_code == 422
    assert "no speech" in response.json()["detail"]


def test_a_refused_enrolment_leaves_the_previous_print_standing(
    client: TestClient, store: Store
) -> None:
    """Re-recording badly must not cost the enrolment that already worked."""

    client.post("/api/operator/voiceprint", json={"pcm": sample()})
    silence = base64.b64encode(bytes(SAMPLE_RATE * 2 * 6)).decode("ascii")

    client.post("/api/operator/voiceprint", json={"pcm": silence})

    assert client.get("/api/operator/voiceprint").json()["enrolled"] is True


def test_a_print_from_a_retired_embedder_reads_as_unusable(
    client: TestClient, store: Store
) -> None:
    """Enrolled and verifying nothing is a real state, and the screen has to be
    able to tell it from enrolled and working."""

    store.prints["local-operator"] = OperatorVoiceprint(
        operator_id="local-operator",
        embedding=base64.b64encode(b"\x00" * 96).decode("ascii"),
        embedding_model="ecapa-tdnn-v2",
        sample_duration_ms=42_000,
        enrolled_at=FIXED_NOW,
    )

    body = client.get("/api/operator/voiceprint").json()

    assert body["enrolled"] is True
    assert body["usable"] is False


def test_un_enrolling_removes_the_print(client: TestClient) -> None:
    client.post("/api/operator/voiceprint", json={"pcm": sample()})

    assert client.delete("/api/operator/voiceprint").status_code == 204
    assert client.get("/api/operator/voiceprint").json()["enrolled"] is False


def test_un_enrolling_when_not_enrolled_is_not_a_failure(client: TestClient) -> None:
    """The caller asked for a state, and got it."""

    assert client.delete("/api/operator/voiceprint").status_code == 204
