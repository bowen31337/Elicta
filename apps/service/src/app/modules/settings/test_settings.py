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
from .probes import ProbeFailed, probe_for_vendor
from .router import build_settings_router
from .service import apply_settings_update, check_secret_connection
from .speech_admin import (
    add_credential,
    check_credential,
    remove_credential,
    set_policy,
    update_credential,
)
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

    async def add_speech(payload):
        return add_credential(store, payload)

    async def update_speech(credential_id, payload):
        return update_credential(store, credential_id, payload)

    async def remove_speech(credential_id):
        remove_credential(store, credential_id)

    async def check_speech(credential_id):
        return await check_credential(
            store, credential_id, lambda vendor: probe_for_vendor(vendor.value)
        )

    async def speech_policy(payload):
        return set_policy(store, payload)

    app.include_router(
        build_settings_router(
            read_settings,
            apply,
            check,
            add_speech,
            update_speech,
            remove_speech,
            check_speech,
            speech_policy,
        )
    )
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


async def test_a_probe_failure_reads_as_the_vendor_speaking_not_a_python_class() -> None:
    """`ProbeFailed:` is an internal type name, and an operator reads this string.

    The detail is rendered verbatim next to the field in the settings form, so
    a leaked class name is operator-facing copy that means nothing to them.
    """

    store = _store()
    store.set_secret(SecretKey.ASR_VENDOR_API_KEY, REAL_KEY)

    async def probe(_key: str) -> None:
        raise ProbeFailed("Deepgram rejected the credential (401)")

    check = await check_secret_connection(store, SecretKey.ASR_VENDOR_API_KEY, probe)

    assert check.reachable is False
    assert check.detail == "Deepgram rejected the credential (401)"


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

    from .models import ConnectorSettings

    connectors = ConnectorSettings(
        custom_vendor_name="In-house STT",
        custom_base_url="https://stt.internal",
    )

    assert connectors.custom_base_url == "https://stt.internal"


def test_a_custom_speech_service_without_an_endpoint_is_rejected() -> None:
    """Asserted through the record pair now that the live path has no setting.

    The rule is unchanged — a custom vendor without an endpoint is a meeting
    that fails at the first call — and it was reached through `live_vendor`
    only because that was the shortest way to name a custom vendor. The pool
    chooses the live provider now; the record pair is where a vendor is still
    named in settings.
    """

    from .models import ConnectorSettings, SpeechVendor

    with pytest.raises(ValueError, match="custom_base_url"):
        ConnectorSettings(
            record_vendors=[SpeechVendor.CUSTOM, SpeechVendor.DEEPGRAM]
        )


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


class TestTheDocumentSourceConnector:
    """Where a linked SharePoint or OneDrive document is read from.

    The connector is useless without somewhere to put the tenant, the app
    registration and its secret, and the convention here is that a credential
    lives in the settings store rather than only in the environment — so a key
    entered in the UI takes effect without a restart.
    """

    def test_the_client_secret_is_one_of_the_secrets_an_operator_can_set(self):
        from app.modules.settings.models import SecretKey

        assert SecretKey.MICROSOFT_GRAPH_CLIENT_SECRET.value == (
            "microsoft_graph_client_secret"
        )

    def test_the_tenant_and_client_id_are_not_secrets(self):
        from app.modules.settings.models import DocumentSourceSettings

        settings = DocumentSourceSettings(tenant_id="t-1", client_id="c-1")

        assert settings.tenant_id == "t-1"
        assert settings.client_id == "c-1"

    def test_they_default_to_unconfigured_rather_than_to_a_guess(self):
        from app.modules.settings.models import DocumentSourceSettings

        settings = DocumentSourceSettings()

        assert settings.tenant_id is None
        assert settings.client_id is None

    def test_the_section_round_trips_through_the_store(self):
        from app.modules.settings.models import DocumentSourceSettings
        from app.modules.settings.store import InMemorySettingsStore

        store = InMemorySettingsStore(read_environment=False)
        store.write_documents(DocumentSourceSettings(tenant_id="t-1", client_id="c-1"))

        assert store.read().documents.tenant_id == "t-1"
        assert store.read().documents.client_id == "c-1"

    def test_the_client_secret_round_trips_and_reads_back_as_a_hint_only(self):
        from app.modules.settings.models import SecretKey
        from app.modules.settings.store import InMemorySettingsStore

        store = InMemorySettingsStore(read_environment=False)
        store.set_secret(SecretKey.MICROSOFT_GRAPH_CLIENT_SECRET, "super-secret-value")

        status = {s.key: s for s in store.read().secrets}[
            SecretKey.MICROSOFT_GRAPH_CLIENT_SECRET
        ]
        assert status.configured is True
        assert status.hint == "alue"
        assert "super-secret-value" not in store.read().model_dump_json()

    async def test_an_update_request_can_carry_the_section(self):
        from app.modules.settings.models import (
            DocumentSourceSettings,
            SettingsUpdateRequest,
        )
        from app.modules.settings.service import apply_settings_update
        from app.modules.settings.store import InMemorySettingsStore

        store = InMemorySettingsStore(read_environment=False)
        await apply_settings_update(
            store,
            SettingsUpdateRequest(
                documents=DocumentSourceSettings(tenant_id="t-9", client_id="c-9")
            ),
        )

        assert store.read().documents.tenant_id == "t-9"


