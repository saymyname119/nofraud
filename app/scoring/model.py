"""
app/scoring/model.py — Model artifact loader.

Loads the pickled ML artifact (XGBoost + IsolationForest + calibrator +
encoders) ONCE at startup. The score() method returns a ScoringResult
with a calibrated probability AND reason codes — never one without the other
(spec §9.1, §11 invariant #3).

The artifact is loaded lazily on first call, but validated at app startup
via the lifespan hook in main.py.
"""
from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.scoring.features import FEATURE_COLUMNS, FeatureVector
from app.scoring.reason_codes import ReasonCode, shap_values_to_reasons

logger = logging.getLogger(__name__)

# ── ScoringResult — the indivisible unit of inference output ─────────────────


@dataclass(frozen=True)
class ScoringResult:
    """
    Spec §9.1: score() always returns the probability and its reasons together.
    A caller cannot obtain a score without reasons.
    """
    p: float                          # calibrated P(fraud) ∈ [0,1]
    reasons: list[ReasonCode]         # from the fixed §6.6 vocabulary
    feature_vector_hash: str          # so explanation can be recomputed/defended
    model_version: str
    raw_xgb_score: float              # internal — for audit log only
    raw_iso_score: float              # internal — for audit log only
    shap_values: dict[str, float]     # internal — for audit log, not customer-facing


# ── Model artifact structure ─────────────────────────────────────────────────
# This must match what ml/train.py pickles.

class FraudModel:
    """Wraps the pickled artifact and exposes a single score() method."""

    def __init__(self, artifact_path: str | Path, version_path: str | Path):
        self._artifact_path = Path(artifact_path)
        self._version_path = Path(version_path)
        self._model: dict[str, Any] | None = None
        self._version: str = "unknown"

    def load(self) -> None:
        """Load artifact from disk. Called once at startup."""
        if not self._artifact_path.exists():
            raise FileNotFoundError(
                f"ML artifact not found at {self._artifact_path}. "
                "Run: python ml/train.py  to train and pickle the model."
            )

        logger.info(f"Loading ML artifact from {self._artifact_path}")
        with open(self._artifact_path, "rb") as f:
            self._model = pickle.load(f)

        if self._version_path.exists():
            with open(self._version_path, "r") as f:
                version_info = json.load(f)
                self._version = version_info.get("version", "unknown")

        logger.info(f"Model loaded: version={self._version}")

        # Pre-warm SHAP explainer (avoids first-request latency spike)
        self._prewarm_shap()

    def _prewarm_shap(self) -> None:
        """Run a dummy SHAP explanation to JIT-compile the explainer."""
        try:
            import shap
            booster = self._model["xgb"]
            explainer = self._model.get("shap_explainer")
            if explainer is None:
                explainer = shap.TreeExplainer(booster)
                self._model["shap_explainer"] = explainer

            # Dummy row to pre-warm
            dummy = np.zeros((1, len(FEATURE_COLUMNS)))
            _ = explainer.shap_values(dummy)
            logger.info("SHAP TreeExplainer pre-warmed")
        except Exception as e:
            logger.warning(f"SHAP pre-warm failed (non-fatal): {e}")

    @property
    def version(self) -> str:
        return self._version

    def score(self, fv: FeatureVector) -> ScoringResult:
        """
        Score a single transaction. Returns probability + reasons (indivisible).

        Pipeline (spec §6.1):
          1. XGBoost raw score
          2. Isolation Forest anomaly score
          3. Blend as additional feature
          4. Isotonic calibration → P(fraud)
          5. SHAP TreeExplainer → top reasons
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        import shap

        X = np.array([fv.to_array()], dtype=np.float32)

        # Step 1: XGBoost raw score
        xgb = self._model["xgb"]
        xgb_raw = float(xgb.predict_proba(X)[0, 1])

        # Step 2: Isolation Forest anomaly score
        iso = self._model["iso"]
        # Slice X for numeric features only
        from app.scoring.features import FEATURE_COLUMNS, CATEGORICAL_COLUMNS
        numeric_indices = [i for i, col in enumerate(FEATURE_COLUMNS) if col not in CATEGORICAL_COLUMNS]
        X_numeric = X[:, numeric_indices]
        iso_raw_score = float(iso.score_samples(X_numeric)[0])

        # Normalize using artifact-stored z-score params (falls back to legacy /0.7 if absent)
        iso_mean = self._model.get("iso_mean", None)
        iso_std = self._model.get("iso_std", None)
        if iso_mean is not None and iso_std is not None:
            # z-score normalization: invert so higher = more anomalous, map to [0,1]
            iso_z = (iso_mean - iso_raw_score) / iso_std
            iso_normalized = float(max(0.0, min(1.0, (iso_z + 2) / 4)))
        else:
            # Legacy fallback for old artifacts
            iso_normalized = max(0.0, min(1.0, (-iso_raw_score - 0.0) / 0.7))

        # Step 3: Blend using artifact-stored alpha (falls back to 0.75 if absent)
        blend_alpha = float(self._model.get("blend_alpha", 0.75))
        blended = blend_alpha * xgb_raw + (1.0 - blend_alpha) * iso_normalized

        # Step 4: Calibration — supports both isotonic and Platt calibrators
        calibrator = self._model["calibrator"]
        calibrator_type = self._model.get("calibrator_type", "isotonic")
        if calibrator_type == "platt" or hasattr(calibrator, "predict_proba"):
            import numpy as _np
            p_fraud = float(_np.clip(calibrator.predict_proba([[blended]])[0, 1], 0.0, 1.0))
        else:
            p_fraud = float(calibrator.predict([blended])[0])
        p_fraud = max(0.0, min(1.0, p_fraud))  # clamp to [0,1]

        # Step 5: SHAP values from XGBoost branch
        explainer = self._model.get("shap_explainer")
        if explainer is None:
            explainer = shap.TreeExplainer(xgb)
            self._model["shap_explainer"] = explainer

        shap_vals = explainer.shap_values(X)[0]  # shape: (n_features,)
        shap_dict: dict[str, float] = {
            feat: abs(float(shap_vals[i]))
            for i, feat in enumerate(FEATURE_COLUMNS)
        }

        # Add isolation forest as a virtual feature for reason mapping
        shap_dict["isolation_forest_score"] = iso_normalized * (1.0 - blend_alpha)

        reasons = shap_values_to_reasons(shap_dict, top_n=3)

        return ScoringResult(
            p=p_fraud,
            reasons=reasons,
            feature_vector_hash=fv.to_hash(),
            model_version=self._version,
            raw_xgb_score=xgb_raw,
            raw_iso_score=iso_normalized,
            shap_values=shap_dict,
        )


# ── Singleton instance ────────────────────────────────────────────────────────
# Loaded once by main.py lifespan; imported everywhere else.

_model_instance: FraudModel | None = None


def get_model() -> FraudModel:
    global _model_instance
    if _model_instance is None:
        raise RuntimeError("Model not initialized. Ensure lifespan startup ran.")
    return _model_instance


def init_model(artifact_path: str, version_path: str) -> FraudModel:
    """Called once during app startup."""
    global _model_instance
    _model_instance = FraudModel(artifact_path, version_path)
    _model_instance.load()
    return _model_instance
