"""
tests/test_shadow_mode.py

Tests for shadow mode (spec §11 invariant #9 / CLAUDE.md §Shadow Mode).

When shadow_mode = True:
  - decision.shadow_mode must be True
  - decision.effective_action must be "PASS (shadow)" for non-CAPTURE actions
  - decision.action (the ML directive) is still recorded honestly
  - CAPTURE decisions are NOT suppressed (only adverse actions are shadowed)
"""
import pytest
from unittest.mock import patch, AsyncMock
from app.decision.engine import decide
from app.scoring.model import ScoringResult
from app.scoring.reason_codes import ReasonCode


def tx_payload(email="normal@example.com", amount=10000):
    return {
        "id": "pay_shadow",
        "amount": amount,
        "currency": "INR",
        "email": email,
        "contact": "9999999999",
        "method": "card",
    }


def make_scoring_result(p: float) -> ScoringResult:
    return ScoringResult(
        p=p,
        reasons=[ReasonCode.AMOUNT_ANOMALY],
        feature_vector_hash="sha256:abc",
        model_version="test-v1",
        raw_xgb_score=p,
        raw_iso_score=0.0,
        shap_values={"amount": 0.9},
    )


# ── Shadow mode suppresses HOLD ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shadow_mode_suppresses_hold():
    """
    With shadow_mode=True and ML producing HOLD,
    effective_action must be "PASS (shadow)" — not HOLD.
    """
    with patch("app.decision.engine.get_compliance_lists", return_value={}):
        with patch("app.decision.engine.is_shadow_mode", return_value=True):
            with patch("app.decision.engine.score_payment",
                       new=AsyncMock(return_value=make_scoring_result(p=0.99))):
                with patch("app.decision.engine.select_action",
                           return_value=("HOLD", {"p_fraud": 0.99})):
                    decision = await decide(tx_payload(), velocity={})

    assert decision.shadow_mode is True
    assert decision.action == "HOLD"                    # recorded directive
    assert decision.effective_action == "PASS (shadow)"  # suppressed


@pytest.mark.asyncio
async def test_shadow_mode_suppresses_verify():
    """
    With shadow_mode=True and ML producing VERIFY,
    effective_action must be "PASS (shadow)".
    """
    with patch("app.decision.engine.get_compliance_lists", return_value={}):
        with patch("app.decision.engine.is_shadow_mode", return_value=True):
            with patch("app.decision.engine.score_payment",
                       new=AsyncMock(return_value=make_scoring_result(p=0.25))):
                with patch("app.decision.engine.select_action",
                           return_value=("VERIFY", {"p_fraud": 0.25})):
                    decision = await decide(tx_payload(), velocity={})

    assert decision.shadow_mode is True
    assert decision.action == "VERIFY"
    assert decision.effective_action == "PASS (shadow)"


@pytest.mark.asyncio
async def test_shadow_mode_does_not_suppress_capture():
    """
    CAPTURE is never adverse — shadow mode must not alter it.
    effective_action must equal "CAPTURE" even in shadow mode.
    """
    with patch("app.decision.engine.get_compliance_lists", return_value={}):
        with patch("app.decision.engine.is_shadow_mode", return_value=True):
            with patch("app.decision.engine.score_payment",
                       new=AsyncMock(return_value=make_scoring_result(p=0.01))):
                with patch("app.decision.engine.select_action",
                           return_value=("CAPTURE", {"p_fraud": 0.01})):
                    decision = await decide(tx_payload(), velocity={})

    assert decision.shadow_mode is True
    assert decision.action == "CAPTURE"
    assert decision.effective_action == "CAPTURE"  # NOT suppressed


# ── Non-shadow mode is unaffected ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_normal_mode_hold_not_suppressed():
    """With shadow_mode=False, effective_action must equal action (HOLD)."""
    with patch("app.decision.engine.get_compliance_lists", return_value={}):
        with patch("app.decision.engine.is_shadow_mode", return_value=False):
            with patch("app.decision.engine.score_payment",
                       new=AsyncMock(return_value=make_scoring_result(p=0.99))):
                with patch("app.decision.engine.select_action",
                           return_value=("HOLD", {"p_fraud": 0.99})):
                    decision = await decide(tx_payload(), velocity={})

    assert decision.shadow_mode is False
    assert decision.action == "HOLD"
    assert decision.effective_action == "HOLD"  # passes through unchanged


# ── Shadow mode still records the ML score ───────────────────────────────────


@pytest.mark.asyncio
async def test_shadow_mode_records_p_fraud():
    """
    Even in shadow mode the true ML p_fraud must be recorded on the decision
    so the audit log reflects the model's actual assessment.
    """
    with patch("app.decision.engine.get_compliance_lists", return_value={}):
        with patch("app.decision.engine.is_shadow_mode", return_value=True):
            with patch("app.decision.engine.score_payment",
                       new=AsyncMock(return_value=make_scoring_result(p=0.87))):
                with patch("app.decision.engine.select_action",
                           return_value=("HOLD", {"p_fraud": 0.87})):
                    decision = await decide(tx_payload(), velocity={})

    assert decision.p_fraud == pytest.approx(0.87)
