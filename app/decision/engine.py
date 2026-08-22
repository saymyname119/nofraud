"""
app/decision/engine.py — Decision engine. Owns ALL policy.

Spec §9.2 layer order (MUST be preserved):
  1. Compliance gate   → HOLD + escalate (sanctions/watchlist — deterministic, list-driven)
  2. Blocklist         → HOLD (confirmed-compromised cards/emails)
  3. Allowlist         → CAPTURE (repeat known-good — skips ML entirely)
  4. Circuit breaker   → CAPTURE if OPEN (ML bypassed, but layers 1–2 already ran)
  5. ML action select  → CAPTURE / VERIFY / HOLD (cost.select_action)
  6. Safety governor   → suppresses directive only (shadow_mode)

Every layer's verdict is recorded on the decision record.
"Which layer decided this?" is always answerable from the audit log.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.config import get_compliance_lists, get_config_hash, is_shadow_mode
from app.decision.circuit_breaker import get_breaker
from app.decision.cost import select_action
from app.scoring.model import ScoringResult
from app.scoring.pipeline import score_payment
from app.scoring.reason_codes import ReasonCode

logger = logging.getLogger(__name__)


@dataclass
class DecisionResult:
    """Full output of the decision engine for one transaction."""
    tx_id: str
    payment_id: str
    amount: float

    # ML scoring (None if a pre-filter resolved it)
    scoring_result: ScoringResult | None
    p_fraud: float

    # Final directive
    action: str               # CAPTURE | VERIFY | HOLD
    escalate: bool            # True if compliance layer forced escalation
    reasons: list[str]        # reason code strings (customer-safe vocabulary)

    # Shadow mode: if True the action directive is suppressed, score still logged
    shadow_mode: bool
    effective_action: str     # = action unless shadow_mode, then = "PASS (shadow)"

    # Which layer resolved this decision
    resolving_layer: str
    layer_verdicts: dict[str, str]

    # For audit log
    config_hash: str
    model_version: str
    feature_vector_hash: str
    cost_breakdown: dict


async def decide(
    payment: dict[str, Any],
    velocity: dict[str, float],
) -> DecisionResult:
    """
    Run the full decision pipeline for one payment.authorized event.

    Args:
        payment: Razorpay payment dict
        velocity: velocity counts from the velocity store

    Returns:
        DecisionResult with every field needed for the audit log and action layer.
    """
    tx_id = "fs_" + str(uuid.uuid4()).replace("-", "")[:20]
    payment_id = payment.get("id", "")
    amount_paise = int(payment.get("amount", 0))
    amount = amount_paise / 100.0  # paise → rupees

    notes = payment.get("notes") or {}
    email = (notes.get("email") or payment.get("email") or "").lower()
    card = payment.get("card") or {}
    card_last4 = card.get("last4", "")

    compliance_lists = get_compliance_lists()
    layer_verdicts: dict[str, str] = {}

    # ── Layer 1: Compliance gate ────────────────────────────────────────────
    # Sanctions/watchlist — deterministic, list-driven, never a model output.
    # This is the one carve-out from the "no hard block" rule (legal obligation).
    sanctioned = compliance_lists.get("sanctioned_keywords", [])
    email_blocked = any(kw in email for kw in sanctioned)
    if email_blocked or any(kw in str(payment) for kw in sanctioned):
        layer_verdicts["compliance"] = "HOLD_ESCALATE"
        layer_verdicts.update({"blocklist": "SKIP", "allowlist": "SKIP", "breaker": "SKIP", "ml": "SKIP"})
        logger.info(f"[{tx_id}] Layer 1 COMPLIANCE hit → HOLD+escalate")
        return _build_result(
            tx_id=tx_id, payment_id=payment_id, amount=amount,
            action="HOLD", escalate=True,
            reasons=[ReasonCode.NOVEL_PATTERN.value],
            resolving_layer="compliance",
            layer_verdicts=layer_verdicts,
            scoring_result=None, p_fraud=1.0,
            cost_breakdown={},
        )

    layer_verdicts["compliance"] = "PASS"

    # ── Layer 2: Blocklist ───────────────────────────────────────────────────
    blocklisted_cards = compliance_lists.get("blocklisted_cards", [])
    blocklisted_emails = compliance_lists.get("blocklisted_emails", [])
    if email in blocklisted_emails or card_last4 in blocklisted_cards:
        layer_verdicts["blocklist"] = "HOLD"
        layer_verdicts.update({"allowlist": "SKIP", "breaker": "SKIP", "ml": "SKIP"})
        logger.info(f"[{tx_id}] Layer 2 BLOCKLIST hit → HOLD")
        return _build_result(
            tx_id=tx_id, payment_id=payment_id, amount=amount,
            action="HOLD", escalate=False,
            reasons=[ReasonCode.NOVEL_PATTERN.value],
            resolving_layer="blocklist",
            layer_verdicts=layer_verdicts,
            scoring_result=None, p_fraud=1.0,
            cost_breakdown={},
        )

    layer_verdicts["blocklist"] = "PASS"

    # ── Layer 3: Allowlist ───────────────────────────────────────────────────
    # Known-good repeat customers — skip ML entirely (cheapest path).
    allowlisted_emails = compliance_lists.get("allowlisted_emails", [])
    if email in allowlisted_emails:
        layer_verdicts["allowlist"] = "CAPTURE"
        layer_verdicts.update({"breaker": "SKIP", "ml": "SKIP"})
        logger.info(f"[{tx_id}] Layer 3 ALLOWLIST hit → CAPTURE (model skipped)")
        return _build_result(
            tx_id=tx_id, payment_id=payment_id, amount=amount,
            action="CAPTURE", escalate=False,
            reasons=[],
            resolving_layer="allowlist",
            layer_verdicts=layer_verdicts,
            scoring_result=None, p_fraud=0.0,
            cost_breakdown={},
        )

    layer_verdicts["allowlist"] = "NO_MATCH"

    # ── Layer 4: Circuit breaker ─────────────────────────────────────────────
    # If OPEN: bypass ML, default to CAPTURE.
    # Layers 1 + 2 have already run, so the floor policy is preserved.
    breaker = get_breaker()
    breaker_status = await breaker.status()
    layer_verdicts["breaker"] = breaker_status.state

    if breaker_status.state == "OPEN":
        logger.warning(f"[{tx_id}] Layer 4 BREAKER OPEN → CAPTURE (ML bypassed)")
        layer_verdicts["ml"] = "BYPASSED"
        return _build_result(
            tx_id=tx_id, payment_id=payment_id, amount=amount,
            action="CAPTURE", escalate=False,
            reasons=[],
            resolving_layer="circuit_breaker",
            layer_verdicts=layer_verdicts,
            scoring_result=None, p_fraud=0.0,
            cost_breakdown={"breaker_rate": breaker_status.hold_rate},
        )

    # ── Layer 5: ML action selection ─────────────────────────────────────────
    scoring_result: ScoringResult = await score_payment(payment, velocity)
    p = scoring_result.p
    action, cost_breakdown = select_action(p, amount)

    layer_verdicts["ml"] = action
    reasons = [r.value for r in scoring_result.reasons]

    logger.info(
        f"[{tx_id}] ML: p={p:.3f} amount=₹{amount:.0f} → {action} "
        f"reasons={reasons}"
    )

    # ── Layer 6: Safety governor (shadow mode) ───────────────────────────────
    # Shadow mode: score and log, but suppress the action directive.
    # This is a config flag, NOT a code fork (spec §11 invariant #9).
    shadow = is_shadow_mode()

    # Record the breaker's contribution to hold rate (for hysteresis tracking)
    await breaker.record(is_hold=(action == "HOLD"))

    return _build_result(
        tx_id=tx_id, payment_id=payment_id, amount=amount,
        action=action, escalate=False,
        reasons=reasons,
        resolving_layer="ml",
        layer_verdicts=layer_verdicts,
        scoring_result=scoring_result, p_fraud=p,
        cost_breakdown=cost_breakdown,
        shadow=shadow,
    )


def _build_result(
    *,
    tx_id: str,
    payment_id: str,
    amount: float,
    action: str,
    escalate: bool,
    reasons: list[str],
    resolving_layer: str,
    layer_verdicts: dict[str, str],
    scoring_result: ScoringResult | None,
    p_fraud: float,
    cost_breakdown: dict,
    shadow: bool = False,
) -> DecisionResult:
    effective = f"PASS (shadow)" if shadow and action != "CAPTURE" else action
    return DecisionResult(
        tx_id=tx_id,
        payment_id=payment_id,
        amount=amount,
        scoring_result=scoring_result,
        p_fraud=p_fraud,
        action=action,
        escalate=escalate,
        reasons=reasons,
        shadow_mode=shadow,
        effective_action=effective,
        resolving_layer=resolving_layer,
        layer_verdicts=layer_verdicts,
        config_hash=get_config_hash(),
        model_version=scoring_result.model_version if scoring_result else "n/a",
        feature_vector_hash=scoring_result.feature_vector_hash if scoring_result else "",
        cost_breakdown=cost_breakdown,
    )
