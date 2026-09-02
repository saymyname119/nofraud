import pytest
import json
from httpx import AsyncClient
from unittest.mock import patch
from tests.test_webhooks import sign_payload


@pytest.mark.asyncio
async def test_dashboard_endpoints(client: AsyncClient):
    # Process a webhook first to populate records
    with patch("app.action.action_handler.capture_payment") as mock_capture:
        mock_capture.return_value = {"status": "captured"}
        payload = {
            "event": "payment.authorized",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_DASHBOARD1",
                        "amount": 250000,
                        "currency": "INR",
                        "email": "user@example.com",
                        "contact": "9876543210",
                        "method": "card",
                    }
                }
            },
        }
        headers = {"x-razorpay-signature": sign_payload(payload)}
        resp = await client.post("/api/v1/webhooks/razorpay", content=json.dumps(payload).encode(), headers=headers)
        assert resp.status_code == 200

    # Test /api/v1/dashboard/payments
    payments_resp = await client.get("/api/v1/dashboard/payments")
    assert payments_resp.status_code == 200
    payments_data = payments_resp.json()
    assert "payments" in payments_data
    assert len(payments_data["payments"]) >= 1
    assert payments_data["payments"][0]["payment_id"] == "pay_DASHBOARD1"

    # Test /api/v1/dashboard/audit
    audit_resp = await client.get("/api/v1/dashboard/audit")
    assert audit_resp.status_code == 200
    audit_data = audit_resp.json()
    assert "logs" in audit_data
    assert len(audit_data["logs"]) >= 2  # DECIDED + ACTION_RESULT

    # Test /api/v1/dashboard/stats
    stats_resp = await client.get("/api/v1/dashboard/stats")
    assert stats_resp.status_code == 200
    stats_data = stats_resp.json()
    assert stats_data["total_decisions"] >= 1
    assert stats_data["total_volume"] >= 2500.0
