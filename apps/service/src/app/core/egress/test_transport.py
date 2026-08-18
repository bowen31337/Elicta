import pytest

from app.core.egress.errors import EgressTransportError
from app.core.egress.models import ProcessorRequest, ProcessorSuccess
from app.core.egress.pinning import CertificatePin, ProcessorPinRegistry
from app.core.egress.retention import ProcessorRetentionRegistry, RetentionParameter
from app.core.egress.transport import PinningEgressTransport, RetentionEnforcingEgressTransport


class StubInnerTransport:
    def __init__(self, success: ProcessorSuccess) -> None:
        self._success = success

    def execute(self, request: ProcessorRequest) -> ProcessorSuccess:
        return self._success


def sample_request(**overrides: object) -> ProcessorRequest:
    defaults = {
        "processor_name": "transcription-vendor",
        "engagement_id": "engagement-1",
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


class SpyInnerTransport:
    def __init__(self, success: ProcessorSuccess) -> None:
        self._success = success
        self.received: ProcessorRequest | None = None

    def execute(self, request: ProcessorRequest) -> ProcessorSuccess:
        self.received = request
        return self._success


def test_a_processor_with_a_registered_retention_parameter_gets_it_forced_to_zero():
    inner = SpyInnerTransport(ProcessorSuccess(response_bytes=5))
    registry = ProcessorRetentionRegistry(
        {"transcription-vendor": RetentionParameter(name="mip_opt_out", zero_value=True)}
    )
    transport = RetentionEnforcingEgressTransport(inner, registry)

    transport.execute(sample_request())

    assert inner.received is not None
    assert inner.received.vendor_params == {"mip_opt_out": True}


def test_a_caller_supplied_value_for_the_retention_parameter_is_overwritten():
    inner = SpyInnerTransport(ProcessorSuccess(response_bytes=5))
    registry = ProcessorRetentionRegistry(
        {"transcription-vendor": RetentionParameter(name="mip_opt_out", zero_value=True)}
    )
    transport = RetentionEnforcingEgressTransport(inner, registry)

    transport.execute(sample_request(vendor_params={"mip_opt_out": False}))

    assert inner.received.vendor_params == {"mip_opt_out": True}


def test_other_vendor_params_are_preserved_alongside_the_forced_retention_parameter():
    inner = SpyInnerTransport(ProcessorSuccess(response_bytes=5))
    registry = ProcessorRetentionRegistry(
        {"transcription-vendor": RetentionParameter(name="mip_opt_out", zero_value=True)}
    )
    transport = RetentionEnforcingEgressTransport(inner, registry)

    transport.execute(sample_request(vendor_params={"multichannel": True}))

    assert inner.received.vendor_params == {"multichannel": True, "mip_opt_out": True}


def test_a_processor_with_no_registered_retention_parameter_passes_through_unchanged():
    inner = SpyInnerTransport(ProcessorSuccess(response_bytes=5))
    transport = RetentionEnforcingEgressTransport(inner, ProcessorRetentionRegistry())

    transport.execute(sample_request(vendor_params={"multichannel": True}))

    assert inner.received.vendor_params == {"multichannel": True}


def test_retention_enforcement_is_scoped_to_the_processor_name_not_applied_globally():
    inner = SpyInnerTransport(ProcessorSuccess(response_bytes=5))
    registry = ProcessorRetentionRegistry(
        {"other-vendor": RetentionParameter(name="mip_opt_out", zero_value=True)}
    )
    transport = RetentionEnforcingEgressTransport(inner, registry)

    transport.execute(sample_request(processor_name="transcription-vendor"))

    assert inner.received.vendor_params == {}
