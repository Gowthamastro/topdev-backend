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
    from app.ai.gemini_service import score_answers
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
            cats = {"technical": (0, 0), "communication": (0, 0), "cultural_fit": (0, 0)}
            for s in scored:
                cat = s.get("category", "technical")
                if cat not in cats:
                    cat = "technical"
                earned, total = cats[cat]
                cats[cat] = (earned + s.get("score", 0), total + s.get("max_score", 10))

            weights = await get_active_weights(db)
            scores = compute_weighted_score(
                cats["technical"][0], cats["communication"][0], cats["cultural_fit"][0],
                cats["technical"][1] or 1, cats["communication"][1] or 1, cats["cultural_fit"][1] or 1,
                weights,
            )

            badge, qualified = assign_badge(scores["total_score"], weights.qualification_threshold)

            attempt.total_score = scores["total_score"]
            attempt.technical_score = scores["technical_score"]
            attempt.communication_score = scores["communication_score"]
            attempt.cultural_fit_score = scores["cultural_fit_score"]
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


@celery_app.task(name="compute_integrity_score", bind=True, max_retries=2)
def compute_integrity_score_task(self, attempt_id: int):
    """Compute the integrity score for a submitted test attempt by analyzing proctor events and running plagiarism detection."""
    from app.core.database import AsyncSessionLocal
    from app.models.test_attempt import TestAttempt
    from app.models.proctor import ProctoringEvent, EventType
    from app.models.assessment import Question
    from app.ai.gemini_service import check_plagiarism
    from sqlalchemy import select, func

    async def _compute():
        async with AsyncSessionLocal() as db:
            # Load attempt
            result = await db.execute(select(TestAttempt).where(TestAttempt.id == attempt_id))
            attempt = result.scalar_one_or_none()
            if not attempt:
                return

            # ── Count proctor events by type ──────────────────────────────
            event_counts = {}
            for et in EventType:
                count_result = await db.execute(
                    select(func.count(ProctoringEvent.id)).where(
                        ProctoringEvent.attempt_id == attempt_id,
                        ProctoringEvent.event_type == et.value,
                    )
                )
                count = count_result.scalar() or 0
                if count > 0:
                    event_counts[et.value] = count

            # ── Calculate base integrity score ────────────────────────────
            score = 100.0

            tab_switches = event_counts.get("tab_switch", 0)
            focus_lost = event_counts.get("focus_lost", 0)
            pastes = event_counts.get("paste", 0)
            copies = event_counts.get("copy", 0)
            right_clicks = event_counts.get("right_click", 0)
            declined = event_counts.get("proctoring_declined", 0)

            # Deductions
            score -= min(tab_switches * 3, 30)     # max -30 for tab switches
            score -= min(focus_lost * 2, 20)        # max -20 for focus loss
            score -= min(pastes * 5, 25)            # max -25 for pastes
            score -= min(copies * 2, 10)            # max -10 for copies
            score -= min(right_clicks * 1, 5)       # max -5 for right clicks
            if declined > 0:
                score -= 10                          # -10 for declining proctoring

            # ── Run AI plagiarism detection ────────────────────────────────
            plagiarism_results = []
            if attempt.answers:
                q_result = await db.execute(
                    select(Question).where(Question.assessment_id == attempt.assessment_id)
                )
                questions = q_result.scalars().all()
                answers = attempt.answers or {}
                qa_pairs = [
                    {
                        "question_id": q.id,
                        "question_type": getattr(q.question_type, "value", q.question_type),
                        "question_text": q.question_text,
                        "answer": answers.get(str(q.id), ""),
                    }
                    for q in questions
                ]
                plagiarism_results = await check_plagiarism(qa_pairs, db)

                # Apply plagiarism deductions
                for pr in plagiarism_results:
                    originality = pr.get("originality_score", 100)
                    flags = pr.get("flags", [])
                    if "ai_generated" in flags:
                        score -= 15
                    elif "copied_from_web" in flags:
                        score -= 12
                    elif "boilerplate_heavy" in flags:
                        score -= 5
                    elif originality < 40:
                        score -= 10

            score = max(0, min(100, score))  # clamp 0-100

            # ── Build summary ─────────────────────────────────────────────
            flags_summary = {
                "tab_switches": tab_switches,
                "focus_lost": focus_lost,
                "pastes": pastes,
                "copies": copies,
                "right_clicks": right_clicks,
                "proctoring_declined": declined > 0,
                "plagiarism_results": plagiarism_results,
            }

            # Generate narrative
            concerns = []
            if tab_switches > 3:
                concerns.append(f"switched browser tabs {tab_switches} times")
            if pastes > 0:
                concerns.append(f"used paste {pastes} time(s)")
            if focus_lost > 5:
                concerns.append(f"lost window focus {focus_lost} times")
            if declined > 0:
                concerns.append("declined proctoring consent")
            flagged_answers = [pr for pr in plagiarism_results if "none" not in pr.get("flags", ["none"])]
            if flagged_answers:
                concerns.append(f"{len(flagged_answers)} answer(s) flagged for potential plagiarism/AI generation")

            if not concerns:
                narrative = "No integrity concerns detected. Candidate behavior appears normal throughout the assessment."
            else:
                narrative = f"Integrity concerns: candidate {', '.join(concerns)}. Integrity score: {score:.0f}/100."

            # ── Persist ───────────────────────────────────────────────────
            attempt.integrity_score = round(score, 1)
            attempt.integrity_flags = flags_summary
            attempt.proctor_summary = narrative
            await db.commit()

    asyncio.run(_compute())
