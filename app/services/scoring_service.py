"""
Scoring Service — computes final weighted candidate score and assigns rating badge.
Weights are read from the ScoringWeights table (admin-editable).
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.admin import ScoringWeights
from app.models.test_attempt import RatingBadge


PLAN_ROLE_LIMITS = {
    "free": 5,
    "starter": 5,
    "growth": 20,
    "enterprise": 9999,
}


async def get_active_weights(db: AsyncSession) -> ScoringWeights:
    result = await db.execute(
        select(ScoringWeights).where(ScoringWeights.is_default == True)
    )
    weights = result.scalar_one_or_none()
    if not weights:
        # Fallback to defaults
        return ScoringWeights(
            technical_weight=0.40,
            communication_weight=0.40,
            cultural_fit_weight=0.20,
            qualification_threshold=60.0,
        )
    return weights


def compute_weighted_score(
    technical_raw: float,
    communication_raw: float,
    cultural_fit_raw: float,
    technical_max: float,
    communication_max: float,
    cultural_fit_max: float,
    weights: ScoringWeights,
) -> dict:
    """Compute final 0-100 score from raw category scores."""
    t_pct = (technical_raw / technical_max * 100) if technical_max > 0 else 0
    c_pct = (communication_raw / communication_max * 100) if communication_max > 0 else 0
    cf_pct = (cultural_fit_raw / cultural_fit_max * 100) if cultural_fit_max > 0 else 0

    final = (
        t_pct * weights.technical_weight
        + c_pct * weights.communication_weight
        + cf_pct * weights.cultural_fit_weight
    )

    return {
        "technical_score": round(t_pct, 2),
        "communication_score": round(c_pct, 2),
        "cultural_fit_score": round(cf_pct, 2),
        "total_score": round(final, 2),
    }


def assign_badge(score: float, threshold: float) -> tuple[RatingBadge, bool]:
    """Assign rating badge and qualification status."""
    if score >= 90:
        return RatingBadge.ELITE, True
    elif score >= 75:
        return RatingBadge.STRONG, True
    elif score >= threshold:
        return RatingBadge.QUALIFIED, True
    else:
        return RatingBadge.BELOW_THRESHOLD, False
