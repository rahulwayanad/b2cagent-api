import logging
import secrets

from fastapi import HTTPException, status
from redis.asyncio import Redis

from app.services.notifications import EmailSender

OTP_TTL_SECONDS = 300

otp_logger = logging.getLogger("b2cagent.otp")


def _otp_key(user_id: str) -> str:
    return f"otp:{user_id}"


class OTPService:
    def __init__(self, redis: Redis, email_sender: EmailSender) -> None:
        self.redis = redis
        self.email_sender = email_sender

    async def send_email_otp(self, email: str, user_id: str) -> None:
        # Always overwrite any prior OTP so login retries / re-sends work
        # without hitting a cooldown. The frontend Resend button has its own
        # 60s disable, so this isn't a UX abuse vector in practice.
        otp = f"{secrets.randbelow(1_000_000):06d}"
        await self.redis.set(_otp_key(user_id), otp, ex=OTP_TTL_SECONDS)

        otp_logger.warning("OTP for %s (user %s): %s", email, user_id, otp)

        await self.email_sender.send(
            to=email,
            subject="Your ResortBid OTP",
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
