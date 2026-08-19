"""Settings behaviour, with the security properties as the headline tests.

An admin screen that handles vendor credentials has one failure mode that
matters more than the rest: leaking a secret back out. Several of these
tests exist purely to make that leak impossible to reintroduce quietly.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from .models import (
    InferenceSettings,
    SecretKey,
    SecretUpdate,
    SecretValue,
    SettingsUpdateRequest,
    VendorSettings,
)
from .router import build_settings_router
from .service import apply_settings_update, check_secret_connection
from .store import InMemorySettingsStore

REAL_KEY = "sk-ant-api03-VERYSECRETVALUE-abcd"


def _client(store: InMemorySettingsStore) -> TestClient:
    app = FastAPI()

    async def read_settings():
        return store.read()

    async def apply(payload):
        return await apply_settings_update(store, payload)

    async def check(key):
        return await check_secret_connection(store, key)

    app.include_router(build_settings_router(read_settings, apply, check))
    return TestClient(app)


def _store() -> InMemorySettingsStore:
    return InMemorySettingsStore(read_environment=False)


# --------------------------------------------------------------------------
# Secrets go in, never out.
# --------------------------------------------------------------------------


def test_a_stored_secret_is_never_returned_by_the_api() -> None:
    """The single most important property of this surface."""

    store = _store()
    client = _client(store)

    client.put(
        "/api/admin/settings",
        json={"secrets": [{"key": "anthropic_api_key", "value": REAL_KEY}]},
    )
    body = client.get("/api/admin/settings").text

    assert REAL_KEY not in body
    assert "VERYSECRETVALUE" not in body


def test_a_read_reports_presence_and_a_hint_so_the_operator_knows_which_key() -> None:
    store = _store()
    client = _client(store)

    client.put(
        "/api/admin/settings",
        json={"secrets": [{"key": "anthropic_api_key", "value": REAL_KEY}]},
    )
    secrets = {s["key"]: s for s in client.get("/api/admin/settings").json()["secrets"]}

    assert secrets["anthropic_api_key"]["configured"] is True
    assert secrets["anthropic_api_key"]["hint"] == "abcd"
    assert secrets["asr_vendor_api_key"]["configured"] is False


def test_a_secret_refuses_to_print_itself() -> None:
    """Redaction is the default path, not a call-site habit.

    A stray log line or a traceback that renders locals must not be able to
    print a live credential.
    """

    secret = SecretValue(REAL_KEY)

    assert REAL_KEY not in repr(secret)
    assert REAL_KEY not in str(secret)
    assert REAL_KEY not in f"{secret}"
    assert secret.reveal() == REAL_KEY


def test_an_unset_secret_reports_no_hint() -> None:
    assert _store().read().secrets[0].hint is None


# --------------------------------------------------------------------------
# Saving one panel must not disturb the others.
# --------------------------------------------------------------------------


async def test_omitting_a_section_leaves_it_untouched() -> None:
    """The admin UI saves one panel at a time."""

    store = _store()
    await apply_settings_update(
        store, SettingsUpdateRequest(vendors=VendorSettings(asr_base_url="https://asr.example"))
    )

    await apply_settings_update(
        store, SettingsUpdateRequest(inference=InferenceSettings(model="claude-sonnet-5"))
    )

    settings = store.read()
    assert settings.vendors.asr_base_url == "https://asr.example"
    assert settings.inference.model == "claude-sonnet-5"


async def test_saving_without_a_secret_entry_does_not_clear_the_stored_one() -> None:
    """The form cannot resend a secret it was never given.

    If an absent field cleared the secret, every unrelated save would log the
    operator out of their vendor.
    """

    store = _store()
    store.set_secret(SecretKey.ANTHROPIC_API_KEY, REAL_KEY)

    await apply_settings_update(
        store, SettingsUpdateRequest(inference=InferenceSettings(model="claude-opus-5"))
    )

    assert store.get_secret(SecretKey.ANTHROPIC_API_KEY) is not None


async def test_an_empty_value_clears_a_secret() -> None:
    """Clearing must be possible, and must actually remove the value."""

    store = _store()
    store.set_secret(SecretKey.ANTHROPIC_API_KEY, REAL_KEY)

    await apply_settings_update(
        store,
        SettingsUpdateRequest(
            secrets=[SecretUpdate(key=SecretKey.ANTHROPIC_API_KEY, value="")]
        ),
    )

    assert store.get_secret(SecretKey.ANTHROPIC_API_KEY) is None
    assert store.read().secrets[0].configured is False


# --------------------------------------------------------------------------
# Environment fallback, connection test, and the API's own shape.
# --------------------------------------------------------------------------


def test_the_environment_still_configures_a_headless_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", REAL_KEY)
    store = InMemorySettingsStore()

    assert store.get_secret(SecretKey.ANTHROPIC_API_KEY) is not None


def test_a_value_set_in_the_ui_wins_over_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The more specific and more recent statement of intent wins."""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-environment-0000")
    store = InMemorySettingsStore()

    store.set_secret(SecretKey.ANTHROPIC_API_KEY, REAL_KEY)

    assert store.get_secret(SecretKey.ANTHROPIC_API_KEY).reveal() == REAL_KEY


