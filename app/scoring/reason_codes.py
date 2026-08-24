"""
app/scoring/reason_codes.py — SHAP driver → fixed reason-code vocabulary.

Spec §6.6: Never surface raw feature names, SHAP values, or thresholds
to anything a customer or attacker can read. Map internal SHAP results
to a fixed, sanitized vocabulary of 6 reason codes.
"""
from __future__ import annotations

from enum import Enum
from typing import NamedTuple

from app.scoring.features import (
    FEAT_COUNT_TX_5MIN, FEAT_COUNT_TX_1HR, FEAT_COUNT_TX_24HR,
    FEAT_COUNT_CARD_5MIN, FEAT_COUNT_CARD_1HR,
    FEAT_AMOUNT, FEAT_AMOUNT_VS_AVG,
    FEAT_DEVICE_TYPE, FEAT_DEVICE_INFO, FEAT_IS_NEW_DEVICE,
    FEAT_EMAIL_DOMAIN, FEAT_IS_DISPOSABLE_EMAIL,
    FEAT_DAYS_SINCE_LAST, FEAT_IS_LARGE_AMOUNT,
)


class ReasonCode(str, Enum):
    """The complete, fixed reason-code vocabulary (spec §6.6)."""
    VELOCITY_HIGH = "VELOCITY_HIGH"
    AMOUNT_ANOMALY = "AMOUNT_ANOMALY"
    NEW_DEVICE = "NEW_DEVICE"
    NEW_EMAIL_DOMAIN = "NEW_EMAIL_DOMAIN"
    RAPID_REPEAT = "RAPID_REPEAT"
    NOVEL_PATTERN = "NOVEL_PATTERN"


class ReasonDetail(NamedTuple):
    code: ReasonCode
    customer_text: str   # safe to show to any audience
    internal_text: str   # for audit / review dashboard only


# Full vocabulary with both safe and internal descriptions
REASON_DETAILS: dict[ReasonCode, ReasonDetail] = {
    ReasonCode.VELOCITY_HIGH: ReasonDetail(
        code=ReasonCode.VELOCITY_HIGH,
        customer_text="Unusual number of recent transactions",
        internal_text="High velocity: multiple transactions in a short window from same account/card",
    ),
    ReasonCode.AMOUNT_ANOMALY: ReasonDetail(
        code=ReasonCode.AMOUNT_ANOMALY,
        customer_text="Amount unusual for this account",
        internal_text="Transaction amount significantly higher than account average",
    ),
    ReasonCode.NEW_DEVICE: ReasonDetail(
        code=ReasonCode.NEW_DEVICE,
        customer_text="Payment from an unrecognized device",
        internal_text="Device fingerprint not seen in transaction history for this account",
    ),
    ReasonCode.NEW_EMAIL_DOMAIN: ReasonDetail(
        code=ReasonCode.NEW_EMAIL_DOMAIN,
        customer_text="New or unusual email domain",
        internal_text="Email domain is new, disposable, or not seen before on this account",
    ),
    ReasonCode.RAPID_REPEAT: ReasonDetail(
        code=ReasonCode.RAPID_REPEAT,
        customer_text="Rapid repeat activity on this account",
        internal_text="Short time since last transaction indicates burst activity",
    ),
    ReasonCode.NOVEL_PATTERN: ReasonDetail(
        code=ReasonCode.NOVEL_PATTERN,
        customer_text="Doesn't match typical activity",
        internal_text="Isolation Forest: transaction is an outlier vs the overall population",
    ),
}

# ── Feature → ReasonCode mapping ──────────────────────────────────────────────
# Maps each feature name to the reason code it triggers when SHAP says it's dominant.

FEATURE_TO_REASON: dict[str, ReasonCode] = {
    # Velocity features → VELOCITY_HIGH
    FEAT_COUNT_TX_5MIN: ReasonCode.VELOCITY_HIGH,
    FEAT_COUNT_TX_1HR: ReasonCode.VELOCITY_HIGH,
    FEAT_COUNT_TX_24HR: ReasonCode.VELOCITY_HIGH,
    FEAT_COUNT_CARD_5MIN: ReasonCode.VELOCITY_HIGH,
    FEAT_COUNT_CARD_1HR: ReasonCode.VELOCITY_HIGH,
    # Amount anomaly
    FEAT_AMOUNT: ReasonCode.AMOUNT_ANOMALY,
    FEAT_AMOUNT_VS_AVG: ReasonCode.AMOUNT_ANOMALY,
    FEAT_IS_LARGE_AMOUNT: ReasonCode.AMOUNT_ANOMALY,
    # Device
    FEAT_DEVICE_TYPE: ReasonCode.NEW_DEVICE,
    FEAT_DEVICE_INFO: ReasonCode.NEW_DEVICE,
    FEAT_IS_NEW_DEVICE: ReasonCode.NEW_DEVICE,
    # Email domain
    FEAT_EMAIL_DOMAIN: ReasonCode.NEW_EMAIL_DOMAIN,
    FEAT_IS_DISPOSABLE_EMAIL: ReasonCode.NEW_EMAIL_DOMAIN,
    # Rapid repeat (time delta)
    FEAT_DAYS_SINCE_LAST: ReasonCode.RAPID_REPEAT,
    # Isolation Forest signal
    "isolation_forest_score": ReasonCode.NOVEL_PATTERN,
}

# Default code for any feature not in the above map
DEFAULT_REASON = ReasonCode.NOVEL_PATTERN


def shap_values_to_reasons(
    shap_feature_importance: dict[str, float],
    top_n: int = 3,
) -> list[ReasonCode]:
    """
    Convert a dict of {feature_name: abs_shap_value} into an ordered list
    of at most `top_n` unique ReasonCodes, ranked by SHAP magnitude.

    This is the ONLY place that translates internal features to reason codes.
    Callers must never emit feature names externally.

    Args:
        shap_feature_importance: {feature_name: absolute_shap_value}
        top_n: how many reason codes to return

    Returns:
        Ordered list of unique ReasonCodes (most impactful first).
    """
    # Sort by abs SHAP descending
    ranked = sorted(shap_feature_importance.items(), key=lambda x: x[1], reverse=True)

    reasons: list[ReasonCode] = []
    seen: set[ReasonCode] = set()

    for feat_name, _ in ranked:
        code = FEATURE_TO_REASON.get(feat_name, DEFAULT_REASON)
        if code not in seen:
            reasons.append(code)
            seen.add(code)
        if len(reasons) >= top_n:
            break

    # Always return at least one reason
    if not reasons:
        reasons.append(DEFAULT_REASON)

    return reasons
