"""
ODISHA FLOOD EARLY WARNING SYSTEM
ai_flood_engine.py — v1.0

Project statement alignment:
AI/ML-Based Integrated heavy rainfall Early Warning and
Inundation Prediction System using Satellite, Radar,
observational Weather and numerical weather prediction model data.

This module is deliberately honest about model readiness:
- If a trained sklearn/joblib model is configured, it is used.
- Otherwise a deterministic multi-source screening fallback is used.
- Fallback output is explicitly marked as screening, not trained ML.

Expected feature vector (in this exact order):
1 rainfall_obs_1h_mm
2 rainfall_obs_6h_mm
3 rainfall_obs_24h_mm
4 rainfall_satellite_24h_mm
5 rainfall_radar_1h_mm
6 rainfall_radar_3h_mm
7 nwp_rain_3h_mm
8 nwp_rain_24h_mm
9 temperature_c
10 humidity_pct
11 wind_speed_kmh
12 elevation_m
13 slope_deg
14 soil_moisture_pct
15 distance_to_river_m
16 observed_water_level_cm
17 previous_flood_flag

The model is expected to return either:
- probability in [0,1], or
- a regression/classification-compatible scalar.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


MODULE_DIR = Path(__file__).resolve().parent

def _env_model_path() -> str:
    return os.getenv("EWS_FLOOD_MODEL_PATH", "").strip()

def _env_model_type() -> str:
    return os.getenv("EWS_FLOOD_MODEL_TYPE", "auto").strip().lower()

def _env_model_version() -> str:
    return os.getenv("EWS_FLOOD_MODEL_VERSION", "unconfigured").strip()

FEATURE_NAMES = [
    "rainfall_obs_1h_mm",
    "rainfall_obs_6h_mm",
    "rainfall_obs_24h_mm",
    "rainfall_satellite_24h_mm",
    "rainfall_radar_1h_mm",
    "rainfall_radar_3h_mm",
    "nwp_rain_3h_mm",
    "nwp_rain_24h_mm",
    "temperature_c",
    "humidity_pct",
    "wind_speed_kmh",
    "elevation_m",
    "slope_deg",
    "soil_moisture_pct",
    "distance_to_river_m",
    "observed_water_level_cm",
    "previous_flood_flag",
]


@dataclass
class FloodSources:
    observational_weather: bool = False
    satellite: bool = False
    radar: bool = False
    nwp: bool = False

    def count(self) -> int:
        return sum(
            int(v)
            for v in (
                self.observational_weather,
                self.satellite,
                self.radar,
                self.nwp,
            )
        )


@dataclass
class PredictionResult:
    rainfall_early_warning: str
    flood_probability_pct: float
    hazard_tier: str
    inundation_probability_pct: float
    predicted_inundation_depth_m: Optional[float]
    lead_time_hours: Optional[float]
    model_type: str
    model_version: str
    model_ready: bool
    sources: FloodSources
    feature_count: int
    explanation: Dict[str, Any]


_model: Any = None
_model_error: Optional[str] = None


def _load_model() -> Any:
    global _model, _model_error
    if _model is not None:
        return _model
    model_path = _env_model_path()
    if not model_path:
        _model_error = "EWS_FLOOD_MODEL_PATH is not configured."
        return None
    path = Path(model_path)
    if not path.is_absolute():
        path = MODULE_DIR / path
    if not path.exists():
        _model_error = f"Configured model file does not exist: {path}"
        return None
    try:
        import joblib  # type: ignore

        _model = joblib.load(path)
        _model_error = None
        return _model
    except Exception as exc:
        _model_error = str(exc)
        return None


def model_status() -> Dict[str, Any]:
    model = _load_model()
    return {
        "configured": bool(_env_model_path()),
        "ready": model is not None,
        "path": _env_model_path() or None,
        "type": _env_model_type(),
        "version": _env_model_version(),
        "features": FEATURE_NAMES,
        "feature_count": len(FEATURE_NAMES),
        "load_error": _model_error,
        "note": (
            "Trained ML model is active."
            if model is not None
            else "No trained ML model is active; deterministic screening fallback is used."
        ),
    }


def _num(data: Dict[str, Any], key: str, default: float = 0.0) -> float:
    value = data.get(key, default)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return float(default)
    return value if value == value else float(default)


def build_feature_vector(data: Dict[str, Any]) -> list[float]:
    return [
        _num(data, key)
        for key in FEATURE_NAMES
    ]


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _screening_probability(data: Dict[str, Any]) -> float:
    obs6 = _num(data, "rainfall_obs_6h_mm")
    obs24 = _num(data, "rainfall_obs_24h_mm")
    sat24 = _num(data, "rainfall_satellite_24h_mm")
    radar1 = _num(data, "rainfall_radar_1h_mm")
    radar3 = _num(data, "rainfall_radar_3h_mm")
    nwp3 = _num(data, "nwp_rain_3h_mm")
    nwp24 = _num(data, "nwp_rain_24h_mm")
    humidity = _clip(_num(data, "humidity_pct"), 0, 100)
    elevation = max(0.0, _num(data, "elevation_m"))
    soil = _clip(_num(data, "soil_moisture_pct"), 0, 100)
    river = max(0.0, _num(data, "distance_to_river_m"))
    water = max(0.0, _num(data, "observed_water_level_cm"))
    previous = 1.0 if _num(data, "previous_flood_flag") > 0 else 0.0

    rain_score = (
        0.25 * _clip(obs6 / 120.0, 0, 1)
        + 0.20 * _clip(obs24 / 250.0, 0, 1)
        + 0.15 * _clip(sat24 / 250.0, 0, 1)
        + 0.10 * _clip(radar1 / 80.0, 0, 1)
        + 0.10 * _clip(radar3 / 140.0, 0, 1)
        + 0.10 * _clip(nwp3 / 120.0, 0, 1)
        + 0.10 * _clip(nwp24 / 250.0, 0, 1)
    )
    terrain_score = (
        0.45 * _clip((150.0 - elevation) / 150.0, 0, 1)
        + 0.25 * _clip(soil / 100.0, 0, 1)
        + 0.20 * _clip((1000.0 - river) / 1000.0, 0, 1)
        + 0.10 * previous
    )
    water_score = _clip(water / 150.0, 0, 1)
    humidity_score = humidity / 100.0

    probability = (
        0.62 * rain_score
        + 0.18 * terrain_score
        + 0.15 * water_score
        + 0.05 * humidity_score
    )
    return _clip(probability, 0.0, 1.0)


def _hazard(probability: float) -> str:
    if probability >= 0.80:
        return "CRITICAL"
    if probability >= 0.60:
        return "HIGH"
    if probability >= 0.35:
        return "MEDIUM"
    return "LOW"


def _early_warning(probability: float, data: Dict[str, Any]) -> str:
    nwp3 = _num(data, "nwp_rain_3h_mm")
    radar1 = _num(data, "rainfall_radar_1h_mm")
    if probability >= 0.80 or nwp3 >= 80 or radar1 >= 50:
        return "SEVERE HEAVY-RAINFALL / FLOOD WARNING"
    if probability >= 0.60 or nwp3 >= 50 or radar1 >= 30:
        return "HEAVY-RAINFALL / FLOOD WATCH"
    if probability >= 0.35:
        return "ELEVATED FLOOD MONITORING"
    return "NORMAL MONITORING"


def _fallback_depth(data: Dict[str, Any], probability: float) -> Optional[float]:
    water_cm = _num(data, "observed_water_level_cm")
    if water_cm <= 0 and probability < 0.35:
        return None
    rainfall_factor = _clip(
        (
            _num(data, "rainfall_obs_24h_mm")
            + _num(data, "rainfall_satellite_24h_mm")
            + _num(data, "nwp_rain_24h_mm")
        ) / 600.0,
        0,
        1,
    )
    depth = (
        (water_cm / 100.0) * 0.60
        + rainfall_factor * 1.20
        + probability * 0.80
    )
    return round(_clip(depth, 0.10, 3.50), 2)


def _predict_trained(model: Any, vector: Sequence[float]) -> Optional[float]:
    try:
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba([list(vector)])
            if hasattr(proba, "__len__") and len(proba):
                row = proba[0]
                if hasattr(row, "__len__") and len(row) >= 2:
                    return _clip(float(row[-1]), 0, 1)
        if hasattr(model, "predict"):
            prediction = model.predict([list(vector)])
            value = float(prediction[0])
            if value > 1.0:
                value = value / 100.0
            return _clip(value, 0, 1)
    except Exception:
        return None
    return None


def predict(data: Dict[str, Any]) -> PredictionResult:
    vector = build_feature_vector(data)
    sources = FloodSources(
        observational_weather=bool(data.get("observational_weather_available")),
        satellite=bool(data.get("satellite_available")),
        radar=bool(data.get("radar_available")),
        nwp=bool(data.get("nwp_available")),
    )

    model = _load_model()
    probability = _predict_trained(model, vector) if model is not None else None
    trained = probability is not None
    if probability is None:
        probability = _screening_probability(data)

    tier = _hazard(probability)
    lead_time = data.get("lead_time_hours")
    try:
        lead_time = float(lead_time) if lead_time is not None else None
    except (TypeError, ValueError):
        lead_time = None

    depth = data.get("predicted_inundation_depth_m")
    try:
        depth = float(depth) if depth is not None else None
    except (TypeError, ValueError):
        depth = None
    if depth is None and not trained:
        depth = _fallback_depth(data, probability)

    return PredictionResult(
        rainfall_early_warning=_early_warning(probability, data),
        flood_probability_pct=round(probability * 100.0, 2),
        hazard_tier=tier,
        inundation_probability_pct=round(probability * 100.0, 2),
        predicted_inundation_depth_m=(round(depth, 2) if depth is not None else None),
        lead_time_hours=lead_time,
        model_type=("trained_ml" if trained else "multi_source_screening_fallback"),
        model_version=(_env_model_version() if trained else "screening-1.0"),
        model_ready=trained,
        sources=sources,
        feature_count=len(FEATURE_NAMES),
        explanation={
            "source_count": sources.count(),
            "source_fusion": [
                "observational_weather",
                "satellite",
                "radar",
                "nwp",
            ],
            "feature_names": FEATURE_NAMES,
            "model_error": _model_error if not trained else None,
            "disclaimer": (
                "Output is from a configured trained ML model."
                if trained
                else "Output is a deterministic screening fallback and must not be represented as trained AI/ML."
            ),
        },
    )


def prediction_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    result = predict(data)
    payload = asdict(result)
    payload["sources"] = asdict(result.sources)
    return payload


def model_metadata() -> Dict[str, Any]:
    return {
        "project_statement": (
            "AI/ML-Based Integrated heavy rainfall Early Warning and "
            "Inundation Prediction System using Satellite, Radar, "
            "observational Weather and numerical weather prediction model data."
        ),
        "model": model_status(),
        "feature_schema": FEATURE_NAMES,
    }


if __name__ == "__main__":
    print(json.dumps(model_metadata(), indent=2))
