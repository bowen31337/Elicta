"""A pool of speech credentials, and which one serves a call.

The settings screen had a single speech field bound to `asr_vendor_api_key` —
a key read by the probe dispatch and by nothing that transcribes. Two keys
typed into it overwrote each other while the two the service actually reads
stayed empty, with no field to set them, under a warning naming a remedy the
screen could not offer.

Two fixed fields would have fixed that and nothing else. The cases that need
more than one key per vendor are ordinary: a key per client so spend is
attributable, replacing a key without downtime by adding the new one and
draining the old, and holding a spare against one being revoked mid-meeting.

**What this is not for.** Rotating keys does not raise a quota. Deepgram and
AssemblyAI meter per project rather than per key, so keys from one account
share one limit and rotation buys nothing against a 429 — and rotating across
separate accounts to multiply throughput is the case that runs into vendor
terms. Rotation here is failover and attribution, and saying so is cheaper
than somebody discovering it during a meeting.

**Vendor before policy.** Every lookup is per vendor, because a Deepgram key
cannot serve an AssemblyAI call: it authenticates as a *bad* credential rather
than a wrong one, which sends an operator to re-enter a key that was correct.
"""

from __future__ import annotations

import re
from enum import Enum
from itertools import count

from pydantic import BaseModel, Field, PrivateAttr

from .models import SpeechVendor

#: What an id may contain where it becomes a storage address. The secrets
#: table is keyed by plain string, so an unconstrained id is one write away
#: from naming `anthropic_api_key`.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: The prefix every speech credential's secret is stored under, so they are
#: distinguishable from the fixed `SecretKey` names sharing the table.
SECRET_PREFIX = "asr."


class SelectionPolicy(str, Enum):
    """How the pool chooses between the credentials a vendor has.

    Two, deliberately. A third — weighted, or health-ranked — is a guess about
    a deployment nobody is running yet, and each additional policy is another
    branch that has to be right when a meeting is in progress.
    """

    #: One serves; the rest are spares an operator can switch to.
    SINGLE = "single"
    #: Round-robin over the enabled ones, per vendor.
    ROTATE = "rotate"


class SpeechCredential(BaseModel):
    """One key an operator has, and what it is for.

    The value is not here. It lives in the secrets table under
    `secret_key_for(id)`, write-only like every other secret: a read reports
    that it is configured and its last four characters, never the key.
    """

    id: str = Field(description="Stable address for this credential's secret.")
    vendor: SpeechVendor
    label: str = Field(
        default="",
        description=(
            "What the operator calls it — 'Deepgram, Northwind account'. The "
            "point of a pool is telling them apart, and a four-character hint "
            "cannot do that."
        ),
    )
    enabled: bool = Field(
        default=True,
        description=(
            "Whether it is in service. Disabling rather than deleting is how "
            "a key is taken out without losing it: deleting means re-entering "
            "the secret to resume, which nobody will do mid-meeting."
        ),
    )


class SpeechCredentialPool(BaseModel):
    """Every speech credential, and the rule for choosing between them."""

    credentials: tuple[SpeechCredential, ...] = ()
    policy: SelectionPolicy = SelectionPolicy.SINGLE
    active_id: str | None = Field(
        default=None,
        description="Under `single`, the one that serves. Ignored under `rotate`.",
    )

    #: One cursor per vendor, in memory. A shared cursor would let a busy
    #: vendor advance a quiet one's position — a deployment transcribing live
    #: on one and reconciling on another would rotate the second by however
    #: many live windows happened to pass, making its rotation depend on
    #: somebody talking. Not persisted: starting at the first key after a
    #: restart is harmless, and persisting would mean a settings write per
    #: transcription.
    _cursors: dict[SpeechVendor, count[int]] = PrivateAttr(default_factory=dict)
    #: Cursors for cross-provider selection, keyed by the set asked for.
    _domain_cursors: dict[frozenset, count[int]] = PrivateAttr(default_factory=dict)

    def enabled_for(self, vendor: SpeechVendor) -> tuple[SpeechCredential, ...]:
        return tuple(c for c in self.credentials if c.vendor is vendor and c.enabled)

    def has_any_for(self, vendors: set[SpeechVendor] | frozenset[SpeechVendor]) -> bool:
        """Whether the pool holds an enabled credential for any of `vendors`.

        The caller needs this to tell an empty pool from one holding only
        credentials this service cannot drive: "no key" and "a key this
        service cannot use" send an operator to two different places, and one
        of them is a key they already set.
        """

        return any(c.vendor in vendors and c.enabled for c in self.credentials)

    def next_among(
        self, vendors: set[SpeechVendor] | frozenset[SpeechVendor]
    ) -> SpeechCredential | None:
        """The credential that should serve the next call, from any of `vendors`.

        The ASR service takes one credential at a time and the credential
        carries its vendor, so choosing it is choosing the provider. `vendors`
        is what the caller can actually drive — a pool may hold a key for a
        provider that has no client yet, and selecting it would turn a
        configuration problem into a failure mid-meeting.
        """

        available = tuple(
            c for c in self.credentials if c.vendor in vendors and c.enabled
        )
        if not available:
            return None

        if self.policy is SelectionPolicy.SINGLE:
            if self.active_id is not None:
                for candidate in available:
                    if candidate.id == self.active_id:
                        return candidate
            return available[0]

        # Its own cursor, keyed by the selection domain: a caller asking for a
        # narrower set is a different rotation from one asking for a wider
        # one, and sharing a cursor would let each disturb the other's order.
        key = frozenset(vendors)
        cursor = self._domain_cursors.setdefault(key, count())
        return available[next(cursor) % len(available)]

    def next_for(self, vendor: SpeechVendor) -> SpeechCredential | None:
        """The credential that should serve the next call to `vendor`."""

        available = self.enabled_for(vendor)
        if not available:
            return None

        if self.policy is SelectionPolicy.SINGLE:
            if self.active_id is not None:
                for candidate in available:
                    if candidate.id == self.active_id:
                        return candidate
                # Named but disabled or deleted. Falling through to the first
                # enabled one rather than failing: an operator who disabled the
                # active key meant to stop using it, not to stop transcribing.
            return available[0]

        cursor = self._cursors.setdefault(vendor, count())
        return available[next(cursor) % len(available)]


def secret_key_for(credential_id: str) -> str:
    """Where this credential's secret is stored.

    Validated here rather than at the edge because this is the function that
    turns an id into an address, and an address is the thing an unconstrained
    id could aim somewhere else.
    """

    if not _ID_RE.match(credential_id):
        raise ValueError(
            f"a speech credential id must be 1-64 characters of letters, digits, "
            f"'-' or '_': {credential_id!r}"
        )
    return f"{SECRET_PREFIX}{credential_id}"
