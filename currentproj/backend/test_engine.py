from dataclasses import dataclass
from typing import List


@dataclass
class RiskResult:
    probability_pct: float
    hazard_tier: str
    directive: str


class OdishaFloodRiskEngine:
    """
    Deterministic flood-risk scoring engine.

    IMPORTANT:
    This is a risk-estimation model, not an official IMD flood warning.
    Replace the coefficients with coefficients trained from verified
    historical Odisha flood observations when that dataset is available.
    """

    def calculate(
        self,
        rainfall_24h_mm: float,
        rainfall_6h_mm: float,
        elevation_m: float,
        vulnerability_index: float,
    ) -> RiskResult:

        rainfall_24h_mm = max(0.0, float(rainfall_24h_mm))
        rainfall_6h_mm = max(0.0, float(rainfall_6h_mm))
        elevation_m = max(0.0, float(elevation_m))
        vulnerability_index = min(
            1.0,
            max(0.0, float(vulnerability_index))
        )

        # ------------------------------------------------------
        # Rainfall component
        # ------------------------------------------------------

        rain_score = min(
            rainfall_24h_mm / 150.0,
            1.0
        )

        short_term_score = min(
            rainfall_6h_mm / 80.0,
            1.0
        )

        # ------------------------------------------------------
        # Low elevation component
        # ------------------------------------------------------

        elevation_score = max(
            0.0,
            min(
                1.0,
                1.0 - (elevation_m / 100.0)
            )
        )

        # ------------------------------------------------------
        # Combined environmental risk
        # ------------------------------------------------------

        score = (
            rain_score * 0.45
            + short_term_score * 0.20
            + elevation_score * 0.15
            + vulnerability_index * 0.20
        )

        score = max(
            0.0,
            min(1.0, score)
        )

        probability = round(
            score * 100.0,
            2
        )

        # ------------------------------------------------------
        # Hazard classification
        # ------------------------------------------------------

        if probability >= 70:
            tier = "CRITICAL"

            directive = (
                "Critical rainfall and environmental risk detected. "
                "Follow official district/Panchayat emergency instructions."
            )

        elif probability >= 35:
            tier = "HIGH RISK"

            directive = (
                "Elevated flood-risk conditions detected. "
                "Continue close monitoring and follow official advisories."
            )

        else:
            tier = "NORMAL"

            directive = (
                "No elevated risk detected by the current model inputs. "
                "Continue routine monitoring."
            )

        return RiskResult(
            probability_pct=probability,
            hazard_tier=tier,
            directive=directive,
        )