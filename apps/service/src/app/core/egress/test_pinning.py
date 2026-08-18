import pytest

from app.core.egress.pinning import CertificatePin, ProcessorPinRegistry


def test_a_pin_matches_regardless_of_colon_separators_and_case():
    pin = CertificatePin.of("AB:CD:EF:01")

    assert pin.matches("abcdef01")
    assert pin.matches("AB:CD:EF:01")


def test_a_pin_matches_any_one_of_multiple_registered_fingerprints():
    pin = CertificatePin.of("aaaa", "bbbb")

    assert pin.matches("aaaa")
    assert pin.matches("bbbb")
    assert not pin.matches("cccc")


def test_a_pin_requires_at_least_one_fingerprint():
    with pytest.raises(ValueError):
        CertificatePin.of()


def test_the_registry_returns_none_for_a_processor_with_no_registered_pin():
    registry = ProcessorPinRegistry({"vendor-a": CertificatePin.of("aaaa")})

    assert registry.pin_for("vendor-b") is None
    assert registry.supports_pinning("vendor-a") is True
    assert registry.supports_pinning("vendor-b") is False


def test_an_empty_registry_supports_no_processors():
    registry = ProcessorPinRegistry()

    assert registry.pin_for("vendor-a") is None
    assert registry.supports_pinning("vendor-a") is False