class TestTheHeadlessFallbackForTheConnector:
    """A deployment with no operator at a screen still has to be configurable.

    The convention here is that the environment is a fallback a UI-set value
    overrides — so the tenant and client id need one too, not just the secret.
    Documenting a variable nothing reads is how a runbook starts lying.
    """

    def test_the_tenant_and_client_id_come_from_the_environment_when_unset(
        self, monkeypatch
    ):
        from app.modules.settings.store import InMemorySettingsStore

        monkeypatch.setenv("ELICTA_GRAPH_TENANT_ID", "tenant-from-env")
        monkeypatch.setenv("ELICTA_GRAPH_CLIENT_ID", "client-from-env")

        documents = InMemorySettingsStore().read().documents

        assert documents.tenant_id == "tenant-from-env"
        assert documents.client_id == "client-from-env"

    def test_a_value_set_in_the_ui_wins_over_the_environment(self, monkeypatch):
        from app.modules.settings.models import DocumentSourceSettings
        from app.modules.settings.store import InMemorySettingsStore

        monkeypatch.setenv("ELICTA_GRAPH_TENANT_ID", "tenant-from-env")
        store = InMemorySettingsStore()
        store.write_documents(DocumentSourceSettings(tenant_id="tenant-from-ui"))

        assert store.read().documents.tenant_id == "tenant-from-ui"

    def test_the_environment_is_ignored_when_the_store_is_told_to(self, monkeypatch):
        from app.modules.settings.store import InMemorySettingsStore

        monkeypatch.setenv("ELICTA_GRAPH_TENANT_ID", "tenant-from-env")

        assert InMemorySettingsStore(read_environment=False).read().documents.tenant_id is None


class TestTheModelEnvironmentFallback:
    """`ELICTA_INFERENCE_MODEL` has to actually choose the model.

    It was consulted only when the settings carried no model — and the field
    defaults to `claude-opus-5`, so it never did. An operator whose credential
    cannot reach that model set the documented variable, watched every call
    return 429, and had no way to tell that the variable was being ignored.

    Same contract as every other environment value here: it fills a setting
    nobody has chosen, and anything chosen in the UI wins.
    """

    def test_an_unwritten_model_comes_from_the_environment(self, monkeypatch):
        from app.modules.settings.store import InMemorySettingsStore

        monkeypatch.setenv("ELICTA_INFERENCE_MODEL", "claude-haiku-4-5-20251001")

        assert InMemorySettingsStore().read().inference.model == (
            "claude-haiku-4-5-20251001"
        )

    def test_a_model_chosen_in_the_ui_wins(self, monkeypatch):
        from app.modules.settings.models import InferenceSettings
        from app.modules.settings.store import InMemorySettingsStore

        monkeypatch.setenv("ELICTA_INFERENCE_MODEL", "claude-haiku-4-5-20251001")
        store = InMemorySettingsStore()
        store.write_inference(InferenceSettings(model="claude-opus-5"))

        assert store.read().inference.model == "claude-opus-5"

    def test_with_no_variable_the_built_in_default_still_applies(self, monkeypatch):
        from app.modules.settings.store import InMemorySettingsStore

        monkeypatch.delenv("ELICTA_INFERENCE_MODEL", raising=False)

        assert InMemorySettingsStore().read().inference.model == "claude-opus-5"

    def test_the_durable_store_reads_it_too(self, monkeypatch, tmp_path):
        from app.modules.settings.sqlite_store import SqliteSettingsStore

        monkeypatch.setenv("ELICTA_INFERENCE_MODEL", "claude-haiku-4-5-20251001")

        assert SqliteSettingsStore(tmp_path / "s.db").read().inference.model == (
            "claude-haiku-4-5-20251001"
        )


class TestTheAuthModeFallback:
    """A headless deployment has to be able to use the credential it was given.

    `.env.example` says either credential works and "the Settings screen
    selects which is live" — which leaves a service with no operator at a
    screen unable to select anything. `auth_mode` defaults to `api_key`, so a
    deployment given only `ANTHROPIC_AUTH_TOKEN` fails closed with "no api key
    configured for anthropic" while holding a perfectly good token.

    A default that contradicts the only credential present is not a choice.
    """

    def test_only_an_oauth_token_configured_selects_oauth(self, monkeypatch):
        from app.modules.settings.models import AuthMode
        from app.modules.settings.store import InMemorySettingsStore

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-ant-oat01-whatever")

        assert InMemorySettingsStore().read().inference.auth_mode is AuthMode.OAUTH_TOKEN

    def test_an_api_key_keeps_the_default(self, monkeypatch):
        from app.modules.settings.models import AuthMode
        from app.modules.settings.store import InMemorySettingsStore

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-whatever")
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

        assert InMemorySettingsStore().read().inference.auth_mode is AuthMode.API_KEY

    def test_both_configured_leaves_the_default_alone(self, monkeypatch):
        """With both present there is a real choice to make, and it is not ours."""
        from app.modules.settings.models import AuthMode
        from app.modules.settings.store import InMemorySettingsStore

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-whatever")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-ant-oat01-whatever")

        assert InMemorySettingsStore().read().inference.auth_mode is AuthMode.API_KEY

    def test_a_mode_chosen_in_the_ui_wins(self, monkeypatch):
        from app.modules.settings.models import AuthMode, InferenceSettings
        from app.modules.settings.store import InMemorySettingsStore

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-ant-oat01-whatever")
        store = InMemorySettingsStore()
        store.write_inference(InferenceSettings(auth_mode=AuthMode.API_KEY))

        assert store.read().inference.auth_mode is AuthMode.API_KEY


