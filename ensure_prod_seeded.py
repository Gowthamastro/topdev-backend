import asyncio
import sys
import os

# Railway DB string from reset_rahul.py
DATABASE_URL = "postgresql+asyncpg://postgres:gBUTsXvULpLhoRAUpXZjIIfhwXvxlaJI@interchange.proxy.rlwy.net:11571/railway"

# Ensure app is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.models.admin import PlatformSettings, EmailTemplate, ScoringWeights, FeatureFlag, RoleTemplate
from sqlalchemy import select

engine = create_async_engine(DATABASE_URL)
AsyncSession_ = async_sessionmaker(engine, expire_on_commit=False)

# Data from seed.py
PLATFORM_SETTINGS = [
    {"key": "qualification_threshold", "value": "60", "description": "Minimum score for candidate to be shown to client", "category": "scoring"},
    {"key": "test_link_expiry_hours", "value": "48", "description": "Hours before test link expires", "category": "testing"},
    {"key": "default_mcq_count", "value": "10", "description": "Default number of MCQ questions per assessment", "category": "testing"},
    {"key": "default_coding_count", "value": "2", "description": "Default number of coding questions", "category": "testing"},
    {"key": "default_scenario_count", "value": "3", "description": "Default number of scenario questions", "category": "testing"},
    {"key": "frontend_url", "value": "https://topdevhq.com", "description": "Frontend URL for generating test links", "category": "general"},
]

EMAIL_TEMPLATES = [
    {
        "slug": "test_invitation",
        "name": "Test Invitation",
        "subject": "Your {{role_title}} Assessment at {{company_name}}",
        "html_body": "...", # Truncated for script simplicity, in reality we'd want full data but admin is priority
        "variables": ["candidate_name", "role_title", "company_name", "test_link", "expires_hours"],
    }
]

async def seed():
    async with AsyncSession_() as db:
        print(f"🌱 Seeding production database: {DATABASE_URL.split('@')[-1]}...")

        # Admin user
        existing_admin = await db.execute(select(User).where(User.email == "admin@topdev.ai"))
        user = existing_admin.scalar_one_or_none()
        if not user:
            print("  Creating Admin user...")
            admin = User(
                email="admin@topdev.ai",
                full_name="TopDev Admin",
                hashed_password=get_password_hash("Admin@123"),
                role=UserRole.ADMIN.value,
                is_active=True,
                is_verified=True,
            )
            db.add(admin)
        else:
            print("  Admin user exists. Updating password to Admin@123...")
            user.hashed_password = get_password_hash("Admin@123")
            user.role = UserRole.ADMIN.value
            user.is_active = True

        # Minimal settings if missing
        for s in PLATFORM_SETTINGS:
            existing = await db.execute(select(PlatformSettings).where(PlatformSettings.key == s["key"]))
            if not existing.scalar_one_or_none():
                db.add(PlatformSettings(**s))

        await db.commit()
        print("✅ Production seeding complete!")

if __name__ == "__main__":
    asyncio.run(seed())
