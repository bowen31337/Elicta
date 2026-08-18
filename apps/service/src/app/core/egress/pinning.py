"""Certificate pinning for processors whose enterprise gateway supports it
(PRD NFR-2.7).

Not every processor's gateway offers a stable, pinnable certificate, so
pinning is opt-in per processor via `ProcessorPinRegistry` rather than a
blanket requirement. A processor with no registered pin still gets ordinary
TLS chain and hostname verification from the concrete transport — it just
doesn't get the extra pinned-fingerprint check `PinningEgressTransport`
layers on top for processors that do have one.
"""

from __future__ import annotations

from dataclasses import dataclass


def _normalize(fingerprint: str) -> str:
    return fingerprint.replace(":", "").replace(" ", "").lower()


@dataclass(frozen=True)
class CertificatePin:
    """One or more acceptable SHA-256 fingerprints of a processor's leaf
    TLS certificate.

    Accepting more than one fingerprint lets a planned certificate rotation
    list both the outgoing and incoming certs until the old one expires,
    instead of forcing a flag-day cutover that breaks egress the moment the
    gateway rotates.
    """

    sha256_fingerprints: frozenset[str]

    @staticmethod
    def of(*fingerprints: str) -> CertificatePin:
        if not fingerprints:
            raise ValueError("a CertificatePin needs at least one fingerprint")
        return CertificatePin(frozenset(_normalize(fp) for fp in fingerprints))

    def matches(self, sha256_fingerprint: str) -> bool:
        return _normalize(sha256_fingerprint) in self.sha256_fingerprints


class ProcessorPinRegistry:
    """Maps ``processor_name`` to its `CertificatePin`, for the subset of
    processors whose enterprise gateway supports pinning."""

    def __init__(self, pins: dict[str, CertificatePin] | None = None) -> None:
        self._pins = dict(pins or {})

    def pin_for(self, processor_name: str) -> CertificatePin | None:
        return self._pins.get(processor_name)

    def supports_pinning(self, processor_name: str) -> bool:
        return processor_name in self._pins
