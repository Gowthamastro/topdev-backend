"""Auth routes: register, login, refresh token."""
from datetime import timedelta
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr
from app.core.database import get_db
from app.core.security import verify_password, get_password_hash, create_access_token, create_refresh_token, decode_token
from app.models.user import User, UserRole
from app.models.client import Client
from app.models.candidate import Candidate
from app.core.config import settings
from app.services.audit_service import log_audit_event

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: UserRole = UserRole.CANDIDATE
    company_name: str | None = None  # Required if role=CLIENT


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleLoginRequest(BaseModel):
    access_token: str
    role: str = "candidate"

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: int
    role: str
    full_name: str


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=data.email,
        hashed_password=get_password_hash(data.password),
        full_name=data.full_name,
        role=data.role.value,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    # Create profile
    if data.role == UserRole.CLIENT:
        if not data.company_name:
            raise HTTPException(status_code=400, detail="company_name required for client registration")
        client = Client(user_id=user.id, company_name=data.company_name)
        db.add(client)
    elif data.role == UserRole.CANDIDATE:
        candidate = Candidate(user_id=user.id)
        db.add(candidate)

    await db.commit()
    await db.refresh(user)

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user_id=user.id,
        role=user.role,
        full_name=user.full_name,
    )


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    await log_audit_event(
        db=db,
        action="login",
        user_id=user.id,
        resource_type="user",
        resource_id=str(user.id),
        details={"email": user.email, "role": user.role},
        request=request,
    )

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user_id=user.id,
        role=user.role,
        full_name=user.full_name,
    )


@router.post("/google", response_model=TokenResponse)
async def google_auth(data: GoogleLoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    # Verify access_token with Google
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {data.access_token}"}
            )
            resp.raise_for_status()
            user_info = resp.json()
        except httpx.HTTPError:
            raise HTTPException(status_code=401, detail="Invalid Google token")

    email = user_info.get("email")
    full_name = user_info.get("name", "Google User")

    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email")

    # Check if user already exists
    existing = await db.execute(select(User).where(User.email == email))
    user = existing.scalar_one_or_none()

    if not user:
        # Create user automatically
        # Assign a random unguessable password since they auth via google
        import secrets
        import string
        alphabet = string.ascii_letters + string.digits
        random_pwd = ''.join(secrets.choice(alphabet) for i in range(20))

        user = User(
            email=email,
            hashed_password=get_password_hash(random_pwd),
            full_name=full_name,
            role=data.role,
            is_active=True,
        )
        db.add(user)
        await db.flush()

        # Create profile
        if data.role == "client":
            client_profile = Client(user_id=user.id, company_name="Workspace")
            db.add(client_profile)
        elif data.role == "candidate":
            candidate = Candidate(user_id=user.id)
            db.add(candidate)

        await db.commit()
        await db.refresh(user)

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    await log_audit_event(
        db=db,
        action="login_google",
        user_id=user.id,
        resource_type="user",
        resource_id=str(user.id),
        details={"email": user.email, "role": user.role},
        request=request,
    )

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user_id=user.id,
        role=user.role,
        full_name=user.full_name,
    )



class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(data.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    result = await db.execute(select(User).where(User.id == int(payload["sub"])))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user_id=user.id,
        role=user.role,
        full_name=user.full_name,
    )
