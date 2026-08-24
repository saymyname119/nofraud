import pytest
from sqlalchemy import select
import json
from httpx import AsyncClient
from unittest.mock import patch
from app.audit.models import AuditRecord
from app.audit.log import _compute_record_hash
from tests.conftest import TestingSessionLocal
from tests.test_webhooks import sign_payload

@pytest.mark.asyncio
async def test_audit_hash_chain_integrity(client: AsyncClient):
    with patch("app.action.action_handler.capture_payment") as mock_capture:
        mock_capture.return_value = {"status": "captured"}
        # Simulate a few transactions to build the chain
        payloads = [
            {"event": "payment.authorized", "payload": {"payment": {"entity": {"id": f"pay_tx{i}", "amount": 1000 + i, "currency": "INR", "email": f"user{i}@example.com", "contact": "9999999999", "method": "card"}}}}
            for i in range(3)
        ]
        
        for payload in payloads:
            headers = {"x-razorpay-signature": sign_payload(payload)}
            response = await client.post("/api/v1/webhooks/razorpay", content=json.dumps(payload).encode(), headers=headers)
            assert response.status_code == 200, response.json()
        
        async with TestingSessionLocal() as session:
            result = await session.execute(select(AuditRecord).order_by(AuditRecord.id))
            records = result.scalars().all()
            
        assert len(records) > 0
        
        # Verify the chain
        previous_hash = "0" * 64
        for record in records:
            assert record.previous_log_hash == previous_hash, f"Broken chain at record {record.id}"
            
            # Build the dictionary of fields the same way it was inserted
            if record.record_type == "DECIDED":
                fields = {
                    "record_type": "DECIDED",
                    "tx_id": record.tx_id,
                    "payment_id": record.payment_id,
                    "timestamp": record.timestamp.isoformat() + "Z",
                    "amount": record.amount,
                    "p_fraud": round(record.p_fraud, 6) if record.p_fraud is not None else None,
                    "action": record.action,
                    "escalate": record.escalate,
                    "reasons": json.loads(record.reasons) if record.reasons else [],
                    "layer_verdicts": json.loads(record.layer_verdicts) if record.layer_verdicts else {},
                    "feature_vector_hash": record.feature_vector_hash,
                    "model_version": record.model_version,
                    "config_hash": record.config_hash,
                    "shadow_mode": record.shadow_mode,
                    "previous_log_hash": record.previous_log_hash,
                }
            else:
                fields = {
                    "record_type": "ACTION_RESULT",
                    "tx_id": record.tx_id,
                    "payment_id": record.payment_id,
                    "timestamp": record.timestamp.isoformat() + "Z",
                    "action_status": record.action_status,
                    "razorpay_response": json.loads(record.razorpay_response) if record.razorpay_response else None,
                    "previous_log_hash": record.previous_log_hash,
                }
            
            expected_hash = _compute_record_hash(fields)
            assert record.record_hash == expected_hash, f"Hash mismatch at record {record.id}"
            
            previous_hash = record.record_hash
