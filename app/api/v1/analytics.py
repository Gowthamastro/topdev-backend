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

    def get_count_query(stage=None):
        q = (
            select(func.count(TestAttempt.id))
            .join(Assessment, TestAttempt.assessment_id == Assessment.id)
            .join(JobDescription, Assessment.job_description_id == JobDescription.id)
            .where(JobDescription.client_id == client.id)
        )
        if stage:
            q = q.where(TestAttempt.pipeline_stage == stage)
        return q

    total_candidates_res = await db.execute(get_count_query())
    total_candidates = total_candidates_res.scalar() or 0
    
    interview_res = await db.execute(get_count_query('interview'))
    active_interviews = interview_res.scalar() or 0
    
    offers_res = await db.execute(get_count_query('offered'))
    offers_extended = offers_res.scalar() or 0
    
    hired_res = await db.execute(get_count_query('hired'))
    hired = hired_res.scalar() or 0
    
    acceptance_rate = round((hired / offers_extended) * 100, 1) if offers_extended > 0 else 0.0

    # Funnel
    funnel_stages = ['sourced', 'applied', 'screened', 'interview', 'offered', 'hired']
    funnel_data = []
    for stage in funnel_stages:
        count_res = await db.execute(get_count_query(stage))
        funnel_data.append({"stage": stage.capitalize(), "count": count_res.scalar() or 0})

    # Top Roles
    top_roles_res = await db.execute(
        select(JobDescription.title, func.count(TestAttempt.id))
        .join(Assessment, TestAttempt.assessment_id == Assessment.id)
        .join(JobDescription, Assessment.job_description_id == JobDescription.id)
        .where(JobDescription.client_id == client.id)
        .group_by(JobDescription.title)
        .order_by(func.count(TestAttempt.id).desc())
        .limit(4)
    )
    top_roles = [{"role": row[0], "count": row[1]} for row in top_roles_res]

    # Growth velocity — empty until real time-series tracking is implemented
    growth_velocity = []

    return {
        "kpis": {
            "active_interviews": active_interviews,
            "total_candidates": total_candidates,
            "offers_extended": offers_extended,
            "acceptance_rate": acceptance_rate
        },
        "funnel": funnel_data,
        "growth_velocity": growth_velocity,
        "top_roles": top_roles
    }


@router.get("/dashboard")
async def client_dashboard_analytics(db: AsyncSession = Depends(get_db), current_user: User = Depends(require_client)):
    client_res = await db.execute(select(Client).where(Client.user_id == current_user.id))
    client = client_res.scalar_one_or_none()
    if not client:
        return {"active_roles": 0, "qualified_candidates": 0, "avg_ai_score": 0, "pipeline_activity": 0}

    # Active Roles
    roles_res = await db.execute(select(func.count(JobDescription.id)).where(JobDescription.client_id == client.id))
    active_roles = roles_res.scalar() or 0

    # Pipeline Activity (Total Attempts)
    activity_res = await db.execute(
        select(func.count(TestAttempt.id))
        .join(Assessment, TestAttempt.assessment_id == Assessment.id)
        .join(JobDescription, Assessment.job_description_id == JobDescription.id)
        .where(JobDescription.client_id == client.id)
    )
    pipeline_activity = activity_res.scalar() or 0

    # Qualified Candidates
    qualified_res = await db.execute(
        select(func.count(TestAttempt.id))
        .join(Assessment, TestAttempt.assessment_id == Assessment.id)
        .join(JobDescription, Assessment.job_description_id == JobDescription.id)
        .where(JobDescription.client_id == client.id, TestAttempt.is_qualified == True)
    )
    qualified_candidates = qualified_res.scalar() or 0

    # Avg AI Score
    avg_score_res = await db.execute(
        select(func.avg(TestAttempt.total_score))
        .join(Assessment, TestAttempt.assessment_id == Assessment.id)
        .join(JobDescription, Assessment.job_description_id == JobDescription.id)
        .where(JobDescription.client_id == client.id, TestAttempt.total_score.isnot(None))
    )
    avg_ai_score = round(avg_score_res.scalar() or 0, 1)

    return {
        "active_roles": active_roles,
        "qualified_candidates": qualified_candidates,
        "avg_ai_score": avg_ai_score,
        "pipeline_activity": pipeline_activity,
        "time_to_hire": 18 if pipeline_activity > 0 else 0, # Mocked for now
        "trends": {
            "roles": 2 if active_roles > 0 else 0,
            "candidates": -5 if qualified_candidates > 0 else 0,
            "score": 3 if avg_ai_score > 0 else 0,
            "activity": 12 if pipeline_activity > 0 else 0
        }
    }
