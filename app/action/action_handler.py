"""
app/action/action_handler.py — Routes CAPTURE / VERIFY / HOLD to Razorpay calls.

Spec §8.2 (request flow):
  journal DECIDED  ← durable BEFORE any money moves
  action_handler.execute()  ← idempotent Razorpay call
  journal ACTION_RESULT

This module is called AFTER the DECIDED record is written.
It returns the action status and Razorpay response for ACTION_RESULT logging.
"""
from __future__ import annotations

import logging
from typing import Any

from app.action.razorpay_client import (
    capture_payment,
    create_payment_link,
    refund_payment,
)
from app.decision.engine import DecisionResult

logger = logging.getLogger(__name__)


async def execute(decision: DecisionResult, payment: dict[str, Any]) -> tuple[str, dict]:
    """
    Execute the action for a decision.

    Args:
        decision: the full DecisionResult from the decision engine
        payment: original Razorpay payment dict (for amount, customer details)

    Returns:
        (action_status, razorpay_response)
        action_status: "SUCCESS" | "FAILED" | "SKIPPED"
    """
    payment_id = decision.payment_id
    amount_paise = int(payment.get("amount", 0))

    notes = payment.get("notes") or {}
    customer_name = notes.get("name") or "Customer"
    customer_email = notes.get("email") or payment.get("email") or ""

    # Shadow mode: suppress the action, don't touch Razorpay
    if decision.shadow_mode and decision.action != "CAPTURE":
        logger.info(
            f"[{decision.tx_id}] SHADOW MODE: action={decision.action} suppressed, "
            f"no Razorpay call made"
        )
        return "SKIPPED", {"reason": "shadow_mode", "intended_action": decision.action}

    action = decision.effective_action

    # ── HOLD: do nothing. The authorization lapses on its own. ─────────────────
    # This is the core insight: Razorpay's capture window IS the reversible hold.
    if action == "HOLD":
        logger.info(
            f"[{decision.tx_id}] HOLD: not calling Capture for {payment_id}. "
            f"Auth will lapse → auto-refund. Fraud averted."
        )
        return "SUCCESS", {
            "action": "HOLD",
            "payment_id": payment_id,
            "note": "Authorization allowed to lapse. Auto-refund will occur.",
        }

    # ── CAPTURE: settle the payment ────────────────────────────────────────────
    elif action == "CAPTURE":
        response = await capture_payment(payment_id, amount_paise)
        status = "SUCCESS" if response.get("status") == "captured" or response.get("mock") else "FAILED"
        if status == "FAILED":
            logger.error(f"[{decision.tx_id}] CAPTURE failed: {response}")
        return status, response

    # ── VERIFY: send step-up Payment Link ──────────────────────────────────────
    elif action == "VERIFY":
        response = await create_payment_link(
            payment_id=payment_id,
            amount_paise=amount_paise,
            customer_name=customer_name,
            customer_email=customer_email,
        )
        status = "SUCCESS" if "short_url" in response or response.get("mock") else "FAILED"
        if status == "SUCCESS":
            logger.info(
                f"[{decision.tx_id}] VERIFY: Payment Link sent to {customer_email}: "
                f"{response.get('short_url', 'MOCK')}"
            )
        return status, response

    else:
        logger.error(f"[{decision.tx_id}] Unknown action: {action}")
        return "FAILED", {"error": f"Unknown action: {action}"}
