"""
app/api/dashboard.py — REST API for the internal frontend dashboard.

Provides endpoints for fetching recent payments, the audit log hash chain,
and business cost statistics. Also mounts the SSE endpoint.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditRecord
from app.database import get_session
from app.sse import broadcaster

router = APIRouter()


@router.get("/payments")
async def get_recent_payments(
    limit: int = 50,
    session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Return the most recent DECIDED records."""
    stmt = (
        select(AuditRecord)
        .where(AuditRecord.record_type == "DECIDED")
        .order_by(desc(AuditRecord.id))
        .limit(limit)
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    payments = []
    for r in records:
        payments.append({
            "id": r.id,
            "tx_id": r.tx_id,
            "payment_id": r.payment_id,
            "timestamp": r.timestamp.isoformat(),
            "amount": r.amount,
            "action": r.action,
            "p_fraud": r.p_fraud,
            "reasons": json.loads(r.reasons) if r.reasons else [],
            "shadow_mode": r.shadow_mode,
        })
    return {"payments": payments}


@router.get("/audit")
async def get_audit_log(
    limit: int = 100,
    session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Return the most recent audit records to render the hash chain."""
    stmt = (
        select(AuditRecord)
        .order_by(desc(AuditRecord.id))
        .limit(limit)
    )
    result = await session.execute(stmt)
    # Return ascending order so the chain visualizes naturally top-to-bottom
    records = reversed(result.scalars().all())

    logs = []
    for r in records:
        logs.append({
            "id": r.id,
            "record_type": r.record_type,
            "tx_id": r.tx_id,
            "timestamp": r.timestamp.isoformat(),
            "previous_log_hash": r.previous_log_hash,
            "record_hash": r.record_hash,
        })
    return {"logs": logs}


@router.get("/stats")
async def get_stats(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """
    Compute business cost comparison.
    Cost if we allowed all vs Cost of current actions.
    (Simple MVP version based on last 24h)
    """
    yesterday = datetime.utcnow() - timedelta(days=1)
    stmt = (
        select(AuditRecord)
        .where(AuditRecord.record_type == "DECIDED")
        .where(AuditRecord.timestamp >= yesterday)
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    # NOTE: The true cost requires labels (which we don't have for live data).
    # For the dashboard demo, we estimate "fraud prevented" based on p_fraud.
    # If p_fraud > 0.5, we assume it was fraud.
    
    total_volume = 0.0
    fraud_prevented = 0.0
    false_positives = 0.0

    for r in records:
        amount = r.amount or 0.0
        total_volume += amount
        
        is_high_risk = r.p_fraud is not None and r.p_fraud > 0.5
        
        if r.action in ("HOLD", "VERIFY"):
            if is_high_risk:
                fraud_prevented += amount
            else:
                false_positives += 1

    return {
        "period": "24h",
        "total_volume": total_volume,
        "fraud_prevented": fraud_prevented,
        "false_positives_count": false_positives,
        "total_decisions": len(records),
    }


@router.get("/events")
async def sse_events():
    """Server-Sent Events endpoint for real-time dashboard updates."""
    queue = broadcaster.subscribe()
    return StreamingResponse(
        broadcaster.event_generator(queue),
        media_type="text/event-stream"
    )
