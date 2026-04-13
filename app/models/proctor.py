from __future__ import annotations
import enum
from typing import Optional, Dict
from datetime import datetime
from sqlalchemy import String, DateTime, Integer, ForeignKey, Text, Float, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class EventType(str, enum.Enum):
    TAB_SWITCH = "tab_switch"
    FOCUS_LOST = "focus_lost"
    FOCUS_GAINED = "focus_gained"
    COPY = "copy"
    PASTE = "paste"
    RIGHT_CLICK = "right_click"
    FULLSCREEN_EXIT = "fullscreen_exit"
    PROCTORING_DECLINED = "proctoring_declined"


class ProctoringEvent(Base):
    __tablename__ = "proctor_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    attempt_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("test_attempts.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    client_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    event_data: Mapped[Optional[Dict]] = mapped_column(JSONB)  # extra context per event
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    attempt: Mapped["TestAttempt"] = relationship("TestAttempt", back_populates="proctor_events")
