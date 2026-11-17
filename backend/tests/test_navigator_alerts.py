"""Navigator 공고 알림 구독·발송 테스트."""
import re
import uuid
from datetime import date, timedelta

import psycopg
import pytest

from app.services import mailer
from app.services.ratelimit import limiter
from tests.conftest import TEST_URL, as_user
from tests.test_navigator_matching import _seed, _token

STAFF = 1
HANBIT, NURI, SAEBOM = 101, 102, 103


def _clear_subscriptions():
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute("DELETE FROM ax.alert_subscription WHERE organization_id IN (101, 102, 103)")


@pytest.fixture(autouse=True)
def _clean():
    limiter.reset()
    _clear_subscriptions()
    yield
    _clear_subscriptions()   # 다른 테스트의 공고 등록이 알림을 돌리지 않게


def _announcement(status: str = "PUBLISHED", **extra) -> dict:
    today = date.today()
    return {
        "announcement_no": f"ALERT-{uuid.uuid4().hex[:8]}", "title": "전술 데이터링크 모뎀 국산화 (테스트)",
        "agency_name": "(가상)기관", "receipt_start": today.isoformat(),
        "receipt_end": (today + timedelta(days=30)).isoformat(), "status": status,
        "summary": "전술 데이터링크 통신 모뎀 부품 국산화",
        "requirements": [{"req_type_code": "COMPANY_SIZE", "rule": {"allowed": ["SME", "STARTUP", "VENTURE"]},
                          "is_mandatory": True, "description": "중소기업"}],
        "tech_needs": [{"tech_name": "전술 데이터링크 통신 모뎀", "ipc_codes": ["H04B"]}],
        **extra,
    }


def _mails_to(email: str, since: int) -> list[mailer.Mail]:
    return [m for m in mailer.OUTBOX[since:] if m.to == email]


async def test_subscription_confirm_rules(client):
    _seed()
    h = await _token(client, "9998100015", "contact@hanbit.example")

    # 관리 링크를 받은 주소는 바로 시작
    r = await client.post("/navigator/manage/subscriptions", headers=h, json={"email": "Contact@Hanbit.example"})
    assert r.status_code == 201, r.text
    own = r.json()
    assert own["email_confirmed_at"] and not own["confirm_sent"] and own["channels"] == ["SCREEN", "EMAIL"]

    # 다른 주소는 확인 메일
    n = len(mailer.OUTBOX)
    r = await client.post("/navigator/manage/subscriptions", headers=h,
                          json={"email": "rnd@hanbit.example", "keywords": [" 데이터링크 ", ""]})
    other = r.json()
    assert r.status_code == 201 and other["email_confirmed_at"] is None and other["confirm_sent"]
    assert other["keywords"] == ["데이터링크"]
    mail = _mails_to("rnd@hanbit.example", n)[0]
    token = re.search(r"#t=(\S+)", mail.body).group(1)

    assert (await client.post("/navigator/manage/subscriptions", headers=h,
                              json={"email": "rnd@hanbit.example"})).status_code == 409
    assert (await client.post("/navigator/manage/subscriptions", headers=h,
                              json={"email": "x@hanbit.example", "channels": ["SMS"]})).status_code == 422
    assert (await client.post("/navigator/manage/subscriptions", headers=h,
                              json={"email": "x@hanbit.example", "min_score": 2})).status_code == 422
    assert (await client.post("/navigator/subscriptions/confirm", json={"token": "x" * 20})).status_code == 404

    r = await client.post("/navigator/subscriptions/confirm", json={"token": token})
    assert r.status_code == 200 and r.json()["company_name"] == "(가상)한빛전자통신"
    assert "***" in r.json()["email"]
    assert (await client.post("/navigator/subscriptions/confirm", json={"token": token})).status_code == 404  # 1회용

    subs = (await client.get("/navigator/manage/subscriptions", headers=h)).json()
    assert subs["registered_email"] == "contact@hanbit.example"
    assert all(s["email_confirmed_at"] for s in subs["subscriptions"])
    assert (await client.post(f"/navigator/manage/subscriptions/{other['id']}/confirm-mail",
                              headers=h)).status_code == 409   # 이미 확인됨

    # 수신자 상한
    for i in range(3):
        assert (await client.post("/navigator/manage/subscriptions", headers=h,
                                  json={"email": f"p{i}@hanbit.example"})).status_code == 201
    assert (await client.post("/navigator/manage/subscriptions", headers=h,
                              json={"email": "p9@hanbit.example"})).status_code == 409

    # 다른 기업 구독은 못 건드림
    s = await _token(client, "9998300038", "hello@saebom.example")
    assert (await client.patch(f"/navigator/manage/subscriptions/{other['id']}", headers=s,
                               json={"is_active": False})).status_code == 404
    assert (await client.delete(f"/navigator/manage/subscriptions/{other['id']}", headers=s)).status_code == 404
    assert (await client.get("/navigator/manage/subscriptions")).status_code == 401


