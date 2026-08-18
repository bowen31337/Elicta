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
