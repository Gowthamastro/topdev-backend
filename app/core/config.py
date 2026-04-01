from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # App
    APP_NAME: str = "TopDev"
    APP_ENV: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "change-me-in-production"
    # Comma-separated list (works well in .env). Parsed via `allowed_origins_list`.
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:5174,http://localhost:3000"
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://topdev:topdev@127.0.0.1:5432/topdev"
    SYNC_DATABASE_URL: str = "postgresql://topdev:topdev@127.0.0.1:5432/topdev"

    @property
    def get_database_url(self) -> str:
        if self.DATABASE_URL.startswith("postgres://"):
            url = self.DATABASE_URL.replace("postgres://", "postgresql://", 1)
        else:
            url = self.DATABASE_URL
            
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # JWT
    JWT_SECRET_KEY: str = "change-me-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Gemini
    GEMINI_API_KEY: str = ""  # Set via .env — NEVER hardcode API keys
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_STARTER_PRICE_ID: str = ""
    STRIPE_GROWTH_PRICE_ID: str = ""
    STRIPE_ENTERPRISE_PRICE_ID: str = ""

    # SendGrid
    SENDGRID_API_KEY: str = ""
    FROM_EMAIL: str = "noreply@topdev.ai"
    FROM_NAME: str = "TopDev"

    # AWS S3
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    S3_BUCKET_NAME: str = "topdev-files"
    S3_SIGNED_URL_EXPIRY: int = 3600

    # Defaults (overridable via PlatformSettings DB table)
    DEFAULT_QUALIFICATION_THRESHOLD: int = 60
    DEFAULT_TEST_LINK_EXPIRY_HOURS: int = 48

    @property
    def allowed_origins_list(self) -> List[str]:
        s = (self.ALLOWED_ORIGINS or "").strip()
        if not s:
            return []
        return [item.strip() for item in s.split(",") if item.strip()]

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
