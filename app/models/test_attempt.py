import enum
import secrets
from typing import Optional, List, Dict
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Integer, ForeignKey, Text, Numeric, func, Float
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class AttemptStatus(str, enum.Enum):
    INVITED = "invited"
    STARTED = "started"
    SUBMITTED = "submitted"
    SCORED = "scored"
    EXPIRED = "expired"


class PipelineStage(str, enum.Enum):
    SOURCED = "sourced"
    APPLIED = "applied"
    SCREENED = "screened"
    INTERVIEW = "interview"
    OFFERED = "offered"
    HIRED = "hired"


class RatingBadge(str, enum.Enum):
    ELITE = "elite"          # 90+
    STRONG = "strong"        # 75-89
    QUALIFIED = "qualified"  # 60-74
    BELOW_THRESHOLD = "below_threshold"


class TestAttempt(Base):
    __tablename__ = "test_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    assessment_id: Mapped[int] = mapped_column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(Integer, ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    job_description_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("job_descriptions.id"), index=True, nullable=True)

    # Secure token for test link
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True, default=lambda: secrets.token_urlsafe(32))
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    status: Mapped[str] = mapped_column(String(50), default=AttemptStatus.INVITED.value)
    pipeline_stage: Mapped[str] = mapped_column(String(50), default=PipelineStage.SOURCED.value)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    answers: Mapped[Optional[Dict]] = mapped_column(JSONB)  # {question_id: answer_text}

    # Scoring
    total_score: Mapped[Optional[float]] = mapped_column(Float)
    technical_score: Mapped[Optional[float]] = mapped_column(Float)
    communication_score: Mapped[Optional[float]] = mapped_column(Float)
    cultural_fit_score: Mapped[Optional[float]] = mapped_column(Float)
    rating_badge: Mapped[Optional[str]] = mapped_column(String(50))
    is_qualified: Mapped[bool] = mapped_column(Boolean, default=False)
    score_breakdown: Mapped[Optional[Dict]] = mapped_column(JSONB)
    ai_feedback: Mapped[Optional[str]] = mapped_column(Text)

    # Proctoring / Integrity
    integrity_score: Mapped[Optional[float]] = mapped_column(Float)  # 0-100, higher = more trustworthy
    integrity_flags: Mapped[Optional[Dict]] = mapped_column(JSONB)   # {"tab_switches": 5, ...}
    proctor_summary: Mapped[Optional[str]] = mapped_column(Text)     # AI-generated integrity narrative
    proctoring_consented: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    scored_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    assessment: Mapped["Assessment"] = relationship("Assessment", back_populates="test_attempts")
    candidate: Mapped["Candidate"] = relationship("Candidate", back_populates="test_attempts")
    proctor_events: Mapped[List["ProctoringEvent"]] = relationship("ProctoringEvent", back_populates="attempt", cascade="all, delete-orphan")
