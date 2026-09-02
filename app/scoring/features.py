"""
app/scoring/features.py — Shared feature specification.

THIS IS THE SINGLE SOURCE OF TRUTH for feature names and engineering.
Both ml/train.py and app/scoring/pipeline.py import from here.
Divergence between train and serve = training-serving skew (§11 invariant #10).

IEEE-CIS → Razorpay field mapping (spec §6.2):
  TransactionAmt   → payment.amount
  ProductCD        → payment method type
  card4/card6      → card network / card type
  P_emaildomain    → customer email domain
  DeviceType       → device type from user-agent
  DeviceInfo       → device fingerprint / user-agent
  C1–C14           → velocity count features (self-computed)
  D1–D15           → time-delta features (time since last tx)
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# ── Feature name constants ────────────────────────────────────────────────────
# These are the ONLY feature names used anywhere. Never reference string literals
# for feature names in other modules.

FEAT_AMOUNT = "TransactionAmt"
FEAT_PRODUCT = "ProductCD"
FEAT_CARD4 = "card4"        # card network: visa, mastercard, etc.
FEAT_CARD6 = "card6"        # card type: credit, debit
FEAT_EMAIL_DOMAIN = "P_emaildomain"
FEAT_DEVICE_TYPE = "DeviceType"
FEAT_DEVICE_INFO = "DeviceInfo"

# Velocity / count features (C1–C14 proxies)
FEAT_COUNT_TX_5MIN = "C1"        # transactions from same email in last 5 min
FEAT_COUNT_TX_1HR = "C2"         # transactions from same email in last 1 hour
FEAT_COUNT_TX_24HR = "C3"        # transactions from same email in last 24 hours
FEAT_COUNT_CARD_5MIN = "C4"      # transactions from same card in last 5 min
FEAT_COUNT_CARD_1HR = "C5"       # transactions from same card in last 1 hour
FEAT_AMOUNT_VS_AVG = "C6"        # current amount / avg amount for this email
FEAT_UNIQUE_EMAILS_CARD = "C7"   # unique emails seen on same card (last 24h)
FEAT_UNIQUE_CARDS_EMAIL = "C8"   # unique cards seen on same email (last 24h)

# Time-delta features (D1–D15 proxies)
FEAT_DAYS_SINCE_LAST = "D1"      # days since last transaction (same email)
FEAT_DAYS_SINCE_FIRST = "D2"     # account age proxy (days since first tx in data)
FEAT_TIME_OF_DAY_HOUR = "D3"     # hour of day (0–23) — fraud spikes at night
FEAT_DAY_OF_WEEK = "D4"          # 0=Monday, 6=Sunday

# Engineered boolean flags
FEAT_IS_DISPOSABLE_EMAIL = "is_disposable_email"
FEAT_IS_NEW_DEVICE = "is_new_device"
FEAT_IS_WEEKEND = "is_weekend"
FEAT_IS_LARGE_AMOUNT = "is_large_amount"   # amount > ₹10,000

# Derived/interaction features (improves split efficiency in tree models)
FEAT_LOG_AMOUNT = "log_amount"            # log1p(TransactionAmt) — compresses skewed amount dist
FEAT_AMOUNT_X_VELOCITY = "amount_x_vel"  # TransactionAmt × C5 (card velocity in 1hr)
FEAT_HOUR_SIN = "hour_sin"               # sin(2π × hour / 24) — cyclical hour encoding
FEAT_HOUR_COS = "hour_cos"               # cos(2π × hour / 24)
FEAT_DOW_SIN = "dow_sin"                 # sin(2π × dow / 7) — cyclical day-of-week
FEAT_DOW_COS = "dow_cos"                 # cos(2π × dow / 7)

# All features in a fixed, ordered list. Order matters for the trained model.
FEATURE_COLUMNS: list[str] = [
    FEAT_AMOUNT,
    FEAT_PRODUCT,
    FEAT_CARD4,
    FEAT_CARD6,
    FEAT_EMAIL_DOMAIN,
    FEAT_DEVICE_TYPE,
    FEAT_DEVICE_INFO,
    FEAT_COUNT_TX_5MIN,
    FEAT_COUNT_TX_1HR,
    FEAT_COUNT_TX_24HR,
    FEAT_COUNT_CARD_5MIN,
    FEAT_COUNT_CARD_1HR,
    FEAT_AMOUNT_VS_AVG,
    FEAT_UNIQUE_EMAILS_CARD,
    FEAT_UNIQUE_CARDS_EMAIL,
    FEAT_DAYS_SINCE_LAST,
    FEAT_DAYS_SINCE_FIRST,
    FEAT_TIME_OF_DAY_HOUR,
    FEAT_DAY_OF_WEEK,
    FEAT_IS_DISPOSABLE_EMAIL,
    FEAT_IS_NEW_DEVICE,
    FEAT_IS_WEEKEND,
    FEAT_IS_LARGE_AMOUNT,
    # Derived/interaction features (appended — do NOT reorder above entries)
    FEAT_LOG_AMOUNT,
    FEAT_AMOUNT_X_VELOCITY,
    FEAT_HOUR_SIN,
    FEAT_HOUR_COS,
    FEAT_DOW_SIN,
    FEAT_DOW_COS,
]

# Categorical columns that need label-encoding (not one-hot, to keep tree-model-friendly)
CATEGORICAL_COLUMNS: list[str] = [
    FEAT_PRODUCT,
    FEAT_CARD4,
    FEAT_CARD6,
    FEAT_EMAIL_DOMAIN,
    FEAT_DEVICE_TYPE,
    FEAT_DEVICE_INFO,
]

# Numeric columns (fed directly)
NUMERIC_COLUMNS: list[str] = [c for c in FEATURE_COLUMNS if c not in CATEGORICAL_COLUMNS]

# ── Known disposable email domains ───────────────────────────────────────────
DISPOSABLE_EMAIL_DOMAINS: frozenset[str] = frozenset({
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "throwam.com",
    "trashmail.com", "yopmail.com", "fakeinbox.com", "sharklasers.com",
    "guerrillamailblock.com", "grr.la", "spam4.me", "dispostable.com",
    "tempmail.com", "temp-mail.org", "maildrop.cc", "spamgourmet.com",
    "spamgourmet.net", "spamgourmet.org", "mailnull.com",
})

# ── Feature vector dataclass ─────────────────────────────────────────────────

@dataclass
class FeatureVector:
    """Typed container for a single transaction's feature values.

    Fields map 1:1 to FEATURE_COLUMNS. Missing/unknown values use sentinel -1
    (never 0 or NaN, to preserve distinguishability per spec §A.4).
    """
    TransactionAmt: float = 0.0
    ProductCD: int = -1
    card4: int = -1
    card6: int = -1
    P_emaildomain: int = -1
    DeviceType: int = -1
    DeviceInfo: int = -1
    C1: float = 0.0    # count_tx_5min
    C2: float = 0.0    # count_tx_1hr
    C3: float = 0.0    # count_tx_24hr
    C4: float = 0.0    # count_card_5min
    C5: float = 0.0    # count_card_1hr
    C6: float = 1.0    # amount_vs_avg (1.0 = average)
    C7: float = 0.0    # unique_emails_card
    C8: float = 0.0    # unique_cards_email
    D1: float = -1.0   # days_since_last (-1 = first transaction)
    D2: float = -1.0   # days_since_first
    D3: float = 12.0   # time_of_day_hour (default: noon)
    D4: float = 0.0    # day_of_week
    is_disposable_email: float = 0.0
    is_new_device: float = 0.0
    is_weekend: float = 0.0
    is_large_amount: float = 0.0
    # Derived/interaction features
    log_amount: float = 0.0        # log1p(TransactionAmt)
    amount_x_vel: float = 0.0      # TransactionAmt × C5
    hour_sin: float = 0.0          # sin(2π × D3 / 24)
    hour_cos: float = 1.0          # cos(2π × D3 / 24) — default noon → cos(π) ≈ -1 but we use 1.0 for safety
    dow_sin: float = 0.0           # sin(2π × D4 / 7)
    dow_cos: float = 1.0           # cos(2π × D4 / 7)

    def to_array(self) -> list[float]:
        """Return feature values in FEATURE_COLUMNS order."""
        return [getattr(self, col) for col in FEATURE_COLUMNS]

    def to_hash(self) -> str:
        """SHA-256 of the canonical JSON feature vector (sorted keys)."""
        d = {col: getattr(self, col) for col in FEATURE_COLUMNS}
        canonical = json.dumps(d, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


# ── Category encoders ─────────────────────────────────────────────────────────
# These dicts are fitted during training and saved in the model artifact.
# Here we define the DEFAULT fallback mapping for inference-time unknown values.

PRODUCT_CODES = {"W": 0, "H": 1, "C": 2, "S": 3, "R": 4}
CARD4_CODES = {"visa": 0, "mastercard": 1, "american express": 2, "discover": 3}
CARD6_CODES = {"debit": 0, "credit": 1, "charge card": 2}
DEVICE_TYPE_CODES = {"desktop": 0, "mobile": 1, "tablet": 2}

UNKNOWN_CODE = -1  # sentinel for unseen categories


def encode_categorical(value: str | None, mapping: dict[str, int]) -> int:
    """Map a string category to its integer code, or UNKNOWN_CODE if unseen."""
    if value is None:
        return UNKNOWN_CODE
    return mapping.get(str(value).strip().lower(), UNKNOWN_CODE)


def extract_email_domain(email: str | None) -> str | None:
    """Extract domain from an email address."""
    if not email or "@" not in email:
        return None
    return email.split("@", 1)[1].lower().strip()


def is_disposable(email: str | None) -> bool:
    """Return True if the email domain is in the known disposable list."""
    domain = extract_email_domain(email)
    return domain in DISPOSABLE_EMAIL_DOMAINS if domain else False


# ── Razorpay payload → FeatureVector ─────────────────────────────────────────

def build_feature_vector(
    payment: dict[str, Any],
    velocity: dict[str, float],
    email_domain_encoder: dict[str, int],
    device_info_encoder: dict[str, int],
) -> FeatureVector:
    """
    Convert a Razorpay payment.authorized webhook payload + velocity counts
    into a FeatureVector suitable for model inference.

    Args:
        payment: the Razorpay payment dict from the webhook
        velocity: pre-computed velocity counts from the velocity store
            keys: count_tx_5min, count_tx_1hr, count_tx_24hr,
                  count_card_5min, count_card_1hr, amount_vs_avg,
                  unique_emails_card, unique_cards_email,
                  days_since_last, days_since_first
        email_domain_encoder: domain→int map from training artifact
        device_info_encoder: device_info→int map from training artifact
    """
    import datetime

    notes = payment.get("notes") or {}
    amount_paise = int(payment.get("amount", 0))
    amount = amount_paise / 100.0  # Razorpay amounts are in paise

    email = (notes.get("email") or payment.get("email") or "").lower()
    email_domain = extract_email_domain(email) or ""

    method = payment.get("method", "card")
    bank = (payment.get("bank") or "").lower()
    wallet = (payment.get("wallet") or "").lower()

    # Map Razorpay method to ProductCD proxy
    product_map = {"card": "W", "netbanking": "H", "upi": "C", "wallet": "S", "emi": "R"}
    product_str = product_map.get(method, "W")

    card = payment.get("card") or {}
    card_network = (card.get("network") or "").lower()
    card_type = (card.get("type") or "").lower()  # credit / debit

    device_info_raw = notes.get("device_info") or payment.get("user_agent") or ""

    # Infer device type from user agent / device_info
    device_type_str = "desktop"
    ua = device_info_raw.lower()
    if any(x in ua for x in ["mobile", "android", "iphone", "ios"]):
        device_type_str = "mobile"
    elif "tablet" in ua or "ipad" in ua:
        device_type_str = "tablet"

    # Time features
    now = datetime.datetime.now(datetime.timezone.utc)
    hour = now.hour
    dow = now.weekday()  # 0=Monday
    is_weekend = 1.0 if dow >= 5 else 0.0

    # Email domain encoding
    email_code = email_domain_encoder.get(email_domain, UNKNOWN_CODE)
    device_code = device_info_encoder.get(device_info_raw[:50], UNKNOWN_CODE)

    import math
    c5 = float(velocity.get("count_card_1hr", 0))

    return FeatureVector(
        TransactionAmt=amount,
        ProductCD=encode_categorical(product_str, PRODUCT_CODES),
        card4=encode_categorical(card_network, CARD4_CODES),
        card6=encode_categorical(card_type, CARD6_CODES),
        P_emaildomain=email_code,
        DeviceType=encode_categorical(device_type_str, DEVICE_TYPE_CODES),
        DeviceInfo=device_code,
        C1=float(velocity.get("count_tx_5min", 0)),
        C2=float(velocity.get("count_tx_1hr", 0)),
        C3=float(velocity.get("count_tx_24hr", 0)),
        C4=float(velocity.get("count_card_5min", 0)),
        C5=c5,
        C6=float(velocity.get("amount_vs_avg", 1.0)),
        C7=float(velocity.get("unique_emails_card", 0)),
        C8=float(velocity.get("unique_cards_email", 0)),
        D1=float(velocity.get("days_since_last", -1.0)),
        D2=float(velocity.get("days_since_first", -1.0)),
        D3=float(hour),
        D4=float(dow),
        is_disposable_email=1.0 if is_disposable(email) else 0.0,
        is_new_device=1.0 if device_code == UNKNOWN_CODE else 0.0,
        is_weekend=is_weekend,
        is_large_amount=1.0 if amount >= 10000 else 0.0,
        # Derived/interaction features
        log_amount=math.log1p(amount),
        amount_x_vel=amount * c5,
        hour_sin=math.sin(2 * math.pi * hour / 24),
        hour_cos=math.cos(2 * math.pi * hour / 24),
        dow_sin=math.sin(2 * math.pi * dow / 7),
        dow_cos=math.cos(2 * math.pi * dow / 7),
    )
