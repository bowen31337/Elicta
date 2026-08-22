"""Operator-administered service settings — vendor credentials and endpoints.

These are the values that were environment variables: the inference
credential, the model, per-vendor base URLs. Environment variables are the
wrong home for them in a product with an operator-facing UI, because changing
one means a redeploy by somebody who is not the person who needs it changed.

The security shape is the part worth getting right, and it is enforced by the
types here rather than by discipline at each call site:

* **A secret is write-only over the API.** `SecretStatus` is what a read
  returns — whether a value is configured, and the last four characters to
  confirm *which* key is in place. The secret itself never leaves the
  service. There is deliberately no model in this module that carries a
  secret value outward.
* **Clearing is explicit.** Sending an empty string clears a secret; omitting
  the field leaves it untouched. Without that distinction, a settings form
  that round-trips a masked value would erase the real one on every save.
* **Secrets never reach a log.** `SecretValue` overrides its own repr, so a
  stray `logger.info(settings)` or a traceback frame cannot print a live
  credential.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SecretKey(str, Enum):
    """The secrets an operator can configure.

    An enum rather than free-form strings: a typo'd key name would otherwise
    silently create a second, never-read secret while the real one stayed
    unset.
    """

    ANTHROPIC_API_KEY = "anthropic_api_key"
    ANTHROPIC_OAUTH_TOKEN = "anthropic_oauth_token"
    ASR_VENDOR_API_KEY = "asr_vendor_api_key"
    CAPTURE_VENDOR_API_KEY = "capture_vendor_api_key"
    MICROSOFT_GRAPH_CLIENT_SECRET = "microsoft_graph_client_secret"
    STATE_DATABASE_URL = "state_database_url"


class SecretValue:
    """A secret held in memory, which refuses to print itself.

    Wrapping rather than passing a bare `str` is what makes redaction the
    default: every accidental path to output — repr, str, f-string, a
    traceback frame that renders locals — goes through this class.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        """The actual secret. The only way out, and named so it is greppable."""

        return self._value

    def hint(self) -> str:
        """The last four characters, for confirming which key is in place."""

        return self._value[-4:] if len(self._value) >= 4 else "****"

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "SecretValue(***redacted***)"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SecretValue) and self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)


class SecretStatus(BaseModel):
    """What a read of a secret returns: presence, not value."""

    key: SecretKey
    configured: bool
    hint: str | None = Field(
        default=None,
        description="Last four characters of the stored secret, to confirm which one is set.",
    )
    updated_at: datetime | None = None


class AuthMode(str, Enum):
    """Which credential the service authenticates Claude calls with.

    Both are "bring your own": an API key issued from the console, or an
    OAuth token from `claude setup-token` / `ant auth login`. Which one an
    operator has depends on how their organisation issues access, so this is
    an explicit choice rather than an inference from whichever field happens
    to be filled — an operator with both configured must be able to say which
    one is live.
    """

    API_KEY = "api_key"
    OAUTH_TOKEN = "oauth_token"

    @property
    def secret_key(self) -> SecretKey:
        """The secret this mode authenticates with."""

        return (
            SecretKey.ANTHROPIC_API_KEY
            if self is AuthMode.API_KEY
            else SecretKey.ANTHROPIC_OAUTH_TOKEN
        )


class LlmProvider(str, Enum):
    """Where Claude calls are routed.

    Every option here speaks the **Anthropic Messages API**, and that is a
    hard constraint rather than a current limitation. The service depends on
    surface that only exists there: schema-enforced structured outputs
    (§14.4), explicit cache-boundary control on a hand-partitioned prefix
    (§14.3), and the request shape `core/crates/slow-lane` builds. An
    OpenAI-shaped endpoint would not fail at configuration time — it would
    fail per stage, at the point where a debrief was expected — so the
    provider list is closed to Messages-API surfaces on purpose.

    Within that, the choice is wide open: Anthropic direct, the three cloud
    resellers, or any self-hosted or third-party gateway that presents a
    compatible endpoint.
    """

    ANTHROPIC = "anthropic"
    BEDROCK = "bedrock"
    VERTEX = "vertex"
    FOUNDRY = "foundry"
    COMPATIBLE = "anthropic_compatible"

    @property
    def uses_stored_credential(self) -> bool:
        """Whether the credential comes from settings or the cloud environment.

        Bedrock and Vertex authenticate with the host's own credential chain —
        an IAM role, or GCP application-default credentials. Asking an
        operator to paste a key for those would invite them to create a
        long-lived static credential where their cloud already has a better
        mechanism.
        """

        return self in (
            LlmProvider.ANTHROPIC,
            LlmProvider.FOUNDRY,
            LlmProvider.COMPATIBLE,
        )


