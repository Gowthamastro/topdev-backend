from __future__ import annotations
import enum
from typing import Optional, List, Dict
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Integer, ForeignKey, Text, Numeric, func, ARRAY, Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class ExperienceLevel(str, enum.Enum):
    JUNIOR = "junior"        # 0-2 years
    MID = "mid"              # 3-5 years
    SENIOR = "senior"        # 6+ years


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    location: Mapped[Optional[str]] = mapped_column(String(255))
    years_of_experience: Mapped[Optional[int]] = mapped_column(Integer)
    experience_level: Mapped[Optional[str]] = mapped_column(String(50))
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(500))
    github_url: Mapped[Optional[str]] = mapped_column(String(500))
    portfolio_url: Mapped[Optional[str]] = mapped_column(String(500))
    resume_url: Mapped[Optional[str]] = mapped_column(String(500))  # S3 key
    resume_s3_key: Mapped[Optional[str]] = mapped_column(String(500))
    headline: Mapped[Optional[str]] = mapped_column(String(500))
    bio: Mapped[Optional[str]] = mapped_column(Text)
    skills: Mapped[Optional[List[str]]] = mapped_column(JSONB)  # ["Python", "React", ...]
    current_salary: Mapped[Optional[int]] = mapped_column(Integer)
    expected_salary: Mapped[Optional[int]] = mapped_column(Integer)
    notice_period_days: Mapped[Optional[int]] = mapped_column(Integer)  # 0=immediate, 15, 30, 60, 90

    # ─── Phase 1: Profile completion tracking ────────────────────────────
    is_profile_complete: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="candidate_profile")
    test_attempts: Mapped[List["TestAttempt"]] = relationship("TestAttempt", back_populates="candidate")
