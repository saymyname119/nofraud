"""
app/audit/log.py — SHA-256 hash-chained append-only audit log.

Spec §9.5 + CLAUDE.md invariants:
  - DECIDED is written BEFORE any Razorpay action (journal before act)
  - ACTION_RESULT is written AFTER the Razorpay call
  - Each record embeds previous_log_hash and record_hash
  - Canonical JSON (sorted keys, no insignificant whitespace) for reproducibility
  - On store failure → fail open to local audit_dlq.jsonl (availability > completeness)
  - Genesis row uses 64-zero sentinel as previous_log_hash
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditRecord
from app.config import get_audit_cfg

logger = logging.getLogger(__name__)


def _canonical_json(data: dict) -> str:
    """Produce deterministic JSON: sorted keys, no insignificant whitespace."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _compute_record_hash(fields: dict) -> str:
    """SHA-256 of canonical JSON of all fields except record_hash itself."""
    payload = {k: v for k, v in fields.items() if k != "record_hash"}
    canonical = _canonical_json(payload)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _to_dlq(payload: dict, error: str) -> None:
    """Write a failed record to the local dead-letter queue (spec §A.9)."""
    cfg = get_audit_cfg()
    dlq_path = Path(cfg.get("dlq_path", "audit_dlq.jsonl"))
    entry = {"error": error, "timestamp": datetime.utcnow().isoformat() + "Z", **payload}
    try:
        with open(dlq_path, "a", encoding="utf-8") as f:
            f.write(_canonical_json(entry) + "\n")
        logger.warning(f"Audit record sent to DLQ: {dlq_path}")
    except Exception as e2:
        logger.error(f"DLQ write also failed: {e2} — record lost: {payload.get('tx_id')}")


async def _get_last_hash(session: AsyncSession) -> str:
    """Return the record_hash of the most recent audit record, or the genesis sentinel."""
    cfg = get_audit_cfg()
    sentinel = cfg.get("genesis_sentinel", "0" * 64)
    result = await session.execute(
        select(AuditRecord.record_hash).order_by(AuditRecord.id.desc()).limit(1)
    )
    row = result.scalar_one_or_none()
    return row if row else sentinel


async def append_decided(
    session: AsyncSession,
    *,
    tx_id: str,
    payment_id: str,
    amount: float,
    p_fraud: float,
    action: str,
    escalate: bool,
    reasons: list[str],
    layer_verdicts: dict[str, str],
    feature_vector_hash: str,
    model_version: str,
    config_hash: str,
    shadow_mode: bool,
) -> AuditRecord:
    """
    Append a DECIDED record. Must be called BEFORE any Razorpay action.
    Returns the created record.
    """
    previous_hash = await _get_last_hash(session)
    now = datetime.utcnow()

    fields: dict[str, Any] = {
        "record_type": "DECIDED",
        "tx_id": tx_id,
        "payment_id": payment_id,
        "timestamp": now.isoformat() + "Z",
        "amount": amount,
        "p_fraud": round(p_fraud, 6),
        "action": action,
        "escalate": escalate,
        "reasons": reasons,
        "layer_verdicts": layer_verdicts,
        "feature_vector_hash": feature_vector_hash,
        "model_version": model_version,
        "config_hash": config_hash,
        "shadow_mode": shadow_mode,
        "previous_log_hash": previous_hash,
    }

    record_hash = _compute_record_hash(fields)
    fields["record_hash"] = record_hash

    record = AuditRecord(
        record_type="DECIDED",
        tx_id=tx_id,
        payment_id=payment_id,
        timestamp=now,
        amount=amount,
        p_fraud=p_fraud,
        action=action,
        escalate=escalate,
        reasons=json.dumps(reasons),
        layer_verdicts=json.dumps(layer_verdicts),
        feature_vector_hash=feature_vector_hash,
        model_version=model_version,
        config_hash=config_hash,
        shadow_mode=shadow_mode,
        previous_log_hash=previous_hash,
        record_hash=record_hash,
    )

    try:
        session.add(record)
        await session.flush()
        await session.refresh(record)
        logger.info(f"Audit DECIDED: tx={tx_id[:12]}... action={action} p={p_fraud:.3f}")
        return record
    except Exception as e:
        logger.error(f"Audit store failed for DECIDED tx={tx_id}: {e}")
        _to_dlq(fields, str(e))
        # Fail open — return a dummy record so the payment path continues
        record.id = -1
        return record


