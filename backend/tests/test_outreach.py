"""실제 메일 발송(SMTP)과 담당자 참여 권유."""
import os
import re
import subprocess

import psycopg
import pytest

from app.config import get_settings
from app.services import mailer
from app.services.ratelimit import limiter
from tests.conftest import ROOT, TEST_URL, _psql_url, as_user

PLANNER = 1
HANBIT, HANBIT_BRN, HANBIT_MAIL = 101, "9998100015", "contact@hanbit.example"
NURI = 102


def _q(sql, *args):
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        cur = conn.execute(sql, args)
        return cur.fetchall() if cur.description else []


@pytest.fixture
def seeded(database):
    limiter.reset()
    env = {**os.environ, "PGPASSWORD": os.environ.get("PGPASSWORD", "")}
    for f in ("navigator_companies.sql", "navigator_announcements.sql"):
        subprocess.run(["psql", _psql_url(TEST_URL), "-X", "-q", "-v", "ON_ERROR_STOP=1",
                        "-f", str(ROOT / "seeds" / f)], check=True, capture_output=True, env=env)
    _q("DELETE FROM ax.outreach_message")
    _q("UPDATE ax.company_profile SET outreach_consent_at = NULL")
    _q("DELETE FROM ax.eligibility_answer WHERE organization_id IN (101, 102, 103)")
    yield
    _q("DELETE FROM ax.outreach_message")
    _q("UPDATE ax.company_profile SET outreach_consent_at = NULL")


class FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout=None, **_):
        self.host, self.port, self.calls = host, port, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user))

    def send_message(self, msg):
        FakeSMTP.sent.append((self, msg))


@pytest.fixture
def smtp(monkeypatch):
    s = get_settings()
    for k, v in {"mailer": "smtp", "smtp_host": "smtp.example.com", "smtp_port": 587, "smtp_user": "bot@example.com",
                 "smtp_password": "pw", "smtp_from": "", "smtp_security": "starttls"}.items():
        monkeypatch.setattr(s, k, v)
    FakeSMTP.sent = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    yield s


def test_smtp_send(smtp):
    mailer.send("a@example.com", "[Navigator] 한글 제목", "본문입니다", reply_to="staff@example.com")
    server, msg = FakeSMTP.sent[0]
    assert (server.host, server.port) == ("smtp.example.com", 587)
    assert server.calls == ["starttls", ("login", "bot@example.com")]
    assert msg["To"] == "a@example.com" and "bot@example.com" in msg["From"]
    assert msg["Subject"] == "[Navigator] 한글 제목" and msg["Reply-To"] == "staff@example.com"
    assert msg.get_content().strip() == "본문입니다"


def test_smtp_misconfigured(smtp, monkeypatch):
    monkeypatch.setattr(smtp, "smtp_host", "")
    with pytest.raises(mailer.MailError):
        mailer.send("a@example.com", "s", "b")
    monkeypatch.setattr(smtp, "mailer", "carrier-pigeon")
    with pytest.raises(mailer.MailError):
        mailer.send("a@example.com", "s", "b")


async def test_mail_failure_handling(client, seeded, smtp, monkeypatch):
    monkeypatch.setattr(smtp, "smtp_host", "")       # 모든 발송 실패
    # 관리 링크 재발송은 실패를 알려야 함
    r = await client.post(f"/navigator/companies/{HANBIT_BRN}/access-link")
    assert r.status_code == 503 and "메일" in r.json()["detail"]


async def test_outreach_flow(client, seeded):
    staff = as_user(PLANNER)
    _q("DELETE FROM ax.company_match_run WHERE announcement_id = 101")
    assert (await client.post("/navigator/matching/announcements/101/outreach", headers=staff,
                              json={"organization_ids": [HANBIT]})).status_code == 409   # 판정 전
    assert (await client.post("/navigator/matching/announcements/101", headers=staff)).status_code == 201

    c = (await client.get("/navigator/matching/announcements/101/outreach", headers=staff)).json()
    hanbit = next(x for x in c["companies"] if x["organization_id"] == HANBIT)
    assert c["open"] and hanbit["verdict"] == "ELIGIBLE" and not hanbit["consent"] and not hanbit["sendable"]
    assert all(x["verdict"] != "INELIGIBLE" for x in c["companies"])

    r = (await client.post("/navigator/matching/announcements/101/outreach", headers=staff,
                           json={"organization_ids": [HANBIT, NURI, 999999]})).json()
    assert r["sent"] == 0
    assert {s["organization_id"]: s["reason"] for s in r["skipped"]} == {
        HANBIT: "NO_CONSENT", NURI: "INELIGIBLE", 999999: "NOT_IN_RESULT"}

    # 기업이 동의
    h = {"X-Manage-Token": (await client.post(f"/navigator/companies/{HANBIT_BRN}/open")).json()["token"]}
    ok = await client.put("/navigator/manage/outreach-consent", headers=h, json={"consent": True})
    assert ok.status_code == 200 and ok.json()["outreach_consent"] is True
    assert (await client.get("/navigator/manage/profile", headers=h)).json()["outreach_consent_at"]

    before = len(mailer.OUTBOX)
    r = (await client.post("/navigator/matching/announcements/101/outreach", headers=staff,
                           json={"organization_ids": [HANBIT], "note": "  설명회 11/20 대전에서 합니다  "})).json()
    assert r["sent"] == 1 and r["skipped"] == []
    mail = mailer.OUTBOX[before]
    assert mail.to == HANBIT_MAIL and "참여 권유" in mail.subject
    assert "설명회 11/20 대전에서 합니다" in mail.body and "필수 조건" in mail.body
    sent = next(x for x in r["candidates"]["companies"] if x["organization_id"] == HANBIT)
    assert sent["sent_status"] == "SENT" and not sent["sendable"]

    again = (await client.post("/navigator/matching/announcements/101/outreach", headers=staff,
                               json={"organization_ids": [HANBIT]})).json()
    assert again["sent"] == 0 and again["skipped"][0]["reason"] == "ALREADY_SENT"

    # 수신 거부 링크 → 동의 해제
    token = re.search(r"/navigator/outreach/optout#t=(\S+)", mail.body).group(1)
    r = await client.post("/navigator/outreach/optout", json={"token": token})
    assert r.status_code == 200 and r.json()["company_name"] == "(가상)한빛전자통신"
    assert _q("SELECT outreach_consent_at FROM ax.company_profile WHERE organization_id = %s", HANBIT)[0][0] is None
    assert (await client.post("/navigator/outreach/optout", json={"token": "x" * 40})).status_code == 404


async def test_outreach_rules(client, seeded):
    staff = as_user(PLANNER)
    # 마감 공고에는 못 보냄
    assert (await client.post("/navigator/matching/announcements/105", headers=staff)).status_code == 201
    r = await client.post("/navigator/matching/announcements/105/outreach", headers=staff,
                          json={"organization_ids": [HANBIT]})
    assert r.status_code == 409
    # 담당자만
    assert (await client.get("/navigator/matching/announcements/101/outreach", headers=as_user(5))).status_code == 403
    assert (await client.post("/navigator/matching/announcements/101/outreach",
                              json={"organization_ids": [HANBIT]})).status_code == 401
