# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This repository currently contains **design documentation only** — `README.md` is the sole tracked-intent file. There is no source code, no dependency manifest, no test suite, and no build tooling. The git repository has no commits yet (branch `master`, untracked `.idea/` and `README.md`).

Consequences for working here:

- There are no build, lint, or test commands to run. Do not invent them or claim to have run them.
- The directory tree in `README.md` §3 (`/fraudspike/...`) is a **plan**, not the filesystem. None of those files exist.
- Implementing any part of this system means bootstrapping the project scaffolding (dependency manifest, test runner, `config.yaml`) as part of that work. Confirm language/tooling choices with the user before creating them — the README implies Python (Pydantic, XGBoost, SHAP, TreeExplainer), but the IDE module is configured as a generic `JAVA_MODULE` with no SDK, so nothing is actually pinned.

## What the system is

A Fraud-Spike Detection System: a streaming pipeline that scores live financial transactions for anomalies, velocity spikes, and sequential fraud patterns. `README.md` is the authoritative spec — read it in full before implementing any module.

## Architecture invariants

These are the design decisions that span multiple planned modules. Preserve them; they are the point of the system, and violating one silently breaks its regulatory and product guarantees.

**Safe Reversible Action.** The system never issues hard declines or irreversible bans automatically. The only automated adverse action is a temporary hold (e.g. 24h) that buys time for human review. Any code path that can permanently deny a customer is a design violation.

**False positives are expensive on purpose.** Blocking a legitimate customer is treated as costlier than a small fraud loss (LTV/churn). This drives the evaluation approach: standard F1/AUC are considered insufficient, and models are judged by a business cost matrix that assigns a flat cash penalty to each false positive (`/evaluation/cost_matrix.py`), minimizing net financial loss rather than maximizing recall.

**Two models, one SLA.** A classic interpretable model (XGBoost) and a sequence model (LSTM/Transformer) run concurrently on the same transaction. The decision engine waits at most **200 ms** for the sequence model; on timeout it discards that score and decides on the classic model alone rather than letting the payment queue back up. The timeout is a hard latency budget, not a retry point.

**Explainability is a return value, not a side channel.** The classic model returns a score *plus* the top contributing features via SHAP `TreeExplainer`. Downstream consumers (audit log, human review dashboard) depend on these reasons being present, so scores must not be plumbed through without them.

**Circuit breaker fails toward the customer.** A rolling hold rate above ~5% of traffic over 5 minutes trips the breaker — which then defaults every transaction to `PASS` and alerts engineers. This deliberately accepts fraud exposure to avoid a system-wide customer freeze caused by a broken model or a legitimate traffic spike (e.g. Black Friday). The breaker state is recorded on every decision.

**The audit log is a hash chain.** Each decision record embeds `previous_log_hash` and is hashed with SHA-256, so editing any historical record invalidates every subsequent hash. Records are append-only. See `README.md` §4 for the exact payload shape (`tx_id`, `timestamp`, `decision`, `scores`, `explainability`, `circuit_breaker`, `action_status`, `previous_log_hash`).

**Fail-open on ledger loss.** If the audit log store is unavailable, the transaction is allowed to proceed and the log payload goes to a local dead-letter queue for later reconciliation. Availability of the payment path outranks completeness of the ledger in the moment; the DLQ is what makes that recoverable.

**Idempotency at ingestion.** A 60-second idempotency cache in the ingestion layer recognizes repeated identical requests (the "retry attack") and replays the prior decision instead of re-running inference. Hold-placement API calls to the banking core are likewise idempotent.

**Shadow Mode.** New models can be deployed to score transactions and write to the audit log while `hold_manager.py` ignores their directives, so production accuracy can be measured without touching customer funds. This is a `config.yaml` toggle — keep the scoring path and the action path separable enough that it stays a config flag rather than a code fork.

## Layering

Data flows one direction: ingestion/validation → feature store (Redis) → parallel inference → decision engine → action + audit log → human review, whose manual resolution labels feed back as training data. Thresholds, SLA limits, and feature toggles belong in `config.yaml`, not inlined at call sites. `/action` is intended to be the only layer with external side effects (banking core API); keep gateway calls out of the decision and inference layers.

See `README.md` §5 for the intended per-stage latency budget of a single transaction, and §6 for the edge cases the design commits to handling.
