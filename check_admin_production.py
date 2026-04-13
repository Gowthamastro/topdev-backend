import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select

# Railway DB string from reset_rahul.py
DATABASE_URL = "postgresql+asyncpg://postgres:gBUTsXvULpLhoRAUpXZjIIfhwXvxlaJI@interchange.proxy.rlwy.net:11571/railway"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def check_admin():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app.models.user import User
    
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).where(User.email == "admin@topdev.ai"))
        user = res.scalar_one_or_none()
        if user:
            print(f"Found User: {user.email}")
            print(f"Role: {user.role}")
            print(f"Is Active: {user.is_active}")
            print(f"Hashed Password: {user.hashed_password}")
        else:
            print("Admin user not found in Railway DB")

if __name__ == "__main__":
    asyncio.run(check_admin())
