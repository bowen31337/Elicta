"""Settings behaviour, with the security properties as the headline tests.

An admin screen that handles vendor credentials has one failure mode that
matters more than the rest: leaking a secret back out. Several of these
tests exist purely to make that leak impossible to reintroduce quietly.
"""

from __future__ import annotations

from pathlib import Path

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


# --------------------------------------------------------------------------
# Provider choice. Every option is an Anthropic Messages API surface — that
# is a constraint, not a gap: the service depends on structured outputs and
# cache-boundary control that only exist there.
# --------------------------------------------------------------------------


def test_every_offered_provider_is_an_anthropic_messages_api_surface() -> None:
    """An OpenAI-shaped endpoint would fail per stage, not at configuration.

    Keeping the list closed is what turns that into an impossible choice
    rather than a debrief that fails hours later.
    """

    from .models import LlmProvider

    assert {p.value for p in LlmProvider} == {
        "anthropic",
        "bedrock",
        "vertex",
        "foundry",
        "anthropic_compatible",
    }


def test_a_compatible_gateway_needs_an_endpoint() -> None:
    from .models import InferenceSettings, LlmProvider

    with pytest.raises(ValueError, match="base_url"):
        InferenceSettings(provider=LlmProvider.COMPATIBLE)


def test_a_compatible_gateway_is_accepted_with_one() -> None:
    """Any self-hosted or third-party Messages-API endpoint is a valid choice."""

    from .models import InferenceSettings, LlmProvider

    settings = InferenceSettings(
        provider=LlmProvider.COMPATIBLE, base_url="https://llm.internal/v1"
    )

    assert settings.base_url == "https://llm.internal/v1"


@pytest.mark.parametrize(
    ("provider", "kwargs", "missing"),
    [
        ("bedrock", {}, "region"),
        ("vertex", {"region": "us"}, "project_id"),
        ("vertex", {"project_id": "p"}, "region"),
        ("foundry", {}, "resource"),
    ],
)
def test_a_provider_missing_what_it_needs_is_rejected_at_save_time(
    provider: str, kwargs: dict, missing: str
) -> None:
    from .models import InferenceSettings

    with pytest.raises(ValueError, match=missing):
        InferenceSettings(provider=provider, **kwargs)


def test_cloud_providers_use_the_hosts_own_credentials() -> None:
    """Asking for a pasted key where IAM or ADC exists invites a worse one."""

    from .models import LlmProvider

    assert LlmProvider.BEDROCK.uses_stored_credential is False
    assert LlmProvider.VERTEX.uses_stored_credential is False
    assert LlmProvider.ANTHROPIC.uses_stored_credential is True
    assert LlmProvider.COMPATIBLE.uses_stored_credential is True


def test_a_custom_speech_service_can_be_configured() -> None:
    """An engagement may mandate a processor we have never heard of."""

    from .models import ConnectorSettings, SpeechVendor

    connectors = ConnectorSettings(
        live_vendor=SpeechVendor.CUSTOM,
        custom_vendor_name="In-house STT",
        custom_base_url="https://stt.internal",
    )

    assert connectors.live_vendor is SpeechVendor.CUSTOM


def test_a_custom_speech_service_without_an_endpoint_is_rejected() -> None:
    from .models import ConnectorSettings, SpeechVendor

    with pytest.raises(ValueError, match="custom_base_url"):
        ConnectorSettings(live_vendor=SpeechVendor.CUSTOM)


def test_the_record_pair_must_still_differ_even_when_custom() -> None:
    """T3 holds regardless of vendor: identical engines agree by construction."""

    from .models import ConnectorSettings, SpeechVendor

    with pytest.raises(ValueError, match="different vendors"):
        ConnectorSettings(
            record_vendors=[SpeechVendor.CUSTOM, SpeechVendor.CUSTOM],
            custom_base_url="https://stt.internal",
        )


