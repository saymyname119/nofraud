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
    python ml/train.py --synthetic   # generate synthetic data if dataset not present

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
    FEAT_LOG_AMOUNT,
    FEAT_AMOUNT_X_VELOCITY,
    FEAT_HOUR_SIN,
    FEAT_HOUR_COS,
    FEAT_DOW_SIN,
    FEAT_DOW_COS,
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

DATASET_DIR = ROOT / "data" if (ROOT / "data" / "train_transaction.csv").exists() else (ROOT / "ieee-fraud-detection")
ARTIFACT_DIR = ROOT / "ml" / "artifact"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


# ── Synthetic Data Generation (for testing & development) ─────────────


def generate_synthetic_data(n_samples: int = 5000, seed: int = 42) -> pd.DataFrame:
    """Generate realistic synthetic transaction data matching IEEE-CIS schema."""
    logger.info(f"Generating {n_samples:,} synthetic transactions for local training/testing...")
    rng = np.random.default_rng(seed)

    fraud_rate = 0.05
    is_fraud = rng.choice([0, 1], size=n_samples, p=[1 - fraud_rate, fraud_rate])

    # Time: sequential seconds over 30 days
    time_deltas = rng.exponential(scale=500, size=n_samples)
    transaction_dt = np.cumsum(time_deltas).astype(int)

    # Amounts (log-normal, fraud tends higher)
    amounts = np.where(
        is_fraud == 1,
        rng.lognormal(mean=8.5, sigma=1.2, size=n_samples),   # ~₹5,000 - ₹50,000+
        rng.lognormal(mean=6.5, sigma=1.0, size=n_samples),   # ~₹500 - ₹5,000
    )
    amounts = np.round(np.clip(amounts, 50.0, 200000.0), 2)

    product_cds = rng.choice(["W", "H", "C", "S", "R"], size=n_samples, p=[0.7, 0.1, 0.1, 0.05, 0.05])
    card4s = rng.choice(["visa", "mastercard", "american express", "discover"], size=n_samples, p=[0.6, 0.3, 0.07, 0.03])
    card6s = rng.choice(["debit", "credit"], size=n_samples, p=[0.7, 0.3])

    legit_domains = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com"]
    disp_domains = list(DISPOSABLE_EMAIL_DOMAINS)
    email_domains = []
    for f in is_fraud:
        if f == 1 and rng.random() < 0.4:
            email_domains.append(rng.choice(disp_domains))
        else:
            email_domains.append(rng.choice(legit_domains))

    device_types = rng.choice(["desktop", "mobile", "tablet"], size=n_samples, p=[0.5, 0.45, 0.05])
    device_infos = rng.choice(["Windows", "iOS", "Android", "Macintosh", "Linux"], size=n_samples)

    # Velocity features
    c1 = np.where(is_fraud == 1, rng.poisson(lam=5, size=n_samples), rng.poisson(lam=0.2, size=n_samples))
    c2 = np.where(is_fraud == 1, rng.poisson(lam=8, size=n_samples), rng.poisson(lam=0.5, size=n_samples))
    c3 = np.where(is_fraud == 1, rng.poisson(lam=15, size=n_samples), rng.poisson(lam=1.5, size=n_samples))
    c4 = np.where(is_fraud == 1, rng.poisson(lam=4, size=n_samples), rng.poisson(lam=0.1, size=n_samples))
    c5 = np.where(is_fraud == 1, rng.poisson(lam=6, size=n_samples), rng.poisson(lam=0.3, size=n_samples))
    c6 = np.where(is_fraud == 1, rng.uniform(2.0, 8.0, size=n_samples), rng.uniform(0.5, 1.8, size=n_samples))
    c7 = np.where(is_fraud == 1, rng.poisson(lam=2, size=n_samples), np.zeros(n_samples))
    c8 = np.where(is_fraud == 1, rng.poisson(lam=2, size=n_samples), np.zeros(n_samples))

    d1 = np.where(is_fraud == 1, rng.uniform(0.0, 2.0, size=n_samples), rng.uniform(0.0, 60.0, size=n_samples))
    d2 = np.where(is_fraud == 1, rng.uniform(0.0, 5.0, size=n_samples), rng.uniform(10.0, 365.0, size=n_samples))

    df = pd.DataFrame({
        "TransactionID": np.arange(1000000, 1000000 + n_samples),
        "isFraud": is_fraud,
        "TransactionDT": transaction_dt,
        "TransactionAmt": amounts,
        "ProductCD": product_cds,
        "card4": card4s,
        "card6": card6s,
        "P_emaildomain": email_domains,
        "DeviceType": device_types,
        "DeviceInfo": device_infos,
        "C1": c1.astype(float),
        "C2": c2.astype(float),
        "C3": c3.astype(float),
        "C4": c4.astype(float),
        "C5": c5.astype(float),
        "C6": c6.astype(float),
        "C7": c7.astype(float),
        "C8": c8.astype(float),
        "D1": d1.astype(float),
        "D2": d2.astype(float),
    })
    return df


