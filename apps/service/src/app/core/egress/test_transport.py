import pytest

from app.core.egress.errors import EgressTransportError
from app.core.egress.models import ProcessorRequest, ProcessorSuccess
from app.core.egress.pinning import CertificatePin, ProcessorPinRegistry
from app.core.egress.transport import PinningEgressTransport


class StubInnerTransport:
    def __init__(self, success: ProcessorSuccess) -> None:
        self._success = success

    def execute(self, request: ProcessorRequest) -> ProcessorSuccess:
        return self._success


def sample_request(**overrides: object) -> ProcessorRequest:
    defaults = {
        "processor_name": "transcription-vendor",
        "destination": "https://processor.example/run",
        "body_bytes": 10,
    }
    defaults.update(overrides)
    return ProcessorRequest(**defaults)


def test_a_processor_with_no_registered_pin_passes_through_unchanged():
    inner = StubInnerTransport(ProcessorSuccess(response_bytes=5))
    transport = PinningEgressTransport(inner, ProcessorPinRegistry())

    result = transport.execute(sample_request())

    assert result.response_bytes == 5


def test_a_matching_pin_is_accepted():
    inner = StubInnerTransport(
        ProcessorSuccess(response_bytes=5, peer_certificate_sha256="aaaa")
    )
    registry = ProcessorPinRegistry({"transcription-vendor": CertificatePin.of("aaaa")})
    transport = PinningEgressTransport(inner, registry)

    result = transport.execute(sample_request())

    assert result.response_bytes == 5


def test_a_mismatched_pin_is_rejected_even_though_the_inner_transport_succeeded():
    inner = StubInnerTransport(
        ProcessorSuccess(response_bytes=5, peer_certificate_sha256="bbbb")
    )
    registry = ProcessorPinRegistry({"transcription-vendor": CertificatePin.of("aaaa")})
    transport = PinningEgressTransport(inner, registry)

    with pytest.raises(EgressTransportError, match="pin mismatch"):
        transport.execute(sample_request())


def test_a_pinned_processor_with_no_reported_certificate_is_rejected():
    inner = StubInnerTransport(ProcessorSuccess(response_bytes=5))
    registry = ProcessorPinRegistry({"transcription-vendor": CertificatePin.of("aaaa")})
    transport = PinningEgressTransport(inner, registry)

    with pytest.raises(EgressTransportError, match="pin mismatch"):
        transport.execute(sample_request())


def test_pinning_is_scoped_to_the_processor_name_not_applied_globally():
    inner = StubInnerTransport(ProcessorSuccess(response_bytes=5))
    registry = ProcessorPinRegistry({"other-vendor": CertificatePin.of("aaaa")})
    transport = PinningEgressTransport(inner, registry)

    result = transport.execute(sample_request(processor_name="transcription-vendor"))

    assert result.response_bytes == 5
