"""
app/audit/models.py — SQLAlchemy ORM models for the append-only audit log.

Spec §9.5 + §11 invariant #7:
  - Append-only: no UPDATE, no DELETE — enforced at the ORM layer
  - Each record has previous_log_hash + record_hash (SHA-256 hash chain)
  - Genesis row uses a 64-zero sentinel as previous_log_hash
  - record_hash computed over canonical JSON (sorted keys) of all other fields
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column, DateTime, Float, Integer, String, Text, Boolean,
    event, exc as sqlalchemy_exc,
)
from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    pass


class AuditRecord(Base):
    """
    Append-only audit log entry.

    Two record_types are written per transaction (spec §9.5):
      DECIDED — written BEFORE any Razorpay call
      ACTION_RESULT — written AFTER the Razorpay call completes
    """
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Record identity
    record_type = Column(String(20), nullable=False)      # DECIDED | ACTION_RESULT
    tx_id = Column(String(64), nullable=False, index=True) # internal FraudSpike ID
    payment_id = Column(String(64), nullable=True)         # Razorpay payment ID

    # Transaction data
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    amount = Column(Float, nullable=True)

    # Decision fields (populated on DECIDED records)
    p_fraud = Column(Float, nullable=True)
    action = Column(String(20), nullable=True)           # CAPTURE | VERIFY | HOLD
    escalate = Column(Boolean, nullable=True, default=False)
    reasons = Column(Text, nullable=True)                # JSON array of ReasonCode strings
    layer_verdicts = Column(Text, nullable=True)         # JSON dict of layer→verdict
    feature_vector_hash = Column(String(80), nullable=True)
    model_version = Column(String(64), nullable=True)
    config_hash = Column(String(80), nullable=True)
    shadow_mode = Column(Boolean, nullable=True, default=False)

    # Action result fields (populated on ACTION_RESULT records)
    action_status = Column(String(20), nullable=True)    # SUCCESS | FAILED | SKIPPED
    razorpay_response = Column(Text, nullable=True)      # JSON of raw Razorpay response

    # Hash chain (spec §9.5)
    previous_log_hash = Column(String(80), nullable=False)  # sha256:... of previous record
    record_hash = Column(String(80), nullable=False)         # sha256:... of this record's fields

    def __repr__(self) -> str:
        return f"<AuditRecord id={self.id} type={self.record_type} tx={self.tx_id[:8]}...>"


class DecisionCache(Base):
    """
    Short-lived idempotency cache (spec §11 invariant #8).
    Keyed on the canonical payload hash; TTL enforced in app code.
    Separate from the audit log to keep concerns clean.
    """
    __tablename__ = "decision_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    payload_hash = Column(String(80), nullable=False, unique=True, index=True)
    tx_id = Column(String(64), nullable=False)
    payment_id = Column(String(64), nullable=True)
    action = Column(String(20), nullable=False)
    p_fraud = Column(Float, nullable=False)
    reasons = Column(Text, nullable=False)      # JSON
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class VelocityRecord(Base):
    """
    Lightweight velocity store (SQLite-based MVP; swap to Redis for production).
    Records each scored transaction for window-count queries.
    """
    __tablename__ = "velocity"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(256), nullable=True, index=True)
    card_last4 = Column(String(8), nullable=True, index=True)
    amount = Column(Float, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    tx_id = Column(String(64), nullable=False)


# ── Append-only enforcement ───────────────────────────────────────────────────
# Raises an exception if anyone tries to UPDATE or DELETE from audit_log.
# This is the ORM-layer enforcement of the append-only invariant (spec §11 #7).

@event.listens_for(Session, "after_bulk_update")
def _block_audit_update(update_context):
    if update_context.mapper and update_context.mapper.class_ is AuditRecord:
        raise sqlalchemy_exc.InvalidRequestError(
            "AuditRecord is append-only. UPDATE operations are not permitted."
        )


@event.listens_for(Session, "after_bulk_delete")
def _block_audit_delete(delete_context):
    if delete_context.mapper and delete_context.mapper.class_ is AuditRecord:
        raise sqlalchemy_exc.InvalidRequestError(
            "AuditRecord is append-only. DELETE operations are not permitted."
        )
