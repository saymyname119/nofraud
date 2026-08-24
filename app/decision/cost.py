"""
app/decision/cost.py — Expected-cost action selection.

Spec §5 + §A.7:
  hold_is_worth_it when p > (F + c) / (h * L + F + c)
  where L = amount * (1 - recovery_rate)

The threshold is a function of amount, not a constant global value.
Thresholds are read from config.yaml (the GENERATED section from ml/evaluate.py).
Hard-coding a threshold here is a spec violation (§11 invariant #2).
"""
from __future__ import annotations

import logging
from typing import Literal

from app.config import get_amount_thresholds, get_cost_params

logger = logging.getLogger(__name__)

Action = Literal["CAPTURE", "VERIFY", "HOLD"]


def threshold_for_amount(amount: float) -> float:
    """
    Return the minimum fraud probability needed to trigger a HOLD for this amount.
    Derived from the cost sweep in ml/evaluate.py, stored in config.yaml.
    """
    buckets = get_amount_thresholds()
    for bucket in buckets:
        if amount <= bucket["max_amount"]:
            return float(bucket["min_fraud_prob"])
    return float(buckets[-1]["min_fraud_prob"])


def break_even_probability(amount: float) -> float:
    """
    The exact break-even P(fraud) above which holding is cheaper than allowing.
    From §A.7:  p* = (F + c) / (h * L + F + c)
    L = amount * (1 - recovery_rate)

    This is the formula behind §5's table — used for the demo slide.
    """
    params = get_cost_params()
    F = params["friction_cost"]
    c = params["review_cost"]
    h = params["hold_efficacy"]
    r = params["recovery_rate"]

    L = amount * (1 - r)
    denominator = h * L + F + c
    if denominator <= 0:
        return 1.0  # pathological: never hold
    return min(1.0, (F + c) / denominator)


def expected_cost_hold(p: float, amount: float) -> float:
    """Expected cost if we HOLD this payment."""
    params = get_cost_params()
    F = params["friction_cost"]
    c = params["review_cost"]
    h = params["hold_efficacy"]
    L = amount * (1 - params["recovery_rate"])
    return p * (1 - h) * L + (1 - p) * F + c


def expected_cost_allow(p: float, amount: float) -> float:
    """Expected cost if we CAPTURE (allow) this payment."""
    params = get_cost_params()
    L = amount * (1 - params["recovery_rate"])
    return p * L


def select_action(p: float, amount: float) -> tuple[Action, dict]:
    """
    Select CAPTURE / VERIFY / HOLD based on the calibrated P(fraud) and amount.

    Logic (spec §5):
      - p < low_threshold   → CAPTURE (risk too low to bother)
      - p >= high_threshold → HOLD    (risk clearly too high)
      - low <= p < high    → VERIFY   (step-up — let owner self-clear)

    The VERIFY band is the middle third of the [CAPTURE, HOLD] range.
    This is where the Razorpay Payment Link fits.

    Returns (action, cost_breakdown) where cost_breakdown is for the audit log.
    """
    hold_threshold = threshold_for_amount(amount)

    # VERIFY band: lower threshold is 60% of the hold threshold
    verify_threshold = hold_threshold * 0.60

    cost_allow = expected_cost_allow(p, amount)
    cost_hold = expected_cost_hold(p, amount)

    cost_breakdown = {
        "p_fraud": round(p, 4),
        "amount": amount,
        "hold_threshold": round(hold_threshold, 4),
        "verify_threshold": round(verify_threshold, 4),
        "cost_allow": round(cost_allow, 2),
        "cost_hold": round(cost_hold, 2),
    }

    if p >= hold_threshold:
        action: Action = "HOLD"
    elif p >= verify_threshold:
        action = "VERIFY"
    else:
        action = "CAPTURE"

    logger.debug(
        f"select_action: p={p:.3f}, amount={amount:.0f} → {action} "
        f"(hold_thresh={hold_threshold:.3f}, verify_thresh={verify_threshold:.3f})"
    )

    return action, cost_breakdown