async def test_publish_alerts_subscribed_companies_only(client):
    _seed()
    with psycopg.connect(TEST_URL, autocommit=True) as conn:   # 다른 테스트에서 등록한 기업은 등록 때 자동 구독됨
        conn.execute("DELETE FROM ax.alert_subscription WHERE organization_id NOT IN (101, 102, 103)")
    hanbit = await _token(client, "9998100015", "contact@hanbit.example")
    nuri = await _token(client, "9998200026", "rnd@nuri.example")
    saebom = await _token(client, "9998300038", "hello@saebom.example")

    await client.post("/navigator/manage/subscriptions", headers=hanbit, json={"email": "contact@hanbit.example"})
    r = await client.post("/navigator/manage/subscriptions", headers=hanbit,
                          json={"email": "team@hanbit.example", "keywords": ["데이터링크"]})
    n = len(mailer.OUTBOX)
    token = re.search(r"#t=(\S+)", mailer.OUTBOX[-1].body).group(1)
    await client.post("/navigator/subscriptions/confirm", json={"token": token})
    await client.post("/navigator/manage/subscriptions", headers=hanbit, json={"email": "late@hanbit.example"})
    await client.post("/navigator/manage/subscriptions", headers=nuri, json={"email": "rnd@nuri.example"})
    await client.post("/navigator/manage/subscriptions", headers=saebom,
                      json={"email": "hello@saebom.example", "keywords": ["복합소재"]})

    # 작성중 공고는 알림 없음, 공개로 바꾸면 알림
    r = await client.post("/navigator/announcements", headers=as_user(STAFF), json=_announcement("DRAFT"))
    assert r.status_code == 201, r.text
    ann_id = r.json()["id"]
    n = len(mailer.OUTBOX)
    assert (await client.get(f"/navigator/alerts/announcements/{ann_id}",
                             headers=as_user(STAFF))).json()["notifications"] == []
    r = await client.patch(f"/navigator/announcements/{ann_id}", headers=as_user(STAFF),
                           json={"status": "PUBLISHED"})
    assert r.status_code == 204, r.text

    staff = (await client.get(f"/navigator/alerts/announcements/{ann_id}", headers=as_user(STAFF))).json()
    got = {(x["company_name"], x["status"]) for x in staff["notifications"]}
    assert got == {("(가상)한빛전자통신", "SENT")}, got       # 누리 부적격, 새봄 관심 분야 불일치, late 미확인
    assert len(staff["notifications"]) == 2                   # 한빛 수신자 2명
    assert len(_mails_to("contact@hanbit.example", n)) == 1 and len(_mails_to("team@hanbit.example", n)) == 1
    assert not _mails_to("late@hanbit.example", n) and not _mails_to("rnd@nuri.example", n)
    assert not _mails_to("hello@saebom.example", n)
    mail = _mails_to("team@hanbit.example", n)[0]
    assert "지원 가능" in mail.subject and "/navigator/unsubscribe#t=" in mail.body
    assert not re.search(r"\b(A|B|C)+[+-]?\b", mail.body)      # 신용등급 값 없음

    # 구독 기업만 판정한 실행은 담당자 화면의 마지막 결과로 쓰지 않는다
    latest = (await client.get(f"/navigator/matching/announcements/{ann_id}", headers=as_user(STAFF))).json()
    assert latest["run"] is None

    # 화면 알림: 공고당 하나
    a = (await client.get("/navigator/manage/alerts", headers=hanbit)).json()
    assert a["unread"] == 1 and a["alerts"][0]["announcement_id"] == ann_id
    assert a["alerts"][0]["verdict_label"] == "지원 가능"
    assert (await client.post("/navigator/manage/alerts/read", headers=hanbit, json={})).status_code == 204
    assert (await client.get("/navigator/manage/alerts", headers=hanbit)).json()["unread"] == 0
    assert (await client.get("/navigator/manage/alerts", headers=nuri)).json()["alerts"] == []

    # 다시 보내도 중복 없음
    r = await client.post(f"/navigator/alerts/announcements/{ann_id}", headers=as_user(STAFF))
    assert r.status_code == 200 and r.json()["notifications"] == 0

    # 메일의 해지 링크 → 다음 공고부터 안 감
    unsub = re.search(r"unsubscribe#t=(\S+)", mail.body).group(1)
    r = await client.post("/navigator/subscriptions/unsubscribe", json={"token": unsub})
    assert r.status_code == 200, r.text
    n = len(mailer.OUTBOX)
    r = await client.post("/navigator/announcements", headers=as_user(STAFF), json=_announcement())
    assert r.status_code == 201
    assert len(_mails_to("contact@hanbit.example", n)) == 1 and not _mails_to("team@hanbit.example", n)

    # 해지한 수신자는 확인 메일로만 되살릴 수 있다
    subs = (await client.get("/navigator/manage/subscriptions", headers=hanbit)).json()["subscriptions"]
    team = next(s for s in subs if s["email"] == "team@hanbit.example")
    assert team["unsubscribed_at"]
    r = await client.post(f"/navigator/manage/subscriptions/{team['id']}/confirm-mail", headers=hanbit)
    assert r.status_code == 200 and r.json()["confirm_sent"]


