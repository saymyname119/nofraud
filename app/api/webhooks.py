"""
app/api/webhooks.py — Webhook listener for Razorpay.

Spec §10.1:
  - Validates the X-Razorpay-Signature (using the webhook secret).
  - Listens specifically for `payment.authorized`.
  - Runs the decision pipeline: idempotency → velocity → engine → audit.
"""
from __future__ import annotations

import hmac
import hashlib
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.action import action_handler
from app.audit import log as audit_log
from app.config import get_settings
from app.database import get_session
from app.decision.engine import decide
from app.idempotency import check_cache, store_decision
from app.velocity import compute_velocity, record_transaction

logger = logging.getLogger(__name__)

router = APIRouter()


async def verify_signature(request: Request) -> bytes:
    """Verify Razorpay webhook signature (spec §11 #6)."""
    settings = get_settings()
    signature = request.headers.get("x-razorpay-signature", "")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature")

    body = await request.body()
    secret = settings.razorpay_webhook_secret.encode()

    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        logger.warning("Invalid Razorpay webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    return body


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    body: bytes = Depends(verify_signature),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """
    Main webhook entrypoint.
    Executes the entire FraudSpike transaction lifecycle.
    """
    try:
        import json
        payload = json.loads(body.decode())
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("event")
    if event_type != "payment.authorized":
        # We only score authorizations
        return {"status": "ignored", "reason": "not payment.authorized"}

    payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
    payment_id = payment.get("id")
    if not payment_id:
        raise HTTPException(status_code=400, detail="Missing payment_id")

    # 1. Idempotency Check (spec §11 #8)
    cached = await check_cache(session, payment)
    if cached:
        # Return success immediately; don't re-execute action.
        return {"status": "ok", "reason": "idempotent_replay"}

    # 2. Velocity Extraction
    velocity = await compute_velocity(session, payment)

    # 3. Decision Engine (Pure logic)
    decision = await decide(payment, velocity)

    # 4. Journal DECIDED (Append-only hash chain)
    decided_record = await audit_log.append_decided(
        session,
        tx_id=decision.tx_id,
        payment_id=payment_id,
        amount=decision.amount,
        p_fraud=decision.p_fraud,
        action=decision.effective_action,
        escalate=decision.escalate,
        reasons=decision.reasons,
        layer_verdicts=decision.layer_verdicts,
        feature_vector_hash=decision.feature_vector_hash,
        model_version=decision.model_version,
        config_hash=decision.config_hash,
        shadow_mode=decision.shadow_mode,
    )

    # 5. Execute Action (I/O)
    status, rp_response = await action_handler.execute(decision, payment)

    # 6. Journal ACTION_RESULT
    await audit_log.append_action_result(
        session,
        tx_id=decision.tx_id,
        payment_id=payment_id,
        action_status=status,
        razorpay_response=rp_response,
    )

    # 7. Update State (Velocity + Idempotency)
    await record_transaction(session, payment, decision.tx_id)
    await store_decision(
        session, payment, decision.tx_id, payment_id,
        decision.action, decision.p_fraud, decision.reasons
    )

    return {"status": "ok", "tx_id": decision.tx_id}
