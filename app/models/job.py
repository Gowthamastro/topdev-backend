import enum
from typing import Optional, List, Dict
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Integer, ForeignKey, Text, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class DifficultyLevel(str, enum.Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class JDStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    FILLED = "filled"


class JobDescription(Base):
    __tablename__ = "job_descriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    jd_file_url: Mapped[Optional[str]] = mapped_column(String(500))
    jd_s3_key: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(50), default=JDStatus.ACTIVE.value)

    # AI Extracted fields
    required_skills: Mapped[Optional[List[str]]] = mapped_column(JSONB)   # list of strings
    preferred_skills: Mapped[Optional[List[str]]] = mapped_column(JSONB)
    min_years_experience: Mapped[Optional[int]] = mapped_column(Integer)
    max_years_experience: Mapped[Optional[int]] = mapped_column(Integer)
    seniority_level: Mapped[Optional[str]] = mapped_column(String(100))
    difficulty_level: Mapped[Optional[str]] = mapped_column(String(50))
    parsed_summary: Mapped[Optional[str]] = mapped_column(Text)
    technologies: Mapped[Optional[List[str]]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    client: Mapped["Client"] = relationship("Client", back_populates="job_descriptions")
    assessments: Mapped[List["Assessment"]] = relationship("Assessment", back_populates="job_description")
