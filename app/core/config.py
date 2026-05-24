from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"

    FRONTEND_URL: str = "http://localhost:5173"

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"
    GOOGLE_PLACES_API_KEY: str = ""

    JWT_SECRET: str = Field(..., min_length=16)
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRES_MINUTES: int = 60 * 24
    PRE_AUTH_TOKEN_EXPIRES_MINUTES: int = 10

    OTP_TTL_SECONDS: int = 300

    EMAIL_BACKEND: Literal["console", "smtp", "sendgrid"] = "console"
    EMAIL_FROM: str = "no-reply@b2cagent.local"
    EMAIL_FROM_NAME: str = "B2C Tour Agent"
    # Base URL of the web app. Used to build the absolute href on every
    # email button (templates substitute {link_url} / {app_url}).
    FRONTEND_BASE_URL: str = "http://localhost:5173"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_STARTTLS: bool = True
    # When true, connects via implicit TLS (SMTPS) instead of STARTTLS.
    # Port 465 requires this; port 587 typically uses STARTTLS.
    SMTP_SSL: bool = False
    SENDGRID_API_KEY: str = ""

    SMS_BACKEND: Literal["console", "twilio"] = "console"
    TWILIO_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE: str = ""

    STORAGE_BACKEND: Literal["s3", "local"] = "local"
    LOCAL_UPLOAD_DIR: str = "./uploads"
    STORAGE_PUBLIC_URL: str = "http://localhost:8001/uploads"
    MAX_PHOTO_SIZE_BYTES: int = 20 * 1024 * 1024

    S3_BUCKET: str = ""
    S3_PUBLIC_URL_PREFIX: str = ""
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