async def test_alert_filters_and_channels(client):
    _seed()
    saebom = await _token(client, "9998300038", "hello@saebom.example")
    r = await client.post("/navigator/manage/subscriptions", headers=saebom,
                          json={"email": "hello@saebom.example", "min_score": 0.99})
    sub = r.json()
    n = len(mailer.OUTBOX)
    r = await client.post("/navigator/announcements", headers=as_user(STAFF), json=_announcement())
    assert r.status_code == 201
    assert not _mails_to("hello@saebom.example", n)                 # 최소 점수 미달

    r = await client.patch(f"/navigator/manage/subscriptions/{sub['id']}", headers=saebom,
                           json={"min_score": 0, "channels": ["SCREEN"]})
    assert r.status_code == 200 and r.json()["channels"] == ["SCREEN"]
    ann_id = (await client.post("/navigator/announcements", headers=as_user(STAFF),
                                json=_announcement())).json()["id"]
    assert not _mails_to("hello@saebom.example", n)                 # 화면만
    alerts = (await client.get("/navigator/manage/alerts", headers=saebom)).json()["alerts"]
    assert [x["announcement_id"] for x in alerts] == [ann_id]

    # 끄면 안 감
    await client.patch(f"/navigator/manage/subscriptions/{sub['id']}", headers=saebom, json={"is_active": False})
    ann2 = (await client.post("/navigator/announcements", headers=as_user(STAFF),
                              json=_announcement())).json()["id"]
    assert ann2 not in {x["announcement_id"] for x in
                        (await client.get("/navigator/manage/alerts", headers=saebom)).json()["alerts"]}

    # 마감 공고는 알림 안 함
    await client.patch(f"/navigator/manage/subscriptions/{sub['id']}", headers=saebom, json={"is_active": True})
    past = date.today() - timedelta(days=10)
    r = await client.post("/navigator/announcements", headers=as_user(STAFF),
                          json=_announcement(receipt_start=(past - timedelta(days=10)).isoformat(),
                                             receipt_end=past.isoformat()))
    closed = r.json()["id"]
    assert closed not in {x["announcement_id"] for x in
                          (await client.get("/navigator/manage/alerts", headers=saebom)).json()["alerts"]}

    assert (await client.delete(f"/navigator/manage/subscriptions/{sub['id']}", headers=saebom)).status_code == 204


async def test_alert_staff_endpoints_need_role(client):
    assert (await client.get("/navigator/alerts/announcements/101")).status_code == 401
    assert (await client.post("/navigator/alerts/announcements/101", headers=as_user(2))).status_code == 403
    assert (await client.post("/navigator/alerts/announcements/999999",
                              headers=as_user(STAFF))).status_code == 404


async def test_mail_failure_is_recorded(client, monkeypatch):
    _seed()
    h = await _token(client, "9998100015", "contact@hanbit.example")
    await client.post("/navigator/manage/subscriptions", headers=h, json={"email": "contact@hanbit.example"})

    def broken(*_a, **_k):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(mailer, "send", broken)
    r = await client.post("/navigator/announcements", headers=as_user(STAFF), json=_announcement())
    assert r.status_code == 201                                   # 공고 등록은 성공
    staff = (await client.get(f"/navigator/alerts/announcements/{r.json()['id']}", headers=as_user(STAFF))).json()
    assert [x["status"] for x in staff["notifications"]] == ["FAILED"]
    assert (await client.get("/navigator/manage/alerts", headers=h)).json()["unread"] == 1   # 화면 알림은 남음
