"""
tests/test_circuit_breaker.py

Tests for the rolling-window circuit breaker (spec §9.4 / CLAUDE.md invariant #5).

Covers:
  - Breaker trips when hold_rate > threshold and minimum_sample is satisfied
  - Hysteresis: breaker stays OPEN until hysteresis_seconds pass AND rate drops
  - Decision engine bypasses ML and defaults to CAPTURE when breaker is OPEN
  - Compliance + blocklist layers still apply when breaker is OPEN
"""
import pytest
import time
from unittest.mock import patch, AsyncMock
from app.decision.circuit_breaker import CircuitBreaker, CircuitBreakerStatus
from app.decision.engine import decide


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_cfg(threshold=0.05, window=300, min_sample=10, hysteresis=60):
    return {
        "hold_rate_threshold": threshold,
        "hold_rate_window_seconds": window,
        "minimum_sample": min_sample,
        "hysteresis_seconds": hysteresis,
    }


def tx_payload(email="normal@example.com", amount=1000):
    return {"id": "pay_brk", "amount": amount, "currency": "INR",
            "email": email, "contact": "9999999999", "method": "card"}


# ── CircuitBreaker unit tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_breaker_starts_closed():
    """Fresh breaker must be CLOSED with zero hold rate."""
    breaker = CircuitBreaker()
    with patch("app.decision.circuit_breaker.get_circuit_breaker_cfg", return_value=make_cfg()):
        status = await breaker.status()
    assert status.state == "CLOSED"
    assert status.hold_rate == 0.0
    assert status.window_size == 0


@pytest.mark.asyncio
async def test_breaker_does_not_trip_below_min_sample():
    """Breaker must NOT trip when event count < minimum_sample even at 100% hold."""
    breaker = CircuitBreaker()
    with patch("app.decision.circuit_breaker.get_circuit_breaker_cfg", return_value=make_cfg(min_sample=10)):
        for _ in range(5):
            await breaker.record(is_hold=True)
        status = await breaker.status()
    assert status.state == "CLOSED", "Should stay CLOSED below minimum_sample"


@pytest.mark.asyncio
async def test_breaker_trips_at_threshold():
    """Breaker must OPEN when hold_rate > threshold and min_sample is satisfied."""
    breaker = CircuitBreaker()
    with patch("app.decision.circuit_breaker.get_circuit_breaker_cfg", return_value=make_cfg(threshold=0.05, min_sample=10)):
        for _ in range(8):
            await breaker.record(is_hold=False)
        for _ in range(2):
            await breaker.record(is_hold=True)
        status = await breaker.status()
    assert status.state == "OPEN"
    assert status.hold_rate > 0.05


@pytest.mark.asyncio
async def test_breaker_stays_open_during_hysteresis():
    """Breaker must stay OPEN for the full hysteresis period even if rate drops."""
    breaker = CircuitBreaker()
    t0 = 1000.0  # use a fixed base to avoid monotonic drift in CI
    cfg = make_cfg(threshold=0.05, min_sample=4, hysteresis=60)

    with patch("app.decision.circuit_breaker.get_circuit_breaker_cfg", return_value=cfg):
        # Inject monotonic values: 4 records, then a status check 5 s later
        side = [t0] * 4 + [t0] * 4 + [t0 + 5, t0 + 5]
        with patch("time.monotonic", side_effect=side):
            # 2 passes + 2 holds → rate=0.5 > 0.05, sample=4 >= 4
            await breaker.record(is_hold=False)
            await breaker.record(is_hold=False)
            await breaker.record(is_hold=True)
            await breaker.record(is_hold=True)
            status = await breaker.status()

    assert status.state == "OPEN", "Must remain OPEN inside hysteresis window"


@pytest.mark.asyncio
async def test_breaker_auto_closes_after_hysteresis():
    """
    Breaker must close after hysteresis_seconds pass and the hold rate is back below threshold.
    We directly set _opened_at to simulate a previously-tripped breaker and mock time
    to be well past the hysteresis window, with an empty event window so rate=0.
    """
    breaker = CircuitBreaker()
    t0 = 1000.0
    cfg = make_cfg(threshold=0.05, min_sample=4, window=300, hysteresis=60)

    # Simulate a previously-tripped breaker that opened at t0
    breaker._opened_at = t0

    # status() is called at t0 + 400: past hysteresis (60s) AND past window (300s),
    # so all events are pruned → rate = 0 < 0.05 → breaker closes
    with patch("app.decision.circuit_breaker.get_circuit_breaker_cfg", return_value=cfg):
        with patch("time.monotonic", return_value=t0 + 400):
            status = await breaker.status()

    assert status.state == "CLOSED", "Must auto-close after hysteresis + rate recovery"


# ── Engine integration tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_captures_when_breaker_open():
    """
    With breaker OPEN the engine must:
    - skip ML (layer_verdicts["ml"] == "BYPASSED")
    - default to CAPTURE (fail-open invariant)
    - record breaker state in layer_verdicts
    """
    open_status = CircuitBreakerStatus(
        state="OPEN", hold_rate=0.25, window_size=100,
        opened_at=time.monotonic(), reason="test",
    )
    with patch("app.decision.engine.get_compliance_lists", return_value={}):
        with patch("app.decision.engine.get_breaker") as mock_get_breaker:
            mock_breaker = AsyncMock()
            mock_breaker.status = AsyncMock(return_value=open_status)
            mock_get_breaker.return_value = mock_breaker
            decision = await decide(tx_payload(), velocity={})

    assert decision.action == "CAPTURE"
    assert decision.layer_verdicts["breaker"] == "OPEN"
    assert decision.layer_verdicts["ml"] == "BYPASSED"
    assert decision.resolving_layer == "circuit_breaker"


@pytest.mark.asyncio
async def test_compliance_still_fires_before_breaker():
    """
    Compliance (layer 1) runs BEFORE the circuit breaker.
    A sanctioned email must be HOLDed even when the breaker is OPEN.
    """
    open_status = CircuitBreakerStatus(
        state="OPEN", hold_rate=0.25, window_size=100,
        opened_at=time.monotonic(), reason="test",
    )
    with patch("app.decision.engine.get_compliance_lists",
               return_value={"sanctioned_keywords": ["evil.org"]}):
        with patch("app.decision.engine.get_breaker") as mock_get_breaker:
            mock_breaker = AsyncMock()
            mock_breaker.status = AsyncMock(return_value=open_status)
            mock_get_breaker.return_value = mock_breaker
            decision = await decide(tx_payload(email="bad@evil.org"), velocity={})

    assert decision.action == "HOLD"
    assert decision.escalate is True
    assert decision.layer_verdicts["compliance"] == "HOLD_ESCALATE"
