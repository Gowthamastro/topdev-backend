"""Admin Dashboard APIs — no-code control of all platform settings."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel
from typing import Optional, Any
from app.core.database import get_db
from app.core.deps import require_admin
from app.models.user import User
from app.models.admin import (
    PlatformSettings, EmailTemplate, ScoringWeights,
    FeatureFlag, RoleTemplate, AuditLog
)
from app.services.audit_service import log_audit_event

router = APIRouter(prefix="/admin", tags=["admin"])


# ─── Platform Settings ───────────────────────────────────────────────────────

@router.get("/settings")
async def list_settings(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    result = await db.execute(select(PlatformSettings))
    return [{"id": s.id, "key": s.key, "value": s.value, "description": s.description, "category": s.category} for s in result.scalars()]

@router.get("/audit-logs")
async def list_audit_logs(
    limit: int = 200,
    user_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    limit = max(1, min(limit, 1000))
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    result = await db.execute(stmt)
    logs = result.scalars().all()
    return [
        {
            "id": l.id,
            "user_id": l.user_id,
            "action": l.action,
            "resource_type": l.resource_type,
            "resource_id": l.resource_id,
            "details": l.details,
            "ip_address": l.ip_address,
            "created_at": l.created_at,
        }
        for l in logs
    ]


class UpdateSettingRequest(BaseModel):
    value: str


@router.put("/settings/{key}")
async def update_setting(
    key: str,
    data: UpdateSettingRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(PlatformSettings).where(PlatformSettings.key == key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(404, f"Setting '{key}' not found")
    setting.value = data.value
    setting.updated_by = current_user.id
    await log_audit_event(
        db=db,
        action="update_setting",
        user_id=current_user.id,
        resource_type="platform_setting",
        resource_id=key,
        details={"value": data.value},
        request=request,
    )
    await db.commit()
    return {"key": key, "value": data.value}


# ─── Scoring Weights ─────────────────────────────────────────────────────────

@router.get("/scoring-weights")
async def get_scoring_weights(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    result = await db.execute(select(ScoringWeights))
    return result.scalars().all()


class ScoringWeightsUpdate(BaseModel):
    technical_weight: float
    communication_weight: float
    cultural_fit_weight: float
    qualification_threshold: float


@router.put("/scoring-weights/{weights_id}")
async def update_scoring_weights(
    weights_id: int,
    data: ScoringWeightsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    total = data.technical_weight + data.communication_weight + data.cultural_fit_weight
    if abs(total - 1.0) > 0.01:
        raise HTTPException(400, f"Weights must sum to 1.0, got {total}")
    result = await db.execute(select(ScoringWeights).where(ScoringWeights.id == weights_id))
    weights = result.scalar_one_or_none()
    if not weights:
        raise HTTPException(404, "Weights not found")
    weights.technical_weight = data.technical_weight
    weights.communication_weight = data.communication_weight
    weights.cultural_fit_weight = data.cultural_fit_weight
    weights.qualification_threshold = data.qualification_threshold
    await log_audit_event(
        db=db,
        action="update_scoring_weights",
        user_id=current_user.id,
        resource_type="scoring_weights",
        resource_id=str(weights_id),
        details=data.model_dump(),
        request=request,
    )
    await db.commit()
    return {"message": "Scoring weights updated"}


# ─── Email Templates ──────────────────────────────────────────────────────────

@router.get("/email-templates")
async def list_email_templates(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    result = await db.execute(select(EmailTemplate))
    return result.scalars().all()


class EmailTemplateUpdate(BaseModel):
    subject: str
    html_body: str
    text_body: Optional[str] = None


@router.put("/email-templates/{slug}")
async def update_email_template(
    slug: str,
    data: EmailTemplateUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(EmailTemplate).where(EmailTemplate.slug == slug))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(404, "Template not found")
    template.subject = data.subject
    template.html_body = data.html_body
    template.text_body = data.text_body
    await log_audit_event(
        db=db,
        action="update_email_template",
        user_id=current_user.id,
        resource_type="email_template",
        resource_id=slug,
        details={"subject": data.subject},
        request=request,
    )
    await db.commit()
    return {"message": "Email template updated"}


# ─── Feature Flags ────────────────────────────────────────────────────────────

@router.get("/feature-flags")
async def list_flags(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    result = await db.execute(select(FeatureFlag))
    return result.scalars().all()


class ToggleFlagRequest(BaseModel):
    is_enabled: bool


@router.put("/feature-flags/{flag_name}")
async def toggle_flag(
    flag_name: str,
    data: ToggleFlagRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(FeatureFlag).where(FeatureFlag.flag_name == flag_name))
    flag = result.scalar_one_or_none()
    if not flag:
        raise HTTPException(404, "Flag not found")
    flag.is_enabled = data.is_enabled
    await log_audit_event(
        db=db,
        action="toggle_feature_flag",
        user_id=current_user.id,
        resource_type="feature_flag",
        resource_id=flag_name,
        details={"is_enabled": data.is_enabled},
        request=request,
    )
    await db.commit()
    return {"flag_name": flag_name, "is_enabled": data.is_enabled}


# ─── Role Templates ────────────────────────────────────────────────────────────

@router.get("/role-templates")
async def list_role_templates(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    result = await db.execute(select(RoleTemplate))
    return result.scalars().all()


class RoleTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    default_skills: Optional[list[str]] = None
    mcq_count: int = 10
    coding_count: int = 2
    scenario_count: int = 3
    time_limit_minutes: int = 90
    has_coding_round: bool = True
    difficulty: str = "intermediate"


@router.post("/role-templates")
async def create_role_template(
    data: RoleTemplateCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    template = RoleTemplate(**data.model_dump())
    db.add(template)
    await db.flush()
    await log_audit_event(
        db=db,
        action="create_role_template",
        user_id=current_user.id,
        resource_type="role_template",
        resource_id=str(template.id),
        details={"name": data.name},
        request=request,
    )
    await db.commit()
    await db.refresh(template)
    return template


@router.delete("/role-templates/{template_id}")
async def delete_role_template(
    template_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(RoleTemplate).where(RoleTemplate.id == template_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(404, "Template not found")
    await db.delete(template)
    await log_audit_event(
        db=db,
        action="delete_role_template",
        user_id=current_user.id,
        resource_type="role_template",
        resource_id=str(template_id),
        details={"name": template.name},
        request=request,
    )
    await db.commit()
    return {"message": "Deleted"}


# ─── Overview Stats ───────────────────────────────────────────────────────────

@router.get("/stats")
async def admin_stats(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    from app.models.user import User as UserModel
    from app.models.test_attempt import TestAttempt
    from sqlalchemy import func
    users = await db.execute(select(func.count(UserModel.id)))
    attempts = await db.execute(select(func.count(TestAttempt.id)))
    qualified = await db.execute(select(func.count(TestAttempt.id)).where(TestAttempt.is_qualified == True))
    avg_score = await db.execute(select(func.avg(TestAttempt.total_score)).where(TestAttempt.total_score.isnot(None)))
    return {
        "total_users": users.scalar(),
        "total_attempts": attempts.scalar(),
        "qualified_candidates": qualified.scalar(),
        "average_score": round(avg_score.scalar() or 0, 2),
    }
