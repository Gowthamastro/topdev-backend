"""
AI Integration Layer — OpenAI-powered JD parsing, test generation, and answer scoring.
All prompts are pulled from PlatformSettings (DB) so admins can edit them without code changes.
"""
from typing import Optional
from openai import AsyncOpenAI
from app.core.config import settings
import json
import re

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def get_prompt_from_settings(db, key: str, fallback: str) -> str:
    """Pull editable prompt from PlatformSettings table."""
    from sqlalchemy import select
    from app.models.admin import PlatformSettings
    result = await db.execute(select(PlatformSettings).where(PlatformSettings.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else fallback


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
    """Robustly extract JSON from GPT response."""
    text = text.strip()
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting from code block
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        return json.loads(match.group(1))
    raise ValueError(f"Could not extract JSON from response: {text[:200]}")


async def parse_job_description(jd_text: str, db=None) -> dict:
    """Use GPT to extract structured data from a job description."""
    if db:
        prompt_template = await get_prompt_from_settings(db, "jd_parse_prompt", DEFAULT_JD_PARSE_PROMPT)
    else:
        prompt_template = DEFAULT_JD_PARSE_PROMPT

    prompt = prompt_template.replace("{jd_text}", jd_text)

    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    return _extract_json(response.choices[0].message.content)


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

    prompt = prompt_template.format(
        role=role,
        skills=", ".join(skills),
        seniority=seniority,
        years_exp=years_exp,
        difficulty=difficulty,
        mcq_count=mcq_count,
        coding_count=coding_count,
        scenario_count=scenario_count,
    )

    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        response_format={"type": "json_object"},
    )
    return _extract_json(response.choices[0].message.content)


async def score_answers(
    assessment_context: str,
    qa_pairs: list[dict],
    db=None,
) -> list[dict]:
    """Score candidate's answers using GPT."""
    if db:
        prompt_template = await get_prompt_from_settings(db, "scoring_prompt", DEFAULT_SCORING_PROMPT)
    else:
        prompt_template = DEFAULT_SCORING_PROMPT

    qa_text = "\n".join(
        [f"Q{i+1} [{q['question_type']}]: {q['question_text']}\nAnswer: {q['answer']}" 
         for i, q in enumerate(qa_pairs)]
    )
    prompt = prompt_template.format(
        assessment_context=assessment_context,
        qa_pairs=qa_text,
    )

    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    result = _extract_json(response.choices[0].message.content)
    # Handle both {"scores": [...]} and direct list
    if isinstance(result, dict) and "scores" in result:
        return result["scores"]
    if isinstance(result, list):
        return result
    return []
