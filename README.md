# FraudSpike — Real-Time Fraud Defense on Razorpay

**One line:** We turn Razorpay's authorize→capture window into a smart, reversible fraud checkpoint — scoring every payment in real time and only capturing the money if it's safe, so genuine customers never get blocked and fraud gets held before it settles.

**The pitch (30 seconds):** Most fraud systems either decline a payment (angry real customer) or let it through (fraud loss). Razorpay already gives merchants a third option almost nobody uses: **authorize now, capture later.** The money is reserved but not taken. FraudSpike scores each authorized payment in ~200 ms, then decides: **capture** (safe), **verify** (send a step-up link and capture only if the real owner confirms), or **let it lapse** (auto-refunds itself — a fraud loss that never happened). Every decision is explained and logged in a tamper-evident chain. No hard declines, ever.

> Built for [insert hackathon]. Razorpay **Test Mode** end to end — no real money moves. Team of 3–4, ~36 hours.

---

## 1. Why this wins

| Judges look for | What we show |
|---|---|
| **Real Razorpay integration** | Orders API, `payment.authorized` webhook, delayed **Capture** API, Payment Links for step-up, Refunds — the actual product surface, not a mock |
| **A non-obvious insight** | Manual capture = a free, built-in reversible hold. We didn't build a fraud "block," we built a fraud **pause** on infra Razorpay already ships |
| **Solves a real merchant pain** | False declines cost Indian merchants more than fraud does. Our whole design optimizes *money*, not model accuracy |
| **Live demo that works** | Three seeded payments (safe / suspicious / fraud) run through the real API and land in three different states on screen in under a minute |
| **Depth on tap** | A live risk score with **human-readable reasons** (SHAP), a **circuit breaker**, and a **hash-chained audit log** — see Appendix A for the full production design we scoped down from |

**The money argument (put this on a slide):** A false decline doesn't just lose one sale — it churns a customer worth many future sales. So FraudSpike never declines. Its worst automated action is a *pause you can undo with one tap.* That's the entire product philosophy in one sentence.

---

## 2. How it works

```
Customer pays
   │
   ▼
Razorpay Order (payment_capture = 0  ← manual capture: money authorized, NOT taken)
   │
   ▼   webhook: payment.authorized
FraudSpike Scoring API  ──►  risk score + top reasons (SHAP)
   │
   ├─ score LOW      →  CAPTURE now                    (money settles, customer happy)
   ├─ score MEDIUM   →  VERIFY: send Razorpay Payment  (step-up)
   │                     Link / OTP; capture on pass,
   │                     let it lapse on fail/timeout
   └─ score HIGH     →  HOLD: don't capture            (auto-refunds in N days → fraud averted)
   │
   ▼
Every decision → Hash-chained Audit Log → Merchant Dashboard (live)
```

**The core trick:** create the Razorpay Order with `payment_capture = 0`. The customer completes payment normally — Razorpay **authorizes** it and fires the `payment.authorized` webhook, but the funds are *not yet captured*. That handoff is our decision point. We call the **Capture API** only for payments we trust. Anything we don't capture **auto-refunds on its own** within Razorpay's authorization window — a fraud loss that reverses itself with zero manual work.

This is why we never need a "banking core," a custom hold ledger, or irreversible-action safeguards: **Razorpay's own capture window is the reversible action.**

---

## 3. Scope — what we build in 36 hours

### MVP (must demo)
1. **Merchant checkout** (Razorpay Checkout, test mode) creating manual-capture orders.
2. **Webhook receiver** for `payment.authorized` (with signature verification — free security points).
3. **Scoring service**: a calibrated XGBoost model (blended with an Isolation Forest anomaly signal) returning a true probability `p ∈ [0,1]` **plus the top 3 reasons** via SHAP, mapped to a fixed reason-code vocabulary — full design and training procedure in §6.
4. **Decision engine**: three actions — `CAPTURE` / `VERIFY` / `HOLD` — chosen by **amount-aware thresholds** (a ₹100 payment and a ₹50,000 payment do *not* get the same bar; see §5).
5. **Action layer**: calls Razorpay **Capture**, or generates a **Payment Link** for step-up, or does nothing (lets it lapse).
6. **Live dashboard**: incoming payments streaming in, their score, reasons, chosen action, and current state.
7. **Hash-chained audit log**: each decision record SHA-256-linked to the previous — one screen showing "edit any row → every later hash turns red."

### Stretch (if time allows, in priority order)
- **Circuit breaker**: if hold-rate spikes (broken model or a legit flash sale), stop auto-holding and alert — fail toward the customer.
- **Velocity features from Redis**: `count_tx_5min`, `amount_vs_avg` — makes the "spike" in FraudSpike real.
- **Step-up actually working**: the Payment Link verification round-trip captures the original payment on success.
- **Cost-savings counter**: a live "₹ fraud prevented / false declines avoided" tally — judges love a number that goes up.

### Explicitly cut (say this out loud — scoping is a skill judges score)
Sequence/LSTM model, graph features, Merkle anchoring, crypto-shredding, multi-region, off-policy label learning. All designed in Appendix A; none needed to prove the idea.