class TestWhereTheDataIsKept:
    """SQLite by default; anything else is opted into from the Settings screen.

    A PostgreSQL URL carries a password, so the URL itself is a secret and is
    write-only like every other one. What comes back is the same URL with the
    password removed — enough to see which server a deployment is pointed at,
    and not enough to connect to it.
    """

    def test_the_url_is_one_of_the_secrets_an_operator_can_set(self):
        from app.modules.settings.models import SecretKey

        assert SecretKey.STATE_DATABASE_URL.value == "state_database_url"

    def test_with_nothing_set_the_settings_say_sqlite(self, monkeypatch, tmp_path):
        from app.modules.settings.store import InMemorySettingsStore

        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("ELICTA_STATE_DIR", str(tmp_path))

        assert InMemorySettingsStore().read().storage.database.startswith("sqlite:///")

    def test_a_configured_url_is_shown_back_without_its_password(self, monkeypatch):
        from app.modules.settings.models import SecretKey
        from app.modules.settings.store import InMemorySettingsStore

        monkeypatch.delenv("DATABASE_URL", raising=False)
        store = InMemorySettingsStore()
        store.set_secret(
            SecretKey.STATE_DATABASE_URL, "postgresql://elicta:hunter2@db.internal:5432/elicta"
        )

        shown = store.read().storage.database

        assert "hunter2" not in shown
        assert "db.internal" in shown

    def test_the_raw_url_never_leaves_over_the_api(self, monkeypatch):
        from app.modules.settings.models import SecretKey
        from app.modules.settings.store import InMemorySettingsStore

        monkeypatch.delenv("DATABASE_URL", raising=False)
        store = InMemorySettingsStore()
        store.set_secret(
            SecretKey.STATE_DATABASE_URL, "postgresql://elicta:hunter2@db.internal:5432/elicta"
        )

        assert "hunter2" not in store.read().model_dump_json()

    def test_the_settings_say_a_restart_is_needed_rather_than_implying_otherwise(self):
        from app.modules.settings.models import StorageSettings

        assert StorageSettings.model_fields["applies_on_restart"].default is True


# -- consent -------------------------------------------------------------


def test_consent_defaults_to_standing_for_the_engagement() -> None:
    """The stage default, now said out loud in a place an operator can change.

    It was a constant in `composition.py` whose docstring called it "the
    fail-open one": every engagement took `ENGAGEMENT_LEVEL`, no meeting ever
    stopped to ask, and the only way to change that was to edit Python. The
    default is unchanged — what changes is that it is now administered rather
    than compiled in.
    """

    from .models import ConsentModelSetting, ServiceSettings

    assert ServiceSettings().consent.model is ConsentModelSetting.ENGAGEMENT_LEVEL


async def test_saving_the_consent_model_keeps_it() -> None:
    from .models import ConsentModelSetting, ConsentSettings, SettingsUpdateRequest
    from .service import apply_settings_update
    from .store import InMemorySettingsStore

    store = InMemorySettingsStore(read_environment=False)

    settings = await apply_settings_update(
        store,
        SettingsUpdateRequest(
            consent=ConsentSettings(model=ConsentModelSetting.PER_MEETING)
        ),
    )

    assert settings.consent.model is ConsentModelSetting.PER_MEETING
    assert store.read().consent.model is ConsentModelSetting.PER_MEETING


async def test_a_settings_save_that_omits_consent_leaves_it_alone() -> None:
    """The admin UI saves one panel at a time; an omitted section is untouched."""

    from .models import (
        ConsentModelSetting,
        ConsentSettings,
        SettingsUpdateRequest,
        VendorSettings,
    )
    from .service import apply_settings_update
    from .store import InMemorySettingsStore

    store = InMemorySettingsStore(read_environment=False)
    await apply_settings_update(
        store,
        SettingsUpdateRequest(
            consent=ConsentSettings(model=ConsentModelSetting.PER_MEETING)
        ),
    )

    await apply_settings_update(store, SettingsUpdateRequest(vendors=VendorSettings()))

    assert store.read().consent.model is ConsentModelSetting.PER_MEETING
