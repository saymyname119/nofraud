"""
tests/test_velocity.py

Tests for the SQLite velocity feature store (app/velocity.py).
Also tests idempotency purge_expired from app/idempotency.py.

Covers:
  - compute_velocity returns zeros on empty DB
  - record_transaction persists a row and velocity counts update correctly
  - Window exclusion: old transactions outside 5-min window are not counted
  - amount_vs_avg is calculated correctly
  - purge_expired removes stale idempotency entries
"""
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.velocity import compute_velocity, record_transaction
from app.idempotency import check_cache, store_decision, purge_expired
from app.audit.models import VelocityRecord, DecisionCache
from tests.conftest import TestingSessionLocal


# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_payment(email="test@example.com", amount_paise=10000, card_last4="1234"):
    return {
        "id": "pay_test",
        "amount": amount_paise,
        "currency": "INR",
        "email": email,
        "contact": "9999999999",
        "method": "card",
        "card": {"last4": card_last4},
    }


# ── compute_velocity ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compute_velocity_empty_db(db_session: AsyncSession):
    """All velocity counts must be zero on an empty database."""
    payment = make_payment()
    vel = await compute_velocity(db_session, payment)

    assert vel["count_tx_5min"] == 0.0
    assert vel["count_tx_1hr"] == 0.0
    assert vel["count_tx_24hr"] == 0.0
    assert vel["count_card_5min"] == 0.0
    assert vel["count_card_1hr"] == 0.0
    assert vel["unique_emails_card"] == 0.0
    assert vel["unique_cards_email"] == 0.0
    # days_since_last is -1 when no prior transaction
    assert vel["days_since_last"] == -1.0
    assert vel["days_since_first"] == -1.0


@pytest.mark.asyncio
async def test_velocity_counts_after_record(db_session: AsyncSession):
    """After recording a transaction, velocity counts for that email/card must increment."""
    payment = make_payment()

    # Record the payment into the velocity store
    await record_transaction(db_session, payment, tx_id="fs_test001")
    await db_session.commit()

    # Now compute velocity for a second transaction from the same email
    vel = await compute_velocity(db_session, payment)

    assert vel["count_tx_5min"] >= 1.0
    assert vel["count_tx_1hr"] >= 1.0
    assert vel["count_tx_24hr"] >= 1.0
    assert vel["count_card_5min"] >= 1.0


@pytest.mark.asyncio
async def test_velocity_window_exclusion(db_session: AsyncSession):
    """Transactions older than the 5-min window must NOT count in count_tx_5min."""
    email = "old@example.com"

    # Insert a velocity record 10 minutes in the past
    old_ts = datetime.now(timezone.utc) - timedelta(minutes=10)
    # VelocityRecord.timestamp is naive in the model; strip tzinfo to match DB
    old_record = VelocityRecord(
        email=email,
        card_last4="9999",
        amount=100.0,
        tx_id="fs_old001",
        timestamp=old_ts.replace(tzinfo=None),
    )
    db_session.add(old_record)
    await db_session.commit()

    payment = make_payment(email=email, card_last4="9999")
    vel = await compute_velocity(db_session, payment)

    # 5-min window should be 0 (old record is outside)
    assert vel["count_tx_5min"] == 0.0
    # 1-hr and 24-hr should include it
    assert vel["count_tx_1hr"] >= 1.0


@pytest.mark.asyncio
async def test_amount_vs_avg_ratio(db_session: AsyncSession):
    """amount_vs_avg must be ratio of current amount to historical average."""
    email = "ratio@example.com"

    # Record a past transaction at 100 INR
    past = VelocityRecord(email=email, card_last4=None, amount=100.0, tx_id="fs_ratio001")
    db_session.add(past)
    await db_session.commit()

    # Score a new transaction at 500 INR → ratio = 500/100 = 5.0
    payment = make_payment(email=email, amount_paise=50000)
    vel = await compute_velocity(db_session, payment)

    assert vel["amount_vs_avg"] == pytest.approx(5.0, rel=0.01)


@pytest.mark.asyncio
async def test_days_since_last_populated(db_session: AsyncSession):
    """days_since_last must be a small positive float after a past transaction."""
    email = "delta@example.com"
    past_ts = datetime.now(timezone.utc) - timedelta(hours=2)
    rec = VelocityRecord(
        email=email, card_last4=None, amount=50.0, tx_id="fs_delta001",
        timestamp=past_ts.replace(tzinfo=None),
    )
    db_session.add(rec)
    await db_session.commit()

    payment = make_payment(email=email)
    vel = await compute_velocity(db_session, payment)

    # ~2 hours = ~0.083 days
    assert 0.05 < vel["days_since_last"] < 0.5


# ── purge_expired (idempotency) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_purge_expired_removes_stale_entries(db_session: AsyncSession):
    """purge_expired must delete entries older than the TTL and leave fresh ones."""
    from unittest.mock import patch

    # Insert one fresh and one stale DecisionCache entry directly
    fresh = DecisionCache(
        payload_hash="sha256:fresh",
        tx_id="fs_fresh",
        payment_id="pay_fresh",
        action="CAPTURE",
        p_fraud=0.01,
        reasons="[]",
    )
    stale = DecisionCache(
        payload_hash="sha256:stale",
        tx_id="fs_stale",
        payment_id="pay_stale",
        action="HOLD",
        p_fraud=0.9,
        reasons="[]",
        # Back-date creation to 2 minutes ago
        created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=2),
    )
    db_session.add_all([fresh, stale])
    await db_session.commit()

    # Purge with a 60-second TTL; stale entry (120 s old) should be removed
    with patch("app.idempotency.get_idempotency_cfg", return_value={"ttl_seconds": 60}):
        deleted = await purge_expired(db_session)
        await db_session.commit()

    assert deleted >= 1

    # Verify fresh entry survives
    result = await db_session.execute(
        select(DecisionCache).where(DecisionCache.payload_hash == "sha256:fresh")
    )
    assert result.scalar_one_or_none() is not None

    # Verify stale entry is gone
    result2 = await db_session.execute(
        select(DecisionCache).where(DecisionCache.payload_hash == "sha256:stale")
    )
    assert result2.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_payload_hash_is_order_independent(db_session: AsyncSession):
    """Two dicts with the same keys in different order must produce the same hash."""
    from app.idempotency import _payload_hash
    p1 = {"id": "pay_1", "amount": 1000, "email": "a@b.com"}
    p2 = {"email": "a@b.com", "id": "pay_1", "amount": 1000}
    assert _payload_hash(p1) == _payload_hash(p2)
