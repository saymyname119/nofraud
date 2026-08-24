"""
ml/evaluate.py — Expected-cost sweep and threshold derivation.

Spec §6.5: Run over the held-out test set to:
  1. Derive amount-bucket thresholds that minimise expected cost
     (rather than guessing them by hand)
  2. Compare three baselines: allow-everything, fixed-threshold, amount-aware model
  3. Write the winning threshold table back to config.yaml (the GENERATED section)

Usage:
    python ml/evaluate.py              # derives thresholds and writes to config.yaml
    python ml/evaluate.py --no-update  # print results without modifying config.yaml

The threshold table written here is what the demo §5 table is based on.
Spec §6.5: "Present the ₹100→0.95 / ₹2,000→0.5 / ₹50,000→0.08 table as the
OUTPUT of this sweep, not an assumption."
"""
from __future__ import annotations

import argparse
import json
import logging
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import yaml

from app.scoring.features import CATEGORICAL_COLUMNS, FEATURE_COLUMNS, FEAT_AMOUNT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ARTIFACT_DIR = ROOT / "ml" / "artifact"
CONFIG_PATH = ROOT / "config.yaml"
DATASET_DIR = ROOT / "ieee-fraud-detection"

# Amount buckets to evaluate thresholds for (₹ values)
AMOUNT_BUCKET_MAXES = [500, 5000, float("inf")]


def load_artifact():
    artifact_path = ARTIFACT_DIR / "model.pkl"
    if not artifact_path.exists():
        raise FileNotFoundError(f"Run python ml/train.py first — artifact not found at {artifact_path}")
    with open(artifact_path, "rb") as f:
        return pickle.load(f)


