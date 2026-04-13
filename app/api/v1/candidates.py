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
import io
try:
    import PyPDF2
except ImportError:
    PyPDF2 = None
from app.ai.gemini_service import parse_resume_for_profile, generate_assessment
from app.services.storage_service import upload_file, get_signed_url
from app.workers.tasks import score_test_attempt_task, compute_integrity_score_task
from app.core.config import settings

router = APIRouter(prefix="/candidates", tags=["candidates"])


# ─── Required fields for profile completion ───────────────────────────────────
PROFILE_REQUIRED_FIELDS = [
    "phone", "years_of_experience", "current_salary",
    "expected_salary", "resume_s3_key",
]


@router.get("/profile")
async def get_profile(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(Candidate).where(Candidate.user_id == current_user.id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(404, "Candidate profile not found")
    resume_url = None
    if candidate.resume_s3_key:
        resume_url = get_signed_url(candidate.resume_s3_key)
    return {
        **candidate.__dict__,
        "resume_signed_url": resume_url,
        "is_profile_complete": candidate.is_profile_complete,
        "phone_verified": candidate.phone_verified,
    }


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


# ─── My Attempts (Dashboard) ──────────────────────────────────────────────────

@router.get("/my-attempts")
async def get_my_attempts(db: AsyncSession = Depends(get_db), current_user: User = Depends(require_candidate)):
    """Returns all test attempts for the logged-in candidate — for the dashboard."""
    result = await db.execute(select(Candidate).where(Candidate.user_id == current_user.id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(404, "Candidate not found")

    att_res = await db.execute(
        select(TestAttempt).where(TestAttempt.candidate_id == candidate.id).order_by(TestAttempt.created_at.desc())
    )
    attempts = att_res.scalars().all()

    output = []
    for a in attempts:
        # Get role title
        role_title = None
        company = None
        if a.job_description_id:
            jd_res = await db.execute(select(JobDescription).where(JobDescription.id == a.job_description_id))
            jd = jd_res.scalar_one_or_none()
            if jd:
                role_title = jd.title
                from app.models.client import Client
                cl_res = await db.execute(select(Client).where(Client.id == jd.client_id))
                cl = cl_res.scalar_one_or_none()
                company = cl.company_name if cl else "TopDev Client"
        else:
            # Self-onboarding generic assessment
            ass_res = await db.execute(select(Assessment).where(Assessment.id == a.assessment_id))
            ass = ass_res.scalar_one_or_none()
            role_title = ass.title if ass else "General Screening Test"
            company = "TopDev"

        output.append({
            "id": a.id,
            "token": a.token,
            "role_title": role_title,
            "company": company,
            "status": getattr(a.status, "value", a.status),
            "total_score": a.total_score,
            "technical_score": a.technical_score,
            "communication_score": a.communication_score,
            "cultural_fit_score": a.cultural_fit_score,
            "rating_badge": getattr(a.rating_badge, "value", a.rating_badge) if a.rating_badge else None,
            "is_qualified": a.is_qualified,
            "ai_feedback": a.ai_feedback,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
        })

    return output


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
    # Enqueue integrity / proctoring analysis
    compute_integrity_score_task.delay(attempt.id)

    return {
        "message": "Answers submitted successfully. Results will be available shortly.",
        "attempt_id": attempt.id,
    }


@router.get("/results/{attempt_id}")
async def get_results(attempt_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(TestAttempt).where(TestAttempt.id == attempt_id))
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(404, "Not found")
    return {
        "status": getattr(attempt.status, "value", attempt.status),
        "total_score": attempt.total_score,
        "technical_score": attempt.technical_score,
        "communication_score": attempt.communication_score,
        "cultural_fit_score": attempt.cultural_fit_score,
        "rating_badge": getattr(attempt.rating_badge, "value", attempt.rating_badge) if attempt.rating_badge else None,
        "is_qualified": attempt.is_qualified,
        "ai_feedback": attempt.ai_feedback,
        "score_breakdown": attempt.score_breakdown,
    }


@router.get("/results/by-token/{token}")
async def get_results_by_token(token: str, db: AsyncSession = Depends(get_db)):
    """Public endpoint — get results by test token (no auth required, used after submission)."""
    result = await db.execute(select(TestAttempt).where(TestAttempt.token == token))
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(404, "Not found")
    if attempt.status not in (AttemptStatus.SUBMITTED, AttemptStatus.SCORED):
        raise HTTPException(400, "Test not yet submitted")
    return {
        "attempt_id": attempt.id,
        "status": getattr(attempt.status, "value", attempt.status),
        "total_score": attempt.total_score,
        "technical_score": attempt.technical_score,
        "communication_score": attempt.communication_score,
        "cultural_fit_score": attempt.cultural_fit_score,
        "rating_badge": getattr(attempt.rating_badge, "value", attempt.rating_badge) if attempt.rating_badge else None,
        "is_qualified": attempt.is_qualified,
        "ai_feedback": attempt.ai_feedback,
        "score_breakdown": attempt.score_breakdown,
    }


# ─── Onboarding & Matching ───────────────────────────────────────────────────

class OnboardRequest(BaseModel):
    phone: Optional[str] = None
    location: Optional[str] = None
    years_of_experience: Optional[int] = None
    experience_level: Optional[str] = None
    headline: Optional[str] = None
    bio: Optional[str] = None
    skills: Optional[list[str]] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    current_salary: Optional[int] = None
    expected_salary: Optional[int] = None
    notice_period_days: Optional[int] = None

@router.post("/parse-resume")
async def parse_resume_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_candidate),
):
    if not PyPDF2:
        raise HTTPException(500, "PyPDF2 is not installed on the server backend.")
    content = await file.read()
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(content))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
    except Exception as e:
        raise HTTPException(400, f"Could not read PDF: {str(e)}")
    
    parsed = await parse_resume_for_profile(text, db)
    return parsed

@router.post("/onboard")
async def onboard_candidate(
    data: OnboardRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_candidate),
):
    result = await db.execute(select(Candidate).where(Candidate.user_id == current_user.id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(404, "Candidate not found")
        
    candidate.phone = data.phone
    candidate.location = data.location
    candidate.years_of_experience = data.years_of_experience
    candidate.experience_level = data.experience_level
    candidate.headline = data.headline
    candidate.bio = data.bio
    candidate.skills = data.skills
    candidate.linkedin_url = data.linkedin_url
    candidate.github_url = data.github_url
    candidate.portfolio_url = data.portfolio_url
    candidate.current_salary = data.current_salary
    candidate.expected_salary = data.expected_salary
    candidate.notice_period_days = data.notice_period_days

    # ─── Phase 1: Compute profile completeness ───────────────────────────
    all_filled = all([
        current_user.full_name,
        current_user.email,
        candidate.phone,
        candidate.phone_verified,
        candidate.resume_s3_key,
        candidate.years_of_experience is not None,
        candidate.current_salary is not None,
        candidate.expected_salary is not None,
    ])
    candidate.is_profile_complete = all_filled

    await db.commit()
    
    # Generate assessment only if feature is enabled
    if settings.ENABLE_ASSESSMENTS and candidate.skills:
        try:
            gen_data = await generate_assessment(
                role=data.headline or "Software Engineer",
                skills=candidate.skills,
                seniority=data.experience_level or "mid",
                years_exp=data.years_of_experience or 3,
                difficulty="intermediate",
                mcq_count=10,
                coding_count=1,
                scenario_count=2,
                db=db
            )
            
            assessment = Assessment(
                title=f"General Screening Test - {current_user.full_name}",
                has_coding_round=True,
                mcq_count=10,
                coding_count=1,
                scenario_count=2,
                time_limit_minutes=60
            )
            db.add(assessment)
            await db.flush()
            
            questions_data = gen_data.get("questions", [])
            for i, q in enumerate(questions_data):
                from app.models.assessment import QuestionType
                qt = QuestionType(q.get("question_type", "mcq"))
                question = Question(
                    assessment_id=assessment.id,
                    question_type=qt,
                    question_text=q.get("question_text", ""),
                    options=q.get("options"),
                    correct_answer=q.get("correct_answer"),
                    explanation=q.get("explanation"),
                    difficulty=q.get("difficulty", "intermediate"),
                    skills_tested=q.get("skills_tested", []),
                    max_score=q.get("max_score", 10),
                    order_index=i,
                )
                db.add(question)
                
            attempt = TestAttempt(
                assessment_id=assessment.id,
                candidate_id=candidate.id,
                status=AttemptStatus.INVITED
            )
            db.add(attempt)
            await db.commit()
            
        except Exception as e:
            print("Failed to generate screening test:", e)
            
    return {
        "message": "Onboarding complete",
        "is_profile_complete": candidate.is_profile_complete,
    }


@router.get("/profile-status")
async def get_profile_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns a breakdown of which profile fields are complete."""
    result = await db.execute(select(Candidate).where(Candidate.user_id == current_user.id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        return {"is_profile_complete": False, "completion_percent": 0, "fields": {}}

    fields = {
        "full_name": bool(current_user.full_name),
        "email": bool(current_user.email),
        "phone": bool(candidate.phone),
        "phone_verified": bool(candidate.phone_verified),
        "resume": bool(candidate.resume_s3_key),
        "years_of_experience": candidate.years_of_experience is not None,
        "current_salary": candidate.current_salary is not None,
        "expected_salary": candidate.expected_salary is not None,
    }
    filled = sum(1 for v in fields.values() if v)
    total = len(fields)

    return {
        "is_profile_complete": candidate.is_profile_complete,
        "completion_percent": int((filled / total) * 100),
        "fields": fields,
    }


@router.get("/matched-jobs")
async def get_matched_jobs(db: AsyncSession = Depends(get_db), current_user: User = Depends(require_candidate)):
    result = await db.execute(select(Candidate).where(Candidate.user_id == current_user.id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(404, "Candidate not found")
        
    jd_res = await db.execute(select(JobDescription).order_by(JobDescription.id.desc()))
    jds = jd_res.scalars().all()
    
    matched = []
    cand_skills = set(s.lower() for s in (candidate.skills or []))
    for j in jds:
        req_skills = set(s.lower() for s in (j.required_skills or []))
        match_count = len(cand_skills.intersection(req_skills))
        match_pct = int((match_count / max(len(req_skills), 1)) * 100) if req_skills else 50
        
        # Check if already applied
        att_res = await db.execute(select(TestAttempt).where(TestAttempt.candidate_id == candidate.id, TestAttempt.job_description_id == j.id))
        existing = att_res.scalar_one_or_none()
        
        # Get Job's Client Company Name
        from app.models.client import Client
        client_res = await db.execute(select(Client).where(Client.id == j.client_id))
        client = client_res.scalar_one_or_none()
        
        matched.append({
            "id": j.id,
            "title": j.title,
            "company": client.company_name if client else "TopDev Client",
            "difficulty": getattr(j.difficulty_level, "value", j.difficulty_level) if j.difficulty_level else None,
            "skills": j.required_skills,
            "match_percent": match_pct,
            "has_applied": bool(existing),
            "created_at": j.created_at
        })
        
    matched.sort(key=lambda x: x["match_percent"], reverse=True)
    return matched


@router.post("/jobs/{job_id}/apply")
async def apply_job(job_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_candidate)):
    result = await db.execute(select(Candidate).where(Candidate.user_id == current_user.id))
    candidate = result.scalar_one_or_none()
    
    jd_res = await db.execute(select(JobDescription).where(JobDescription.id == job_id))
    jd = jd_res.scalar_one_or_none()
    if not jd:
        raise HTTPException(404, "Job not found")
        
    # Job has assessments?
    ass_res = await db.execute(select(Assessment).where(Assessment.job_description_id == jd.id))
    assessment = ass_res.scalar_one_or_none()
    if not assessment:
        raise HTTPException(400, "Job has no assessment configured")
        
    # Check if already applied
    att_res = await db.execute(select(TestAttempt).where(TestAttempt.candidate_id == candidate.id, TestAttempt.job_description_id == jd.id))
    existing = att_res.scalar_one_or_none()
    if existing:
        raise HTTPException(400, "Already applied to this job")
        
    attempt = TestAttempt(
        assessment_id=assessment.id,
        candidate_id=candidate.id,
        job_description_id=jd.id,
        status=AttemptStatus.INVITED
    )
    db.add(attempt)
    await db.commit()
    return {"message": "Applied successfully", "token": attempt.token}
