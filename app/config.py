"""
app/config.py — Central config loader.

Loads config.yaml once at startup. All modules import `settings` and `cfg`
from here; nothing else reads config files directly.
"""
from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


# ── Pydantic Settings (from .env) ────────────────────────────────────────────


class AppSettings(BaseSettings):
    """Environment-variable-backed settings (secrets, URLs)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    razorpay_key_id: str = "rzp_test_MOCK"
    razorpay_key_secret: str = "MOCK"
    razorpay_webhook_secret: str = "MOCK"

    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str = "sqlite+aiosqlite:///./fraudspike.db"
    ngrok_url: str = "https://placeholder.ngrok-free.app"
    redis_url: str = ""


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()


# ── YAML Config ──────────────────────────────────────────────────────────────

_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    """Load and cache config.yaml. Returns the full dict."""
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def get_config_hash() -> str:
    """SHA-256 of the raw config.yaml bytes. Recorded on every decision."""
    raw = _CONFIG_PATH.read_bytes()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def get_amount_thresholds() -> list[dict]:
    """Return the list of amount-bucket threshold dicts from config."""
    return load_config()["thresholds"]["amount_buckets"]


def get_cost_params() -> dict[str, float]:
    return load_config()["cost_params"]


def get_circuit_breaker_cfg() -> dict:
    return load_config()["circuit_breaker"]


def get_idempotency_cfg() -> dict:
    return load_config()["idempotency"]


def is_shadow_mode() -> bool:
    return bool(load_config().get("shadow_mode", False))


def get_model_cfg() -> dict:
    return load_config()["model"]


def get_audit_cfg() -> dict:
    return load_config()["audit"]


def get_compliance_lists() -> dict:
    return load_config().get("compliance", {})


def get_velocity_cfg() -> dict:
    return load_config().get("velocity", {})


def get_step_up_cfg() -> dict:
    return load_config().get("step_up", {})


def is_razorpay_mock() -> bool:
    return bool(load_config().get("razorpay", {}).get("mock_mode", False))