---

## 4. Razorpay integration map

| Feature | Razorpay API | Why |
|---|---|---|
| Reversible hold | **Orders** with `payment_capture: 0`, **Payments Capture** | The heart of the project — authorize, decide, capture-or-lapse |
| Real-time trigger | **Webhooks** (`payment.authorized`) + `X-Razorpay-Signature` verify | Score the moment money is authorized, not on a poll |
| Step-up verification | **Payment Links** (or Razorpay Checkout re-auth / OTP) | Let the real owner self-clear a medium-risk payment |
| Undo a hold | **Refunds** (or simply don't capture → auto-refund) | Proves "no irreversible action" |
| Payouts side (stretch) | **RazorpayX / Route** | Score the beneficiary side for mule/payout fraud |

All in **Test Mode** with test keys. Use Razorpay's test cards to generate authorized-but-uncaptured payments live on stage.

---

## 5. The one piece of real cleverness to demo

Don't use a single fraud threshold. **Blocking a ₹100 coffee needs near-certainty; pausing a ₹80,000 transfer needs almost none.** Decide by expected cost:

```
hold_is_worth_it  when  fraud_probability  >  friction_cost / (fraud_probability_helps × amount + friction_cost)
```

In plain terms: the risk bar to pause a payment **drops as the amount rises**. Small payments almost always sail through (protecting the customer experience); large ones face real scrutiny (protecting the merchant). Put this table on a slide — it's the moment a judge realizes you understand fraud economics, not just ML:

| Payment | Risk needed to pause |
|---|---|
| ₹100 | very high (~0.95) — friction isn't worth it |
| ₹2,000 | moderate (~0.5) |
| ₹50,000 | low (~0.08) — a real hold candidate |

One rule, three behaviors, all defensible on stage.

---

## 6. Model Architecture & Training

This is the part a technical judge will actually probe, so it needs to be more than "we used XGBoost." Three specific problems with a naive approach, and how this design avoids them:

1. A raw XGBoost score is a **margin, not a probability** — but §5's cost formula requires a true probability `p`. Skip calibration and the slide's math is invalid.
2. The obvious dataset choice (Kaggle's anonymized `V1..V28` credit-card fraud set) has **no human-readable features** — SHAP would explain a decision with "V14 = -3.2," which is useless on stage and undercuts the "human-readable reasons" pitch in §1.
3. Hand-picked thresholds (₹100→0.95, ₹50,000→0.08) look arbitrary to a judge who knows fraud modeling unless you show they were **derived from data**, not guessed.

### 6.1 Architecture

```
raw payment payload
      │
      ▼
deterministic pre-filter   (obvious allow: known-good repeat email+device; obvious deny-candidate: sanctioned/blocklisted card)
      │
      ▼
feature builder            (§6.2 — engineered, human-readable features only)
      │
      ├──► XGBoost classifier ──┐
      │                          ├─► blended raw score ──► isotonic calibration ──► calibrated p
      └──► Isolation Forest ────┘
                                                                   │
                                                                   ▼
                                                    SHAP TreeExplainer (on the XGBoost branch)
                                                                   │
                                                                   ▼
                                                fixed reason-code vocabulary (§6.6)
                                                                   │
                                                                   ▼
                                    expected-cost action selection (§5, using calibrated p)
```

**Why two model branches, not just XGBoost:** a supervised classifier is only as good as the fraud patterns present in its training labels. A hackathon's demo transactions and any live judge-driven payment are, almost by definition, *not* in that training distribution. Isolation Forest is unsupervised — it flags "this point doesn't look like anything else," which is exactly the fallback signal you want for a genuinely novel input on stage, and it doubles as the story for thin-file / first-time users (§A.4's cold-start problem) at near-zero implementation cost (`sklearn.ensemble.IsolationForest`, ~10 lines). Its output is folded in as one more feature into the final blend, not run as a separate veto path — keeps the decision surface to one calibrated number.

**Why calibrate:** wrap the trained booster with isotonic regression (`sklearn.isotonic.IsotonicRegression`, fit on a held-out calibration split — never the training or test fold) so the output is a genuine `P(fraud)`, not an arbitrary score range. This is what makes §5's formula load-bearing instead of decorative.

**Why a deterministic pre-filter in front of the model:** mirrors Appendix A's policy-layer-before-ML ordering, at hackathon scale. Cuts obvious cases (a card that's captured successfully 10 times already, a known test-fraud card number) before they burn a model call — cheap to build, and it's a legitimate architecture point ("policy first, ML second") rather than pure decoration.

### 6.2 Dataset

Use **IEEE-CIS Fraud Detection** (Kaggle), not the anonymized credit-card dataset. It has real, human-readable columns that map honestly onto what Razorpay's Checkout payload and a small transaction-history table can actually supply:

| IEEE-CIS field | Maps to (Razorpay-realistic) | Feeds |
|---|---|---|
| `TransactionAmt` | `payment.amount` | amount features (§5's cost driver) |
| `ProductCD`, `card4`, `card6` | payment method / card network / card type | "unusual method for this amount" reasons |
| `P_emaildomain` | customer email domain from Checkout prefill | `NEW_EMAIL_DOMAIN` / `DISPOSABLE_EMAIL` reason |
| `DeviceType`, `DeviceInfo` | Checkout user-agent / device fingerprint | `NEW_DEVICE` reason |
| `C1`–`C14` (count features) | self-computed velocity counts (same account/card/email seen N times) | the actual "spike" in FraudSpike |
| `D1`–`D15` (time-delta features) | time since last transaction / account age proxy | thin-file vs established-account behavior |

Drop everything else (hundreds of sparse anonymized `V*` columns) — they'd reintroduce the same explainability problem the dataset was chosen to avoid. Fewer, honest, human-readable features beat more, unexplainable ones for this specific pitch.

**Split by time, not randomly.** IEEE-CIS carries a `TransactionDT` (relative timestamp). Train on the earliest ~70%, validate on the next ~15%, test on the final ~15%. A random k-fold split leaks information from near-duplicate or linked transactions across train/test and will report an offline score you will not see live — call this out explicitly if asked; it's a mistake many teams make under time pressure and catching it is a credibility signal.

### 6.3 Class imbalance

IEEE-CIS is ~3.5% fraud — imbalanced but workable. Use XGBoost's `scale_pos_weight = (#negative / #positive)` rather than naive random oversampling or SMOTE: SMOTE on tabular fraud data interpolates between real fraud points and can fabricate implausible synthetic transactions, and combined with a careless random split it's a common source of leaked, overstated offline metrics. If time permits, treat SMOTE as an experiment to *compare against* on the validation set, not a default.

### 6.4 Training procedure

- **Model:** `XGBClassifier`, `max_depth` 3–6, `learning_rate` 0.03–0.1, `n_estimators` up to ~300 with early stopping on validation PR-AUC, `subsample`/`colsample_bytree` ~0.7–0.9. Small random search over this grid, not a manual guess-and-check.
- **Isolation Forest:** `n_estimators=100`, `contamination` set near the known fraud prevalence, fit on the numeric amount/time/velocity features only (unsupervised — never sees the label).
- **Calibration:** isotonic regression on the held-out calibration split (distinct from train/validation/test), applied on top of the blended score.
- **Artifact:** pickle the calibrated model + Isolation Forest + a version string; the scoring service loads it once at startup. No live training, no online learning — a static, versioned artifact is the right scope here (full lifecycle/registry concerns are Appendix A.14).

### 6.5 Evaluation — tied to the business metric, not just ML habit

Standard ML metrics still get reported (PR-AUC, recall at fixed FPR, Brier score / reliability curve for calibration quality — the last one matters *because* §5 depends on calibration being real). But the metric that actually proves the model is worth demoing is the **same expected-cost formula from §5, run over the held-out test set**:

- Compute total expected cost for: (a) allow-everything baseline, (b) a single fixed-threshold baseline (the naive version of §5), (c) this model with amount-aware, cost-derived thresholds.
- Report the ₹ difference. This is the one slide that proves the model isn't just accurate — it's *net cheaper for the merchant*, which is the entire thesis of the project.

**Derive §5's thresholds from this evaluation, not by hand.** For each amount bucket, sweep the threshold on the calibrated `p` and pick the value that minimizes expected cost on the validation set; freeze the resulting curve into `config.yaml`. The ₹100→0.95 / ₹2,000→0.5 / ₹50,000→0.08 table in §5 should be presented as the *output* of this sweep, not an assumption — that distinction is what separates a demo from a defensible result.

### 6.6 Reason-code mapping

Map SHAP's top contributing features to a small, fixed, demo-safe vocabulary — never surface raw feature names or thresholds to a customer-facing string (an internal fraud team can see the raw SHAP values; a customer or a curious fraudster should not):

| Dominant SHAP driver | Reason code | Customer-safe text |
|---|---|---|
| `C1`–`C14` velocity features | `VELOCITY_HIGH` | "Unusual number of recent transactions" |
| `TransactionAmt` vs account average | `AMOUNT_ANOMALY` | "Amount unusual for this account" |
| `DeviceType`/`DeviceInfo` mismatch | `NEW_DEVICE` | "Payment from an unrecognized device" |
| `P_emaildomain` novelty | `NEW_EMAIL_DOMAIN` | "New or unusual email domain" |
| `D1`–`D15` short time-since-last | `RAPID_REPEAT` | "Rapid repeat activity on this account" |
| Isolation Forest branch dominant | `NOVEL_PATTERN` | "Doesn't match typical activity" |

Cache global SHAP feature importance once at training time too — it's the "why the model works, in general" slide, distinct from "why *this* transaction scored the way it did."

### 6.7 Demo-data engineering

Design the three seeded demo transactions to each trip **one dominant, unambiguous reason code** — a clean outlier on one or two dimensions, not borderline on all of them. A transaction that's simultaneously a bit odd on five dimensions produces a SHAP explanation that reads as noise on stage and a score that can wobble slightly between runs. Picking clean, single-cause examples is a legitimate part of "model architecture for a demo," not cheating — it's the same reason real fraud-ops teams keep curated test cases for any model change.

---

## 7. Tech stack

- **Backend:** Python + **FastAPI** (async webhooks, fast to write). `razorpay` Python SDK.
- **ML:** XGBoost + Isolation Forest (`scikit-learn`) + isotonic calibration + SHAP (`TreeExplainer`) — see §6 for the full architecture and training procedure. Train offline on IEEE-CIS; ship the pickled artifact, don't train live.
- **State:** SQLite for the audit log and decisions (zero-setup); Redis only if you attempt velocity features.
- **Frontend:** React + a chart lib for the live dashboard. Server-Sent Events or polling — skip WebSockets unless you have spare time.
- **Tunnel:** `ngrok` to expose the webhook endpoint to Razorpay during the demo.
- **Config:** one `config.yaml` for thresholds and cost params — never hard-code them (and it lets you tune live if the demo misbehaves).

---

## 8. Module Architecture (planned)

**This is a design plan, not the filesystem.** No source files exist yet — nothing under the tree below should be created until the build actually starts.

```text
fraudspike/
├── pyproject.toml
├── config.yaml                  # every tunable — see §10; no magic numbers in code
├── .env.example
├── app/
│   ├── main.py                  # FastAPI app factory
│   ├── webhook.py               # /webhook — payment.authorized handler
│   ├── scoring/
│   │   ├── pipeline.py          # PURE: features → inference → calibration → reasons
│   │   ├── features.py          # feature builder (§6.2 mapping) — shared with ml/train.py
│   │   ├── model.py             # loads pickled artifact; score() → (p, shap_top3)
│   │   └── reason_codes.py      # SHAP driver → fixed vocabulary (all 6 codes, §6.6)
│   ├── decision/
│   │   ├── engine.py            # OWNS all policy; layer order per §9.2
│   │   ├── cost.py              # expected-cost selection (§5, §A.7); reads config
│   │   └── circuit_breaker.py   # health governor + floor policy (§9.4)
│   ├── action/
│   │   ├── razorpay_client.py   # ONLY module that touches the Razorpay API
│   │   └── action_handler.py    # routes CAPTURE / VERIFY / HOLD
│   ├── audit/
│   │   ├── log.py               # append-only hash chain (SHA-256, canonical JSON)
│   │   └── models.py            # SQLAlchemy models; previous_log_hash + record_hash
│   └── idempotency.py           # 60s cache keyed on canonical payload hash
├── ml/
│   ├── train.py                 # IEEE-CIS → time split → XGB + IsoForest → calibrate → pickle
│   ├── evaluate.py              # expected-cost sweep (§6.5); emits threshold table → config.yaml
│   └── artifact/                # gitignored: model.pkl + version.json + global_shap.json
├── dashboard/
│   └── src/
│       ├── components/
│       │   ├── PaymentTable.tsx  # score bar, reason chips, action badge
│       │   ├── AuditLog.tsx      # hash chain; tamper → downstream rows turn red
│       │   └── CostCounter.tsx   # ₹ paused / 0 declined
│       └── api.ts               # SSE client + polling fallback
├── scripts/
│   └── seed_demo.py             # the three staged demo payments (§14)
└── tests/                       # see §12
```

### 8.1 Layer boundaries

| Rule | Why |
|---|---|
| `action/razorpay_client.py` is the only module that calls Razorpay | Keeps external side effects in one auditable place; decision and scoring layers stay pure and unit-testable without network mocks |
| `scoring/` contains no policy and no side effects | Policy cannot live inside the ML module if the ordering rule is "policy first, ML second" (§9.2). Scoring maps features to a probability and reasons — nothing else |
| `decision/engine.py` owns every policy layer | One place to read the precedence order; also lets the engine skip the model call entirely on an allowlist or blocklist hit |
| `audit/` is never called from `scoring/` or `decision/` | The journal is written by the orchestration layer at two fixed points (§9.5), not opportunistically mid-pipeline |
| `features.py` constants are imported by `ml/train.py` | One feature spec for train and serve. If the two ever diverge, training-serving skew is silently live in production (§11) |

### 8.2 Request flow

This deliberately fixes an act-then-log ordering flaw — journal precedes the side effect:

```text
POST /webhook
  │
  ├─ verify X-Razorpay-Signature ────────► reject 400 if invalid
  │
  ├─ idempotency check (canonical payload hash)
  │     └─ hit ──► replay stored decision's CURRENT state, do not re-score
  │
  ├─ decision.engine.decide(payload)
  │     ├─ 1. compliance gate      (list-driven; may short-circuit)
  │     ├─ 2. blocklist            (may short-circuit)
  │     ├─ 3. allowlist            (may short-circuit to CAPTURE — skips the model)
  │     ├─ 4. circuit breaker      (if OPEN: skip ML, floor policy already ran above)
  │     ├─ 5. scoring.pipeline     (only reached if no layer above resolved it)
  │     ├─ 6. cost.select_action(p, amount)
  │     └─ 7. safety governor      (shadow_mode suppresses the directive, keeps the log)
  │
  ├─ journal  DECIDED        ◄── durable BEFORE any money moves
  ├─ action.handler.execute()     (idempotent Razorpay call)
  ├─ journal  ACTION_RESULT
  └─ push SSE event → dashboard
```

A DECIDED record with no ACTION_RESULT is a detectable, reconcilable state, whereas acting before logging can leave a captured payment with no audit trail at all.

---

## 9. Component Contracts & Data Model

### 9.1 Scoring contract

`score()` always returns the probability and its reasons together as one value; a caller cannot obtain a score without reasons. Design sketch — a type signature, not implementation:

```python
@dataclass(frozen=True)
class ScoringResult:
    p: float                      # calibrated P(fraud) ∈ [0,1] — see §6.1
    reasons: list[ReasonCode]     # from the fixed §6.6 vocabulary, never raw feature names
    feature_vector_hash: str      # so the explanation can be recomputed and defended later
    model_version: str
```

### 9.2 Decision engine layer order

| # | Layer | Resolves to | Notes |
|---|---|---|---|
| 1 | Compliance gate | HOLD + escalate | Sanctions/watchlist. List-driven and deterministic — never a model output (§1 carve-out) |
| 2 | Blocklist | HOLD | Confirmed-compromised card/device identifiers |
| 3 | Allowlist | CAPTURE | Repeat known-good email+device; skips the model call entirely |
| 4 | Circuit breaker | CAPTURE (ML bypassed) | Layers 1–2 already ran, so screening never fully stops (§9.4) |
| 5 | ML action selection | CAPTURE / VERIFY / HOLD | `cost.select_action(p, amount)` — §5 |
| 6 | Safety governor | suppresses directive only | `shadow_mode`: score and log, take no action |

Every layer's verdict is recorded on the decision record, so "which layer decided this?" is always answerable.

### 9.3 Action set

The MVP uses three actions — CAPTURE / VERIFY / HOLD. Appendix A.1's six-rung ladder collapses onto them for the hackathon: `ALLOW`→CAPTURE, `STEP_UP`→VERIFY, `HOLD_FULL`→HOLD, and `HOLD_AND_ESCALATE`→HOLD with an `escalate=true` flag rather than a separate action. HOLD is passive — it means "do not call Capture," so the authorization lapses and auto-refunds on its own.

### 9.4 Circuit breaker — what survives when it trips

When the breaker is OPEN it bypasses the ML action selection, but layers 1 and 2 have already run, so compliance screening and the confirmed-fraud blocklist stay active. This matters because a breaker that sets literally every transaction to PASS is attacker-triggerable — flood obvious fraud, force the hold rate up, walk through the open door (§A.3, §A.8). Keeping the floor policy is what makes the breaker safe to ship.

Required guards:

- A minimum sample size (5% of 20 transactions is one transaction).
- Hysteresis so the breaker does not oscillate at the boundary.
- Breaker state recorded on every decision.

The full production design (§A.8) goes further and triggers on model-health signals rather than hold rate alone.

### 9.5 Audit record & two-phase journal

```json
{
  "record_type": "DECIDED",
  "tx_id": "fs_01H...",
  "payment_id": "pay_29QQoUBi66xm2f",
  "timestamp": "2026-08-22T11:04:12.338Z",
  "amount": 45000.00,
  "p_fraud": 0.61,
  "action": "VERIFY",
  "escalate": false,
  "reasons": ["NEW_DEVICE", "AMOUNT_ANOMALY"],
  "layer_verdicts": {"compliance": "PASS", "blocklist": "PASS", "allowlist": "NO_MATCH", "breaker": "CLOSED"},
  "feature_vector_hash": "sha256:9ab2...",
  "model_version": "xgb+iso-2026.08.1",
  "config_hash": "sha256:c41d...",
  "shadow_mode": false,
  "previous_log_hash": "sha256:f6e5...",
  "record_hash": "sha256:1f0c..."
}
```

`record_hash` is computed over every field except itself, using canonical JSON (sorted keys, no insignificant whitespace) so the hash is reproducible — non-deterministic serialization would silently break verification later. The genesis row uses a sixty-four-zero sentinel as `previous_log_hash`. An `ACTION_RESULT` record references the DECIDED row's `tx_id` and carries the Razorpay response body and status. The table is append-only: no UPDATE, no DELETE, enforced at the ORM layer rather than by convention. On store failure the write falls to a local `audit_dlq.jsonl` and the payment proceeds — availability of the payment path outranks completeness of the ledger in the moment (§A.9 replaces this local file with a replicated log for production, because a local queue on an ephemeral host is data loss).

Idempotency replay note: a replayed decision must return the action's CURRENT resolved state, not blindly re-assert the original directive — a redelivery hours later must not re-place a hold that review or a step-up has already cleared.

---

## 10. Configuration Surface

Every threshold, window, and toggle lives in `config.yaml`; nothing is inlined at a call site, so the demo can be retuned without a redeploy.

```yaml
# GENERATED SECTION — produced by ml/evaluate.py (§6.5). Do not hand-edit.
thresholds:
  amount_buckets:
    - max_amount: 500
      min_fraud_prob: 0.95
    - max_amount: 5000
      min_fraud_prob: 0.50
    - max_amount: .inf
      min_fraud_prob: 0.08

cost_params:            # drive BOTH the online rule and offline evaluation
  friction_cost: 50     # F — cost of holding a legitimate payment
  review_cost: 5        # c — per-hold human review labour
  hold_efficacy: 0.90   # h — P(hold actually prevents the loss)
  recovery_rate: 0.70   # card rail; lower for irreversible rails

circuit_breaker:
  hold_rate_window_seconds: 300
  hold_rate_threshold: 0.05
  minimum_sample: 20         # below this, the rate is statistical noise
  floor_policy_always_on: true

idempotency:
  ttl_seconds: 60

shadow_mode: false           # score and log, suppress the action directive
```

(a) The threshold table is an OUTPUT of the §6.5 cost sweep, committed as a generated artifact — the numbers shown are placeholders until that sweep runs. (b) The same `cost_params` are read by both `decision/cost.py` and `ml/evaluate.py`, so the model is evaluated against the identical objective it optimizes online, rather than an eval script scoring a policy it does not control. `config_hash` is recorded on every decision record (§9.5), so a decision can be replayed against the exact config that produced it.

---

## 11. Architecture Invariants

These are load-bearing constraints rather than preferences; if an implementation choice would violate one, stop and surface the conflict instead of quietly working around it.

1. **No hard declines.** The worst automated action is a hold that expires on its own. One carve-out: sanctions/watchlist screening is a legal obligation, so it is deterministic, list-driven, and lives in layer 1 — any hard block must be traceable to a list entry and never to a model output.
2. **The cost asymmetry is computed, not assumed.** A false positive is usually costlier than a small fraud loss, but not always: the break-even probability is a function of amount and rail (§5, §A.7). Never hard-code a single global threshold, and never invert the sign of the cost model by treating recall as the objective.
3. **Reasons travel with the score.** `score()` returns the probability and its reason codes as one indivisible value. A code path that can produce an actionable score without reasons is a defect, because the audit log, the reviewer dashboard, and the customer-facing message all depend on them.
4. **Customer-facing text comes from the sanitized vocabulary.** Never emit a raw feature name, SHAP value, or threshold to anything a customer or an attacker can read — a verbatim internal reason hands over the detection boundary.
5. **The circuit breaker keeps a floor.** When OPEN it bypasses ML action selection only; compliance and blocklist layers still run. Never implement a state in which all screening stops, and never trip on transaction volume alone (§9.4).
6. **Journal before you act.** Append DECIDED durably, perform the idempotent action, then append ACTION_RESULT. Acting first can leave money moved with no audit record.
7. **The ledger is append-only.** No UPDATE, no DELETE, enforced in code. On store failure, fail open to the DLQ and let the payment proceed.
8. **Idempotency replays, it does not re-score.** And a replay reflects the action's current resolved state, not the original directive.
9. **Shadow mode is a config flag, not a code fork.** The scoring path and the action path stay separable enough that suppressing actions never requires a second branch of the pipeline.
10. **One feature spec for train and serve.** `app/scoring/features.py` and `ml/train.py` share the same constants. Divergence here is training-serving skew, which reports a good offline number while failing live.

**Deliberately out of scope for the MVP:** the sequence/LSTM model, graph and beneficiary features, Merkle anchoring and external attestation, crypto-shredding, exploration holdout and off-policy label learning. All are designed in Appendix A. Because there is no second model in the MVP, there is no 200 ms sequence-model race and no availability-regime split — and §A.2/§A.5 supersede fixed per-stage timeouts with a single propagated deadline anyway, so the MVP simply scores synchronously inside Razorpay's authorization window, where the budget is seconds rather than milliseconds.

---

## 12. Test Strategy (planned)

The tests worth writing are the ones that pin the invariants in §11; everything else is secondary for a 36-hour build.

| Test file | Asserts |
|---|---|
| `test_webhook.py` | Valid signature passes; tampered or absent signature returns 400 and is never scored; a duplicate payload replays the stored decision instead of re-scoring |
| `test_scoring.py` | Calibrated `p` always lands in [0,1]; every returned reason code belongs to the fixed §6.6 vocabulary; no customer-facing string contains a raw feature name |
| `test_decision.py` | Layer precedence holds — a blocklist hit resolves without invoking the model; high `p` on a large amount yields HOLD while low `p` on a small amount yields CAPTURE; with the breaker OPEN the ML path is bypassed **but a compliance-gate hit still resolves to HOLD** (the floor policy, §9.4) |
| `test_audit.py` | Editing any historical row invalidates that row's hash and every subsequent `previous_log_hash` link; the genesis row uses the zero sentinel; an UPDATE or DELETE against the table raises |
| `test_idempotency.py` | Identical canonical payload within the TTL returns the cached decision; a differing payload scores fresh; an expired entry re-scores |
| `test_cost.py` | The break-even threshold decreases monotonically as amount rises; bucket boundaries are read from config rather than hard-coded |

The Razorpay client is mocked at its module boundary so no test performs a real HTTP call.

---

## 13. Build plan (36-hour sprint)

| Block | Goal | Owner |
|---|---|---|
| H0–H4 | Razorpay test account, keys, manual-capture Order, Checkout page taking a test payment | Backend |
| H0–H4 | Load IEEE-CIS, build the feature set in §6.2, time-based split | ML |
| H4–H10 | Webhook receiver with signature verification; wire `payment.authorized` → `/score` → decision | Backend |
| H4–H10 | Dashboard skeleton: table of payments, states, scores | Frontend |
| H4–H10 | Train XGBoost + Isolation Forest, calibrate, evaluate expected cost vs baselines (§6.4–6.5) | ML |
| H10–H18 | Capture / Payment-Link / hold action layer working against the real API | Backend + ML |
| H10–H18 | Derive amount-bucket thresholds from the cost sweep (§6.5) into `config.yaml`; wire reason-code mapping (§6.6) | ML |
| H18–H26 | Hash-chained audit log + the "tamper turns it red" screen | Backend + Frontend |
| H18–H26 | Dashboard polish: reasons, live updates, the cost-savings counter | Frontend |
| H26–H32 | Stretch: circuit breaker OR working step-up round-trip (pick one) | Team |
| H32–H36 | **Demo script, seed data, rehearse 3× on the real ngrok URL, record a backup video** | Team |

**Rule:** the demo must run on the real Razorpay test API end to end by H26. Everything after is polish. Record a backup video the moment it works — live demos die on conference WiFi.

---

## 14. Demo script (3 minutes)

1. **Frame it (20s):** "False declines cost merchants more than fraud. We never decline. Watch." Show the dashboard, empty.
2. **Safe payment (30s):** pay ₹499 with a normal test card → webhook fires → score 0.08, reasons shown → **auto-captured** → row goes green. "Customer never felt a thing."
3. **Suspicious payment (40s):** pay ₹45,000, odd pattern → score 0.6 → **VERIFY** → a Razorpay Payment Link appears → click it, confirm → original payment **captured**. "The real owner cleared it in one tap. A fraudster couldn't."
4. **Fraud spike (40s):** fire 3 rapid high-value payments → velocity reasons light up → **HELD** (not captured) → "these auto-refund themselves; the merchant loses nothing and did zero work."
5. **The mic drop (30s):** open the audit log, edit one historical amount → **every subsequent hash turns red.** "Tamper-evident by construction — an auditor can trust this."
6. **Close (20s):** the cost-savings counter: "₹X in fraud paused, 0 customers declined. Built entirely on Razorpay's own capture window."

---

## 15. What to say when a judge pushes

- *"Is the ML real?"* — Yes: XGBoost + Isolation Forest, calibrated, trained on IEEE-CIS with a time-based split and `scale_pos_weight` for imbalance (§6). We evaluate with the same expected-cost formula that drives production decisions, against an allow-everything and a fixed-threshold baseline, and derive §5's thresholds from that sweep rather than hand-picking them. But the **product** insight is the reversible-capture flow; the model is swappable.
- *"What about latency?"* — We decide inside the authorization window, so we have seconds, not milliseconds. Appendix A covers the 200 ms path for a full streaming build.
- *"Scale?"* — Webhook-driven and stateless per payment; the model is a pickled artifact behind an API. Appendix A has the sharded/streaming design.
- *"What did you cut?"* — (Show §3's cut list.) "We designed the full platform" — point at Appendix A — "and shipped the 20% that proves it."

---

## 16. Setup

```bash
# 1. Razorpay test keys → .env
RAZORPAY_KEY_ID=rzp_test_xxx
RAZORPAY_KEY_SECRET=xxx
RAZORPAY_WEBHOOK_SECRET=xxx

# 2. Backend
pip install -r requirements.txt        # fastapi, razorpay, xgboost, scikit-learn, shap, uvicorn
uvicorn app.main:app --reload

# 3. Expose webhook to Razorpay
ngrok http 8000
# → paste the https URL + /webhook into Razorpay Dashboard → Webhooks, subscribe to payment.authorized

# 4. Frontend
cd dashboard && npm install && npm run dev
```

> Everything runs in Razorpay **Test Mode**. Use Razorpay test cards to create authorized payments. No real funds move.

---

## Appendix A — Full production architecture (what we scoped down from)

The sections below are the enterprise-grade design. **None of it is required for the hackathon MVP** — it's here to show the depth behind the scoped build, and it's the roadmap if this becomes a real product. Judges: skim §A.7 (expected-cost decisioning) and §A.9 (ledger integrity) for the ideas we distilled into the demo.

<details>
<summary><b>Expand full v2 architecture (streaming pipeline, dual-model inference, segmented circuit breakers, Merkle-anchored ledger, feedback loop, threat model)</b></summary>

### A.1 Philosophy
Cheapest reversible action, chosen by computed expected cost rather than a fixed threshold. Cost depends on amount, rail recoverability, and customer tenure. Six-rung action ladder: `ALLOW → ALLOW_AND_MONITOR → STEP_UP → HOLD_PARTIAL → HOLD_FULL → HOLD_AND_ESCALATE`. Sanctions/OFAC screening is the one mandated hard-block, deterministic and outside the ML surface.

### A.2 Principles
Deadlines propagate (stages check remaining budget, not private timeouts); every decision reproducible (model/policy/config versions + feature-vector hash on the record); journal before acting; one feature spec for train and serve; deterministic policy layer separate from ML; degrade in rungs; assume the adversary reads the design; bound holds by review capacity.

### A.3 Threat model
Breaker-tripping DoS, threshold probing, retry attacks, bust-out/history farming, mule-side concentration, insider ledger tampering, feedback-loop poisoning, model extraction, PII exposure — each with a mitigation. (The hackathon build addresses retry/idempotency and the circuit breaker; the rest is roadmap.)

### A.4 Ingestion & feature platform
Schema registry with explicit failure policy; shared idempotency store (not in-memory) keyed by canonical payload hash; exactly-once *effects* via journal-then-commit; event-time windows. Feature registry: one declarative spec → both streaming job and point-in-time-correct backfill, with CI parity tests and production skew monitoring. Online store (Redis) has a fetch deadline and a degraded intrinsic-feature model; absence is encoded explicitly, never zero-imputed. Feature families: velocity/dispersion, sequence, graph/entity, beneficiary-side, thin-file handling.

### A.5 Inference
XGBoost (score + SHAP + vector hash) and a sequence model. The sequence model's embedding is maintained **asynchronously** and cached, so the hot path is one incremental step, not a 20-step pass — timeouts become rare. Absolute deadline propagation; optional work (sequence → graph → SHAP depth) shed under budget pressure. Every actioning path must carry reasons (SHAP for classic; exemplars + surrogate for sequence). Internal vs customer-safe reason vocabularies.

### A.6 Decision engine — layer order
Compliance gates → blocklists → allowlists → ML action selection → safety governor. Each layer's verdict recorded.

### A.7 Expected-cost action selection *(distilled into demo §5)*
Calibrate each model to a probability, combine in log-odds with a DL-missing indicator and per-regime thresholds, then pick the action minimizing expected cost:
```
C(ALLOW)   = p·L
C(STEP_UP) = p·(1−s)·L + (1−p)·F_step + c_step
C(HOLD)    = p·(1−h)·L + (1−p)·F + c
HOLD beats ALLOW when  p > (F + c) / (h·L + F)
```
`L = amount·(1−recovery) + fees + ops`. The threshold is a function of amount and rail, not a constant — a single fixed threshold is simultaneously too aggressive on small card payments and far too permissive on large irreversible transfers.

### A.8 Safety systems
Segmented, health-signal-driven circuit breakers (score/calibration drift, feature nulls — never volume alone), graduated response down to a floor policy that never disables protection, seasonality-aware baselines, hysteresis, minimum sample gates. Hold budget bounded by human-review capacity. Separate overload ladder that sheds optional work; every shed rung logged.

### A.9 Journal, action, ledger *(distilled into demo §14)*
Journal `DECIDED` → act idempotently → journal `ACTION_RESULT`; offsets commit after the journal write. Ledger: per-shard hash chains + periodic Merkle aggregation, roots signed by an HSM/KMS key and anchored to external WORM/transparency-log/timestamp-authority — because a self-referential chain is forgeable by anyone with DB write access. Canonical serialization (RFC 8785). Continuous verifier. PII in per-subject encrypted envelopes; erasure via crypto-shredding so hashes still verify.

### A.10 Human review & feedback loop
Queue prioritized by expected value of review; SLA tied to hold expiry; reviewer quality controls. Randomized exploration holdout + propensity logging + off-policy evaluation + label vintage/maturity — otherwise the loop learns only from transactions it held and quietly collapses.

### A.11 Evaluation
Expected-cost curves using the *same* parameters as the online rule; LTV/resolution-aware FP cost, recovery-adjusted FN cost, per-hold review labor; PR-AUC in the low-FPR band; calibration (ECE); per-segment reporting; fairness/parity monitoring; vintage backtests; deploy gate.

### A.12 Decision record
Includes schema/seq_no, model+policy+config versions, calibrated scores, availability regime, expected-cost breakdown, reason codes + SHAP, safety/breaker state, propensity, per-stage latency, PII envelope hash, previous hash, shard id.

### A.13 Config & change safety
Versioned, schema-validated, bounds-checked, canaried config with auto-rollback; hash recorded on every decision. A bad threshold push is the likeliest cause of a mass-hold incident.

### A.14 MLOps & reliability
Registry with lineage; shadow mode; champion/challenger + canary; tracing on `tx_id`; SLOs and burn-rate alerts; no silent truncation; active-active regions; chaos + red-team drills; parity tests as a deploy gate.

</details>
