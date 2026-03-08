"""Background Celery tasks for async processing."""
import asyncio
from datetime import datetime, timezone
from app.workers.celery_app import celery_app
from app.core.config import settings


@celery_app.task(name="score_test_attempt", bind=True, max_retries=3)
def score_test_attempt_task(self, attempt_id: int):
    """Score a submitted test attempt asynchronously."""
    from app.core.database import AsyncSessionLocal
    from app.models.test_attempt import TestAttempt, AttemptStatus
    from app.models.assessment import Question
    from app.ai.openai_service import score_answers
    from app.services.scoring_service import get_active_weights, compute_weighted_score, assign_badge
    from app.services.email_service import send_result_notification
    from sqlalchemy import select

    async def _score():
        async with AsyncSessionLocal() as db:
            # Load attempt
            result = await db.execute(select(TestAttempt).where(TestAttempt.id == attempt_id))
            attempt = result.scalar_one_or_none()
            if not attempt:
                return

            # Load questions
            q_result = await db.execute(
                select(Question).where(Question.assessment_id == attempt.assessment_id)
            )
            questions = q_result.scalars().all()

            answers = attempt.answers or {}
            qa_pairs = [
                {
                    "question_id": q.id,
                    "question_type": q.question_type.value,
                    "question_text": q.question_text,
                    "answer": answers.get(str(q.id), ""),
                    "max_score": q.max_score,
                }
                for q in questions
            ]

            scored = await score_answers("Technical assessment", qa_pairs, db)

            # Aggregate by category
            cats = {"technical": (0, 0), "coding": (0, 0), "problem_solving": (0, 0)}
            for s in scored:
                cat = s.get("category", "technical")
                if cat not in cats:
                    cat = "technical"
                earned, total = cats[cat]
                cats[cat] = (earned + s.get("score", 0), total + s.get("max_score", 10))

            weights = await get_active_weights(db)
            scores = compute_weighted_score(
                cats["technical"][0], cats["coding"][0], cats["problem_solving"][0],
                cats["technical"][1] or 1, cats["coding"][1] or 1, cats["problem_solving"][1] or 1,
                weights,
            )

            badge, qualified = assign_badge(scores["total_score"], weights.qualification_threshold)

            attempt.total_score = scores["total_score"]
            attempt.technical_score = scores["technical_score"]
            attempt.coding_score = scores["coding_score"]
            attempt.problem_solving_score = scores["problem_solving_score"]
            attempt.rating_badge = badge
            attempt.is_qualified = qualified
            attempt.score_breakdown = scored
            attempt.status = AttemptStatus.SCORED
            attempt.scored_at = datetime.now(timezone.utc)
            await db.commit()

    asyncio.run(_score())


@celery_app.task(name="send_test_invitation_task")
def send_test_invitation_task(
    candidate_name: str,
    candidate_email: str,
    test_link: str,
    role_title: str,
    company_name: str,
    expires_hours: int = 48,
):
    from app.core.database import AsyncSessionLocal
    from app.services.email_service import send_test_invitation

    async def _send():
        async with AsyncSessionLocal() as db:
            await send_test_invitation(
                db, candidate_name, candidate_email, test_link,
                role_title, company_name, expires_hours
            )

    asyncio.run(_send())