class InferenceSettings(BaseModel):
    """Non-secret inference configuration (architecture ADR-012, §3.10)."""

    model_config = ConfigDict(extra="forbid")

    provider: LlmProvider = Field(
        default=LlmProvider.ANTHROPIC,
        description="Which Anthropic Messages API surface to route calls through.",
    )
    auth_mode: AuthMode = Field(
        default=AuthMode.API_KEY,
        description=(
            "Whether calls authenticate with an API key or an OAuth token. "
            "Ignored for providers that use the host's own credential chain."
        ),
    )
    region: str | None = Field(
        default=None,
        description="Cloud region. Required for Bedrock and Vertex.",
    )
    project_id: str | None = Field(
        default=None, description="GCP project. Required for Vertex."
    )
    resource: str | None = Field(
        default=None, description="Foundry resource name. Required for Foundry."
    )

    model: str = Field(
        default="claude-opus-5",
        min_length=1,
        description="Model used for the context compiler and debrief pipeline.",
    )
    base_url: str | None = Field(
        default=None,
        description="Override the Anthropic API endpoint. Leave unset for the default.",
    )



    @model_validator(mode="after")
    def _require_what_the_provider_needs(self) -> InferenceSettings:
        """Reject a provider that cannot possibly connect.

        Catching this at save time turns a misconfiguration into a form error
        the operator can act on, instead of a stage failure that surfaces
        hours later in a debrief record.
        """

        missing: list[str] = []
        if self.provider is LlmProvider.COMPATIBLE and not self.base_url:
            missing.append("base_url (the compatible endpoint to call)")
        if self.provider is LlmProvider.BEDROCK and not self.region:
            missing.append("region (the AWS region)")
        if self.provider is LlmProvider.VERTEX:
            if not self.region:
                missing.append("region (the Vertex region, or 'global')")
            if not self.project_id:
                missing.append("project_id (the GCP project)")
        if self.provider is LlmProvider.FOUNDRY and not self.resource:
            missing.append("resource (the Foundry resource name)")

        if missing:
            raise ValueError(
                f"{self.provider.value} needs: " + ", ".join(missing)
            )
        return self


class VendorSettings(BaseModel):
    """Non-secret endpoints for the speech vendors (ADR-004, ADR-011)."""

    model_config = ConfigDict(extra="forbid")

    asr_base_url: str | None = None
    capture_base_url: str | None = None


class SpeechVendor(str, Enum):
    """Speech vendors the service can connect to.

    Both are the engines architecture §14.1-14.2 analyses in detail, and they
    are chosen together rather than interchangeably: FR-2.6 runs two batch
    engines over the record path, and T3 warns that the pair is only worth
    running if the engines fail *differently* — two models sharing a training
    lineage agree on the same mistakes and the reconciliation signal is
    worthless. Deepgram and AssemblyAI have independent lineages, which is
    what makes them a usable pair.
    """

    DEEPGRAM = "deepgram"
    ASSEMBLYAI = "assemblyai"
    CUSTOM = "custom"


class ConnectorSettings(BaseModel):
    """Which speech vendors serve each path (ADR-004's dual-path split).

    The live and record paths are configured separately on purpose: they have
    different consumers. The live path is bought on turn-detection latency
    (§14.2), the record path on independent divergence between two engines
    (FR-2.6, T3). Forcing one vendor to serve both would optimise neither.
    """

    model_config = ConfigDict(extra="forbid")

    live_vendor: SpeechVendor = Field(
        default=SpeechVendor.ASSEMBLYAI,
        description=(
            "Streaming engine for the live trigger path. AssemblyAI's "
            "confidence-based turn model reaches a lower latency floor than a "
            "silence timer (§14.2) and is the cheaper of the two per hour."
        ),
    )
    record_vendors: list[SpeechVendor] = Field(
        default_factory=lambda: [SpeechVendor.DEEPGRAM, SpeechVendor.ASSEMBLYAI],
        description=(
            "Batch engines for the record path. FR-2.6 requires two, and T3 "
            "requires that they diverge independently."
        ),
    )
    keyterm_prompting: bool = Field(
        default=True,
        description=(
            "Send the engagement vocabulary as keyterms (FR-2.9). §14.1 ranks "
            "this the highest-leverage engine-side accuracy control."
        ),
    )
    disable_vendor_retention: bool = Field(
        default=True,
        description=(
            "Set the vendor's opt-out parameter on every request (NFR-2.3). "
            "§14.1: a DPA that says retention is off and a request that does "
            "not say so is a gap that surfaces in an audit."
        ),
    )
    region: str | None = Field(
        default=None,
        description=(
            "Vendor region. Pinned once for residency (NFR-2.2) and for "
            "round-trip latency (§14.2) — the same knob serves both."
        ),
    )
    custom_vendor_name: str | None = Field(
        default=None,
        description="Display name for a custom speech service, shown in logs and the UI.",
    )
    custom_base_url: str | None = Field(
        default=None,
        description="Endpoint for a custom speech service. Required when one is selected.",
    )

    @model_validator(mode="after")
    def _a_custom_vendor_needs_an_endpoint(self) -> ConnectorSettings:
        """A custom vendor with nowhere to call is a silent dead end.

        Rejecting it at save time keeps the failure in the form, where the
        operator can fix it, rather than in a meeting.
        """

        selected = [self.live_vendor, *self.record_vendors]
        if SpeechVendor.CUSTOM in selected and not self.custom_base_url:
            raise ValueError(
                "a custom speech service needs custom_base_url — the endpoint to call"
            )
        return self

    @field_validator("record_vendors")
    @classmethod
    def _require_two_independent_engines(
        cls, value: list[SpeechVendor]
    ) -> list[SpeechVendor]:
        """FR-2.6 needs two engines, and T3 needs them to be different ones.

        Configuring the same engine twice would produce two transcripts that
        agree by construction — reconciliation would report perfect agreement
        and flag nothing, which is worse than a single engine because it
        manufactures false assurance.
        """

        if len(value) != 2:
            raise ValueError(
                "the record path runs exactly two batch engines (PRD FR-2.6)"
            )
        if value[0] == value[1]:
            raise ValueError(
                "the two record-path engines must be different vendors: engines "
                "sharing a lineage agree on the same errors, so reconciliation "
                "manufactures false assurance (architecture T3)"
            )
        return value


