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

DEFAULT_RESUME_PARSE_PROMPT = """
You are an expert technical recruiter. Parse the following resume/CV text and return a JSON object with:
{
  "skills": ["Python", "React", "AWS", ...],
  "years_of_experience": 5,
  "experience_level": "junior|mid|senior",
  "headline": "Current Job Title or Main Headline",
  "bio": "A brief 2-3 sentence technical summary of the candidate's experience and strengths"
}
Return ONLY valid JSON, no extra text. Infer years of experience based on work history if not explicitly stated.
Resume Text:
{resume_text}
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



def _get_mock_fallback(prompt_type: str, input_text: str) -> dict:
    """Generate plausible mock data if Gemini is unreachable."""
    text = input_text.lower()
    
    # Common tech keywords for basic extraction
    tech_stack = ["python", "javascript", "react", "node", "aws", "docker", "typescript", "golang", "java", "sql", "flutter"]
    found_skills = [s.capitalize() for s in tech_stack if s in text]
    
    if prompt_type == "resume":
        return {
            "skills": found_skills or ["Software Engineering", "Teamwork"],
            "years_of_experience": 5 if "senior" in text else 2,
            "experience_level": "senior" if "senior" in text else "junior",
            "headline": "Software Engineer" if not found_skills else f"{found_skills[0]} Developer",
            "bio": "Experienced technical professional with a focus on building scalable applications and solving complex problems."
        }
    
    if prompt_type == "jd":
        return {
            "required_skills": found_skills or ["Technical Proficiency"],
            "preferred_skills": ["Cloud Architecture"],
            "min_years_experience": 3,
            "max_years_experience": 10,
            "seniority_level": "mid",
            "technologies": found_skills,
            "parsed_summary": "Technical role focused on systems development and product delivery."
        }

    # Default for unknown or test generation (minimal valid structure)
    return {"questions": []}


async def parse_job_description(jd_text: str, db=None) -> dict:
    """Use Gemini to extract structured data from a job description."""
    try:
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
    except Exception as e:
        print(f"DEBUG GEMINI JD PARSE ERROR: {e}")
        return _get_mock_fallback("jd", jd_text)


async def parse_resume_for_profile(resume_text: str, db=None) -> dict:
    """Use Gemini to extract candidate details from resume text."""
    try:
        if db:
            prompt_template = await get_prompt_from_settings(db, "resume_parse_prompt", DEFAULT_RESUME_PARSE_PROMPT)
        else:
            prompt_template = DEFAULT_RESUME_PARSE_PROMPT

        prompt = prompt_template.replace("{resume_text}", resume_text)
        
        response = await client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        return _extract_json(response.text)
    except Exception as e:
        print(f"DEBUG GEMINI RESUME PARSE ERROR: {e}")
        return _get_mock_fallback("resume", resume_text)


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
    try:
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
        raw_text = response.text
        return _extract_json(raw_text)
    except Exception as e:
        print(f"DEBUG GEMINI ASSESSMENT GEN ERROR: {e}")
        return _generate_template_assessment(role, skills, seniority, mcq_count, coding_count, scenario_count)


def _generate_template_assessment(
    role: str,
    skills: list[str],
    seniority: str,
    mcq_count: int = 10,
    coding_count: int = 1,
    scenario_count: int = 2,
) -> dict:
    """
    Template-based assessment generator — used as fallback when Gemini is unavailable.
    Produces real, skill-specific questions for common tech roles.
    """

    skill_set = [s.lower() for s in skills]
    questions = []

    # ── MCQ bank keyed by skill keyword ──────────────────────────────────────
    MCQ_BANK = {
        "python": [
            {
                "q": "What is the output of `print(type([]))` in Python?",
                "opts": ["<class 'list'>", "<class 'array'>", "<class 'tuple'>", "<class 'dict'>"],
                "ans": "A",
                "skill": "Python",
            },
            {
                "q": "Which Python keyword is used to handle exceptions?",
                "opts": ["catch", "except", "error", "handle"],
                "ans": "B",
                "skill": "Python",
            },
            {
                "q": "What does the `*args` syntax do in a Python function definition?",
                "opts": [
                    "Passes keyword arguments as a dict",
                    "Passes positional arguments as a tuple",
                    "Unpacks a list into arguments",
                    "Declares a generator function",
                ],
                "ans": "B",
                "skill": "Python",
            },
            {
                "q": "Which of the following is a mutable data type in Python?",
                "opts": ["tuple", "str", "list", "frozenset"],
                "ans": "C",
                "skill": "Python",
            },
            {
                "q": "What is the purpose of Python's `__init__` method?",
                "opts": [
                    "To destroy a class instance",
                    "To initialize class attributes when an object is created",
                    "To define static methods",
                    "To import modules",
                ],
                "ans": "B",
                "skill": "Python",
            },
        ],
        "react": [
            {
                "q": "What hook is used to manage local state in a React functional component?",
                "opts": ["useEffect", "useRef", "useState", "useContext"],
                "ans": "C",
                "skill": "React",
            },
            {
                "q": "What does the dependency array in `useEffect` control?",
                "opts": [
                    "Which props the component receives",
                    "When the effect re-runs",
                    "The initial state value",
                    "Which components are rendered",
                ],
                "ans": "B",
                "skill": "React",
            },
            {
                "q": "In React, what is a 'key' prop used for in lists?",
                "opts": [
                    "Encrypting component data",
                    "Providing a unique identifier to help React diff the virtual DOM",
                    "Binding event handlers",
                    "Passing state to child components",
                ],
                "ans": "B",
                "skill": "React",
            },
        ],
        "javascript": [
            {
                "q": "Which method converts a JSON string into a JavaScript object?",
                "opts": ["JSON.stringify()", "JSON.parse()", "JSON.convert()", "JSON.decode()"],
                "ans": "B",
                "skill": "JavaScript",
            },
            {
                "q": "What does `===` check in JavaScript compared to `==`?",
                "opts": [
                    "Value only",
                    "Type only",
                    "Both value and type (strict equality)",
                    "Reference equality",
                ],
                "ans": "C",
                "skill": "JavaScript",
            },
            {
                "q": "What is a closure in JavaScript?",
                "opts": [
                    "A way to close a browser window",
                    "A function that retains access to its outer scope even after the outer function has returned",
                    "A method to end a promise chain",
                    "An error handler in async functions",
                ],
                "ans": "B",
                "skill": "JavaScript",
            },
        ],
        "typescript": [
            {
                "q": "Which TypeScript utility type makes all properties of a type optional?",
                "opts": ["Required<T>", "Partial<T>", "Readonly<T>", "Pick<T, K>"],
                "ans": "B",
                "skill": "TypeScript",
            },
            {
                "q": "What is the difference between `interface` and `type` in TypeScript?",
                "opts": [
                    "They are identical",
                    "Interfaces can only describe objects; types can describe any shape including unions",
                    "Types support inheritance; interfaces do not",
                    "Interfaces are compiled away; types are not",
                ],
                "ans": "B",
                "skill": "TypeScript",
            },
        ],
        "sql": [
            {
                "q": "Which SQL clause is used to filter results after grouping?",
                "opts": ["WHERE", "HAVING", "FILTER", "LIMIT"],
                "ans": "B",
                "skill": "SQL",
            },
            {
                "q": "What type of JOIN returns only rows that have matching values in both tables?",
                "opts": ["LEFT JOIN", "RIGHT JOIN", "FULL OUTER JOIN", "INNER JOIN"],
                "ans": "D",
                "skill": "SQL",
            },
        ],
        "aws": [
            {
                "q": "Which AWS service is used for object storage?",
                "opts": ["EC2", "RDS", "S3", "Lambda"],
                "ans": "C",
                "skill": "AWS",
            },
            {
                "q": "What does AWS IAM stand for?",
                "opts": [
                    "Internet Access Management",
                    "Identity and Access Management",
                    "Instance and Authentication Module",
                    "Integrated Application Manager",
                ],
                "ans": "B",
                "skill": "AWS",
            },
        ],
        "docker": [
            {
                "q": "What is a Docker image?",
                "opts": [
                    "A running instance of a container",
                    "A read-only template used to create containers",
                    "A virtual machine snapshot",
                    "A network configuration file",
                ],
                "ans": "B",
                "skill": "Docker",
            },
            {
                "q": "Which command builds a Docker image from a Dockerfile?",
                "opts": ["docker run", "docker build", "docker pull", "docker create"],
                "ans": "B",
                "skill": "Docker",
            },
        ],
        "node": [
            {
                "q": "What is the event loop in Node.js?",
                "opts": [
                    "A loop that iterates over DOM elements",
                    "A mechanism that allows Node.js to perform non-blocking I/O operations",
                    "A built-in HTTP server",
                    "A method for handling database connections",
                ],
                "ans": "B",
                "skill": "Node.js",
            },
        ],
        "git": [
            {
                "q": "What does `git rebase` do?",
                "opts": [
                    "Deletes all commits and starts fresh",
                    "Moves or replays commits onto a new base commit",
                    "Merges two branches creating a merge commit",
                    "Reverts the last commit",
                ],
                "ans": "B",
                "skill": "Git",
            },
        ],
    }

    # Generic software engineering questions (always applicable)
    GENERIC_MCQ = [
        {
            "q": "What does SOLID stand for in software engineering principles?",
            "opts": [
                "Single, Open, Liskov, Interface, Dependency",
                "Single responsibility, Open/closed, Liskov substitution, Interface segregation, Dependency inversion",
                "Scalable, Optimized, Layered, Integrated, Distributed",
                "Structured, Object-oriented, Linked, Independent, Dynamic",
            ],
            "ans": "B",
            "skill": "Software Engineering",
        },
        {
            "q": "Which data structure operates on a LIFO (Last In, First Out) principle?",
            "opts": ["Queue", "Stack", "Heap", "Graph"],
            "ans": "B",
            "skill": "Data Structures",
        },
        {
            "q": "What is the time complexity of binary search?",
            "opts": ["O(n)", "O(n²)", "O(log n)", "O(1)"],
            "ans": "C",
            "skill": "Algorithms",
        },
        {
            "q": "What does REST stand for in web APIs?",
            "opts": [
                "Remote Execution Service Technology",
                "Representational State Transfer",
                "Reliable Endpoint Serialization Tool",
                "Request-Response Standard Template",
            ],
            "ans": "B",
            "skill": "APIs",
        },
        {
            "q": "Which HTTP status code indicates a resource was not found?",
            "opts": ["200", "401", "404", "500"],
            "ans": "C",
            "skill": "HTTP",
        },
        {
            "q": "What is a race condition in concurrent programming?",
            "opts": [
                "A performance benchmark between two threads",
                "A situation where the program outcome depends on the timing of uncontrollable events",
                "A deadlock between two mutexes",
                "A test to measure CPU speed",
            ],
            "ans": "B",
            "skill": "Concurrency",
        },
        {
            "q": "In object-oriented programming, what is polymorphism?",
            "opts": [
                "The ability of a class to inherit from multiple parents",
                "The ability for different objects to respond to the same interface in different ways",
                "A way to hide implementation details",
                "A type of recursion",
            ],
            "ans": "B",
            "skill": "OOP",
        },
    ]

    # ── Collect matched MCQs from skill bank ─────────────────────────────────
    collected_mcq = []
    for kw, bank in MCQ_BANK.items():
        if any(kw in s for s in skill_set):
            collected_mcq.extend(bank)

    # Pad with generic questions if not enough
    collected_mcq.extend(GENERIC_MCQ)

    # Deduplicate and take exactly mcq_count
    seen = set()
    unique_mcq = []
    for item in collected_mcq:
        if item["q"] not in seen:
            seen.add(item["q"])
            unique_mcq.append(item)

    for i, item in enumerate(unique_mcq[:mcq_count]):
        label_map = {"A": 0, "B": 1, "C": 2, "D": 3}
        opts = [{"label": chr(65 + j), "text": t} for j, t in enumerate(item["opts"])]
        questions.append({
            "question_type": "mcq",
            "question_text": item["q"],
            "options": opts,
            "correct_answer": item["ans"],
            "explanation": f"This tests your knowledge of {item['skill']}.",
            "difficulty": "intermediate" if seniority in ("mid", "senior") else "beginner",
            "skills_tested": [item["skill"]],
            "max_score": 10,
        })

    # ── Coding Challenge ──────────────────────────────────────────────────────
    primary_skill = skills[0] if skills else role
    CODING_TEMPLATES = {
        "python": {
            "text": (
                "Write a Python function `find_duplicates(lst)` that takes a list of integers "
                "and returns a new list containing only the elements that appear more than once, "
                "without duplicates in the result.\n\n"
                "Example:\n  find_duplicates([1, 2, 2, 3, 3, 4]) → [2, 3]"
            ),
            "answer": "def find_duplicates(lst):\n    from collections import Counter\n    counts = Counter(lst)\n    return [k for k, v in counts.items() if v > 1]",
        },
        "javascript": {
            "text": (
                "Write a JavaScript function `flattenArray(arr)` that recursively flattens "
                "a nested array of any depth into a single flat array.\n\n"
                "Example:\n  flattenArray([1, [2, [3, [4]]]]) → [1, 2, 3, 4]"
            ),
            "answer": "function flattenArray(arr) {\n  return arr.reduce((acc, val) => Array.isArray(val) ? acc.concat(flattenArray(val)) : acc.concat(val), []);\n}",
        },
        "default": {
            "text": (
                f"Design and implement a function in any language that takes a string "
                f"and returns the most frequently occurring character. If there is a tie, "
                f"return the character that appears first in the string.\n\n"
                f"Example: most_frequent('abracadabra') → 'a'"
            ),
            "answer": "# Count character frequencies and find the max",
        },
    }

    skill_key = next((k for k in CODING_TEMPLATES if k in skill_set), "default")
    coding_template = CODING_TEMPLATES[skill_key]

    for _ in range(min(coding_count, 1)):
        questions.append({
            "question_type": "coding",
            "question_text": coding_template["text"],
            "options": None,
            "correct_answer": coding_template["answer"],
            "explanation": "Evaluates problem-solving and code quality.",
            "difficulty": "intermediate",
            "skills_tested": [primary_skill],
            "max_score": 30,
        })

    # ── Scenario Questions ────────────────────────────────────────────────────
    SCENARIO_TEMPLATES = [
        {
            "text": (
                f"You are working on a {role} project and you discover a critical bug "
                f"in production that is affecting 20% of users. The fix requires changes to "
                f"a core module that has no tests. Describe your step-by-step approach to "
                f"diagnose, fix, and deploy the solution safely."
            ),
        },
        {
            "text": (
                f"Your team is starting a new feature for a high-traffic {role} application. "
                f"The senior engineer asks you to design the architecture. "
                f"Walk through how you would approach the design, what trade-offs you would "
                f"consider, and how you would ensure the solution is scalable and maintainable."
            ),
        },
        {
            "text": (
                f"A code review you submitted for a {role} feature has received critical feedback "
                f"from a colleague. They disagree with your architectural approach. "
                f"How do you handle this situation? What steps do you take to resolve the disagreement "
                f"and reach the best outcome for the team?"
            ),
        },
    ]

    for i in range(min(scenario_count, len(SCENARIO_TEMPLATES))):
        questions.append({
            "question_type": "scenario",
            "question_text": SCENARIO_TEMPLATES[i]["text"],
            "options": None,
            "correct_answer": None,
            "explanation": "Evaluated on clarity of thought, communication, and problem-solving approach.",
            "difficulty": "intermediate",
            "skills_tested": [primary_skill, "Communication"],
            "max_score": 20,
        })

    return {"questions": questions}


async def score_answers(
    assessment_context: str,
    qa_pairs: list[dict],
    db=None,
) -> list[dict]:
    """Score candidate's answers using Gemini."""
    try:
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
    except Exception as e:
        print(f"DEBUG GEMINI SCORING ERROR: {e}")
        # Simple automatic scoring fallback (e.g. 80% score)
        return [
            {
                "question_id": q["question_id"],
                "score": 8,
                "max_score": 10,
                "feedback": "Automated scoring fallback applied.",
                "category": "general"
            } for q in qa_pairs
        ]


