"""메일 발송. MAILER=mock 이면 보내지 않고 OUTBOX 에만 쌓고, smtp 면 SMTP 로 보낸다.

로컬에서 설정 확인: python -m app.services.mailer 받는주소@example.com
"""
import asyncio
import logging
import smtplib
import ssl
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.config import get_settings

log = logging.getLogger("app.mailer")


@dataclass
class Mail:
    to: str
    subject: str
    body: str
    reply_to: str | None = None
    sent_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


OUTBOX: list[Mail] = []


class MailError(RuntimeError):
    pass


def send(to: str, subject: str, body: str, reply_to: str | None = None) -> None:
    mode = get_settings().mailer.lower()
    if mode == "mock":
        OUTBOX.append(Mail(to, subject, body, reply_to))
        log.info("[목업 메일] to=%s subject=%s", mask_email(to), subject)
        log.debug("[목업 메일 본문]\n%s", body)
        return
    if mode == "smtp":
        _send_smtp(to, subject, body, reply_to)
        log.info("[메일] to=%s subject=%s", mask_email(to), subject)
        return
    raise MailError(f"MAILER={mode} 미지원 (mock|smtp)")


async def send_async(to: str, subject: str, body: str, reply_to: str | None = None) -> None:
    """SMTP 는 블로킹이라 요청 처리 중에는 스레드에서 보낸다."""
    if get_settings().mailer.lower() == "mock":
        send(to, subject, body, reply_to)
    else:
        await asyncio.to_thread(send, to, subject, body, reply_to)


def _message(to: str, subject: str, body: str, reply_to: str | None = None) -> EmailMessage:
    s = get_settings()
    sender = s.smtp_from or s.smtp_user
    if not sender:
        raise MailError("SMTP_FROM(또는 SMTP_USER)이 비어 있습니다")
    msg = EmailMessage()
    msg["From"] = formataddr((s.smtp_from_name, sender))
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Message-ID"] = make_msgid(domain=sender.partition("@")[2] or None)
    msg.set_content(body, charset="utf-8")
    return msg


def _send_smtp(to: str, subject: str, body: str, reply_to: str | None = None) -> None:
    s = get_settings()
    if not s.smtp_host:
        raise MailError("SMTP_HOST 가 비어 있습니다")
    msg = _message(to, subject, body, reply_to)
    security = s.smtp_security.lower()
    try:
        if security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_s,
                                                    context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_s)
        with server:
            if security == "starttls":
                server.starttls(context=ssl.create_default_context())
            if s.smtp_user:
                server.login(s.smtp_user, s.smtp_password)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        raise MailError(f"메일 발송 실패: {type(e).__name__}: {e}") from e


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


if __name__ == "__main__":   # 설정 확인용 한 통
    if len(sys.argv) != 2:
        sys.exit("사용법: python -m app.services.mailer 받는주소@example.com")
    logging.basicConfig(level=logging.INFO)
    send(sys.argv[1], "[Navigator] 메일 설정 확인", "이 메일이 보이면 발송 설정이 맞습니다.")
    print("보냈습니다" if get_settings().mailer.lower() != "mock" else "MAILER=mock 이라 실제로 보내지 않았습니다")
