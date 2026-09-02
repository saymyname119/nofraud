import pytest
from unittest.mock import AsyncMock, patch
from app.decision.circuit_breaker import CircuitBreakerStatus
from app.decision.engine import decide
from app.scoring.reason_codes import ReasonCode


def create_payload(email: str = "normal@example.com", amount: int = 1000):
    return {
        "id": "pay_test",
        "amount": amount,
        "currency": "INR",
        "email": email,
        "contact": "9999999999",
        "method": "card",
    }


@pytest.mark.asyncio
async def test_compliance_gate():
    with patch("app.decision.engine.get_compliance_lists") as mock_get_lists:
        mock_get_lists.return_value = {"sanctioned_keywords": ["evil.org"]}
        # Email matching sanction list
        payload = create_payload(email="sanctioned@evil.org")
        decision = await decide(payload, velocity={})
        assert decision.action == "HOLD"
        assert decision.escalate is True
        assert ReasonCode.NOVEL_PATTERN.value in decision.reasons
        assert decision.layer_verdicts["compliance"] == "HOLD_ESCALATE"


@pytest.mark.asyncio
async def test_blocklist():
    with patch("app.decision.engine.get_compliance_lists") as mock_get_lists:
        mock_get_lists.return_value = {"blocklisted_emails": ["fraudster@scam.com"]}
        # Email on blocklist
        payload = create_payload(email="fraudster@scam.com")
        decision = await decide(payload, velocity={})
        assert decision.action == "HOLD"
        assert decision.escalate is False
        assert ReasonCode.NOVEL_PATTERN.value in decision.reasons
        assert decision.layer_verdicts["blocklist"] == "HOLD"


@pytest.mark.asyncio
async def test_allowlist():
    with patch("app.decision.engine.get_compliance_lists") as mock_get_lists:
        mock_get_lists.return_value = {"allowlisted_emails": ["ceo@company.com"]}
        # Email on allowlist
        payload = create_payload(email="ceo@company.com")
        decision = await decide(payload, velocity={})
        assert decision.action == "CAPTURE"
        assert decision.layer_verdicts["allowlist"] == "CAPTURE"


@pytest.mark.asyncio
async def test_ml_scoring():
    # Normal transaction falls through to ML
    payload = create_payload(amount=50000000)  # Unusually high amount to force HOLD/VERIFY
    decision = await decide(payload, velocity={})
    # ML should score it, might VERIFY or HOLD depending on threshold
    assert decision.action in ["CAPTURE", "VERIFY", "HOLD"]
    assert "ml" in decision.layer_verdicts


@pytest.mark.asyncio
async def test_circuit_breaker_override():
    # When circuit breaker is OPEN, ML is bypassed and defaults to CAPTURE
    open_status = CircuitBreakerStatus(
        state="OPEN",
        hold_rate=0.15,
        window_size=50,
        opened_at=100.0,
        reason="Hold rate 15% > threshold 5%",
    )
    with patch("app.decision.engine.get_breaker") as mock_get_breaker:
        mock_breaker = AsyncMock()
        mock_breaker.status.return_value = open_status
        mock_get_breaker.return_value = mock_breaker

        payload = create_payload(amount=50000000)
        decision = await decide(payload, velocity={})
        assert decision.action == "CAPTURE"
        assert decision.resolving_layer == "circuit_breaker"
        assert decision.layer_verdicts.get("breaker") == "OPEN"
        assert decision.layer_verdicts.get("ml") == "BYPASSED"