# ── Data loading ──────────────────────────────────────────────────────


def load_data(fast: bool = False, force_synthetic: bool = False) -> pd.DataFrame:
    """
    Load IEEE-CIS train_transaction.csv (+ train_identity.csv joined on TransactionID).
    If dataset file is missing or force_synthetic is True, falls back to synthetic dataset.
    Drop all V* columns (anonymized — would re-introduce the explainability problem).
    Spec §6.2.
    """
    tx_path = DATASET_DIR / "train_transaction.csv"
    id_path = DATASET_DIR / "train_identity.csv"

    if force_synthetic or not tx_path.exists():
        logger.info(f"Kaggle dataset not found at {tx_path}. Using synthetic transaction data generator.")
        n_rows = 2000 if fast else 6000
        return generate_synthetic_data(n_samples=n_rows)

    logger.info("Loading IEEE-CIS dataset...")

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


# ── Feature engineering ───────────────────────────────────────────────


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

    # ── Derived / interaction features ─────────────────────────────────
    # log-amount: compresses the heavy-tailed amount distribution
    out[FEAT_LOG_AMOUNT] = np.log1p(out[FEAT_AMOUNT])

    # amount × card-velocity-1hr: high amount + high velocity is a strong fraud signal
    out[FEAT_AMOUNT_X_VELOCITY] = out[FEAT_AMOUNT] * out[FEAT_COUNT_CARD_1HR]

    # Cyclical hour-of-day encoding (avoids the 23→0 discontinuity)
    hour = out[FEAT_TIME_OF_DAY_HOUR]
    out[FEAT_HOUR_SIN] = np.sin(2 * np.pi * hour / 24)
    out[FEAT_HOUR_COS] = np.cos(2 * np.pi * hour / 24)

    # Cyclical day-of-week encoding
    dow = out[FEAT_DAY_OF_WEEK]
    out[FEAT_DOW_SIN] = np.sin(2 * np.pi * dow / 7)
    out[FEAT_DOW_COS] = np.cos(2 * np.pi * dow / 7)

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


# ── Train / val / test split (time-based) ─────────────────────────────


