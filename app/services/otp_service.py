import logging
import secrets

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.email_template_service import send_templated_email
from app.services.notifications import EmailSender

OTP_TTL_SECONDS = 300

otp_logger = logging.getLogger("b2cagent.otp")


def _otp_key(user_id: str) -> str:
    return f"otp:{user_id}"


class OTPService:
    def __init__(self, redis: Redis, email_sender: EmailSender) -> None:
        self.redis = redis
        self.email_sender = email_sender

    async def send_email_otp(
        self,
        email: str,
        user_id: str,
        *,
        db: AsyncSession | None = None,
        name: str = "there",
    ) -> None:
        otp = f"{secrets.randbelow(1_000_000):06d}"
        await self.redis.set(_otp_key(user_id), otp, ex=OTP_TTL_SECONDS)

        otp_logger.warning("OTP for %s (user %s): %s", email, user_id, otp)

        context = {"name": name, "otp": otp}
        if db is not None:
            sent = await send_templated_email(
                db,
                self.email_sender,
                code="otp",
                to=email,
                context=context,
                fallback_subject="Your B2C Tour Agent verification code",
                fallback_body="Your OTP is {otp}. Valid for 5 minutes.",
            )
            if sent:
                return
        # No db (legacy callers) or template disabled — send hardcoded.
        await self.email_sender.send(
            to=email,
            subject="Your B2C Tour Agent verification code",
            body=f"Your OTP is {otp}. Valid for 5 minutes.",
        )

    async def verify_otp(self, user_id: str, otp: str) -> bool:
        stored = await self.redis.get(_otp_key(user_id))
        if stored is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OTP expired or not found",
            )
        if not secrets.compare_digest(stored, otp):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OTP",
            )
        await self.redis.delete(_otp_key(user_id))
        return True