async def append_action_result(
    session: AsyncSession,
    *,
    tx_id: str,
    payment_id: str,
    action_status: str,
    razorpay_response: dict | None,
) -> AuditRecord:
    """
    Append an ACTION_RESULT record. Called AFTER the Razorpay call completes.
    """
    previous_hash = await _get_last_hash(session)
    now = datetime.utcnow()

    fields: dict[str, Any] = {
        "record_type": "ACTION_RESULT",
        "tx_id": tx_id,
        "payment_id": payment_id,
        "timestamp": now.isoformat() + "Z",
        "action_status": action_status,
        "razorpay_response": razorpay_response or {},
        "previous_log_hash": previous_hash,
    }

    record_hash = _compute_record_hash(fields)
    fields["record_hash"] = record_hash

    record = AuditRecord(
        record_type="ACTION_RESULT",
        tx_id=tx_id,
        payment_id=payment_id,
        timestamp=now,
        action_status=action_status,
        razorpay_response=json.dumps(razorpay_response or {}),
        previous_log_hash=previous_hash,
        record_hash=record_hash,
    )

    try:
        session.add(record)
        await session.flush()
        await session.refresh(record)
        logger.info(f"Audit ACTION_RESULT: tx={tx_id[:12]}... status={action_status}")
        return record
    except Exception as e:
        logger.error(f"Audit store failed for ACTION_RESULT tx={tx_id}: {e}")
        _to_dlq(fields, str(e))
        record.id = -1
        return record


async def get_all_records(session: AsyncSession) -> list[dict]:
    """Return all audit records ordered by id, with computed verification status."""
    result = await session.execute(
        select(AuditRecord).order_by(AuditRecord.id.asc())
    )
    records = result.scalars().all()

    output = []
    prev_hash = get_audit_cfg().get("genesis_sentinel", "0" * 64)

    for rec in records:
        # Reconstruct the canonical fields to re-verify the hash
        if rec.record_type == "DECIDED":
            fields = {
                "record_type": rec.record_type,
                "tx_id": rec.tx_id,
                "payment_id": rec.payment_id,
                "timestamp": rec.timestamp.isoformat() + "Z",
                "amount": rec.amount,
                "p_fraud": round(rec.p_fraud, 6) if rec.p_fraud is not None else None,
                "action": rec.action,
                "escalate": rec.escalate,
                "reasons": json.loads(rec.reasons) if rec.reasons else [],
                "layer_verdicts": json.loads(rec.layer_verdicts) if rec.layer_verdicts else {},
                "feature_vector_hash": rec.feature_vector_hash,
                "model_version": rec.model_version,
                "config_hash": rec.config_hash,
                "shadow_mode": rec.shadow_mode,
                "previous_log_hash": rec.previous_log_hash,
            }
        else:
            fields = {
                "record_type": rec.record_type,
                "tx_id": rec.tx_id,
                "payment_id": rec.payment_id,
                "timestamp": rec.timestamp.isoformat() + "Z",
                "action_status": rec.action_status,
                "razorpay_response": json.loads(rec.razorpay_response) if rec.razorpay_response else {},
                "previous_log_hash": rec.previous_log_hash,
            }

        expected_hash = _compute_record_hash(fields)
        chain_valid = (
            rec.record_hash == expected_hash and
            rec.previous_log_hash == prev_hash
        )

        output.append({
            "id": rec.id,
            **fields,
            "record_hash": rec.record_hash,
            "hash_valid": chain_valid,       # False → tampered, UI turns row red
            "expected_hash": expected_hash,  # for debugging only
        })

        prev_hash = rec.record_hash

    return output


async def get_stats(session: AsyncSession) -> dict:
    """Return summary stats for the dashboard cost counter."""
    result = await session.execute(
        select(
            func.count(AuditRecord.id).label("total"),
            func.sum(
                func.cast(AuditRecord.action == "HOLD", Integer) * AuditRecord.amount
            ).label("fraud_paused"),
        ).where(AuditRecord.record_type == "DECIDED")
    )
    row = result.one_or_none()
    return {
        "total_decisions": row.total if row else 0,
        "fraud_paused_inr": float(row.fraud_paused or 0),
        "false_declines": 0,   # by design: we never hard-decline
    }
