import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


def _send_email_sync(to_email: str, subject: str, body: str) -> None:
    if not settings.smtp_host or not settings.smtp_from or not to_email:
        return
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = to_email
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


async def send_email(to_email: str, subject: str, body: str) -> None:
    if not settings.smtp_host:
        return
    try:
        await asyncio.to_thread(_send_email_sync, to_email, subject, body)
    except Exception:
        logger.exception("Unable to send optional email notification")
