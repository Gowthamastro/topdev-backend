"""OTP endpoints for phone verification (Phase 1)."""
import random
import time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.candidate import Candidate

router = APIRouter(prefix="/otp", tags=["otp"])

# In-memory OTP store — production should use Redis or a DB table
_otp_store: dict[str, dict] = {}
OTP_EXPIRY_SECONDS = 300  # 5 minutes


class SendOTPRequest(BaseModel):
    phone: str


class VerifyOTPRequest(BaseModel):
    phone: str
    otp: str


@router.post("/send")
async def send_otp(
    data: SendOTPRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a 6-digit OTP and log it to the console.
    In production, this would dispatch via Twilio/AWS SNS."""
    phone = data.phone.strip()
    if not phone or len(phone) < 10:
        raise HTTPException(400, "Invalid phone number")

    # Hardcoded for development testing
    otp_code = "123456"
    _otp_store[f"{current_user.id}:{phone}"] = {
        "otp": otp_code,
        "expires_at": time.time() + OTP_EXPIRY_SECONDS,
    }

    # ── Mock delivery — log to console ──────────────────────────────────
    print(f"[OTP] User {current_user.id} | Phone {phone} | OTP: {otp_code}")

    return {"message": "OTP sent successfully", "phone": phone}


@router.post("/verify")
async def verify_otp(
    data: VerifyOTPRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    phone = data.phone.strip()
    key = f"{current_user.id}:{phone}"
    stored = _otp_store.get(key)

    if not stored:
        raise HTTPException(400, "No OTP requested for this number")

    if time.time() > stored["expires_at"]:
        _otp_store.pop(key, None)
        raise HTTPException(400, "OTP expired. Request a new one.")

    if stored["otp"] != data.otp.strip():
        raise HTTPException(400, "Incorrect OTP")

    # Mark phone as verified
    _otp_store.pop(key, None)
    result = await db.execute(select(Candidate).where(Candidate.user_id == current_user.id))
    candidate = result.scalar_one_or_none()
    if candidate:
        candidate.phone = phone
        candidate.phone_verified = True
        await db.commit()

    return {"message": "Phone verified successfully", "phone_verified": True}