async def test_testing_an_unconfigured_credential_says_so_plainly() -> None:
    check = await check_secret_connection(_store(), SecretKey.ANTHROPIC_API_KEY)

    assert check.reachable is False
    assert "No credential" in check.detail


async def test_an_unverified_credential_is_not_reported_as_reachable() -> None:
    """Configured is not the same as working, and must not be shown as such."""

    store = _store()
    store.set_secret(SecretKey.ANTHROPIC_API_KEY, REAL_KEY)

    check = await check_secret_connection(store, SecretKey.ANTHROPIC_API_KEY)

    assert check.reachable is False
    assert "not verified" in check.detail
    assert REAL_KEY not in check.detail


async def test_a_failing_probe_reports_the_vendor_error_not_the_credential() -> None:
    store = _store()
    store.set_secret(SecretKey.ANTHROPIC_API_KEY, REAL_KEY)

    async def probe(_key: str) -> None:
        raise PermissionError("invalid x-api-key")

    check = await check_secret_connection(store, SecretKey.ANTHROPIC_API_KEY, probe)

    assert check.reachable is False
    assert "invalid x-api-key" in check.detail
    assert REAL_KEY not in check.detail


async def test_a_successful_probe_reports_the_credential_as_verified() -> None:
    store = _store()
    store.set_secret(SecretKey.ANTHROPIC_API_KEY, REAL_KEY)

    async def probe(key: str) -> None:
        assert key == REAL_KEY

    check = await check_secret_connection(store, SecretKey.ANTHROPIC_API_KEY, probe)

    assert check.reachable is True


def test_an_unknown_secret_key_is_rejected_rather_than_silently_stored() -> None:
    """A typo'd key would otherwise create a second, never-read secret."""

    response = _client(_store()).put(
        "/api/admin/settings",
        json={"secrets": [{"key": "anthropc_api_key", "value": "x"}]},
    )

    assert response.status_code == 422


def test_unknown_settings_fields_are_rejected() -> None:
    """A renamed field must fail loudly, not be dropped on the floor."""

    response = _client(_store()).put(
        "/api/admin/settings", json={"inference": {"modle": "claude-opus-5"}}
    )

    assert response.status_code == 422


def test_the_response_tells_the_operator_the_new_state() -> None:
    """The client re-renders from the service, not from an optimistic guess."""

    client = _client(_store())

    body = client.put(
        "/api/admin/settings",
        json={
            "inference": {"model": "claude-opus-5"},
            "secrets": [{"key": "anthropic_api_key", "value": REAL_KEY}],
        },
    ).json()

    assert body["inference"]["model"] == "claude-opus-5"
    hints = {s["key"]: s["hint"] for s in body["secrets"]}
    assert hints["anthropic_api_key"] == "abcd"
