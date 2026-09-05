# FraudSpike — Real-Time Payment Fraud Defense on Razorpay

FraudSpike turns Razorpay's `authorize → capture` window into a smart, reversible fraud checkpoint. It scores every payment in real time (~200 ms) and only captures the funds if it is safe.

Genuine customers never get falsely declined, and fraud gets held before money ever settles.

---

## 💡 How It Works

```text
Customer Pays → Razorpay Authorizes (Funds reserved, NOT captured)
                          │
                          ▼ Webhook: payment.authorized
                 FraudSpike Scoring API (~200ms)
                          │
        ┌─────────────────┼─────────────────┐
     LOW risk          MEDIUM risk       HIGH risk
     CAPTURE             VERIFY            HOLD
  (Settle funds)    (Step-up link sent)  (Do not capture → auto-refunds)
```

1. **Reversible Hold**: Orders use Razorpay's delayed capture (`payment_capture = 0`). The money is reserved, but not settled.
2. **Real-time Explainable AI**: Combines an **XGBoost classifier** (trained on IEEE-CIS) with an **Isolation Forest anomaly signal**, calibrated using isotonic regression. Every score includes top human-readable **SHAP reason codes**.
3. **Amount-Aware Thresholds**: A ₹100 payment needs near-certainty to pause; a ₹50,000 payment faces stricter scrutiny.
4. **Tamper-Evident Audit Trail**: Every decision is logged into an append-only SHA-256 hash chain.
5. **Live Merchant Dashboard**: Real-time event streaming (SSE) showing transactions, reason breakdowns, and audit integrity.

---

## 🚀 Quickstart

### Prerequisites
- Python 3.10+
- Node.js 18+ (for frontend dashboard)
- Docker (optional, for containerized run)

### Option 1: Docker (Recommended)

Run both the API and dashboard with a single command:

```bash
# Clone the repository
git clone https://github.com/saymyname119/nofraud.git
cd nofraud

# Run with Docker Compose
docker compose up --build
```
- API & Swagger docs: `http://localhost:8000/docs`
- Live Dashboard: `http://localhost:8000`

---

### Option 2: Local Development

#### 1. Setup Backend
```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate       # On Linux/macOS
# or: .\.venv\Scripts\activate  # On Windows

# Install dependencies
pip install -r requirements.txt

# Create .env from template
cp .env.example .env

# Run FastAPI backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

#### 2. Setup Dashboard
In a separate terminal:
```bash
cd dashboard
npm install
npm run dev
```
Open `http://localhost:5173` in your browser.

---

## 🧪 Testing the Live Simulation

You can test the entire pipeline end-to-end (scoring, actions, dashboard events, and audit logs) without a real payment card:

```bash
python scripts/seed_demo.py
```

This triggers 3 representative scenarios:
- **₹499 Normal Payment:** Safe transaction → Auto-captured (`CAPTURE`).
- **₹45,000 High-Value:** Unusual amount/device pattern → Step-up link generated (`VERIFY`).
- **3× Rapid ₹80,000 Payments:** Disposable email & velocity burst → Paused (`HOLD`).

Watch the dashboard at `http://localhost:5173` update in real time.

---

## ⚙️ Configuration

Key tunables live in [`config.yaml`](config.yaml):

| Key | Description | Default |
|---|---|---|
| `razorpay.mock_mode` | Simulate Razorpay API responses without real keys | `true` |
| `shadow_mode` | Score and log decisions without executing adverse actions | `false` |
| `thresholds.amount_buckets` | Amount-tiered risk cutoffs | Configured |
| `circuit_breaker.hold_rate_threshold` | Max hold percentage before fail-open safety trips | `0.05` (5%) |
| `velocity.max_tx_5min` | Velocity limit for single customer within 5-minute window | `5` |

---

## 🔗 Razorpay Webhook Setup (Live Test Mode)

To connect live Razorpay test-mode payments:

1. Expose your local port:
   ```bash
   ngrok http 8000
   ```
2. In **Razorpay Dashboard → Settings → Webhooks**:
   - **Webhook URL:** `https://<your-ngrok-domain>/api/v1/webhooks/razorpay`
   - **Secret:** Enter matching `RAZORPAY_WEBHOOK_SECRET` from `.env`.
   - **Active Events:** Select `payment.authorized`.
3. In `config.yaml`, set `razorpay.mock_mode: false` and set your keys in `.env`.

---

## 📁 Repository Structure

```text
nofraud/
├── app/
│   ├── action/          # Razorpay API client & action routing (Capture/Verify/Hold)
│   ├── api/             # Webhook listeners & dashboard REST/SSE endpoints
│   ├── audit/           # Tamper-evident SHA-256 hash-chain ledger
│   ├── decision/        # Policy layers, circuit breaker & cost matrix engine
│   ├── scoring/         # ML feature builder, model inference & SHAP reason mapping
│   ├── config.py        # Settings loader
│   ├── database.py      # SQLite / PostgreSQL async session manager
│   └── main.py          # FastAPI application factory
├── dashboard/           # React + Vite live merchant dashboard
├── ml/
│   ├── train.py         # Offline training pipeline (XGBoost + Isolation Forest)
│   ├── evaluate.py      # Cost matrix sweep & threshold evaluation
│   └── artifact/        # Pretrained model weights & SHAP baseline
├── scripts/
│   └── seed_demo.py     # Staged demo transaction generator
├── tests/               # Automated test suite (pytest)
├── Dockerfile           # Multi-stage production container build
├── docker-compose.yml   # Production compose service
└── config.yaml          # System thresholds & operational config
```

---

## 🛡️ Running Automated Tests

```bash
pytest tests/
```
All 10 integration and unit tests validate:
- Webhook signature security and idempotency replay.
- Policy and circuit breaker fail-safe behaviors.
- SHA-256 hash-chain verification and tamper detection.
