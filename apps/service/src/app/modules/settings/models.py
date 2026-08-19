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

from pydantic import BaseModel, ConfigDict, Field


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


class InferenceSettings(BaseModel):
    """Non-secret inference configuration (architecture ADR-012, §3.10)."""

    model_config = ConfigDict(extra="forbid")

    auth_mode: AuthMode = Field(
        default=AuthMode.API_KEY,
        description="Whether calls authenticate with an API key or an OAuth token.",
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


class VendorSettings(BaseModel):
    """Non-secret endpoints for the speech vendors (ADR-004, ADR-011)."""

    model_config = ConfigDict(extra="forbid")

    asr_base_url: str | None = None
    capture_base_url: str | None = None


class ServiceSettings(BaseModel):
    """Everything an operator can administer, with no secret values in it."""

    model_config = ConfigDict(extra="forbid")

    inference: InferenceSettings = Field(default_factory=InferenceSettings)
    vendors: VendorSettings = Field(default_factory=VendorSettings)
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
    secrets: list[SecretUpdate] = Field(default_factory=list)


class ConnectionCheck(BaseModel):
    """The result of testing a configured vendor credential.

    `detail` is a human-readable reason on failure. It is built from the
    vendor's error type, never from the credential.
    """

    key: SecretKey
    reachable: bool
    detail: str
