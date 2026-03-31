"""
AI Integration Layer — Gemini-powered JD parsing, test generation, and answer scoring.
All prompts are pulled from PlatformSettings (DB) so admins can edit them without code changes.
"""
from typing import Optional
from google import genai
from google.genai import types
from app.core.config import settings
import json
import re

client = genai.Client(api_key=settings.GEMINI_API_KEY)


async def get_prompt_from_settings(db, key: str, fallback: str) -> str:
    """Pull editable prompt from PlatformSettings table."""
    from sqlalchemy import select
    from app.models.admin import PlatformSettings
    result = await db.execute(select(PlatformSettings).where(PlatformSettings.key == key))
    row = result.scalar_one_or_none()
    val = row.value if row else None
    if not val or not val.strip():
        return fallback
    return val


DEFAULT_JD_PARSE_PROMPT = """
You are an expert technical recruiter. Parse the following job description and return a JSON object with:
{
  "required_skills": ["skill1", "skill2"],
  "preferred_skills": ["skill1"],
  "min_years_experience": 0,
  "max_years_experience": 10,
  "seniority_level": "junior|mid|senior",
  "technologies": ["Python", "React"],
  "parsed_summary": "Brief 2-sentence summary of the role"
}
Return ONLY valid JSON, no extra text.
Job Description:
{jd_text}
"""

DEFAULT_TEST_GENERATION_PROMPT = """
You are a senior technical assessment designer. Generate a technical assessment for a {role} position.
Skills required: {skills}
Seniority: {seniority} ({years_exp} years experience)
Difficulty: {difficulty}

Generate exactly:
- {mcq_count} MCQ questions
- {coding_count} coding challenges
- {scenario_count} scenario questions

Return ONLY valid JSON in this format:
{
  "questions": [
    {
      "question_type": "mcq",
      "question_text": "...",
      "options": [{"label": "A", "text": "..."}, ...],
      "correct_answer": "A",
      "explanation": "...",
      "difficulty": "beginner|intermediate|advanced",
      "skills_tested": ["skill1"],
      "max_score": 10
    },
    {
      "question_type": "coding",
      "question_text": "Write a function that...",
      "correct_answer": "def solution():\\n    pass",
      "explanation": "...",
      "difficulty": "intermediate",
      "skills_tested": ["Python"],
      "max_score": 20
    }
  ]
}
"""

DEFAULT_SCORING_PROMPT = """
You are a technical assessment scorer. Score the candidate's answers for each question.

Assessment context: {assessment_context}

Questions and Answers:
{qa_pairs}

For each question, return a JSON array:
[
  {
    "question_id": 1,
    "score": 8.5,
    "max_score": 10,
    "feedback": "Good understanding of X but missed Y",
    "category": "technical|coding|problem_solving"
  }
]
Return ONLY valid JSON, no extra text.
"""


def _extract_json(text: str) -> dict | list:
    """Robustly extract JSON from Gemini response."""
    if not text:
        return {}
    text = text.strip()
    
    # Try direct parse first
    try:
        return json.loads(text)
    except Exception:
        pass
        
    # Remove markdown code blocks if present
    text = re.sub(r'```[a-zA-Z]*', '', text)
    text = text.replace('```', '').strip()
    
    # Try parsing again after strip
    try:
        return json.loads(text)
    except Exception:
        pass

    # Find the outermost array or object
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    first_bracket = text.find('[')
    last_bracket = text.rfind(']')

    # Determine if it's primarily an object or an array
    is_object = first_brace != -1 and last_brace != -1
    is_array = first_bracket != -1 and last_bracket != -1

    if is_object and is_array:
        # Choose whichever starts first
        if first_brace < first_bracket:
            is_array = False
        else:
            is_object = False

    try:
        if is_object:
            return json.loads(text[first_brace:last_brace + 1])
        elif is_array:
            return json.loads(text[first_bracket:last_bracket + 1])
    except Exception as e:
        print(f"DEBUG GEMINI EXTRACTION EXCEPTION: {e}")
        pass

    raise ValueError(f"Could not extract JSON from response: {text[:200]}")


async def parse_job_description(jd_text: str, db=None) -> dict:
    """Use Gemini to extract structured data from a job description."""
    if db:
        prompt_template = await get_prompt_from_settings(db, "jd_parse_prompt", DEFAULT_JD_PARSE_PROMPT)
    else:
        prompt_template = DEFAULT_JD_PARSE_PROMPT

    prompt = prompt_template.replace("{jd_text}", jd_text)
    
    response = await client.aio.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
    return _extract_json(response.text)


async def generate_assessment(
    role: str,
    skills: list[str],
    seniority: str,
    years_exp: int,
    difficulty: str,
    mcq_count: int = 10,
    coding_count: int = 2,
    scenario_count: int = 3,
    db=None,
) -> dict:
    """Generate a full assessment with questions."""
    if db:
        prompt_template = await get_prompt_from_settings(db, "test_generation_prompt", DEFAULT_TEST_GENERATION_PROMPT)
    else:
        prompt_template = DEFAULT_TEST_GENERATION_PROMPT

    prompt = prompt_template
    replacements = {
        "{role}": role,
        "{skills}": ", ".join(skills),
        "{seniority}": seniority,
        "{years_exp}": str(years_exp),
        "{difficulty}": difficulty,
        "{mcq_count}": str(mcq_count),
        "{coding_count}": str(coding_count),
        "{scenario_count}": str(scenario_count),
    }
    for k, v in replacements.items():
        prompt = prompt.replace(k, v)

    response = await client.aio.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.7,
        ),
    )
    try:
        raw_text = response.text
        print("DEBUG GEMINI RAW:", raw_text)
        return _extract_json(raw_text)
    except Exception as e:
        print("DEBUG GEMINI ERROR accessing .text:", e, getattr(response, 'prompt_feedback', ''))
        return {}


async def score_answers(
    assessment_context: str,
    qa_pairs: list[dict],
    db=None,
) -> list[dict]:
    """Score candidate's answers using Gemini."""
    if db:
        prompt_template = await get_prompt_from_settings(db, "scoring_prompt", DEFAULT_SCORING_PROMPT)
    else:
        prompt_template = DEFAULT_SCORING_PROMPT

    qa_text = "\\n".join(
        [f"Question ID {q['question_id']} [{q['question_type']}]: {q['question_text']}\\nAnswer: {q['answer']}" 
         for q in qa_pairs]
    )
    prompt = prompt_template.replace("{assessment_context}", assessment_context).replace("{qa_pairs}", qa_text)

    response = await client.aio.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )
    result = _extract_json(response.text)
    
    # Handle both {"scores": [...]} and direct list
    if isinstance(result, dict) and "scores" in result:
        return result["scores"]
    if isinstance(result, list):
        return result
    return []