def time_split(df: pd.DataFrame, X: pd.DataFrame, y: pd.Series):
    """
    Spec §6.2: Split by TransactionDT, not randomly.
    Train: earliest 70%, cal: next 15%, test: final 15% .
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


# ── Model training ────────────────────────────────────────────────────


def train_xgboost(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    n_search: int = 10,
) -> XGBClassifier:
    """
    Random search over XGBoost hyperparameters.
    Larger grid includes regularization (reg_alpha, reg_lambda, gamma)
    and deeper estimators for better AUC on the full dataset.
    """
    scale_pos_weight = float((y_train == 0).sum() / max(1, (y_train == 1).sum()))
    logger.info(f"XGBoost scale_pos_weight={scale_pos_weight:.1f}")

    param_grid = {
        "max_depth": [3, 4, 5, 6, 7],
        "learning_rate": [0.02, 0.03, 0.05, 0.07, 0.10],
        "n_estimators": [200, 300, 400, 500],
        "subsample": [0.7, 0.8, 0.9],
        "colsample_bytree": [0.7, 0.8, 0.9],
        "min_child_weight": [1, 3, 5],
        "reg_alpha": [0.0, 0.01, 0.1, 0.5],    # L1 regularization
        "reg_lambda": [0.5, 1.0, 2.0, 5.0],    # L2 regularization
        "gamma": [0.0, 0.1, 0.5],              # min split-loss
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
            early_stopping_rounds=30,
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
        if auc >= best_auc or best_model is None:
            best_auc = auc
            best_model = model

    logger.info(f"Best XGBoost PR-AUC on val: {best_auc:.4f}")
    return best_model


def train_isolation_forest(
    X_train: pd.DataFrame, contamination: float
) -> tuple[IsolationForest, float, float]:
    """
    Train IsolationForest on numeric features only (unsupervised — never sees labels).
    Returns the fitted model plus the mean and std of its training scores,
    so inference can use the same z-score normalization instead of a hard-coded divisor.
    """
    numeric_cols = [c for c in FEATURE_COLUMNS if c not in CATEGORICAL_COLUMNS]
    X_numeric = X_train[numeric_cols].values

    contamination_clipped = max(0.01, min(0.5, contamination))
    logger.info(f"Training IsolationForest (n_estimators=200, contamination={contamination_clipped:.3f})...")
    iso = IsolationForest(
        n_estimators=200,
        contamination=contamination_clipped,
        random_state=42,
        n_jobs=-1,
    )
    iso.fit(X_numeric)

    # Compute z-score normalization params on training data
    train_scores = iso.score_samples(X_numeric)  # raw anomaly scores (higher = more normal)
    iso_mean = float(train_scores.mean())
    iso_std = float(train_scores.std()) or 1.0  # guard against zero-std edge case
    logger.info(f"IsoForest score distribution: mean={iso_mean:.4f}, std={iso_std:.4f}")

    return iso, iso_mean, iso_std


def blend_scores(
    xgb_raw: np.ndarray,
    iso_scores: np.ndarray,
    iso_mean: float,
    iso_std: float,
    alpha: float,
) -> np.ndarray:
    """
    Blend XGBoost and IsolationForest scores.
    IsoForest scores are z-score normalized then inverted so higher = more anomalous.
    Alpha is the XGBoost weight (1-alpha for IsoForest).
    """
    # z-score normalize and invert: positive means more anomalous
    iso_z = (iso_mean - iso_scores) / iso_std  # invert: low score → high anomaly
    iso_normalized = np.clip((iso_z + 2) / 4, 0.0, 1.0)  # map ~(-2, +2) → (0, 1)
    return alpha * xgb_raw + (1.0 - alpha) * iso_normalized


def optimize_blend_weight(
    xgb: XGBClassifier,
    iso: IsolationForest,
    iso_mean: float,
    iso_std: float,
    X_cal: pd.DataFrame,
    y_cal: pd.Series,
) -> float:
    """
    Sweep the XGBoost blend weight alpha ∈ [0.6, 1.0] on the calibration set.
    Picks the alpha that maximises PR-AUC — avoids the manual 0.75 assumption.
    """
    logger.info("Optimizing ensemble blend weight alpha...")
    numeric_cols = [c for c in FEATURE_COLUMNS if c not in CATEGORICAL_COLUMNS]

    xgb_raw = xgb.predict_proba(X_cal)[:, 1]
    iso_scores = iso.score_samples(X_cal[numeric_cols].values)

    alpha_candidates = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00]
    best_alpha = 0.75
    best_auc = 0.0

    for alpha in alpha_candidates:
        blended = blend_scores(xgb_raw, iso_scores, iso_mean, iso_std, alpha)
        auc = average_precision_score(y_cal, blended)
        logger.info(f"  alpha={alpha:.2f} → cal PR-AUC={auc:.4f}")
        if auc > best_auc:
            best_auc = auc
            best_alpha = alpha

    logger.info(f"Optimal blend alpha={best_alpha:.2f} (cal PR-AUC={best_auc:.4f})")
    return best_alpha


def calibrate(
    xgb: XGBClassifier,
    iso: IsolationForest,
    iso_mean: float,
    iso_std: float,
    blend_alpha: float,
    X_cal: pd.DataFrame,
    y_cal: pd.Series,
) -> tuple[object, str]:
    """
    Train both isotonic and Platt (sigmoid) calibrators on the held-out calibration
    split. Auto-selects the one with the lower Brier score.
    Returns (calibrator, calibrator_type_name).
    """
    from sklearn.linear_model import LogisticRegression

    logger.info("Calibrating with isotonic regression and Platt scaling...")
    numeric_cols = [c for c in FEATURE_COLUMNS if c not in CATEGORICAL_COLUMNS]

    xgb_raw = xgb.predict_proba(X_cal)[:, 1]
    iso_scores = iso.score_samples(X_cal[numeric_cols].values)
    blended = blend_scores(xgb_raw, iso_scores, iso_mean, iso_std, blend_alpha)

    # Isotonic calibrator
    iso_cal = IsotonicRegression(out_of_bounds="clip")
    iso_cal.fit(blended, y_cal.values)
    iso_preds = iso_cal.predict(blended)
    iso_brier = brier_score_loss(y_cal, iso_preds)

    # Platt scaling (sigmoid calibrator via logistic regression on 1 feature)
    platt_cal = LogisticRegression(solver="lbfgs", max_iter=1000)
    platt_cal.fit(blended.reshape(-1, 1), y_cal.values)
    platt_preds = np.clip(platt_cal.predict_proba(blended.reshape(-1, 1))[:, 1], 0, 1)
    platt_brier = brier_score_loss(y_cal, platt_preds)

    logger.info(f"Isotonic Brier: {iso_brier:.4f} | Platt Brier: {platt_brier:.4f}")

    if iso_brier <= platt_brier:
        logger.info("Selecting: IsotonicRegression")
        return iso_cal, "isotonic"
    else:
        logger.info("Selecting: Platt scaling (LogisticRegression)")
        return platt_cal, "platt"


# ── Evaluation ────────────────────────────────────────────────────────


def evaluate(
    xgb: XGBClassifier,
    iso: IsolationForest,
    iso_mean: float,
    iso_std: float,
    blend_alpha: float,
    calibrator,
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
    blended = blend_scores(xgb_raw, iso_scores, iso_mean, iso_std, blend_alpha)

    # Support both isotonic and Platt calibrators
    if hasattr(calibrator, "predict_proba"):
        p_fraud = np.clip(calibrator.predict_proba(blended.reshape(-1, 1))[:, 1], 0, 1)
    else:
        p_fraud = calibrator.predict(blended)

    pr_auc = average_precision_score(y_test, p_fraud)
    roc_auc = roc_auc_score(y_test, p_fraud) if len(np.unique(y_test)) > 1 else 0.5
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

    return {
        "pr_auc": pr_auc,
        "roc_auc": roc_auc,
        "brier": brier,
    }


# ── Global SHAP importance ────────────────────────────────────────────


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
        logger.warning(f"Global SHAP computation failed: {e}")
        # Fall back to XGBoost's built-in importance
        imp = xgb.get_booster().get_score(importance_type="gain")
        return dict(sorted(imp.items(), key=lambda x: x[1], reverse=True))


# ── Artifact saving ───────────────────────────────────────────────────


def save_artifact(
    xgb: XGBClassifier,
    iso: IsolationForest,
    iso_mean: float,
    iso_std: float,
    blend_alpha: float,
    calibrator,
    calibrator_type: str,
    encoders: dict,
    metrics: dict,
    global_shap: dict,
) -> str:
    """
    Save the model artifact to ml/artifact/model.pkl and version.json.
    The artifact now includes iso_mean, iso_std, blend_alpha, and calibrator_type
    so that inference uses identical normalization and blending to training.
    Returns the version string.
    """
    version = f"xgb+iso-{datetime.now().strftime('%Y.%m.%d-%H%M')}"

    artifact = {
        "xgb": xgb,
        "iso": iso,
        "iso_mean": iso_mean,
        "iso_std": iso_std,
        "blend_alpha": blend_alpha,
        "calibrator": calibrator,
        "calibrator_type": calibrator_type,
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
        "blend_alpha": blend_alpha,
        "calibrator_type": calibrator_type,
        "feature_columns": FEATURE_COLUMNS,
        "artifact_sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
    }
    with open(ARTIFACT_DIR / "version.json", "w") as f:
        json.dump(version_info, f, indent=2)

    # Global SHAP importance (separate file, for the dashboard "why it works" slide)
    with open(ARTIFACT_DIR / "global_shap.json", "w") as f:
        json.dump(global_shap, f, indent=2)

    logger.info(f"Artifact saved. Version: {version} | alpha={blend_alpha:.2f} | cal={calibrator_type}")
    return version


# ── Main ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="FraudSpike model training pipeline")
    parser.add_argument("--fast", action="store_true", help="Use smaller sample for dev speed")
    parser.add_argument("--synthetic", action="store_true", help="Force synthetic data generation")
    parser.add_argument("--search-trials", type=int, default=3, help="Number of hyperparam search trials")
    args = parser.parse_args()

    logger.info(f"Training pipeline started — fast={args.fast}")

    # 1. Load data
    df = load_data(fast=args.fast, force_synthetic=args.synthetic)
    y = df["isFraud"].astype(int)

    # 2. Feature engineering
    X, encoders = build_features(df)

    # 3. Time-based split
    X_train, y_train, X_cal, y_cal, X_test, y_test = time_split(df, X, y)

    # 4. Train XGBoost (use cal set as validation for early stopping)
    xgb = train_xgboost(X_train, y_train, X_cal, y_cal, n_search=args.search_trials)

    # 5. Train Isolation Forest (returns model + normalization stats)
    fraud_prevalence = float(y_train.mean())
    iso, iso_mean, iso_std = train_isolation_forest(X_train, contamination=fraud_prevalence)

    # 6. Optimize ensemble blend weight on calibration set
    blend_alpha = optimize_blend_weight(xgb, iso, iso_mean, iso_std, X_cal, y_cal)

    # 7. Calibrate (auto-selects isotonic vs Platt by Brier score)
    calibrator, calibrator_type = calibrate(xgb, iso, iso_mean, iso_std, blend_alpha, X_cal, y_cal)

    # 8. Evaluate on held-out test set
    metrics = evaluate(xgb, iso, iso_mean, iso_std, blend_alpha, calibrator, X_test, y_test, X_test[FEAT_AMOUNT])

    # 9. Global SHAP importance
    global_shap = compute_global_shap(xgb, X_train)

    # 10. Save artifact
    version = save_artifact(xgb, iso, iso_mean, iso_std, blend_alpha, calibrator, calibrator_type, encoders, metrics, global_shap)

    logger.info(f"Training complete! Version: {version}")
    logger.info("Run python ml/evaluate.py to update threshold table in config.yaml")


if __name__ == "__main__":
    main()