def get_test_predictions(artifact: dict, fast: bool = True) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Reload the test split of IEEE-CIS, run inference, return (p_fraud, y_true, amounts).
    Uses the same time-split logic as train.py.
    """
    from ml.train import load_data, build_features, time_split

    df = load_data(fast=fast)
    y = df["isFraud"].astype(int)
    X, _ = build_features(df)  # encoders from artifact, not re-fitted
    _, _, _, _, X_test, y_test = time_split(df, X, y)

    xgb = artifact["xgb"]
    iso = artifact["iso"]
    calibrator = artifact["calibrator"]

    numeric_cols = [c for c in FEATURE_COLUMNS if c not in CATEGORICAL_COLUMNS]

    xgb_raw = xgb.predict_proba(X_test)[:, 1]
    iso_scores = iso.score_samples(X_test[numeric_cols].values)
    iso_norm = np.clip((-iso_scores) / 0.7, 0.0, 1.0)
    blended = 0.75 * xgb_raw + 0.25 * iso_norm
    p_fraud = calibrator.predict(blended)

    amounts = X_test[FEAT_AMOUNT].values
    return p_fraud, y_test.values, amounts


def expected_cost_scalar(p: float, amount: float, hold: bool, cost_params: dict) -> float:
    """Expected cost for one transaction given action (hold vs allow)."""
    L = amount * (1 - cost_params["recovery_rate"])
    F = cost_params["friction_cost"]
    c = cost_params["review_cost"]
    h = cost_params["hold_efficacy"]
    if hold:
        # Cost of holding: some fraud still slips through, plus friction and review cost
        return p * (1 - h) * L + (1 - p) * F + c
    else:
        # Cost of allowing: expected fraud loss
        return p * L


def sweep_threshold_for_bucket(
    p_fraud: np.ndarray,
    y_true: np.ndarray,
    amounts: np.ndarray,
    max_amount: float,
    cost_params: dict,
    n_thresholds: int = 50,
) -> float:
    """
    Sweep thresholds ∈ [0,1] for transactions in this amount bucket.
    Pick the threshold that minimises total expected cost on the validation set.
    """
    mask = amounts <= max_amount
    if mask.sum() == 0:
        return 0.5  # fallback

    p_bucket = p_fraud[mask]
    amounts_bucket = amounts[mask]

    thresholds = np.linspace(0.01, 0.99, n_thresholds)
    best_thresh = 0.5
    best_cost = float("inf")

    for thresh in thresholds:
        holds = p_bucket >= thresh
        total_cost = sum(
            expected_cost_scalar(float(p), float(a), bool(h), cost_params)
            for p, a, h in zip(p_bucket, amounts_bucket, holds)
        )
        if total_cost < best_cost:
            best_cost = total_cost
            best_thresh = float(thresh)

    return round(best_thresh, 3)


def run_sweep(artifact: dict, fast: bool) -> list[dict]:
    """
    Run the cost sweep for each amount bucket.
    Returns the threshold table as a list of dicts (matching config.yaml format).
    """
    logger.info("Loading test data for threshold sweep...")
    p_fraud, y_true, amounts = get_test_predictions(artifact, fast=fast)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cost_params = cfg["cost_params"]

    logger.info(f"Running cost sweep on {len(p_fraud):,} test transactions...")

    thresholds = []
    prev_max = 0.0

    for i, max_amt in enumerate(AMOUNT_BUCKET_MAXES):
        # Mask to this bucket (> prev_max, <= max_amt)
        bucket_mask = (amounts > prev_max) & (
            amounts <= max_amt if max_amt != float("inf") else np.ones(len(amounts), dtype=bool)
        )

        if bucket_mask.sum() < 10:
            logger.warning(f"Bucket max={max_amt}: only {bucket_mask.sum()} samples, using default")
            thresh = 0.5
        else:
            thresh = sweep_threshold_for_bucket(
                p_fraud[bucket_mask], y_true[bucket_mask], amounts[bucket_mask],
                max_amount=max_amt, cost_params=cost_params
            )

        label = f"₹{int(prev_max):,}–₹{int(max_amt):,}" if max_amt != float("inf") else f"₹{int(prev_max):,}+"
        logger.info(f"  Bucket {label}: optimal threshold = {thresh:.3f}")

        thresholds.append({
            "max_amount": max_amt,
            "min_fraud_prob": thresh,
        })
        prev_max = max_amt

    return thresholds


def compare_baselines(artifact: dict, thresholds: list[dict], fast: bool) -> None:
    """
    Spec §6.5: Compare allow-all, fixed-0.5, and amount-aware model.
    Log the ₹ difference (the slide that proves the model earns its keep).
    """
    p_fraud, y_true, amounts = get_test_predictions(artifact, fast=fast)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cost_params = cfg["cost_params"]

    def threshold_for_amount(amount: float) -> float:
        for bucket in thresholds:
            if amount <= bucket["max_amount"]:
                return bucket["min_fraud_prob"]
        return thresholds[-1]["min_fraud_prob"]

    cost_allow_all = sum(
        expected_cost_scalar(float(p), float(a), hold=False, cost_params=cost_params)
        for p, a in zip(p_fraud, amounts)
    )
    cost_fixed = sum(
        expected_cost_scalar(float(p), float(a), hold=(float(p) >= 0.5), cost_params=cost_params)
        for p, a in zip(p_fraud, amounts)
    )
    cost_aware = sum(
        expected_cost_scalar(float(p), float(a), hold=(float(p) >= threshold_for_amount(float(a))), cost_params=cost_params)
        for p, a in zip(p_fraud, amounts)
    )

    logger.info("=" * 60)
    logger.info("BUSINESS COST COMPARISON (on held-out test set)")
    logger.info(f"  Allow everything:     ₹{cost_allow_all:>12,.0f}")
    logger.info(f"  Fixed threshold 0.5:  ₹{cost_fixed:>12,.0f}  ({cost_allow_all-cost_fixed:+,.0f} vs allow-all)")
    logger.info(f"  Amount-aware model:   ₹{cost_aware:>12,.0f}  ({cost_allow_all-cost_aware:+,.0f} vs allow-all)")
    logger.info("=" * 60)


def update_config(thresholds: list[dict]) -> None:
    """Write the derived threshold table back to config.yaml (the GENERATED section)."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    cfg["thresholds"]["amount_buckets"] = thresholds

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    logger.info(f"config.yaml updated with derived thresholds")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast", action="store_true", help="Use 10%% data sample")
    parser.add_argument("--no-update", action="store_true", help="Don't write to config.yaml")
    args = parser.parse_args()

    artifact = load_artifact()
    thresholds = run_sweep(artifact, fast=args.fast)
    compare_baselines(artifact, thresholds, fast=args.fast)

    if not args.no_update:
        update_config(thresholds)
        logger.info("Run  uvicorn app.main:app --reload  to pick up the new thresholds")
    else:
        logger.info("--no-update: config.yaml NOT modified")


if __name__ == "__main__":
    main()
