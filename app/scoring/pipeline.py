"""
app/scoring/pipeline.py — PURE scoring pipeline.

Features → inference → calibration → reasons.
No policy, no side effects, no Razorpay calls.

Spec §8.1: "scoring/ contains no policy and no side effects"
"""
from __future__ import annotations

import logging
from typing import Any

from app.scoring.features import FeatureVector, build_feature_vector
from app.scoring.model import ScoringResult, get_model

logger = logging.getLogger(__name__)


async def score_payment(
    payment: dict[str, Any],
    velocity: dict[str, float],
) -> ScoringResult:
    """
    Full scoring pipeline for a single payment.

    Args:
        payment: Razorpay payment dict from the webhook payload
        velocity: velocity counts from the velocity store

    Returns:
        ScoringResult with calibrated P(fraud), reason codes, and hashes.
        The model version and feature_vector_hash are included for the audit log.
    """
    model = get_model()
    artifact = model._model  # access the artifact dict

    email_domain_encoder = artifact.get("email_domain_encoder", {})
    device_info_encoder = artifact.get("device_info_encoder", {})

    fv: FeatureVector = build_feature_vector(
        payment=payment,
        velocity=velocity,
        email_domain_encoder=email_domain_encoder,
        device_info_encoder=device_info_encoder,
    )

    logger.debug(f"Feature vector built: amount={fv.TransactionAmt}, hash={fv.to_hash()[:16]}...")

    result: ScoringResult = model.score(fv)

    logger.info(
        f"Scored payment: p={result.p:.3f}, reasons={[r.value for r in result.reasons]}, "
        f"version={result.model_version}"
    )

    return result
