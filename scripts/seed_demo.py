"""
scripts/seed_demo.py — Staged demo transactions for live demonstration.

Simulates the 3 scenarios described in README §14:
  1. Safe payment: ₹499 with known customer -> CAPTURE (score < 0.1)
  2. Suspicious payment: ₹45,000 on new device -> VERIFY (step-up link generated)
  3. Fraud spike: 3 rapid ₹80,000 payments on disposable email -> HOLD (auto-lapses)

Usage:
    python scripts/seed_demo.py [--url http://localhost:8000]
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
import urllib.request
import uuid


def sign_payload(payload: dict, secret: str) -> str:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def send_webhook(base_url: str, payload: dict, secret: str = "dummy_secret_for_local_dev"):
    endpoint = f"{base_url.rstrip('/')}/api/v1/webhooks/razorpay"
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = sign_payload(payload, secret)

    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": signature,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode("utf-8")
            return response.status, json.loads(res_body)
    except urllib.error.HTTPError as e:
        res_body = e.read().decode("utf-8")
        return e.code, res_body
    except Exception as e:
        return 500, str(e)


def main():
    parser = argparse.ArgumentParser(description="Seed FraudSpike demo transactions")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL of FraudSpike API")
    parser.add_argument("--secret", default="dummy_secret_for_local_dev", help="Webhook secret")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print(" 🚀 FraudSpike Live Demo Scenario Runner")
    print("=" * 60)

    # 1. Safe payment
    print("\n[Scenario 1] Submitting SAFE payment: ₹499 (Low risk, auto-capture)...")
    safe_pay_id = f"pay_safe_{uuid.uuid4().hex[:8]}"
    safe_payload = {
        "event": "payment.authorized",
        "payload": {
            "payment": {
                "entity": {
                    "id": safe_pay_id,
                    "amount": 49900,  # ₹499.00
                    "currency": "INR",
                    "status": "authorized",
                    "order_id": f"order_{uuid.uuid4().hex[:8]}",
                    "email": "priya.sharma@gmail.com",
                    "contact": "+919876543210",
                    "method": "card",
                    "card": {
                        "id": "card_safe1",
                        "network": "Visa",
                        "type": "debit",
                        "last4": "4242",
                    },
                }
            }
        },
    }
    status, res = send_webhook(args.url, safe_payload, args.secret)
    print(f"  → Status: {status}, Response: {res}")

    time.sleep(1)

    # 2. Suspicious payment
    print("\n[Scenario 2] Submitting SUSPICIOUS payment: ₹45,000 (Medium risk, step-up verify)...")
    susp_pay_id = f"pay_susp_{uuid.uuid4().hex[:8]}"
    susp_payload = {
        "event": "payment.authorized",
        "payload": {
            "payment": {
                "entity": {
                    "id": susp_pay_id,
                    "amount": 4500000,  # ₹45,000.00
                    "currency": "INR",
                    "status": "authorized",
                    "order_id": f"order_{uuid.uuid4().hex[:8]}",
                    "email": "new_shopper_99@tempmail.com",
                    "contact": "+919123456780",
                    "method": "card",
                    "card": {
                        "id": "card_susp1",
                        "network": "MasterCard",
                        "type": "credit",
                        "last4": "8888",
                    },
                }
            }
        },
    }
    status, res = send_webhook(args.url, susp_payload, args.secret)
    print(f"  → Status: {status}, Response: {res}")

    time.sleep(1)

    # 3. Fraud spike
    print("\n[Scenario 3] Submitting FRAUD SPIKE: 3 rapid ₹80,000 payments on disposable email...")
    for i in range(1, 4):
        fraud_pay_id = f"pay_fraud_{uuid.uuid4().hex[:8]}"
        fraud_payload = {
            "event": "payment.authorized",
            "payload": {
                "payment": {
                    "entity": {
                        "id": fraud_pay_id,
                        "amount": 8000000,  # ₹80,000.00
                        "currency": "INR",
                        "status": "authorized",
                        "order_id": f"order_{uuid.uuid4().hex[:8]}",
                        "email": "scam.bot@mailinator.com",
                        "contact": "+919999999999",
                        "method": "card",
                        "card": {
                            "id": "card_fraud1",
                            "network": "Visa",
                            "type": "credit",
                            "last4": "1111",
                        },
                    }
                }
            },
        }
        status, res = send_webhook(args.url, fraud_payload, args.secret)
        print(f"  → Tx #{i}: Status: {status}, Response: {res}")
        time.sleep(0.3)

    print("\n" + "=" * 60)
    print(" ✅ All demo scenarios dispatched successfully!")
    print(" Check your live dashboard at http://localhost:5173 to view scores, reasons, and hash chains.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
