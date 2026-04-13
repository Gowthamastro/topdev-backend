import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select, delete

# Railway DB string from .env
DATABASE_URL = "postgresql+asyncpg://postgres:gBUTsXvULpLhoRAUpXZjIIfhwXvxlaJI@interchange.proxy.rlwy.net:11571/railway"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def delete_rahul_test():
    from app.models.user import User
    from app.models.candidate import Candidate
    from app.models.test_attempt import TestAttempt
    from app.models.assessment import Assessment

    async with AsyncSessionLocal() as db:
        # Find Rahuls
        res = await db.execute(select(User).where(User.full_name.ilike("%Rahul%")))
        users = res.scalars().all()
        if not users:
            print("User Rahul not found")
            return
            
        for user in users:
            print(f"Found User: {user.full_name} (ID: {user.id})")
            
            # Find candidate
            res = await db.execute(select(Candidate).where(Candidate.user_id == user.id))
            candidate = res.scalar_one_or_none()
            if not candidate:
                print(f"Candidate profile not found for {user.full_name}")
                continue
                
            # Delete his test attempts
            res = await db.execute(select(TestAttempt).where(TestAttempt.candidate_id == candidate.id))
            attempts = res.scalars().all()
            
            if not attempts:
                print(f"No test attempts found to delete for {user.full_name}.")
                continue

            for a in attempts:
                print(f"Deleting Test Attempt ID: {a.id}")
                await db.delete(a)
                
                # also delete the associated assessment if it was a generic one (no job_description_id)
                if not a.job_description_id and a.assessment_id:
                    ass_res = await db.execute(select(Assessment).where(Assessment.id == a.assessment_id))
                    ass = ass_res.scalar_one_or_none()
                    if ass:
                        print(f"Deleting Generic Assessment ID: {ass.id}")
                        await db.delete(ass)
                        
        await db.commit()
        print("✅ Successfully deleted Rahul's old test. He can now generate a new one from his dashboard.")

if __name__ == "__main__":
    asyncio.run(delete_rahul_test())
