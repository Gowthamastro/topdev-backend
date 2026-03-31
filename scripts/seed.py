"""
Database seed script — populates default settings, templates, weights, and admin user.
Run: python scripts/seed.py
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.models.admin import PlatformSettings, EmailTemplate, ScoringWeights, FeatureFlag, RoleTemplate

engine = create_async_engine(settings.DATABASE_URL)
AsyncSession_ = async_sessionmaker(engine, expire_on_commit=False)


PLATFORM_SETTINGS = [
    {"key": "qualification_threshold", "value": "60", "description": "Minimum score for candidate to be shown to client", "category": "scoring"},
    {"key": "test_link_expiry_hours", "value": "48", "description": "Hours before test link expires", "category": "testing"},
    {"key": "default_mcq_count", "value": "10", "description": "Default number of MCQ questions per assessment", "category": "testing"},
    {"key": "default_coding_count", "value": "2", "description": "Default number of coding questions", "category": "testing"},
    {"key": "default_scenario_count", "value": "3", "description": "Default number of scenario questions", "category": "testing"},
    {"key": "frontend_url", "value": "http://localhost:5173", "description": "Frontend URL for generating test links", "category": "general"},
    {"key": "jd_parse_prompt", "value": "", "description": "AI prompt for parsing job descriptions (leave blank for default)", "category": "ai"},
    {"key": "test_generation_prompt", "value": "", "description": "AI prompt for generating assessments (leave blank for default)", "category": "ai"},
    {"key": "scoring_prompt", "value": "", "description": "AI prompt for scoring answers (leave blank for default)", "category": "ai"},
]


EMAIL_TEMPLATES = [
    {
        "slug": "test_invitation",
        "name": "Test Invitation",
        "subject": "Your {{role_title}} Assessment at {{company_name}}",
        "html_body": """
<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;background:#0f0f13;color:#e2e8f0;padding:40px;border-radius:12px">
  <div style="text-align:center;margin-bottom:32px">
    <h1 style="color:#818cf8;font-size:28px;margin:0">TopDev</h1>
    <p style="color:#64748b;margin:4px 0 0">Top Talent. Top Scores.</p>
  </div>
  <h2 style="font-size:20px;margin:0 0 16px">Hello {{candidate_name}},</h2>
  <p>You've been invited to complete a technical assessment for <strong style="color:#818cf8">{{role_title}}</strong> at <strong>{{company_name}}</strong>.</p>
  <div style="text-align:center;margin:32px 0">
    <a href="{{test_link}}" style="background:linear-gradient(135deg,#6366f1,#8b5cf6);color:white;padding:14px 32px;text-decoration:none;border-radius:8px;font-weight:600;font-size:16px">Start Assessment →</a>
  </div>
  <p style="color:#64748b;font-size:14px">This link expires in {{expires_hours}} hours. Please complete the assessment before it expires.</p>
  <p style="color:#64748b;font-size:14px">Good luck! 🚀</p>
</div>
""",
        "variables": ["candidate_name", "role_title", "company_name", "test_link", "expires_hours"],
    },
    {
        "slug": "result_notification",
        "name": "Result Notification",
        "subject": "Your {{role_title}} assessment results — {{badge}}",
        "html_body": """
<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;background:#0f0f13;color:#e2e8f0;padding:40px;border-radius:12px">
  <h1 style="color:#818cf8">TopDev Assessment Results</h1>
  <h2>Hello {{candidate_name}},</h2>
  <p>Your assessment for <strong>{{role_title}}</strong> has been scored.</p>
  <div style="background:#1a1a2e;border-radius:8px;padding:24px;margin:24px 0;text-align:center">
    <div style="font-size:48px;font-weight:700;color:#818cf8">{{score}}</div>
    <div style="color:#64748b">/ 100</div>
    <div style="margin-top:12px;padding:6px 16px;background:#6366f1;border-radius:20px;display:inline-block;font-weight:600">{{badge}}</div>
  </div>
  <p>Thank you for your effort. The hiring team will review your results and reach out soon.</p>
