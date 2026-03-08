"""Client dashboard APIs — view candidates, ranked results, download profiles."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from app.core.database import get_db
from app.core.deps import require_client, get_current_user
from app.models.user import User
from app.models.client import Client
from app.models.test_attempt import TestAttempt, AttemptStatus, RatingBadge
from app.models.candidate import Candidate
from app.models.job import JobDescription
from app.models.assessment import Assessment
from app.services.storage_service import get_signed_url

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("/dashboard")
async def client_dashboard(db: AsyncSession = Depends(get_db), current_user: User = Depends(require_client)):
    client_res = await db.execute(select(Client).where(Client.user_id == current_user.id))
    client = client_res.scalar_one_or_none()
    if not client:
        raise HTTPException(404, "Client not found")

    # Stats
    total_jobs = await db.execute(select(func.count(JobDescription.id)).where(JobDescription.client_id == client.id))
    total_candidates = await db.execute(
        select(func.count(TestAttempt.id))
        .join(Assessment, TestAttempt.assessment_id == Assessment.id)
        .join(JobDescription, Assessment.job_description_id == JobDescription.id)
        .where(JobDescription.client_id == client.id)
    )
    qualified_count = await db.execute(
        select(func.count(TestAttempt.id))
        .join(Assessment, TestAttempt.assessment_id == Assessment.id)
        .join(JobDescription, Assessment.job_description_id == JobDescription.id)
        .where(and_(JobDescription.client_id == client.id, TestAttempt.is_qualified == True))
    )

    return {
        "client": {"id": client.id, "company_name": client.company_name, "plan": client.subscription_plan, "roles_used": client.roles_used_this_month},
        "stats": {
            "total_jobs": total_jobs.scalar(),
            "total_candidates": total_candidates.scalar(),
            "qualified_candidates": qualified_count.scalar(),
        }
    }


@router.get("/jobs/{jd_id}/candidates")
async def get_candidates_for_job(
    jd_id: int,
    min_score: float = Query(None),
    badge: str = Query(None),
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_client),
):
    """Get ranked candidate list for a job — only qualified candidates shown."""
    client_res = await db.execute(select(Client).where(Client.user_id == current_user.id))
    client = client_res.scalar_one_or_none()
    jd_res = await db.execute(select(JobDescription).where(JobDescription.id == jd_id))
    jd = jd_res.scalar_one_or_none()
    if not jd or jd.client_id != client.id:
        raise HTTPException(403, "Access denied")

    query = (
        select(TestAttempt, Candidate)
        .join(Candidate, TestAttempt.candidate_id == Candidate.id)
        .join(Assessment, TestAttempt.assessment_id == Assessment.id)
        .where(
            and_(
                Assessment.job_description_id == jd_id,
                TestAttempt.status == AttemptStatus.SCORED,
                TestAttempt.is_qualified == True,
            )
        )
    )
    if min_score is not None:
        query = query.where(TestAttempt.total_score >= min_score)
    if badge:
        query = query.where(TestAttempt.rating_badge == badge)

    query = query.order_by(TestAttempt.total_score.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    rows = result.all()

    candidates_data = []
    for attempt, candidate in rows:
        resume_url = None
        if candidate.resume_s3_key:
            resume_url = get_signed_url(candidate.resume_s3_key)
        # Load user info
        user_res = await db.execute(select(User).where(User.id == candidate.user_id))
        user = user_res.scalar_one_or_none()
        candidates_data.append({
            "attempt_id": attempt.id,
            "candidate_id": candidate.id,
            "name": user.full_name if user else "",
            "email": user.email if user else "",
            "total_score": attempt.total_score,
            "technical_score": attempt.technical_score,
            "coding_score": attempt.coding_score,
            "problem_solving_score": attempt.problem_solving_score,
            "rating_badge": attempt.rating_badge.value if attempt.rating_badge else None,
            "skills": candidate.skills,
            "years_experience": candidate.years_of_experience,
            "resume_url": resume_url,
            "submitted_at": attempt.submitted_at,
        })

    return {"job_title": jd.title, "candidates": candidates_data, "total": len(candidates_data)}


@router.get("/candidates/{attempt_id}/breakdown")
async def get_score_breakdown(attempt_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_client)):
    result = await db.execute(select(TestAttempt).where(TestAttempt.id == attempt_id))
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(404, "Not found")
    return {
        "total_score": attempt.total_score,
        "technical_score": attempt.technical_score,
        "coding_score": attempt.coding_score,
        "problem_solving_score": attempt.problem_solving_score,
        "score_breakdown": attempt.score_breakdown,
        "ai_feedback": attempt.ai_feedback,
        "rating_badge": attempt.rating_badge.value if attempt.rating_badge else None,
    }