class TestManagedSecretStore:
    """The key comes from wherever a shared deployment keeps its secrets.

    The point of this seam is that it never falls back. A store that could not
    be reached and quietly generated a local key instead would look like it
    worked, and would produce a node whose settings no other node can read.
    """

    def test_the_key_is_read_from_the_operators_secret_store_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cryptography.fernet import Fernet

        from app.modules.settings.sqlite_store import (
            KEY_COMMAND_ENV_VAR,
            SqliteSettingsStore,
        )

        key = Fernet.generate_key().decode()
        monkeypatch.setenv(KEY_COMMAND_ENV_VAR, f"printf %s {key}")

        store = SqliteSettingsStore(tmp_path / "settings.db", read_environment=False)
        store.set_secret(SecretKey.ANTHROPIC_API_KEY, "sk-ant-secret")

        # No key file was written: the whole point is that it stays in the
        # store, so a compromised host yields nothing.
        assert not (tmp_path / "settings.key").exists()
        assert store.get_secret(SecretKey.ANTHROPIC_API_KEY) is not None

    def test_a_second_process_with_the_same_command_reads_the_same_secrets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cryptography.fernet import Fernet

        from app.modules.settings.sqlite_store import (
            KEY_COMMAND_ENV_VAR,
            SqliteSettingsStore,
        )

        key = Fernet.generate_key().decode()
        monkeypatch.setenv(KEY_COMMAND_ENV_VAR, f"printf %s {key}")
        database = tmp_path / "settings.db"

        SqliteSettingsStore(database, read_environment=False).set_secret(
            SecretKey.ANTHROPIC_API_KEY, "sk-ant-secret"
        )
        # A different node in the same deployment, sharing only the store.
        second = SqliteSettingsStore(database, read_environment=False)

        secret = second.get_secret(SecretKey.ANTHROPIC_API_KEY)
        assert secret is not None and secret.reveal() == "sk-ant-secret"

    def test_an_unreachable_store_fails_loudly_rather_than_inventing_a_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.settings.sqlite_store import (
            KEY_COMMAND_ENV_VAR,
            SettingsKeyUnavailableError,
            SqliteSettingsStore,
        )

        monkeypatch.setenv(KEY_COMMAND_ENV_VAR, "printf 'vault sealed' >&2; exit 1")

        with pytest.raises(SettingsKeyUnavailableError) as raised:
            SqliteSettingsStore(tmp_path / "settings.db", read_environment=False)

        # The command's own diagnosis reaches the operator, who is the only
        # one who can fix a sealed vault.
        assert "vault sealed" in str(raised.value)
        assert not (tmp_path / "settings.key").exists()

    def test_an_empty_answer_is_treated_as_a_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A command that succeeds but prints nothing is the shape a typo in a
        # secret's name takes. Accepting it would encrypt everything under an
        # empty key.
        from app.modules.settings.sqlite_store import (
            KEY_COMMAND_ENV_VAR,
            SettingsKeyUnavailableError,
            SqliteSettingsStore,
        )

        monkeypatch.setenv(KEY_COMMAND_ENV_VAR, "true")

        with pytest.raises(SettingsKeyUnavailableError):
            SqliteSettingsStore(tmp_path / "settings.db", read_environment=False)

    def test_the_command_wins_over_a_key_in_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cryptography.fernet import Fernet

        from app.modules.settings.sqlite_store import (
            KEY_COMMAND_ENV_VAR,
            KEY_ENV_VAR,
            SqliteSettingsStore,
        )

        managed = Fernet.generate_key().decode()
        monkeypatch.setenv(KEY_ENV_VAR, Fernet.generate_key().decode())
        monkeypatch.setenv(KEY_COMMAND_ENV_VAR, f"printf %s {managed}")

        SqliteSettingsStore(tmp_path / "settings.db", read_environment=False).set_secret(
            SecretKey.ANTHROPIC_API_KEY, "sk-ant-secret"
        )

        # Readable with the managed key, proving that is the one in use.
        monkeypatch.delenv(KEY_COMMAND_ENV_VAR)
        monkeypatch.setenv(KEY_ENV_VAR, managed)
        reopened = SqliteSettingsStore(tmp_path / "settings.db", read_environment=False)
        secret = reopened.get_secret(SecretKey.ANTHROPIC_API_KEY)
        assert secret is not None and secret.reveal() == "sk-ant-secret"
