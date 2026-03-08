import enum
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Integer, ForeignKey, Text, Numeric, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class SubscriptionPlan(str, enum.Enum):
    STARTER = "starter"
    GROWTH = "growth"
    ENTERPRISE = "enterprise"
    FREE = "free"


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_size: Mapped[str | None] = mapped_column(String(50))
    industry: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(String(255))
    logo_url: Mapped[str | None] = mapped_column(String(500))
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    subscription_plan: Mapped[str] = mapped_column(String(50), default=SubscriptionPlan.FREE.value)
    roles_used_this_month: Mapped[int] = mapped_column(Integer, default=0)
    billing_cycle_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="client_profile")
    job_descriptions: Mapped[list["JobDescription"]] = relationship("JobDescription", back_populates="client")
    subscriptions: Mapped[list["Subscription"]] = relationship("Subscription", back_populates="client")
