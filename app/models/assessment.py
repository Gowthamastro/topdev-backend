import enum
from typing import Optional, List, Dict
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Integer, ForeignKey, Text, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class QuestionType(str, enum.Enum):
    MCQ = "mcq"
    CODING = "coding"
    SCENARIO = "scenario"
    OPEN = "open"


class AssessmentStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    EXPIRED = "expired"


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_description_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("job_descriptions.id", ondelete="CASCADE"), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default=AssessmentStatus.ACTIVE.value)
    has_coding_round: Mapped[bool] = mapped_column(Boolean, default=True)
    mcq_count: Mapped[int] = mapped_column(Integer, default=10)
    coding_count: Mapped[int] = mapped_column(Integer, default=2)
    scenario_count: Mapped[int] = mapped_column(Integer, default=3)
    time_limit_minutes: Mapped[int] = mapped_column(Integer, default=90)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    job_description: Mapped["JobDescription"] = relationship("JobDescription", back_populates="assessments")
    questions: Mapped[List["Question"]] = relationship("Question", back_populates="assessment", cascade="all, delete-orphan")
    test_attempts: Mapped[List["TestAttempt"]] = relationship("TestAttempt", back_populates="assessment")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    assessment_id: Mapped[int] = mapped_column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), index=True)
    question_type: Mapped[str] = mapped_column(String(50), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[Optional[Dict]] = mapped_column(JSONB)           # for MCQ: list of {label, text}
    correct_answer: Mapped[Optional[str]] = mapped_column(Text)      # for MCQ & scenario
    explanation: Mapped[Optional[str]] = mapped_column(Text)
    difficulty: Mapped[Optional[str]] = mapped_column(String(50))
    skills_tested: Mapped[Optional[List[str]]] = mapped_column(JSONB)     # list of strings
    max_score: Mapped[int] = mapped_column(Integer, default=10)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    assessment: Mapped["Assessment"] = relationship("Assessment", back_populates="questions")
