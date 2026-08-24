import pytest
import hmac
import hashlib
import json
from httpx import AsyncClient
from unittest.mock import patch
from app.config import get_settings

def sign_payload(payload: dict) -> str:
    secret = get_settings().razorpay_webhook_secret.encode()
    body = json.dumps(payload).encode()
    return hmac.new(secret, body, hashlib.sha256).hexdigest()

@pytest.mark.asyncio
async def test_missing_signature(client: AsyncClient):
    payload = {"event": "payment.authorized", "payload": {"payment": {"entity": {"id": "pay_123"}}}}
    response = await client.post("/api/v1/webhooks/razorpay", content=json.dumps(payload).encode())
    assert response.status_code == 400
    assert response.json() == {"detail": "Missing signature"}

@pytest.mark.asyncio
async def test_invalid_signature(client: AsyncClient):
    payload = {"event": "payment.authorized", "payload": {"payment": {"entity": {"id": "pay_123"}}}}
    headers = {"x-razorpay-signature": "bad_sig"}
    response = await client.post("/api/v1/webhooks/razorpay", content=json.dumps(payload).encode(), headers=headers)
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid signature"}

@pytest.mark.asyncio
async def test_idempotency_caching(client: AsyncClient):
    with patch("app.action.action_handler.capture_payment") as mock_capture:
        mock_capture.return_value = {"status": "captured"}
        payload = {
            "event": "payment.authorized",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_TESTIDEM",
                        "amount": 50000,
                        "currency": "INR",
                        "email": "test@example.com",
                        "contact": "9999999999",
                        "method": "card"
                    }
                }
            }
        }
        
        headers = {"x-razorpay-signature": sign_payload(payload)}
        
        # First call
        response1 = await client.post("/api/v1/webhooks/razorpay", content=json.dumps(payload).encode(), headers=headers)
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["status"] == "ok"
        tx_id_1 = data1["tx_id"]
        
        # Second call (exact same payload) should return the cached tx_id
        response2 = await client.post("/api/v1/webhooks/razorpay", content=json.dumps(payload).encode(), headers=headers)
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["status"] == "ok"
        assert data2["tx_id"] == tx_id_1  # Must be identically the same transaction ID