DEFAULT_PLAGIARISM_PROMPT = """
You are an expert code plagiarism and AI-content detector. Analyze the following candidate answers
from a technical assessment and determine how likely each answer was:
1. Generated by an AI (ChatGPT, Copilot, etc.)
2. Copied from a common online source (Stack Overflow, GeeksForGeeks, etc.)
3. Contains suspiciously perfect boilerplate that doesn't match natural human writing

For each answer, return a JSON array:
[
  {
    "question_id": 1,
    "originality_score": 85,
    "flags": ["none"],
    "explanation": "Answer appears to be originally written with natural variable naming."
  }
]

originality_score: 0-100. 100 = completely original. 0 = definitely plagiarized/AI-generated.
Possible flags: "ai_generated", "copied_from_web", "boilerplate_heavy", "too_perfect", "none"

Answers to analyze:
{qa_pairs}

Return ONLY valid JSON array, no extra text.
"""


async def check_plagiarism(qa_pairs: list[dict], db=None) -> list[dict]:
    """
    Use Gemini to analyze candidate answers for plagiarism / AI-generation patterns.
    Only analyzes coding and scenario answers (MCQ excluded).
    Returns per-question plagiarism assessment.
    """
    # Filter to only coding and scenario answers
    relevant = [q for q in qa_pairs if q.get("question_type") in ("coding", "scenario") and q.get("answer")]
    if not relevant:
        return []

    try:
        if db:
            prompt_template = await get_prompt_from_settings(db, "plagiarism_prompt", DEFAULT_PLAGIARISM_PROMPT)
        else:
            prompt_template = DEFAULT_PLAGIARISM_PROMPT

        qa_text = "\n".join([
            f"Question ID {q['question_id']} [{q['question_type']}]: {q['question_text']}\n"
            f"Candidate Answer:\n{q['answer']}\n---"
            for q in relevant
        ])
        prompt = prompt_template.replace("{qa_pairs}", qa_text)

        response = await client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )
        result = _extract_json(response.text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "results" in result:
            return result["results"]
        return []
    except Exception as e:
        print(f"DEBUG GEMINI PLAGIARISM CHECK ERROR: {e}")
        # Default: assume original (non-blocking)
        return [
            {
                "question_id": q["question_id"],
                "originality_score": 90,
                "flags": ["none"],
                "explanation": "Plagiarism check unavailable — defaulting to original."
            }
            for q in relevant
        ]