class DocumentSourceSettings(BaseModel):
    """Where a linked reference document is read from (FR-3.2).

    An Entra ID app registration with application permissions, rather than a
    pasted access token: a token expires within the hour, and a connector that
    stops working over lunch is one nobody trusts. The secret half lives in the
    secret store under `microsoft_graph_client_secret`; these two are
    identifiers, not credentials, and are shown back to the operator so they
    can confirm which tenant is wired up.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str | None = Field(
        default=None,
        description=(
            "Entra ID directory (tenant) id the documents live in. Unset means "
            "the connector is off and a linked document contributes nothing."
        ),
    )
    client_id: str | None = Field(
        default=None,
        description=(
            "Application (client) id of the registration Elicta reads as. It "
            "needs Files.Read.All, and Sites.Read.All for team sites."
        ),
    )


class StorageSettings(BaseModel):
    """Where an engagement's memory is kept (PRD G4).

    SQLite by default, because the desktop product ships to people with no
    database server and should not need one. A deployment that wants PostgreSQL
    opts in by saving a URL, which is a secret — it carries a password — so what
    is shown back has the password removed and everything identifying the server
    left in.
    """

    model_config = ConfigDict(extra="forbid")

    database: str = Field(
        default="",
        description=(
            "The database this deployment reads and writes, with any password "
            "removed. Read-only: set it by saving the `state_database_url` "
            "secret."
        ),
    )
    applies_on_restart: bool = Field(
        default=True,
        description=(
            "Whether a change here takes effect only after a restart. It does: "
            "the collections are opened once at startup and bound into the "
            "backend, so a save that claimed to move a live deployment would "
            "be describing something that did not happen."
        ),
    )


class ServiceSettings(BaseModel):
    """Everything an operator can administer, with no secret values in it."""

    model_config = ConfigDict(extra="forbid")

    inference: InferenceSettings = Field(default_factory=InferenceSettings)
    vendors: VendorSettings = Field(default_factory=VendorSettings)
    connectors: ConnectorSettings = Field(default_factory=ConnectorSettings)
    documents: DocumentSourceSettings = Field(default_factory=DocumentSourceSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    secrets: list[SecretStatus] = Field(default_factory=list)
    durable: bool = Field(
        default=False,
        description=(
            "Whether these settings survive a service restart. Surfaced so the "
            "admin screen can say so plainly, rather than letting an operator "
            "discover it after a restart."
        ),
    )
    updated_at: datetime | None = None


class SecretUpdate(BaseModel):
    """One secret being set or cleared.

    An empty `value` clears the secret. That is the only way to remove one,
    and it is deliberately distinct from omitting the entry entirely, which
    leaves the stored secret alone.
    """

    model_config = ConfigDict(extra="forbid")

    key: SecretKey
    value: str = Field(description="The secret, or an empty string to clear it.")


class SettingsUpdateRequest(BaseModel):
    """A settings save from the admin UI.

    Every field is optional so the UI can save one section without having to
    resend the others — and, more importantly, so it never has to resend a
    secret it does not have.
    """

    model_config = ConfigDict(extra="forbid")

    inference: InferenceSettings | None = None
    vendors: VendorSettings | None = None
    connectors: ConnectorSettings | None = None
    documents: DocumentSourceSettings | None = None
    secrets: list[SecretUpdate] = Field(default_factory=list)


class ConnectionCheck(BaseModel):
    """The result of testing a configured vendor credential.

    `detail` is a human-readable reason on failure. It is built from the
    vendor's error type, never from the credential.
    """

    key: SecretKey
    reachable: bool
    detail: str
