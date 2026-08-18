from app.core.consent.gate import CONSENT_PROMPT, evaluate_consent_gate
from app.core.consent.models import ConsentGateStatus, ConsentModel


def test_engagement_level_consent_never_prompts():
    gate = evaluate_consent_gate(ConsentModel.ENGAGEMENT_LEVEL)

    assert gate.status is ConsentGateStatus.NOT_REQUIRED
    assert gate.prompt is None
    assert gate.capture_may_begin is True


def test_engagement_level_consent_never_prompts_even_if_flagged_confirmed():
    gate = evaluate_consent_gate(
        ConsentModel.ENGAGEMENT_LEVEL, confirmed_this_meeting=True
    )

    assert gate.status is ConsentGateStatus.NOT_REQUIRED
    assert gate.capture_may_begin is True


def test_per_meeting_consent_blocks_capture_until_confirmed():
    gate = evaluate_consent_gate(ConsentModel.PER_MEETING)

    assert gate.status is ConsentGateStatus.AWAITING_CONFIRMATION
    assert gate.prompt == CONSENT_PROMPT
    assert gate.capture_may_begin is False


def test_per_meeting_consent_allows_capture_once_confirmed():
    gate = evaluate_consent_gate(ConsentModel.PER_MEETING, confirmed_this_meeting=True)

    assert gate.status is ConsentGateStatus.CONFIRMED
    assert gate.prompt is None
    assert gate.capture_may_begin is True


def test_prompt_cites_the_legal_basis():
    assert "Surveillance Devices Act" in CONSENT_PROMPT.legal_basis
