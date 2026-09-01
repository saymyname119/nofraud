"""
tests/test_reason_codes.py

Tests for the SHAP-to-reason-code translation layer (spec §6.6).

Covers:
  - Top-N ordering by SHAP magnitude
  - Deduplication: multiple features that map to the same code count once
  - Empty input always returns at least [NOVEL_PATTERN]
  - Unknown features fall back to NOVEL_PATTERN
  - The fixed vocabulary has exactly 6 codes
"""
import pytest
from app.scoring.reason_codes import (
    ReasonCode,
    shap_values_to_reasons,
    REASON_DETAILS,
    FEATURE_TO_REASON,
)
from app.scoring.features import (
    FEAT_COUNT_TX_5MIN,
    FEAT_COUNT_TX_1HR,
    FEAT_AMOUNT,
    FEAT_IS_NEW_DEVICE,
    FEAT_EMAIL_DOMAIN,
    FEAT_DAYS_SINCE_LAST,
)


# ── Vocabulary completeness ───────────────────────────────────────────────────


def test_reason_code_vocabulary_size():
    """The fixed vocabulary must have exactly 6 codes (spec §6.6)."""
    assert len(ReasonCode) == 6


def test_all_codes_have_details():
    """Every ReasonCode must have a customer_text and internal_text."""
    for code in ReasonCode:
        assert code in REASON_DETAILS
        detail = REASON_DETAILS[code]
        assert detail.customer_text
        assert detail.internal_text


# ── shap_values_to_reasons ────────────────────────────────────────────────────


def test_empty_shap_returns_novel_pattern():
    """Empty SHAP dict must return [NOVEL_PATTERN] — always at least one reason."""
    reasons = shap_values_to_reasons({})
    assert reasons == [ReasonCode.NOVEL_PATTERN]


def test_single_feature_returns_correct_code():
    """A single dominant velocity feature maps to VELOCITY_HIGH."""
    shap = {FEAT_COUNT_TX_5MIN: 0.8}
    reasons = shap_values_to_reasons(shap, top_n=3)
    assert ReasonCode.VELOCITY_HIGH in reasons


def test_top_n_ordering():
    """Reasons are ordered by descending SHAP magnitude."""
    shap = {
        FEAT_AMOUNT: 0.9,           # → AMOUNT_ANOMALY (highest)
        FEAT_COUNT_TX_5MIN: 0.5,    # → VELOCITY_HIGH
        FEAT_IS_NEW_DEVICE: 0.2,    # → NEW_DEVICE
    }
    reasons = shap_values_to_reasons(shap, top_n=3)
    assert reasons[0] == ReasonCode.AMOUNT_ANOMALY
    assert reasons[1] == ReasonCode.VELOCITY_HIGH
    assert reasons[2] == ReasonCode.NEW_DEVICE


def test_deduplication_same_code():
    """
    Multiple features mapping to the same code must only appear once,
    with the entry ranked at the position of the highest-magnitude feature.
    """
    shap = {
        FEAT_COUNT_TX_5MIN: 0.9,   # VELOCITY_HIGH
        FEAT_COUNT_TX_1HR: 0.8,    # VELOCITY_HIGH (duplicate)
        FEAT_AMOUNT: 0.5,           # AMOUNT_ANOMALY
        FEAT_EMAIL_DOMAIN: 0.3,    # NEW_EMAIL_DOMAIN
    }
    reasons = shap_values_to_reasons(shap, top_n=3)
    # VELOCITY_HIGH must appear only once
    assert reasons.count(ReasonCode.VELOCITY_HIGH) == 1
    assert len(reasons) <= 3


def test_top_n_limit_respected():
    """shap_values_to_reasons must return at most top_n unique codes."""
    shap = {
        FEAT_AMOUNT: 0.9,
        FEAT_COUNT_TX_5MIN: 0.8,
        FEAT_IS_NEW_DEVICE: 0.7,
        FEAT_EMAIL_DOMAIN: 0.6,
        FEAT_DAYS_SINCE_LAST: 0.5,
    }
    reasons = shap_values_to_reasons(shap, top_n=2)
    assert len(reasons) <= 2


def test_unknown_feature_falls_back_to_novel_pattern():
    """A feature name not in FEATURE_TO_REASON must map to NOVEL_PATTERN."""
    shap = {"totally_unknown_feature_xyz": 1.0}
    reasons = shap_values_to_reasons(shap, top_n=3)
    assert ReasonCode.NOVEL_PATTERN in reasons


def test_isolation_forest_maps_to_novel_pattern():
    """The virtual isolation_forest_score feature must map to NOVEL_PATTERN."""
    assert FEATURE_TO_REASON.get("isolation_forest_score") == ReasonCode.NOVEL_PATTERN


def test_all_feature_to_reason_values_are_valid_codes():
    """Every value in FEATURE_TO_REASON must be a valid ReasonCode member."""
    valid_codes = set(ReasonCode)
    for feat, code in FEATURE_TO_REASON.items():
        assert code in valid_codes, f"{feat} maps to invalid code {code}"


def test_reasons_are_reason_code_instances():
    """Returned values must be ReasonCode enum members, not plain strings."""
    shap = {FEAT_AMOUNT: 0.5}
    reasons = shap_values_to_reasons(shap)
    for r in reasons:
        assert isinstance(r, ReasonCode)
