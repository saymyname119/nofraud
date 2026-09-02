import hmac
import hashlib
import json
import time
import urllib.request
import urllib.error
import random

WEBHOOK_SECRET = "test_secret_123"
URL = "http://localhost:8000/api/v1/webhooks/razorpay"

def generate_payload():
    tx_id = f"pay_{int(time.time())}{random.randint(100,999)}"
    amount = random.choice([50000, 150000, 4000000, 12000000]) # Amounts in paise
    email = random.choice(["legit@example.com", "fraudster99@yopmail.com", "test@company.com"])
    
    payload = {
        "entity": "event",
        "account_id": "acc_TestAccount01",
        "event": "payment.authorized",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": tx_id,
                    "entity": "payment",
                    "amount": amount,
                    "currency": "INR",
                    "status": "authorized",
                    "order_id": f"order_{int(time.time())}",
                    "international": False,
                    "method": random.choice(["card", "upi"]),
                    "captured": False,
                    "email": email,
                    "contact": f"+9198765{random.randint(10000,99999)}",
                    "created_at": int(time.time())
                }
            }
        },
        "created_at": int(time.time())
    }
    return json.dumps(payload, separators=(',', ':'))

def simulate():
    body = generate_payload().encode('utf-8')
    signature = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    
    req = urllib.request.Request(URL, data=body, headers={
        "Content-Type": "application/json",
        "x-razorpay-signature": signature
    }, method="POST")
    
    print(f"Sending webhook to {URL}...")
    try:
        with urllib.request.urlopen(req) as response:
            print(f"Status: {response.getcode()}")
            print(f"Response: {response.read().decode()}")
    except urllib.error.URLError as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    for _ in range(5):
        simulate()
        time.sleep(1.5)
