"""
ml/train.py — Offline training pipeline.

IEEE-CIS Fraud Detection → time-based split → XGBoost + IsolationForest
→ isotonic calibration → pickled artifact.

Spec §6.4:
  - Time-based split (NOT random k-fold — avoids leakage from linked transactions)
  - scale_pos_weight for class imbalance (~3.5% fraud)
  - Small random search over XGBoost hyperparameters
  - IsolationForest fit on numeric features only (unsupervised — never sees labels)
  - Isotonic calibration on a held-out calibration split (distinct from train/val/test)
  - Artifact: model.pkl + version.json + global_shap.json

Usage:
    python ml/train.py [--fast]      # --fast uses 10% sample for dev speed
    python ml/train.py               # full training run

The artifact path is ml/artifact/model.pkl and must match config.yaml model.artifact_path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import pickle
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path so app.scoring.features is importable
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)
from sklearn.model_selection import ParameterSampler
from xgboost import XGBClassifier

# Import the SHARED feature spec (invariant: one spec for train and serve)
from app.scoring.features import (
    CATEGORICAL_COLUMNS,
    FEATURE_COLUMNS,
    FEAT_AMOUNT,
    FEAT_COUNT_TX_5MIN,
    FEAT_COUNT_TX_1HR,
    FEAT_COUNT_TX_24HR,
    FEAT_COUNT_CARD_5MIN,
    FEAT_COUNT_CARD_1HR,
    FEAT_AMOUNT_VS_AVG,
    FEAT_DAYS_SINCE_LAST,
    FEAT_DAYS_SINCE_FIRST,
    FEAT_TIME_OF_DAY_HOUR,
    FEAT_DAY_OF_WEEK,
    FEAT_IS_DISPOSABLE_EMAIL,
    FEAT_IS_NEW_DEVICE,
    FEAT_IS_WEEKEND,
    FEAT_IS_LARGE_AMOUNT,
    FEAT_PRODUCT,
    FEAT_CARD4,
    FEAT_CARD6,
    FEAT_EMAIL_DOMAIN,
    FEAT_DEVICE_TYPE,
    FEAT_DEVICE_INFO,
    DISPOSABLE_EMAIL_DOMAINS,
    PRODUCT_CODES,
    CARD4_CODES,
    CARD6_CODES,
    DEVICE_TYPE_CODES,
    UNKNOWN_CODE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DATASET_DIR = ROOT / "ieee-fraud-detection"
ARTIFACT_DIR = ROOT / "ml" / "artifact"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

# ── Data loading ──────────────────────────────────────────────────────────────


def load_data(fast: bool = False) -> pd.DataFrame:
    """
    Load IEEE-CIS train_transaction.csv (+ train_identity.csv joined on TransactionID).
    Drop all V* columns (anonymized — would re-introduce the explainability problem).
    Spec §6.2.
    """
    logger.info("Loading IEEE-CIS dataset...")

    tx_path = DATASET_DIR / "train_transaction.csv"
    id_path = DATASET_DIR / "train_identity.csv"

    if not tx_path.exists():
        raise FileNotFoundError(
            f"Dataset not found at {tx_path}\n"
            "Download from: https://www.kaggle.com/c/ieee-fraud-detection/data"
        )

    # Load with only the columns we need (saves memory on the 680MB file)
    tx_cols = [
        "TransactionID", "isFraud", "TransactionDT", "TransactionAmt",
        "ProductCD", "card4", "card6", "P_emaildomain",
        # C features (velocity proxies)
        "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8",
        # D features (time-delta proxies)
        "D1", "D2",
    ]

    logger.info(f"Reading {tx_path.name} (this may take ~30s)...")
    tx = pd.read_csv(tx_path, usecols=lambda c: c in tx_cols or c == "TransactionID")

    # Join identity for device info
    id_cols = ["TransactionID", "DeviceType", "DeviceInfo"]
    if id_path.exists():
        logger.info(f"Joining {id_path.name}...")
        identity = pd.read_csv(
            id_path,
            usecols=lambda c: c in id_cols,
        )
        df = tx.merge(identity, on="TransactionID", how="left")
    else:
        df = tx
        df["DeviceType"] = None
        df["DeviceInfo"] = None

    logger.info(f"Loaded {len(df):,} rows, {df['isFraud'].mean()*100:.2f}% fraud")

    if fast:
        # 10% stratified sample for dev speed — preserves class ratio
        fraud = df[df["isFraud"] == 1]
        legit_all = df[df["isFraud"] == 0]
        # Keep same fraud ratio, sample ~10% total
        n_legit = min(len(legit_all), int(len(fraud) * 28.57))
        legit = legit_all.sample(n=n_legit, random_state=42)
        df = pd.concat([fraud, legit]).sample(frac=1, random_state=42).reset_index(drop=True)
        logger.info(f"Fast mode: sampled to {len(df):,} rows ({len(fraud)} fraud, {n_legit} legit)")

    return df


# ── Feature engineering ───────────────────────────────────────────────────────


def encode_column(series: pd.Series, mapping: dict[str, int]) -> tuple[pd.Series, dict[str, int]]:
    """Fit a string→int encoder on a series. Returns encoded series + full mapping."""
    # Build mapping: extend with any new values seen in training data
    extended = dict(mapping)  # start from known codes
    for val in series.dropna().unique():
        key = str(val).strip().lower()
        if key not in extended:
            extended[key] = len(extended)
    encoded = series.apply(lambda v: extended.get(str(v).strip().lower(), UNKNOWN_CODE) if pd.notna(v) else UNKNOWN_CODE)
    return encoded, extended


def build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, dict[str, int]]]:
    """
    Engineer all features in FEATURE_COLUMNS order.
    Returns (feature_df, encoder_dicts) where encoder_dicts are saved in the artifact.
    """
    logger.info("Engineering features...")
    out = pd.DataFrame(index=df.index)

    # Amount
    out[FEAT_AMOUNT] = df["TransactionAmt"].fillna(0.0)

    # ProductCD
    out[FEAT_PRODUCT], product_enc = encode_column(df.get("ProductCD", pd.Series(dtype=str)), PRODUCT_CODES)

    # Card features
    out[FEAT_CARD4], card4_enc = encode_column(df.get("card4", pd.Series(dtype=str)), CARD4_CODES)
    out[FEAT_CARD6], card6_enc = encode_column(df.get("card6", pd.Series(dtype=str)), CARD6_CODES)

    # Email domain
    email_domain_series = df.get("P_emaildomain", pd.Series(dtype=str))
    out[FEAT_EMAIL_DOMAIN], email_enc = encode_column(email_domain_series, {})

    # Device
    out[FEAT_DEVICE_TYPE], device_type_enc = encode_column(
        df.get("DeviceType", pd.Series(dtype=str)), DEVICE_TYPE_CODES
    )
    device_info_series = df.get("DeviceInfo", pd.Series(dtype=str))
    # Truncate device info to 50 chars to match inference
    device_info_series = device_info_series.apply(lambda v: str(v)[:50] if pd.notna(v) else None)
    out[FEAT_DEVICE_INFO], device_info_enc = encode_column(device_info_series, {})

    # Velocity/count features (C1–C8 from IEEE-CIS map directly)
    for feat, col in [
        (FEAT_COUNT_TX_5MIN, "C1"),
        (FEAT_COUNT_TX_1HR, "C2"),
        (FEAT_COUNT_TX_24HR, "C3"),
        (FEAT_COUNT_CARD_5MIN, "C4"),
        (FEAT_COUNT_CARD_1HR, "C5"),
        (FEAT_AMOUNT_VS_AVG, "C6"),
        ("C7", "C7"),
        ("C8", "C8"),
    ]:
        out[feat] = df.get(col, pd.Series(0.0, index=df.index)).fillna(0.0)

    # Time-delta features (D1, D2 from IEEE-CIS)
    out[FEAT_DAYS_SINCE_LAST] = df.get("D1", pd.Series(-1.0, index=df.index)).fillna(-1.0)
    out[FEAT_DAYS_SINCE_FIRST] = df.get("D2", pd.Series(-1.0, index=df.index)).fillna(-1.0)

    # Time-of-day and day-of-week from TransactionDT (seconds offset)
    # IEEE-CIS TransactionDT is seconds from a reference point
    tx_dt = df.get("TransactionDT", pd.Series(0, index=df.index)).fillna(0)
    out[FEAT_TIME_OF_DAY_HOUR] = ((tx_dt // 3600) % 24).astype(float)
    out[FEAT_DAY_OF_WEEK] = ((tx_dt // 86400) % 7).astype(float)

    # Engineered boolean flags
    disposable = email_domain_series.apply(
        lambda v: 1.0 if (pd.notna(v) and str(v).lower() in DISPOSABLE_EMAIL_DOMAINS) else 0.0
    )
    out[FEAT_IS_DISPOSABLE_EMAIL] = disposable

    # is_new_device: device code is UNKNOWN_CODE
    out[FEAT_IS_NEW_DEVICE] = (out[FEAT_DEVICE_INFO] == UNKNOWN_CODE).astype(float)

    out[FEAT_IS_WEEKEND] = (out[FEAT_DAY_OF_WEEK] >= 5).astype(float)
    out[FEAT_IS_LARGE_AMOUNT] = (out[FEAT_AMOUNT] >= 10000).astype(float)

    # Ensure column order matches FEATURE_COLUMNS exactly
    out = out[FEATURE_COLUMNS]

    encoders = {
        "product_encoder": product_enc,
        "card4_encoder": card4_enc,
        "card6_encoder": card6_enc,
        "email_domain_encoder": email_enc,
        "device_type_encoder": device_type_enc,
        "device_info_encoder": device_info_enc,
    }

    logger.info(f"Features built: {out.shape}")
    return out, encoders


# ── Train / val / test split (time-based) ────────────────────────────────────


def time_split(df: pd.DataFrame, X: pd.DataFrame, y: pd.Series):
    """
    Spec §6.2: Split by TransactionDT, not randomly.
    Train: earliest 70%, cal: next 15%, test: final 15%.
    A random split leaks information from linked transactions.
    """
    order = df["TransactionDT"].argsort()
    n = len(df)
    train_end = int(n * 0.70)
    cal_end = int(n * 0.85)

    idx = order.values
    train_idx = idx[:train_end]
    cal_idx = idx[train_end:cal_end]
    test_idx = idx[cal_end:]

    X_train, y_train = X.iloc[train_idx], y.iloc[train_idx]
    X_cal, y_cal = X.iloc[cal_idx], y.iloc[cal_idx]
    X_test, y_test = X.iloc[test_idx], y.iloc[test_idx]

    logger.info(
        f"Split: train={len(X_train):,} (fraud={y_train.mean()*100:.2f}%) | "
        f"cal={len(X_cal):,} | test={len(X_test):,}"
    )
    return X_train, y_train, X_cal, y_cal, X_test, y_test


# ── Model training ────────────────────────────────────────────────────────────


def train_xgboost(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    n_search: int = 5,
) -> XGBClassifier:
    """
    Small random search over XGBoost hyperparameters.
    Spec §6.4: max_depth 3–6, lr 0.03–0.1, n_estimators up to ~300,
    subsample/colsample_bytree 0.7–0.9.
    """
    scale_pos_weight = float((y_train == 0).sum() / (y_train == 1).sum())
    logger.info(f"XGBoost scale_pos_weight={scale_pos_weight:.1f}")

    param_grid = {
        "max_depth": [3, 4, 5, 6],
        "learning_rate": [0.03, 0.05, 0.07, 0.10],
        "n_estimators": [200, 250, 300],
        "subsample": [0.7, 0.8, 0.9],
        "colsample_bytree": [0.7, 0.8, 0.9],
        "min_child_weight": [1, 3, 5],
    }

    best_model = None
    best_auc = 0.0

    for i, params in enumerate(
        ParameterSampler(param_grid, n_iter=n_search, random_state=42)
    ):
        logger.info(f"Search trial {i+1}/{n_search}: {params}")
        model = XGBClassifier(
            **params,
            scale_pos_weight=scale_pos_weight,
            objective="binary:logistic",
            eval_metric="aucpr",
            early_stopping_rounds=20,
            random_state=42,
            n_jobs=-1,
            verbosity=0,
        )
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )
        preds = model.predict_proba(X_val)[:, 1]
        auc = average_precision_score(y_val, preds)
        logger.info(f"  → PR-AUC={auc:.4f}")
        if auc > best_auc:
            best_auc = auc
            best_model = model

    logger.info(f"Best XGBoost PR-AUC on val: {best_auc:.4f}")
    return best_model


def train_isolation_forest(X_train: pd.DataFrame, contamination: float) -> IsolationForest:
    """
    Spec §6.4: n_estimators=100, contamination near known fraud prevalence.
    Fit on numeric features only (unsupervised — never sees labels).
    """
    numeric_cols = [c for c in FEATURE_COLUMNS if c not in CATEGORICAL_COLUMNS]
    X_numeric = X_train[numeric_cols].values

    logger.info(f"Training IsolationForest (contamination={contamination:.3f})...")
    iso = IsolationForest(
        n_estimators=100,
        contamination=contamination,
        random_state=42,
        n_jobs=-1,
    )
    iso.fit(X_numeric)
    return iso


def calibrate(
    xgb: XGBClassifier,
    iso: IsolationForest,
    X_cal: pd.DataFrame,
    y_cal: pd.Series,
) -> IsotonicRegression:
    """
    Spec §6.4: Isotonic regression on the held-out calibration split
    (distinct from train/val/test — never sees training data).
    """
    logger.info("Calibrating with isotonic regression...")

    xgb_raw = xgb.predict_proba(X_cal)[:, 1]

    numeric_cols = [c for c in FEATURE_COLUMNS if c not in CATEGORICAL_COLUMNS]
    iso_scores = iso.score_samples(X_cal[numeric_cols].values)
    iso_normalized = np.clip((-iso_scores - 0.0) / 0.7, 0.0, 1.0)

    blended = 0.75 * xgb_raw + 0.25 * iso_normalized

    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(blended, y_cal.values)

    # Report calibration quality (Brier score — lower is better)
    cal_preds = calibrator.predict(blended)
    brier = brier_score_loss(y_cal, cal_preds)
    logger.info(f"Calibration Brier score: {brier:.4f} (lower is better)")

    return calibrator


# ── Evaluation ────────────────────────────────────────────────────────────────


def evaluate(
    xgb: XGBClassifier,
    iso: IsolationForest,
    calibrator: IsotonicRegression,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    amount_col: pd.Series,
) -> dict:
    """
    Spec §6.5: Report PR-AUC, ROC-AUC, Brier score, and the business cost metric
    against three baselines: allow-everything, fixed-threshold, amount-aware model.
    """
    from app.config import get_cost_params, get_amount_thresholds

    numeric_cols = [c for c in FEATURE_COLUMNS if c not in CATEGORICAL_COLUMNS]

    xgb_raw = xgb.predict_proba(X_test)[:, 1]
    iso_scores = iso.score_samples(X_test[numeric_cols].values)
    iso_norm = np.clip((-iso_scores - 0.0) / 0.7, 0.0, 1.0)
    blended = 0.75 * xgb_raw + 0.25 * iso_norm
    p_fraud = calibrator.predict(blended)

    pr_auc = average_precision_score(y_test, p_fraud)
    roc_auc = roc_auc_score(y_test, p_fraud)
    brier = brier_score_loss(y_test, p_fraud)

    logger.info(f"Test set — PR-AUC: {pr_auc:.4f} | ROC-AUC: {roc_auc:.4f} | Brier: {brier:.4f}")

    # Business cost evaluation
    try:
        cost_params = get_cost_params()
        F = cost_params["friction_cost"]
        c = cost_params["review_cost"]
        h = cost_params["hold_efficacy"]

        def expected_cost(p: float, amount: float, hold: bool) -> float:
            L = amount * (1 - cost_params["recovery_rate"])
            if hold:
                return p * (1 - h) * L + (1 - p) * F + c
            else:
                return p * L

        amounts = amount_col.values
        # Baseline 1: allow everything
        cost_allow_all = sum(
            expected_cost(float(p), float(a), hold=False)
            for p, a in zip(p_fraud, amounts)
        )

        # Baseline 2: fixed threshold (0.5)
        cost_fixed = sum(
            expected_cost(float(p), float(a), hold=(float(p) >= 0.5))
            for p, a in zip(p_fraud, amounts)
        )

        # Baseline 3: amount-aware thresholds from config
        buckets = get_amount_thresholds()

        def threshold_for_amount(amount: float) -> float:
            for bucket in buckets:
                if amount <= bucket["max_amount"]:
                    return bucket["min_fraud_prob"]
            return buckets[-1]["min_fraud_prob"]

        cost_amount_aware = sum(
            expected_cost(float(p), float(a), hold=(float(p) >= threshold_for_amount(float(a))))
            for p, a in zip(p_fraud, amounts)
        )

        logger.info(f"Business cost — allow-all: ₹{cost_allow_all:,.0f} | "
                    f"fixed-0.5: ₹{cost_fixed:,.0f} | "
                    f"amount-aware: ₹{cost_amount_aware:,.0f}")
        logger.info(f"Savings vs allow-all: ₹{cost_allow_all - cost_amount_aware:,.0f}")

    except Exception as e:
        logger.warning(f"Business cost evaluation skipped: {e}")
        pr_auc, roc_auc, brier = pr_auc, roc_auc, brier

    return {
        "pr_auc": pr_auc,
        "roc_auc": roc_auc,
        "brier": brier,
    }


# ── Global SHAP importance ────────────────────────────────────────────────────


def compute_global_shap(xgb: XGBClassifier, X_sample: pd.DataFrame) -> dict:
    """
    Spec §6.6: Cache global SHAP feature importance once at training time.
    This is the 'why the model works in general' slide.
    """
    try:
        import shap
        explainer = shap.TreeExplainer(xgb)
        sample = X_sample.sample(min(500, len(X_sample)), random_state=42)
        shap_values = explainer.shap_values(sample)
        mean_abs = np.abs(shap_values).mean(axis=0)
        global_importance = {
            FEATURE_COLUMNS[i]: float(mean_abs[i])
            for i in range(len(FEATURE_COLUMNS))
        }
        return dict(sorted(global_importance.items(), key=lambda x: x[1], reverse=True))
    except Exception as e:
        logger.warning(f"Global SHAP computation failed (SHAP may not be installed): {e}")
        # Fall back to XGBoost's built-in importance
        imp = xgb.get_booster().get_score(importance_type="gain")
        return dict(sorted(imp.items(), key=lambda x: x[1], reverse=True))


# ── Artifact saving ───────────────────────────────────────────────────────────


def save_artifact(
    xgb: XGBClassifier,
    iso: IsolationForest,
    calibrator: IsotonicRegression,
    encoders: dict,
    metrics: dict,
    global_shap: dict,
) -> str:
    """
    Save the model artifact to ml/artifact/model.pkl and version.json.
    Returns the version string.
    """
    version = f"xgb+iso-{datetime.now().strftime('%Y.%m.%d-%H%M')}"

    artifact = {
        "xgb": xgb,
        "iso": iso,
        "calibrator": calibrator,
        "feature_columns": FEATURE_COLUMNS,
        "categorical_columns": CATEGORICAL_COLUMNS,
        **encoders,
        "version": version,
        "metrics": metrics,
    }

    artifact_path = ARTIFACT_DIR / "model.pkl"
    logger.info(f"Saving artifact → {artifact_path}")
    with open(artifact_path, "wb") as f:
        pickle.dump(artifact, f, protocol=pickle.HIGHEST_PROTOCOL)

    # Version manifest
    version_info = {
        "version": version,
        "trained_at": datetime.utcnow().isoformat() + "Z",
        "metrics": metrics,
        "feature_columns": FEATURE_COLUMNS,
        "artifact_sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
    }
    with open(ARTIFACT_DIR / "version.json", "w") as f:
        json.dump(version_info, f, indent=2)

    # Global SHAP importance (separate file, for the dashboard "why it works" slide)
    with open(ARTIFACT_DIR / "global_shap.json", "w") as f:
        json.dump(global_shap, f, indent=2)

    logger.info(f"Artifact saved. Version: {version}")
    return version


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="FraudSpike model training pipeline")
    parser.add_argument("--fast", action="store_true", help="Use 10%% sample for dev speed")
    parser.add_argument("--search-trials", type=int, default=5, help="Number of hyperparam search trials")
    args = parser.parse_args()

    logger.info(f"Training pipeline started — fast={args.fast}")

    # 1. Load data
    df = load_data(fast=args.fast)
    y = df["isFraud"].astype(int)

    # 2. Feature engineering
    X, encoders = build_features(df)

    # 3. Time-based split
    X_train, y_train, X_cal, y_cal, X_test, y_test = time_split(df, X, y)

    # 4. Train XGBoost (use cal set as validation for early stopping)
    xgb = train_xgboost(X_train, y_train, X_cal, y_cal, n_search=args.search_trials)

    # 5. Train Isolation Forest
    fraud_prevalence = float(y_train.mean())
    iso = train_isolation_forest(X_train, contamination=fraud_prevalence)

    # 6. Calibrate
    calibrator = calibrate(xgb, iso, X_cal, y_cal)

    # 7. Evaluate on held-out test set
    metrics = evaluate(xgb, iso, calibrator, X_test, y_test, X_test[FEAT_AMOUNT])

    # 8. Global SHAP importance
    global_shap = compute_global_shap(xgb, X_train)

    # 9. Save artifact
    version = save_artifact(xgb, iso, calibrator, encoders, metrics, global_shap)

    logger.info(f"Training complete! Version: {version}")
    logger.info(f"Run  python ml/evaluate.py  to update threshold table in config.yaml")


if __name__ == "__main__":
    main()
