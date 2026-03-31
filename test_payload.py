import asyncio
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from app.core.database import async_session_maker
from app.models.assessment import Assessment

async def main():
    async with async_session_maker() as session:
        assmt_res = await session.execute(
            select(Assessment)
            .options(joinedload(Assessment.questions))
            .where(Assessment.job_description_id == 20)
        )
        assessment = assmt_res.scalars().first()
        if assessment:
            print(f"Loaded {len(assessment.questions)} questions")
        else:
            print("Assessment not found in DB session")

asyncio.run(main())
