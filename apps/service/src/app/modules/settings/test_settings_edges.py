"""The settings edges: comparing secrets, saving connectors, and the test button.

`test_settings.py` covers the shape an operator sees. What it leaves out is the
narrow set of paths that only appear when something is wrong or unusual — a key
command that hangs, a record-path pair with the wrong number of engines, a
credential test for a key nobody wired a probe to. Each of those is a route by
which the settings screen could quietly tell an operator the wrong thing, so
each is asserted here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from .models import (
    ConnectionCheck,
    ConnectorSettings,
    SecretKey,
    SecretValue,
    SettingsUpdateRequest,
    SpeechVendor,
    VendorSettings,
)
from .probes import ProbeFailed, probe_deepgram
from .router import build_settings_router
from .service import apply_settings_update
from .sqlite_store import (
    SettingsKeyUnavailableError,
    SqliteSettingsStore,
    _key_from_command,
)
from .store import InMemorySettingsStore

# --- SecretValue behaves as a value, without becoming printable ------------


def test_two_secrets_with_the_same_value_are_equal() -> None:
    assert SecretValue("sk-ant-0000") == SecretValue("sk-ant-0000")


def test_a_secret_is_never_equal_to_the_bare_string_that_made_it() -> None:
    # Otherwise a comparison against a plain string would be a route by which
    # code drifts back to handling secrets unwrapped.
    assert SecretValue("sk-ant-0000") != "sk-ant-0000"


def test_secrets_with_different_values_differ() -> None:
    assert SecretValue("sk-ant-0000") != SecretValue("sk-ant-9999")


def test_a_secret_can_be_a_dictionary_key() -> None:
    assert {SecretValue("sk-ant-0000"): "in place"}[SecretValue("sk-ant-0000")] == "in place"


# --- the record path runs exactly two engines ------------------------------


@pytest.mark.parametrize("vendors", [[], [SpeechVendor.DEEPGRAM]])
def test_the_record_path_refuses_fewer_than_two_engines(vendors: list[SpeechVendor]) -> None:
    # One engine has nothing to reconcile against, and reconciliation is the
    # whole reason the record path runs two.
    with pytest.raises(ValueError, match="exactly two batch engines"):
        ConnectorSettings(record_vendors=vendors)


def test_the_record_path_refuses_three_engines() -> None:
    with pytest.raises(ValueError, match="exactly two batch engines"):
        ConnectorSettings(
            record_vendors=[
                SpeechVendor.DEEPGRAM,
                SpeechVendor.ASSEMBLYAI,
                SpeechVendor.DEEPGRAM,
            ]
        )


# --- saving one panel at a time --------------------------------------------


async def test_saving_connectors_alone_leaves_the_other_panels_untouched() -> None:
    store = InMemorySettingsStore()
    store.write_vendors(VendorSettings(asr_base_url="https://asr.example"))

    settings = await apply_settings_update(
        store,
        SettingsUpdateRequest(connectors=ConnectorSettings(live_vendor=SpeechVendor.DEEPGRAM)),
    )

    assert settings.connectors.live_vendor is SpeechVendor.DEEPGRAM
    assert settings.vendors.asr_base_url == "https://asr.example"


def test_writing_connectors_is_readable_back(tmp_path: Path) -> None:
    store = SqliteSettingsStore(tmp_path / "settings.db", read_environment=False)

    store.write_vendors(VendorSettings(asr_base_url="https://asr.example"))
    store.write_connectors(ConnectorSettings(live_vendor=SpeechVendor.DEEPGRAM))

    reopened = SqliteSettingsStore(tmp_path / "settings.db", read_environment=False).read()
    assert reopened.connectors.live_vendor is SpeechVendor.DEEPGRAM
    assert reopened.vendors.asr_base_url == "https://asr.example"


# --- a key command that never returns --------------------------------------


def test_a_key_command_that_hangs_is_given_up_on(monkeypatch: pytest.MonkeyPatch) -> None:
    # Without the timeout the service would hang at startup with no diagnosis.
    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="sleep 600", timeout=30)

    monkeypatch.setattr(subprocess, "run", hang)

    with pytest.raises(SettingsKeyUnavailableError, match="timed out after 30s"):
        _key_from_command("sleep 600")


# --- a vendor that is reachable but broken ---------------------------------


class _Transport(httpx.AsyncBaseTransport):
    def __init__(self, status: int) -> None:
        self.status = status

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(self.status, json={})


@pytest.fixture
def patched_transport(monkeypatch: pytest.MonkeyPatch):
    def install(status: int) -> None:
        original = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = _Transport(status)
            original(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    return install


async def test_a_vendor_error_is_not_reported_as_a_bad_credential(patched_transport) -> None:
    # 500 is the vendor's problem, not the operator's key. Reporting it as a
    # rejected credential would send them to rotate a key that is fine.
    patched_transport(500)

    with pytest.raises(ProbeFailed, match="Deepgram returned 500"):
        await probe_deepgram("dg-key")


# --- the credential test endpoint ------------------------------------------


def _client(check_connection) -> TestClient:
    store = InMemorySettingsStore()

    async def read_settings():
        return store.read()

    async def apply_settings(payload):
        return await apply_settings_update(store, payload)

    app = FastAPI()
    app.include_router(build_settings_router(read_settings, apply_settings, check_connection))
    return TestClient(app)


def test_testing_a_credential_returns_the_verdict_as_a_200() -> None:
    # A failed *check* is not a failed *request*: the operator needs the reason
    # rendered next to the field, not an exception page.
    async def check_connection(key: SecretKey) -> ConnectionCheck:
        return ConnectionCheck(key=key, reachable=False, detail="No credential is configured.")

    response = _client(check_connection).post("/api/admin/settings/anthropic_api_key/test")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "key": "anthropic_api_key",
        "reachable": False,
        "detail": "No credential is configured.",
    }


def test_a_key_with_nothing_behind_it_is_a_404() -> None:
    async def check_connection(key: SecretKey) -> ConnectionCheck:
        raise KeyError(f"no probe registered for {key.value}")

    response = _client(check_connection).post("/api/admin/settings/asr_vendor_api_key/test")

    assert response.status_code == 404
    assert "asr_vendor_api_key" in response.json()["detail"]


def test_a_key_that_is_not_a_settable_secret_is_rejected() -> None:
    async def check_connection(key: SecretKey) -> ConnectionCheck:  # pragma: no cover
        raise AssertionError("an unknown key must never reach the check")

    response = _client(check_connection).post("/api/admin/settings/not_a_secret/test")

    assert response.status_code == 422
