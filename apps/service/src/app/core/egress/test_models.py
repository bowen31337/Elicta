import pytest
from pydantic import ValidationError

from app.core.egress.models import ProcessorRequest


def test_an_https_destination_is_accepted():
    request = ProcessorRequest(
        processor_name="transcription-vendor",
        engagement_id="engagement-1",
        destination="https://processor.example/run",
        body_bytes=10,
    )

    assert request.destination == "https://processor.example/run"


def test_vendor_params_defaults_to_empty_and_is_independent_per_instance():
    first = ProcessorRequest(
        processor_name="transcription-vendor",
        engagement_id="engagement-1",
        destination="https://processor.example/run",
        body_bytes=10,
    )
    second = ProcessorRequest(
        processor_name="transcription-vendor",
        engagement_id="engagement-1",
        destination="https://processor.example/run",
        body_bytes=10,
    )

    assert first.vendor_params == {}
    first.vendor_params["mip_opt_out"] = True
    assert second.vendor_params == {}


@pytest.mark.parametrize(
    "destination",
    [
        "http://processor.example/run",
        "ftp://processor.example/run",
        "processor.example/run",
        "HTTP://processor.example/run",
    ],
)
def test_a_non_tls_destination_is_rejected(destination):
    with pytest.raises(ValidationError, match="TLS"):
        ProcessorRequest(
            processor_name="transcription-vendor",
            engagement_id="engagement-1",
            destination=destination,
            body_bytes=10,
        )