</div>
""",
        "variables": ["candidate_name", "score", "badge", "role_title"],
    },
]


FEATURE_FLAGS = [
    {"flag_name": "coding_round_enabled", "is_enabled": True, "description": "Enable coding round in assessments"},
    {"flag_name": "ai_scoring_enabled", "is_enabled": True, "description": "Use AI for scoring (disable to use manual review)"},
    {"flag_name": "stripe_enabled", "is_enabled": True, "description": "Enable Stripe billing"},
    {"flag_name": "email_enabled", "is_enabled": True, "description": "Enable email notifications"},
    {"flag_name": "candidate_self_apply", "is_enabled": False, "description": "Allow candidates to apply directly (without invite)"},
]


ROLE_TEMPLATES = [
    {"name": "Full-Stack Developer", "default_skills": ["JavaScript", "React", "Node.js", "PostgreSQL"], "mcq_count": 10, "coding_count": 2, "scenario_count": 3},
    {"name": "Backend Engineer (Python)", "default_skills": ["Python", "FastAPI", "SQL", "Docker"], "mcq_count": 10, "coding_count": 3, "scenario_count": 2},
    {"name": "DevOps Engineer", "default_skills": ["Kubernetes", "Docker", "CI/CD", "AWS"], "mcq_count": 10, "coding_count": 1, "scenario_count": 4},
    {"name": "Data Scientist", "default_skills": ["Python", "ML", "Pandas", "SQL"], "mcq_count": 12, "coding_count": 2, "scenario_count": 2},
    {"name": "iOS Developer", "default_skills": ["Swift", "SwiftUI", "Xcode", "UIKit"], "mcq_count": 10, "coding_count": 2, "scenario_count": 3},
]


async def seed():
    async with AsyncSession_(expire_on_commit=False) as db:
        print("🌱 Seeding database...")

        # Admin user
        from sqlalchemy import select
        existing_admin = await db.execute(select(User).where(User.email == "admin@topdev.ai"))
        if not existing_admin.scalar_one_or_none():
            admin = User(
                email="admin@topdev.ai",
                full_name="TopDev Admin",
                hashed_password=get_password_hash("Admin@123"),
                role=UserRole.ADMIN.value,
                is_active=True,
                is_verified=True,
            )
            db.add(admin)
            print("  ✅ Admin user created: admin@topdev.ai / Admin@123")

        # Platform settings
        for s in PLATFORM_SETTINGS:
            existing = await db.execute(select(PlatformSettings).where(PlatformSettings.key == s["key"]))
            if not existing.scalar_one_or_none():
                db.add(PlatformSettings(**s))
        print(f"  ✅ {len(PLATFORM_SETTINGS)} platform settings seeded")

        # Scoring weights
        existing_weights = await db.execute(select(ScoringWeights))
        if not existing_weights.scalar_one_or_none():
            db.add(ScoringWeights(name="default", technical_weight=0.40, communication_weight=0.40, cultural_fit_weight=0.20, qualification_threshold=60.0, is_default=True))
        print("  ✅ Default scoring weights seeded")

        # Email templates
        for t in EMAIL_TEMPLATES:
            existing = await db.execute(select(EmailTemplate).where(EmailTemplate.slug == t["slug"]))
            if not existing.scalar_one_or_none():
                db.add(EmailTemplate(**t))
        print(f"  ✅ {len(EMAIL_TEMPLATES)} email templates seeded")

        # Feature flags
        for f in FEATURE_FLAGS:
            existing = await db.execute(select(FeatureFlag).where(FeatureFlag.flag_name == f["flag_name"]))
            if not existing.scalar_one_or_none():
                db.add(FeatureFlag(**f))
        print(f"  ✅ {len(FEATURE_FLAGS)} feature flags seeded")

        # Role templates
        for rt in ROLE_TEMPLATES:
            existing = await db.execute(select(RoleTemplate).where(RoleTemplate.name == rt["name"]))
            if not existing.scalar_one_or_none():
                db.add(RoleTemplate(**rt))
        print(f"  ✅ {len(ROLE_TEMPLATES)} role templates seeded")

        await db.commit()
        print("✅ Seeding complete!")


if __name__ == "__main__":
    asyncio.run(seed())
