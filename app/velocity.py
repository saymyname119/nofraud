"""
app/velocity.py — SQLite-based velocity feature store (MVP).

Computes velocity counts for a given payment by querying the VelocityRecord table.
Swap REDIS_URL in .env to upgrade to Redis with no code changes in this module.

Features computed (matching FEATURE_COLUMNS in features.py):
  count_tx_5min, count_tx_1hr, count_tx_24hr   — by email
  count_card_5min, count_card_1hr               — by card last4
  amount_vs_avg                                  — amount / avg amount for email
  unique_emails_card, unique_cards_email         — cross-entity signals
  days_since_last, days_since_first              — time-delta features
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import VelocityRecord

logger = logging.getLogger(__name__)


async def compute_velocity(
    session: AsyncSession,
    payment: dict[str, Any],
) -> dict[str, float]:
    """
    Compute velocity features for a payment.
    Must be called BEFORE storing the current payment (so counts are exclusive).
    """
    notes = payment.get("notes") or {}
    email = (notes.get("email") or payment.get("email") or "").lower().strip()
    card = payment.get("card") or {}
    card_last4 = card.get("last4", "")
    amount_paise = int(payment.get("amount", 0))
    amount = amount_paise / 100.0

    now = datetime.now(timezone.utc)

    # Use naive UTC for window boundaries — the DB stores naive timestamps
    now_naive = now.replace(tzinfo=None)

    windows = {
        "5min": now_naive - timedelta(minutes=5),
        "1hr":  now_naive - timedelta(hours=1),
        "24hr": now_naive - timedelta(hours=24),
    }

    async def count_by_email(since: datetime) -> int:
        if not email:
            return 0
        r = await session.execute(
            select(func.count()).select_from(VelocityRecord)
            .where(VelocityRecord.email == email)
            .where(VelocityRecord.timestamp >= since)
        )
        return r.scalar_one() or 0

    async def count_by_card(since: datetime) -> int:
        if not card_last4:
            return 0
        r = await session.execute(
            select(func.count()).select_from(VelocityRecord)
            .where(VelocityRecord.card_last4 == card_last4)
            .where(VelocityRecord.timestamp >= since)
        )
        return r.scalar_one() or 0

    async def avg_amount_email() -> float:
        if not email:
            return amount
        r = await session.execute(
            select(func.avg(VelocityRecord.amount)).select_from(VelocityRecord)
            .where(VelocityRecord.email == email)
        )
        avg = r.scalar_one()
        return float(avg) if avg else amount

    async def unique_emails_for_card() -> int:
        if not card_last4:
            return 0
        r = await session.execute(
            select(func.count(func.distinct(VelocityRecord.email))).select_from(VelocityRecord)
            .where(VelocityRecord.card_last4 == card_last4)
            .where(VelocityRecord.timestamp >= now_naive - timedelta(hours=24))
        )
        return r.scalar_one() or 0

    async def unique_cards_for_email() -> int:
        if not email:
            return 0
        r = await session.execute(
            select(func.count(func.distinct(VelocityRecord.card_last4))).select_from(VelocityRecord)
            .where(VelocityRecord.email == email)
            .where(VelocityRecord.timestamp >= now_naive - timedelta(hours=24))
        )
        return r.scalar_one() or 0

    async def days_since_last() -> float:
        if not email:
            return -1.0
        r = await session.execute(
            select(func.max(VelocityRecord.timestamp)).select_from(VelocityRecord)
            .where(VelocityRecord.email == email)
        )
        last = r.scalar_one()
        if last is None:
            return -1.0
        return (now.replace(tzinfo=None) - last).total_seconds() / 86400.0

    async def days_since_first() -> float:
        if not email:
            return -1.0
        r = await session.execute(
            select(func.min(VelocityRecord.timestamp)).select_from(VelocityRecord)
            .where(VelocityRecord.email == email)
        )
        first = r.scalar_one()
        if first is None:
            return -1.0
        return (now.replace(tzinfo=None) - first).total_seconds() / 86400.0

    # Run all queries
    c_tx_5min  = await count_by_email(windows["5min"])
    c_tx_1hr   = await count_by_email(windows["1hr"])
    c_tx_24hr  = await count_by_email(windows["24hr"])
    c_card_5m  = await count_by_card(windows["5min"])
    c_card_1hr = await count_by_card(windows["1hr"])
    avg_amt    = await avg_amount_email()
    u_emails   = await unique_emails_for_card()
    u_cards    = await unique_cards_for_email()
    d_last     = await days_since_last()
    d_first    = await days_since_first()

    amount_vs_avg = (amount / avg_amt) if avg_amt > 0 else 1.0

    velocity = {
        "count_tx_5min":      float(c_tx_5min),
        "count_tx_1hr":       float(c_tx_1hr),
        "count_tx_24hr":      float(c_tx_24hr),
        "count_card_5min":    float(c_card_5m),
        "count_card_1hr":     float(c_card_1hr),
        "amount_vs_avg":      float(amount_vs_avg),
        "unique_emails_card": float(u_emails),
        "unique_cards_email": float(u_cards),
        "days_since_last":    float(d_last),
        "days_since_first":   float(d_first),
    }
    return velocity


async def record_transaction(
    session: AsyncSession,
    payment: dict[str, Any],
    tx_id: str,
) -> None:
    """Store this transaction in the velocity table AFTER scoring."""
    notes = payment.get("notes") or {}
    email = (notes.get("email") or payment.get("email") or "").lower().strip()
    card = payment.get("card") or {}
    card_last4 = card.get("last4", "")
    amount = int(payment.get("amount", 0)) / 100.0

    rec = VelocityRecord(
        email=email or None,
        card_last4=card_last4 or None,
        amount=amount,
        tx_id=tx_id,
    )
    session.add(rec)
    await session.flush()
