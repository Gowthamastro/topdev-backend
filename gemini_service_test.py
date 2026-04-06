import asyncio
from app.ai.gemini_service import parse_resume_for_profile

async def test_mock():
    print("Testing parse_resume_for_profile with mock fallback...")
    resume_text = "Experienced Python developer with React and AWS knowledge. Senior level."
    result = await parse_resume_for_profile(resume_text)
    print(f"RESULT: {result}")

if __name__ == "__main__":
    asyncio.run(test_mock())
