"""
app/idempotency.py — 60-second idempotency cache.

Spec §11 invariant #8:
  "Idempotency replays, it does not re-score."
  "A replay reflects the action's current resolved state, not the original directive."

  A 60-second TTL catches Razorpay's duplicate webhook deliveries (common on
  retries) and the "retry attack" (attacker replaying the same payment hoping
  for a different score).

  The cache is keyed on the canonical SHA-256 of the payment payload (not the
  payment_id, to catch semantically-identical payloads with different IDs).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import DecisionCache
from app.config import get_idempotency_cfg

logger = logging.getLogger(__name__)


def _payload_hash(payment: dict[str, Any]) -> str:
    """
    Canonical SHA-256 of the payment payload.
    Keys are sorted, floats normalised — two semantically identical payloads
    produce the same hash regardless of key ordering.
    """
    canonical = json.dumps(payment, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


async def check_cache(
    session: AsyncSession,
    payment: dict[str, Any],
) -> DecisionCache | None:
    """
    Return a cached decision if one exists within the TTL, else None.
    Caller should replay the cached action's CURRENT resolved state (not
    blindly re-assert the original directive).
    """
    cfg = get_idempotency_cfg()
    ttl = timedelta(seconds=cfg.get("ttl_seconds", 60))
    key = _payload_hash(payment)

    cutoff = datetime.utcnow() - ttl

    result = await session.execute(
        select(DecisionCache)
        .where(DecisionCache.payload_hash == key)
        .where(DecisionCache.created_at >= cutoff)
    )
    cached = result.scalar_one_or_none()
    if cached:
        logger.info(f"Idempotency HIT for hash={key[:16]}... tx_id={cached.tx_id}")
    return cached


async def store_decision(
    session: AsyncSession,
    payment: dict[str, Any],
    tx_id: str,
    payment_id: str,
    action: str,
    p_fraud: float,
    reasons: list[str],
) -> DecisionCache:
    """Store a new decision in the idempotency cache."""
    key = _payload_hash(payment)
    entry = DecisionCache(
        payload_hash=key,
        tx_id=tx_id,
        payment_id=payment_id,
        action=action,
        p_fraud=p_fraud,
        reasons=json.dumps(reasons),
    )
    session.add(entry)
    await session.flush()
    return entry


async def purge_expired(session: AsyncSession) -> int:
    """Delete expired idempotency entries (call periodically from a background task)."""
    cfg = get_idempotency_cfg()
    ttl = timedelta(seconds=cfg.get("ttl_seconds", 60))
    cutoff = datetime.utcnow() - ttl
    result = await session.execute(
        delete(DecisionCache).where(DecisionCache.created_at < cutoff)
    )
    count = result.rowcount
    if count:
        logger.debug(f"Purged {count} expired idempotency entries")
    return count
