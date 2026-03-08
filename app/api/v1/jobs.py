"""Job Description APIs — upload, AI parsing, management."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional
from app.core.database import get_db
from app.core.deps import get_current_user, require_client
from app.models.user import User
from app.models.client import Client
from app.models.job import JobDescription, JDStatus, DifficultyLevel
from app.models.assessment import Assessment, AssessmentStatus
from app.ai.openai_service import parse_job_description, generate_assessment as ai_generate_assessment
from app.services.storage_service import upload_file, get_signed_url
from app.models.admin import PlatformSettings, ScoringWeights
from app.services.scoring_service import PLAN_ROLE_LIMITS
from datetime import datetime, timezone

router = APIRouter(prefix="/jobs", tags=["jobs"])


def determine_difficulty(years: int) -> DifficultyLevel:
    if years <= 2:
        return DifficultyLevel.BEGINNER
    elif years <= 5:
        return DifficultyLevel.INTERMEDIATE
    return DifficultyLevel.ADVANCED


@router.post("/upload")
async def upload_jd(
    title: str = Form(...),
    jd_text: str = Form(""),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_client),
):
    """Upload + parse a job description and auto-generate an assessment."""
    # Enforce subscription limits
    client_result = await db.execute(select(Client).where(Client.user_id == current_user.id))
    client = client_result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client profile not found")

    limit = PLAN_ROLE_LIMITS.get(client.subscription_plan, 0)
    print("limit", limit)
    print("subscription", client.subscription_plan)
    print("roles used", client.roles_used_this_month)
    if client.roles_used_this_month >= limit and client.subscription_plan != "enterprise":
        raise HTTPException(status_code=402, detail=f"Role limit reached for {client.subscription_plan} plan. Please upgrade.")

    # Handle file upload
    s3_key = None
    if file:
        content = await file.read()
        s3_key = await upload_file(content, file.filename, folder="jd-files")

    # Use text from form or placeholder
    text_to_parse = jd_text if jd_text else title

    # AI parse
    try:
        parsed = await parse_job_description(text_to_parse, db)
    except Exception:
        parsed = {}

    min_exp = parsed.get("min_years_experience", 0)
    difficulty = determine_difficulty(min_exp)
    seniority = parsed.get("seniority_level", "mid")

    jd = JobDescription(
        client_id=client.id,
        title=title,
        original_text=text_to_parse,
        jd_s3_key=s3_key,
        required_skills=parsed.get("required_skills", []),
        preferred_skills=parsed.get("preferred_skills", []),
        min_years_experience=min_exp,
        max_years_experience=parsed.get("max_years_experience", 10),
        seniority_level=seniority,
        difficulty_level=difficulty,
        parsed_summary=parsed.get("parsed_summary"),
        technologies=parsed.get("technologies", []),
    )
    db.add(jd)
    await db.flush()

    # Get test structure settings
    sw_result = await db.execute(select(ScoringWeights).where(ScoringWeights.is_default == True))
    weights = sw_result.scalar_one_or_none()

    # Get platform settings for MCQ/coding counts
    ps_results = await db.execute(select(PlatformSettings).where(
        PlatformSettings.key.in_(["default_mcq_count", "default_coding_count", "default_scenario_count"])
    ))
    ps_map = {p.key: int(p.value) for p in ps_results.scalars().all()}
    mcq_count = ps_map.get("default_mcq_count", 10)
    coding_count = ps_map.get("default_coding_count", 2)
    scenario_count = ps_map.get("default_scenario_count", 3)

    # Generate assessment via AI
    try:
        gen = await ai_generate_assessment(
            role=title,
            skills=(parsed.get("required_skills") or []) + (parsed.get("technologies") or []),
            seniority=seniority,
            years_exp=min_exp,
            difficulty=difficulty.value,
            mcq_count=mcq_count,
            coding_count=coding_count,
            scenario_count=scenario_count,
            db=db,
        )
        questions_data = gen.get("questions", [])
    except Exception:
        questions_data = []

    from app.models.assessment import Question, QuestionType
    assessment = Assessment(
        job_description_id=jd.id,
        title=f"{title} — Technical Assessment",
        has_coding_round=coding_count > 0,
        mcq_count=mcq_count,
        coding_count=coding_count,
        scenario_count=scenario_count,
    )
    db.add(assessment)
    await db.flush()

    for i, q in enumerate(questions_data):
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

    # Increment roles used
    client.roles_used_this_month += 1
    await db.commit()

    return {
        "job_id": jd.id,
        "assessment_id": assessment.id,
        "title": title,
        "parsed": parsed,
        "questions_generated": len(questions_data),
        "message": "Job description uploaded and assessment generated successfully.",
    }


@router.get("/")
async def list_jds(db: AsyncSession = Depends(get_db), current_user: User = Depends(require_client)):
    client_res = await db.execute(select(Client).where(Client.user_id == current_user.id))
    client = client_res.scalar_one_or_none()
    if not client:
        raise HTTPException(404, "Client not found")
    result = await db.execute(select(JobDescription).where(JobDescription.client_id == client.id).order_by(JobDescription.id.desc()))
    jds = result.scalars().all()
    print("jds:", jds)
    return [{"id": j.id, "title": j.title, "status": getattr(j.status, "value", j.status), "difficulty": getattr(j.difficulty_level, "value", j.difficulty_level) if j.difficulty_level else None, "skills": j.required_skills, "created_at": j.created_at} for j in jds]


@router.get("/{jd_id}")
async def get_jd(jd_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(JobDescription).where(JobDescription.id == jd_id))
    jd = result.scalar_one_or_none()
    if not jd:
        raise HTTPException(404, "Not found")
    return jd
