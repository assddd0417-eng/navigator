"""메일 발송. MAILER=mock 이면 보내지 않고 OUTBOX 에만 쌓는다."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import get_settings

log = logging.getLogger("app.mailer")


@dataclass
class Mail:
    to: str
    subject: str
    body: str
    sent_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


OUTBOX: list[Mail] = []


def send(to: str, subject: str, body: str) -> None:
    mode = get_settings().mailer.lower()
    if mode != "mock":
        raise NotImplementedError(f"MAILER={mode} 미지원")
    OUTBOX.append(Mail(to, subject, body))
    log.info("[목업 메일] to=%s subject=%s", mask_email(to), subject)


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"
