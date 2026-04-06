"""Assessments API — invite candidates, manage test links."""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.core.deps import require_client, get_current_user
from app.models.user import User, UserRole
from app.models.client import Client
from app.models.candidate import Candidate
from app.models.job import JobDescription
from app.models.assessment import Assessment
from app.models.test_attempt import TestAttempt, AttemptStatus, RatingBadge
from app.models.admin import PlatformSettings, ScoringWeights
from app.core.config import settings
from app.core.security import get_password_hash
from app.workers.tasks import send_test_invitation_task
from app.ai.gemini_service import score_answers
import secrets

router = APIRouter(prefix="/assessments", tags=["assessments"])


async def get_setting(db: AsyncSession, key: str, default: str) -> str:
    result = await db.execute(select(PlatformSettings).where(PlatformSettings.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else default


class InviteCandidateRequest(BaseModel):
    candidate_email: EmailStr
    candidate_name: str
    job_description_id: int


@router.post("/invite")
async def invite_candidate(
    data: InviteCandidateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_client),
):
    """Invite a candidate — creates user account if needed, generates secure test link."""
    # Verify assessment belongs to client
    client_res = await db.execute(select(Client).where(Client.user_id == current_user.id))
    client = client_res.scalar_one_or_none()
    jd_res = await db.execute(select(JobDescription).where(JobDescription.id == data.job_description_id))
    jd = jd_res.scalar_one_or_none()
    if not jd or jd.client_id != client.id:
        raise HTTPException(403, "Access denied")

    # Get assessment for this JD (assumes 1-to-1 in MVP)
    assmt_res = await db.execute(select(Assessment).where(Assessment.job_description_id == jd.id))
    assessment = assmt_res.scalars().first()
    if not assessment:
        raise HTTPException(404, "Assessment not found for this Job Description")

    # Get or create candidate user
    user_res = await db.execute(select(User).where(User.email == data.candidate_email))
    cand_user = user_res.scalar_one_or_none()
    if not cand_user:
        cand_user = User(
            email=data.candidate_email,
            full_name=data.candidate_name,
            hashed_password=get_password_hash(secrets.token_urlsafe(16)),
            role=UserRole.CANDIDATE,
        )
        db.add(cand_user)
        await db.flush()
        candidate = Candidate(user_id=cand_user.id)
        db.add(candidate)
        await db.flush()
    else:
        cand_res = await db.execute(select(Candidate).where(Candidate.user_id == cand_user.id))
        candidate = cand_res.scalar_one_or_none()
        if not candidate:
            candidate = Candidate(user_id=cand_user.id)
            db.add(candidate)
            await db.flush()

    # Token expiry
    expiry_hours = int(await get_setting(db, "test_link_expiry_hours", "48"))
    expires_at = datetime.now(timezone.utc) + timedelta(hours=expiry_hours)

    attempt = TestAttempt(
        assessment_id=assessment.id,
        candidate_id=candidate.id,
        job_description_id=jd.id,
        token_expires_at=expires_at,
        status=AttemptStatus.INVITED,
    )
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)

    # Build test link (frontend URL)
    frontend_url = await get_setting(db, "frontend_url", "http://localhost:5173")
    test_link = f"{frontend_url}/test/{attempt.token}"

    # Send email via Celery
    send_test_invitation_task.delay(
        candidate_name=data.candidate_name,
        candidate_email=data.candidate_email,
        test_link=test_link,
        role_title=jd.title,
        company_name=client.company_name,
        expires_hours=expiry_hours,
    )

    return {"message": "Invitation sent", "attempt_id": attempt.id, "test_link": test_link}


@router.get("/job/{jd_id}/attempts")
async def list_attempts(jd_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_client)):
    result = await db.execute(
        select(TestAttempt)
        .options(joinedload(TestAttempt.candidate).joinedload(Candidate.user))
        .where(TestAttempt.job_description_id == jd_id)
        .order_by(TestAttempt.total_score.desc())
    )
    attempts = result.scalars().all()
    return [{
        "id": a.id,
        "token": a.token,
        "candidate_name": a.candidate.user.full_name if a.candidate and a.candidate.user else "Unknown",
        "candidate_email": a.candidate.user.email if a.candidate and a.candidate.user else "Unknown",
        "status": getattr(a.status, "value", a.status),
        "total_score": a.total_score,
        "technical_score": a.technical_score,
        "communication_score": a.communication_score,
        "cultural_fit_score": a.cultural_fit_score,
        "badge": getattr(a.rating_badge, "value", a.rating_badge) if a.rating_badge else None,
        "qualified": a.is_qualified,
        "ai_feedback": a.ai_feedback
    } for a in attempts]


