"""이메일 발송. PoC 1단계는 목업(MAILER=mock): 실제로 보내지 않고 OUTBOX 에 쌓고 로그에 남긴다.

실제 발송(SMTP 등)은 5단계(구독·알림)에서 붙인다. 같은 send() 모양을 유지하면 호출부는 그대로다.
"""
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


OUTBOX: list[Mail] = []   # 목업 발송함 (테스트·개발 확인용, 프로세스 메모리)


def send(to: str, subject: str, body: str) -> None:
    mode = get_settings().mailer.lower()
    if mode != "mock":
        raise NotImplementedError(f"MAILER={mode} 는 아직 없습니다 (5단계에서 실제 발송 추가)")
    OUTBOX.append(Mail(to, subject, body))
    log.info("[목업 메일] to=%s subject=%s", mask_email(to), subject)


def mask_email(email: str) -> str:
    """a***@example.com 처럼 가린다 (응답·로그용)."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"
