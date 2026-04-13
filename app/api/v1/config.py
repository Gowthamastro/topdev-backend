"""Public feature-flags endpoint — exposes Phase 1 gating to the frontend."""
from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/features")
async def get_feature_flags():
    """Returns current feature-flag state.  No auth required so the UI can
    decide what to render before the user even logs in."""
    return {
        "assessments_enabled": settings.ENABLE_ASSESSMENTS,
        "ai_features_enabled": settings.ENABLE_AI_FEATURES,
        "advanced_analytics_enabled": settings.ENABLE_ADVANCED_ANALYTICS,
    }
