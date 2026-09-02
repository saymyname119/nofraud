"""
tests/test_cost.py

Tests for the expected-cost action selector (spec §5 + §A.7).

Covers:
  - select_action returns CAPTURE / VERIFY / HOLD at the right p thresholds
  - break_even_probability formula is correct
  - cost_breakdown dict contains all expected keys
  - threshold_for_amount picks the right bucket
"""
import pytest
from unittest.mock import patch
from app.decision.cost import select_action, break_even_probability, threshold_for_amount


MOCK_COST_PARAMS = {
    "friction_cost": 50.0,    # INR: cost of a false positive (LTV/churn)
    "review_cost": 20.0,      # INR: cost of a human review
    "hold_efficacy": 0.85,    # fraction of frauds caught by a hold
    "recovery_rate": 0.10,    # fraction of fraud amount recovered
}

MOCK_THRESHOLDS = [
    {"max_amount": 1000.0,   "min_fraud_prob": 0.30},
    {"max_amount": 10000.0,  "min_fraud_prob": 0.20},
    {"max_amount": 999999.0, "min_fraud_prob": 0.10},
]


@pytest.fixture(autouse=True)
def mock_config():
    with patch("app.decision.cost.get_cost_params", return_value=MOCK_COST_PARAMS):
        with patch("app.decision.cost.get_amount_thresholds", return_value=MOCK_THRESHOLDS):
            yield


# ── threshold_for_amount ──────────────────────────────────────────────────────


def test_threshold_low_amount():
    """Amount in lowest bucket should use its threshold."""
    assert threshold_for_amount(500.0) == pytest.approx(0.30)


def test_threshold_mid_amount():
    assert threshold_for_amount(5000.0) == pytest.approx(0.20)


def test_threshold_high_amount():
    assert threshold_for_amount(50000.0) == pytest.approx(0.10)


def test_threshold_above_all_buckets():
    """Amount exceeding all buckets should fall back to last bucket's threshold."""
    assert threshold_for_amount(10_000_000.0) == pytest.approx(0.10)


# ── select_action ─────────────────────────────────────────────────────────────


def test_select_action_capture():
    """Very low p_fraud → CAPTURE (no reason to hold)."""
    action, breakdown = select_action(p=0.01, amount=1000.0)
    assert action == "CAPTURE"
    assert breakdown["p_fraud"] == pytest.approx(0.01, abs=1e-4)


def test_select_action_hold():
    """p at or above hold threshold → HOLD."""
    action, _ = select_action(p=0.95, amount=1000.0)
    assert action == "HOLD"


def test_select_action_verify_band():
    """p in the VERIFY band (between 60% and 100% of hold threshold) → VERIFY."""
    # hold_threshold for 1000 INR = 0.30; verify_threshold = 0.30 * 0.60 = 0.18
    action, _ = select_action(p=0.22, amount=1000.0)
    assert action == "VERIFY"


def test_select_action_boundary_at_hold_threshold():
    """Exactly at hold threshold → HOLD (>= comparison)."""
    action, _ = select_action(p=0.30, amount=1000.0)
    assert action == "HOLD"


def test_select_action_boundary_just_below_verify():
    """Just below verify_threshold → CAPTURE."""
    # verify_threshold = 0.30 * 0.60 = 0.18; just below = 0.17
    action, _ = select_action(p=0.17, amount=1000.0)
    assert action == "CAPTURE"


def test_cost_breakdown_keys():
    """cost_breakdown must always contain the required audit keys."""
    _, breakdown = select_action(p=0.15, amount=5000.0)
    required_keys = {
        "p_fraud", "amount", "hold_threshold", "verify_threshold",
        "cost_allow", "cost_hold",
    }
    assert required_keys.issubset(breakdown.keys())


def test_cost_breakdown_amount_is_rupees():
    """cost_breakdown['amount'] must be in rupees (not paise)."""
    _, breakdown = select_action(p=0.05, amount=5000.0)
    assert breakdown["amount"] == pytest.approx(5000.0)


# ── break_even_probability ────────────────────────────────────────────────────


def test_break_even_formula_sanity():
    """
    break_even_probability must satisfy:  p* = (F + c) / (h * L + F + c)
    where L = amount * (1 - recovery_rate)
    """
    amount = 10000.0
    F = MOCK_COST_PARAMS["friction_cost"]
    c = MOCK_COST_PARAMS["review_cost"]
    h = MOCK_COST_PARAMS["hold_efficacy"]
    r = MOCK_COST_PARAMS["recovery_rate"]
    L = amount * (1 - r)
    expected = (F + c) / (h * L + F + c)

    result = break_even_probability(amount)
    assert result == pytest.approx(expected, rel=1e-6)


def test_break_even_increases_with_smaller_amounts():
    """Higher amounts should have a LOWER break-even threshold (worth holding for less certainty)."""
    p_small = break_even_probability(100.0)
    p_large = break_even_probability(100_000.0)
    assert p_large < p_small


def test_break_even_capped_at_one():
    """For pathological (near-zero) amounts, break-even must be capped at 1.0."""
    # With amount=0, L=0, denominator = h*0 + F + c = F + c, numerator = F + c → p* = 1.0
    result = break_even_probability(0.0)
    assert result <= 1.0
