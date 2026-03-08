"""Analytics API."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from app.core.database import get_db
from app.core.deps import require_admin, require_client
from app.models.user import User
from app.models.test_attempt import TestAttempt, AttemptStatus
from app.models.job import JobDescription
from app.models.client import Client
from app.models.assessment import Assessment

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/platform")
async def platform_analytics(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    total_attempts = await db.execute(select(func.count(TestAttempt.id)))
    scored = await db.execute(select(func.count(TestAttempt.id)).where(TestAttempt.status == AttemptStatus.SCORED))
    qualified = await db.execute(select(func.count(TestAttempt.id)).where(TestAttempt.is_qualified == True))
    avg_score = await db.execute(select(func.avg(TestAttempt.total_score)).where(TestAttempt.total_score.isnot(None)))

    # Badge distribution
    for_badge = await db.execute(
        select(TestAttempt.rating_badge, func.count(TestAttempt.id))
        .where(TestAttempt.rating_badge.isnot(None))
        .group_by(TestAttempt.rating_badge)
    )
    badge_dist = {row[0].value if row[0] else "none": row[1] for row in for_badge}

    # Drop-off rate: invited but not submitted
    invited = await db.execute(select(func.count(TestAttempt.id)).where(TestAttempt.status == AttemptStatus.INVITED))
    submitted = await db.execute(select(func.count(TestAttempt.id)).where(TestAttempt.status.in_([AttemptStatus.SUBMITTED, AttemptStatus.SCORED])))

    inv_count = invited.scalar() or 0
    sub_count = submitted.scalar() or 0
    dropoff = round(((inv_count) / (inv_count + sub_count) * 100) if (inv_count + sub_count) > 0 else 0, 2)

    return {
        "total_attempts": total_attempts.scalar(),
        "scored_attempts": scored.scalar(),
        "qualified_candidates": qualified.scalar(),
        "average_score": round(avg_score.scalar() or 0, 2),
        "badge_distribution": badge_dist,
        "candidate_dropoff_rate_percent": dropoff,
        "submission_rate_percent": round(100 - dropoff, 2),
    }


@router.get("/client")
async def client_analytics(db: AsyncSession = Depends(get_db), current_user: User = Depends(require_client)):
    client_res = await db.execute(select(Client).where(Client.user_id == current_user.id))
    client = client_res.scalar_one_or_none()

    total_jds = await db.execute(select(func.count(JobDescription.id)).where(JobDescription.client_id == client.id))

    attempts_join = (
        select(func.count(TestAttempt.id))
        .join(Assessment, TestAttempt.assessment_id == Assessment.id)
        .join(JobDescription, Assessment.job_description_id == JobDescription.id)
        .where(JobDescription.client_id == client.id)
    )
    total_candidates = await db.execute(attempts_join)
    qualified = await db.execute(
        attempts_join.where(TestAttempt.is_qualified == True)
    )
    avg_score_q = await db.execute(
        select(func.avg(TestAttempt.total_score))
        .join(Assessment, TestAttempt.assessment_id == Assessment.id)
        .join(JobDescription, Assessment.job_description_id == JobDescription.id)
        .where(and_(JobDescription.client_id == client.id, TestAttempt.total_score.isnot(None)))
    )

    total_c_val = total_candidates.scalar() or 0
    qualified_val = qualified.scalar() or 0

    return {
        "total_roles": total_jds.scalar() or 0,
        "total_candidates_assessed": total_c_val,
        "qualified_candidates": qualified_val,
        "average_score": round(avg_score_q.scalar() or 0, 2),
        "conversion_rate": round(
            (qualified_val / (total_c_val or 1)) * 100, 2
        ),
    }