@router.get("/job/{jd_id}/details")
async def get_assessment_details(jd_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_client)):
    # Verify client owns this job
    client_res = await db.execute(select(Client).where(Client.user_id == current_user.id))
    client = client_res.scalar_one_or_none()
    jd_res = await db.execute(select(JobDescription).where(JobDescription.id == jd_id))
    jd = jd_res.scalar_one_or_none()
    if not jd or jd.client_id != client.id:
        raise HTTPException(403, "Access denied")

    # Get assessment and eager load its questions
    assmt_res = await db.execute(
        select(Assessment)
        .options(joinedload(Assessment.questions))
        .where(Assessment.job_description_id == jd_id)
    )
    assessment = assmt_res.scalars().first()
    
    if not assessment:
        raise HTTPException(404, "Assessment not found for this Job Description")

    return {
        "id": assessment.id,
        "title": assessment.title,
        "description": assessment.description,
        "mcq_count": assessment.mcq_count,
        "coding_count": assessment.coding_count,
        "scenario_count": assessment.scenario_count,
        "time_limit_minutes": assessment.time_limit_minutes,
        "questions": [
            {
                "id": q.id,
                "type": getattr(q.question_type, "value", q.question_type),
                "text": q.question_text,
                "options": q.options,
                "correct_answer": q.correct_answer,
                "explanation": q.explanation,
                "difficulty": q.difficulty,
                "skills_tested": q.skills_tested,
                "max_score": q.max_score,
                "order_index": q.order_index
            } for q in sorted(assessment.questions, key=lambda x: x.order_index) if assessment.questions
        ]
    }

@router.get("/test/{token}")
async def get_test_for_candidate(token: str, db: AsyncSession = Depends(get_db)):
    """Fetch test details for a candidate using their secure token."""
    # Find active attempt by token
    attempt_res = await db.execute(
        select(TestAttempt)
        .options(selectinload(TestAttempt.candidate).selectinload(Candidate.user))
        .where(TestAttempt.token == token)
    )
    attempt = attempt_res.scalar_one_or_none()
    
    if not attempt:
        raise HTTPException(status_code=404, detail="Test link invalid or not found")
        
    if attempt.token_expires_at and attempt.token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Test link has expired")
        
    if attempt.status != AttemptStatus.INVITED and attempt.status != AttemptStatus.STARTED:
        raise HTTPException(status_code=400, detail=f"Test attempt is already {getattr(attempt.status, 'value', attempt.status)}")
        
    # Get the assessment and eager load the questions
    assmt_res = await db.execute(
        select(Assessment)
        .options(selectinload(Assessment.questions))
        .where(Assessment.id == attempt.assessment_id)
    )
    assessment = assmt_res.scalars().first()
    
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
        
    # Mark test as STARTED if this is the first time they open it
    if attempt.status == AttemptStatus.INVITED:
        attempt.status = AttemptStatus.STARTED
        if not attempt.started_at:
            attempt.started_at = datetime.now(timezone.utc)
        await db.commit()

    return {
        "attempt_id": attempt.id,
        "candidate_name": attempt.candidate.user.full_name,
        "assessment_title": assessment.title,
        "time_limit_minutes": assessment.time_limit_minutes,
        "has_coding_round": assessment.has_coding_round,
        "questions": [
            {
                "id": q.id,
                "type": getattr(q.question_type, "value", q.question_type),
                "text": q.question_text,
                # ONLY return options, NEVER correct_answer or explanation
                "options": q.options,
                "difficulty": q.difficulty,
                "max_score": q.max_score,
                "order_index": q.order_index
            } for q in sorted(assessment.questions, key=lambda x: x.order_index) if assessment.questions
        ]
    }

