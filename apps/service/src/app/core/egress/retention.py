"""Vendor-side retention-to-zero enforcement for processors that expose it
as a request parameter (PRD NFR-2.3).

Architecture §14.1 point 8: "Vendor retention is a request parameter, not
only a contract clause" — Deepgram's ``mip_opt_out=true`` opts a request out
of vendor-side data usage. A DPA that says retention is off and a request
that doesn't say so is a gap that surfaces in an audit, so this is enforced
per request rather than left to the contract alone. Not every processor
exposes such a parameter, so — mirroring `ProcessorPinRegistry` — this is
opt-in per processor via `ProcessorRetentionRegistry` rather than a blanket
requirement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RetentionParameter:
    """The request parameter a processor exposes to opt a call out of
    vendor-side data retention entirely.

    ``name`` is the parameter key the vendor's API expects (e.g. Deepgram's
    ``mip_opt_out``). ``zero_value`` is the value that means "retain
    nothing" for that vendor — vendors don't agree on the shape of this
    (a boolean flag, a ``0``, a sentinel string), so it's carried per
    processor rather than assumed to always be ``True``.
    """

    name: str
    zero_value: Any


class ProcessorRetentionRegistry:
    """Maps ``processor_name`` to the `RetentionParameter` it exposes, for
    the subset of processors whose API surfaces vendor-side retention as a
    request parameter (PRD NFR-2.3).

    A processor with no registered entry has no such parameter to send —
    its retention is governed only by the negotiated DPA (PRD NFR-2.1), not
    enforced per request, since there is nothing on the wire to set.
    """

    def __init__(self, parameters: dict[str, RetentionParameter] | None = None) -> None:
        self._parameters = dict(parameters or {})

    def parameter_for(self, processor_name: str) -> RetentionParameter | None:
        return self._parameters.get(processor_name)

    def supports_zero_retention(self, processor_name: str) -> bool:
        return processor_name in self._parameters
