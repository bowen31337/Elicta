from app.core.egress.retention import ProcessorRetentionRegistry, RetentionParameter


def test_the_registry_returns_none_for_a_processor_with_no_registered_parameter():
    registry = ProcessorRetentionRegistry(
        {"transcription-vendor": RetentionParameter(name="mip_opt_out", zero_value=True)}
    )

    assert registry.parameter_for("other-vendor") is None
    assert registry.supports_zero_retention("transcription-vendor") is True
    assert registry.supports_zero_retention("other-vendor") is False


def test_an_empty_registry_supports_no_processors():
    registry = ProcessorRetentionRegistry()

    assert registry.parameter_for("transcription-vendor") is None
    assert registry.supports_zero_retention("transcription-vendor") is False


def test_the_registry_returns_the_registered_parameter():
    parameter = RetentionParameter(name="mip_opt_out", zero_value=True)
    registry = ProcessorRetentionRegistry({"transcription-vendor": parameter})

    assert registry.parameter_for("transcription-vendor") is parameter
