"""Proctoring API — receives behavioral events from the candidate's browser and serves integrity reports."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from app.core.database import get_db
from app.models.test_attempt import TestAttempt, AttemptStatus
from app.models.proctor import ProctoringEvent, EventType

router = APIRouter(prefix="/proctor", tags=["proctoring"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class ProctoringEventIn(BaseModel):
    event_type: str
    client_timestamp: str | None = None  # ISO 8601 from the browser
    metadata: dict | None = None


class BatchEventsRequest(BaseModel):
    events: list[ProctoringEventIn]


class ConsentUpdate(BaseModel):
    consented: bool


# ─── Batch receive events ────────────────────────────────────────────────────

@router.post("/{token}/events")
async def receive_events(token: str, data: BatchEventsRequest, db: AsyncSession = Depends(get_db)):
    """Receive a batch of proctoring events from the candidate's browser (called every ~10s)."""
    result = await db.execute(select(TestAttempt).where(TestAttempt.token == token))
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(404, "Invalid token")
    if attempt.status in (AttemptStatus.SUBMITTED, AttemptStatus.SCORED, AttemptStatus.EXPIRED):
        # Silently accept — don't error after submission
        return {"received": 0}

    created = 0
    for ev in data.events:
        # Validate event type
        try:
            EventType(ev.event_type)
        except ValueError:
            continue  # skip unknown event types

        ts = None
        if ev.client_timestamp:
            try:
                ts = datetime.fromisoformat(ev.client_timestamp.replace("Z", "+00:00"))
            except Exception:
                ts = datetime.now(timezone.utc)

        event = ProctoringEvent(
            attempt_id=attempt.id,
            event_type=ev.event_type,
            client_timestamp=ts,
            event_data=ev.metadata,
        )
        db.add(event)
        created += 1

    await db.commit()
    return {"received": created}


# ─── Consent tracking ────────────────────────────────────────────────────────

@router.post("/{token}/consent")
async def update_consent(token: str, data: ConsentUpdate, db: AsyncSession = Depends(get_db)):
    """Track whether the candidate accepted or declined the proctoring consent."""
    result = await db.execute(select(TestAttempt).where(TestAttempt.token == token))
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(404, "Invalid token")

    attempt.proctoring_consented = data.consented

    if not data.consented:
        # Record the decline as an event
        event = ProctoringEvent(
            attempt_id=attempt.id,
            event_type=EventType.PROCTORING_DECLINED.value,
            client_timestamp=datetime.now(timezone.utc),
            event_data={"reason": "Candidate declined proctoring consent"},
        )
        db.add(event)

    await db.commit()
    return {"consented": data.consented}


# ─── Integrity summary (for recruiters) ──────────────────────────────────────

@router.get("/attempt/{attempt_id}/summary")
async def get_integrity_summary(attempt_id: int, db: AsyncSession = Depends(get_db)):
    """Return the computed integrity report for a test attempt."""
    result = await db.execute(select(TestAttempt).where(TestAttempt.id == attempt_id))
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(404, "Attempt not found")

    # Fetch event counts
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

    return {
        "attempt_id": attempt_id,
        "integrity_score": attempt.integrity_score,
        "integrity_flags": attempt.integrity_flags or {},
        "proctor_summary": attempt.proctor_summary,
        "proctoring_consented": attempt.proctoring_consented,
        "event_counts": event_counts,
    }
