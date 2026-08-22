"""
app/action/razorpay_client.py — The ONLY module that touches the Razorpay API.

Spec §8.1: "action/razorpay_client.py is the only module that calls Razorpay.
Keeps external side effects in one auditable place; decision and scoring layers
stay pure and unit-testable without network mocks."

All calls are idempotent (Razorpay handles duplicate capture/refund gracefully).
Mock mode: set razorpay.mock_mode: true in config.yaml to log calls without hitting the API.
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings, is_razorpay_mock, get_step_up_cfg

logger = logging.getLogger(__name__)


def _get_client():
    """Lazily create Razorpay client (avoids import error if keys are placeholders)."""
    import razorpay
    settings = get_settings()
    return razorpay.Client(
        auth=(settings.razorpay_key_id, settings.razorpay_key_secret)
    )


async def capture_payment(payment_id: str, amount_paise: int) -> dict[str, Any]:
    """
    Call Razorpay Capture API for an authorized payment.
    Amount must match the authorized amount exactly (Razorpay requirement).

    Returns Razorpay response dict.
    """
    if is_razorpay_mock():
        logger.info(f"[MOCK] CAPTURE payment_id={payment_id} amount={amount_paise}")
        return {"id": payment_id, "status": "captured", "mock": True}

    try:
        client = _get_client()
        response = client.payment.capture(payment_id, amount_paise, {"currency": "INR"})
        logger.info(f"Razorpay CAPTURE success: payment_id={payment_id}")
        return dict(response)
    except Exception as e:
        logger.error(f"Razorpay CAPTURE failed for {payment_id}: {e}")
        return {"error": str(e), "payment_id": payment_id, "status": "capture_failed"}


async def create_payment_link(
    payment_id: str,
    amount_paise: int,
    customer_name: str = "Customer",
    customer_email: str = "",
    description: str = "",
) -> dict[str, Any]:
    """
    Create a Razorpay Payment Link for step-up verification (VERIFY action).
    The link allows the real card owner to self-clear the payment.

    Returns the Payment Link object (includes `short_url` for the dashboard).
    """
    cfg = get_step_up_cfg()
    expiry_minutes = cfg.get("payment_link_expiry_minutes", 15)
    desc = description or cfg.get("description", "Please verify this payment")

    if is_razorpay_mock():
        logger.info(f"[MOCK] CREATE PAYMENT LINK for payment_id={payment_id} amount={amount_paise}")
        return {
            "id": f"plink_mock_{payment_id[:8]}",
            "short_url": f"https://rzp.io/i/mock-{payment_id[:6]}",
            "status": "created",
            "mock": True,
        }

    try:
        import time
        client = _get_client()
        payload = {
            "amount": amount_paise,
            "currency": "INR",
            "description": desc,
            "customer": {
                "name": customer_name,
                "email": customer_email,
            },
            "notify": {
                "sms": False,
                "email": bool(customer_email),
            },
            "reminder_enable": False,
            "expire_by": int(time.time()) + (expiry_minutes * 60),
            "notes": {
                "original_payment_id": payment_id,
                "reason": "step_up_verification",
            },
        }
        response = client.payment_link.create(payload)
        logger.info(f"Razorpay PaymentLink created: {response.get('short_url')}")
        return dict(response)
    except Exception as e:
        logger.error(f"Razorpay PaymentLink failed for {payment_id}: {e}")
        return {"error": str(e), "payment_id": payment_id, "status": "link_failed"}


async def refund_payment(payment_id: str, amount_paise: int | None = None) -> dict[str, Any]:
    """
    Issue a refund (or let the authorization lapse — preferred for HOLD).
    Only used if we need to explicitly refund rather than let it expire.

    In the MVP, HOLD means 'do nothing' — the auth window lapses and auto-refunds.
    This function exists for completeness and stretch-goal use.
    """
    if is_razorpay_mock():
        logger.info(f"[MOCK] REFUND payment_id={payment_id} amount={amount_paise}")
        return {"id": f"rfnd_mock_{payment_id[:8]}", "status": "processed", "mock": True}

    try:
        client = _get_client()
        payload = {}
        if amount_paise:
            payload["amount"] = amount_paise
        response = client.payment.refund(payment_id, payload)
        logger.info(f"Razorpay REFUND success: payment_id={payment_id}")
        return dict(response)
    except Exception as e:
        logger.error(f"Razorpay REFUND failed for {payment_id}: {e}")
        return {"error": str(e), "payment_id": payment_id, "status": "refund_failed"}


async def get_payment(payment_id: str) -> dict[str, Any]:
    """Fetch current payment status from Razorpay (for idempotency replay)."""
    if is_razorpay_mock():
        return {"id": payment_id, "status": "authorized", "mock": True}

    try:
        client = _get_client()
        return dict(client.payment.fetch(payment_id))
    except Exception as e:
        logger.error(f"Razorpay fetch failed for {payment_id}: {e}")
        return {"error": str(e)}
