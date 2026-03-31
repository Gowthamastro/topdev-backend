"""Candidate APIs — profile management, test taking, results."""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from app.core.database import get_db
from app.core.deps import get_current_user, require_candidate
from app.models.user import User
from app.models.candidate import Candidate
from app.models.test_attempt import TestAttempt, AttemptStatus
from app.models.assessment import Assessment, Question
from app.models.job import JobDescription
from app.models.admin import PlatformSettings
from app.services.storage_service import upload_file, get_signed_url
from app.workers.tasks import score_test_attempt_task
from app.core.config import settings

router = APIRouter(prefix="/candidates", tags=["candidates"])


@router.get("/profile")
async def get_profile(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(Candidate).where(Candidate.user_id == current_user.id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(404, "Candidate profile not found")
    resume_url = None
    if candidate.resume_s3_key:
        resume_url = get_signed_url(candidate.resume_s3_key)
    return {**candidate.__dict__, "resume_signed_url": resume_url}


@router.post("/resume")
async def upload_resume(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_candidate),
):
    result = await db.execute(select(Candidate).where(Candidate.user_id == current_user.id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    content = await file.read()
    s3_key = await upload_file(content, file.filename, folder="resumes")
    if not s3_key:
        raise HTTPException(500, "File upload failed")
    candidate.resume_s3_key = s3_key
    await db.commit()
    return {"message": "Resume uploaded", "s3_key": s3_key}


# ─── Test Taking ─────────────────────────────────────────────────────────────

@router.get("/test/{token}")
async def get_test_by_token(token: str, db: AsyncSession = Depends(get_db)):
    """Public endpoint — fetch test by secure token."""
    result = await db.execute(select(TestAttempt).where(TestAttempt.token == token))
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(404, "Invalid test link")
    now = datetime.now(timezone.utc)
    if attempt.token_expires_at and attempt.token_expires_at < now:
        attempt.status = AttemptStatus.EXPIRED
        await db.commit()
        raise HTTPException(410, "Test link has expired")
    if attempt.status == AttemptStatus.SUBMITTED:
        raise HTTPException(400, "Test already submitted")

    # Load questions (without correct answers!)
    q_result = await db.execute(
        select(Question).where(Question.assessment_id == attempt.assessment_id).order_by(Question.order_index)
    )
    questions = q_result.scalars().all()

    assessment_result = await db.execute(select(Assessment).where(Assessment.id == attempt.assessment_id))
    assessment = assessment_result.scalar_one_or_none()
    jd_result = await db.execute(select(JobDescription).where(JobDescription.id == attempt.job_description_id))
    jd = jd_result.scalar_one_or_none()

    return {
        "attempt_id": attempt.id,
        "assessment": {"id": assessment.id, "title": assessment.title, "time_limit_minutes": assessment.time_limit_minutes},
        "role": jd.title if jd else "",
        "questions": [
            {
                "id": q.id,
                "type": getattr(q.question_type, "value", q.question_type),
                "text": q.question_text,
                "options": q.options,
                "order": q.order_index,
            }
            for q in questions
        ],
    }


@router.post("/test/{token}/start")
async def start_test(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TestAttempt).where(TestAttempt.token == token))
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(404, "Invalid token")
    if attempt.status not in (AttemptStatus.INVITED,):
        raise HTTPException(400, f"Cannot start test in status {attempt.status.value}")
    attempt.status = AttemptStatus.STARTED
    attempt.started_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "Test started"}


class SubmitAnswersRequest(BaseModel):
    answers: dict  # {question_id: answer_text}


@router.post("/test/{token}/submit")
async def submit_test(token: str, data: SubmitAnswersRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TestAttempt).where(TestAttempt.token == token))
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(404, "Invalid token")
    if attempt.status == AttemptStatus.SUBMITTED:
        raise HTTPException(400, "Already submitted")
    if attempt.token_expires_at and attempt.token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(410, "Link expired")

    attempt.answers = data.answers
    attempt.status = AttemptStatus.SUBMITTED
    attempt.submitted_at = datetime.now(timezone.utc)
    await db.commit()

    # Enqueue scoring task
    score_test_attempt_task.delay(attempt.id)

    return {"message": "Answers submitted successfully. Results will be available shortly."}


@router.get("/results/{attempt_id}")
async def get_results(attempt_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(TestAttempt).where(TestAttempt.id == attempt_id))
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(404, "Not found")
    return {
        "status": attempt.status.value,
        "total_score": attempt.total_score,
        "technical_score": attempt.technical_score,
        "communication_score": attempt.communication_score,
        "cultural_fit_score": attempt.cultural_fit_score,
        "rating_badge": attempt.rating_badge.value if attempt.rating_badge else None,
        "is_qualified": attempt.is_qualified,
    }
