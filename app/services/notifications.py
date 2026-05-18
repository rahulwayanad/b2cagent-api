import asyncio
import smtplib
from email.message import EmailMessage
from typing import Protocol

import httpx

from app.core.config import settings


class EmailSender(Protocol):
    async def send(self, *, to: str, subject: str, body: str) -> None: ...


class SMSSender(Protocol):
    async def send(self, *, to: str, body: str) -> None: ...


class ConsoleEmailSender:
    async def send(self, *, to: str, subject: str, body: str) -> None:
        print(f"[email/console] to={to} subject={subject}\n{body}")


class ConsoleSMSSender:
    async def send(self, *, to: str, body: str) -> None:
        print(f"[sms/console] to={to} body={body}")


class SMTPEmailSender:
    async def send(self, *, to: str, subject: str, body: str) -> None:
        def _send_sync() -> None:
            msg = EmailMessage()
            msg["From"] = settings.EMAIL_FROM
            msg["To"] = to
            msg["Subject"] = subject
            msg.set_content(body)
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
                if settings.SMTP_STARTTLS:
                    smtp.starttls()
                if settings.SMTP_USER:
                    smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                smtp.send_message(msg)

        await asyncio.to_thread(_send_sync)


class SendGridEmailSender:
    async def send(self, *, to: str, subject: str, body: str) -> None:
        payload = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": settings.EMAIL_FROM},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {settings.SENDGRID_API_KEY}"},
                json=payload,
            )
        resp.raise_for_status()


class TwilioSMSSender:
    async def send(self, *, to: str, body: str) -> None:
        from twilio.rest import Client

        def _send_sync() -> None:
            client = Client(settings.TWILIO_SID, settings.TWILIO_AUTH_TOKEN)
            client.messages.create(body=body, from_=settings.TWILIO_PHONE, to=to)

        await asyncio.to_thread(_send_sync)


def get_email_sender() -> EmailSender:
    backend = settings.EMAIL_BACKEND
    if backend == "smtp":
        return SMTPEmailSender()
    if backend == "sendgrid":
        return SendGridEmailSender()
    return ConsoleEmailSender()


def get_sms_sender() -> SMSSender:
    if settings.SMS_BACKEND == "twilio" and settings.TWILIO_SID:
        return TwilioSMSSender()
    return ConsoleSMSSender()


async def send_bid_notification(
    *,
    email_sender: EmailSender,
    sms_sender: SMSSender,
    agent_email: str,
    agent_phone: str | None,
    agent_name: str,
    property_name: str,
    bid_date: str,
    amount: str,
    status: str,
) -> None:
    """Notify an agent about a bid decision. Called from FastAPI BackgroundTasks.

    Takes primitives (not ORM objects) so it's safe to run after the request
    session is closed.
    """
    subject = f"Your bid on {property_name} was {status}"
    body = (
        f"Hi {agent_name},\n\n"
        f"Your bid on '{property_name}' for {bid_date} "
        f"(amount {amount}) was {status}.\n\n"
        "— b2cagent"
    )
    await email_sender.send(to=agent_email, subject=subject, body=body)
    if agent_phone:
        await sms_sender.send(
            to=agent_phone,
            body=f"Your bid on '{property_name}' for {bid_date} was {status}.",
        )
