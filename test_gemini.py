import asyncio
import sys

from app.ai.gemini_service import generate_assessment

async def main():
    try:
        print("Testing gemini generation...")
        res = await generate_assessment(
            role="Junior Python Engineer",
            skills=["Python", "FastAPI"],
            seniority="Junior",
            years_exp=1,
            difficulty="beginner",
            mcq_count=2,
            coding_count=1,
            scenario_count=1,
            db=None
        )
        print("Success:", res)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
