import enum
import secrets
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
    job_description_id: Mapped[int] = mapped_column(Integer, ForeignKey("job_descriptions.id"), index=True)

    # Secure token for test link
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True, default=lambda: secrets.token_urlsafe(32))
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[str] = mapped_column(String(50), default=AttemptStatus.INVITED.value)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answers: Mapped[dict | None] = mapped_column(JSONB)  # {question_id: answer_text}

    # Scoring
    total_score: Mapped[float | None] = mapped_column(Float)
    technical_score: Mapped[float | None] = mapped_column(Float)
    coding_score: Mapped[float | None] = mapped_column(Float)
    problem_solving_score: Mapped[float | None] = mapped_column(Float)
    rating_badge: Mapped[str | None] = mapped_column(String(50))
    is_qualified: Mapped[bool] = mapped_column(Boolean, default=False)
    score_breakdown: Mapped[dict | None] = mapped_column(JSONB)
    ai_feedback: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    assessment: Mapped["Assessment"] = relationship("Assessment", back_populates="test_attempts")
    candidate: Mapped["Candidate"] = relationship("Candidate", back_populates="test_attempts")
