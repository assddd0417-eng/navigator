"""기업 등록부터 공고 공개·알림·담당자 매칭·참여 권유·수신 거부까지 한 번에."""
import re
from datetime import date, timedelta

import psycopg
import pytest

from app.services import mailer
from app.services.ratelimit import limiter
from tests.conftest import TEST_URL, as_user, manage_token
from tests.test_navigator_matching import _seed

PLANNER = 1
BRN, EMAIL = "999-84-00001", "ops@danbi.example"


def _q(sql, *args):
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        cur = conn.execute(sql, args)
        return cur.fetchall() if cur.description else []


def _notice() -> str:
    start, end = date.today() + timedelta(days=1), date.today() + timedelta(days=30)
    return f"""2027년 전술 데이터링크 모뎀 국산화 지원 공고(가상)

1. 사업목적: 수입에 의존하는 전술 데이터링크 모뎀과 RF 모듈의 국산화
2. 지원대상: 중소기업 (기업부설연구소 또는 연구개발전담부서 보유)
3. 신청자격
 - 신용등급 B 이상
 - 국세 체납, 부도·파산 기업 제외
4. 지원내용: 과제당 최대 5억원, 지원기간 24개월
5. 접수기간: {start:%Y. %m. %d.} ~ {end:%Y. %m. %d.}
6. 요구기술: 항재밍 주파수 도약 데이터링크 모뎀
"""


def _mails(to: str, since: int) -> list:
    return [m for m in mailer.OUTBOX[since:] if m.to == to]


@pytest.fixture
def fresh(database):
    limiter.reset()
    _seed()
    _q("DELETE FROM ax.alert_subscription WHERE organization_id NOT IN (101, 102, 103)")
    yield
    # 뒤 테스트의 공고·기업 목록에 끼지 않도록
    _q("UPDATE ax.announcement SET status = 'CANCELLED' WHERE announcement_no LIKE 'E2E-%%'")
    _q("UPDATE ax.organization SET is_active = false WHERE business_reg_no = '9998400001'")


async def test_company_to_outreach_flow(client, fresh):
    staff = as_user(PLANNER)

    # 1. 기업 등록: 등록 이메일은 바로 알림 수신자가 된다
    n = len(mailer.OUTBOX)
    r = await client.post("/navigator/companies", json={
        "business_reg_no": BRN, "company_name": "(가상)단비통신", "representative_name": "김단비",
        "opened_on": "2018-03-02", "email": EMAIL, "company_size": "SME", "region": "대전", "employee_count": 35,
        "main_business": "전술 데이터링크 모뎀"})
    assert r.status_code == 201, r.text
    assert "등록 완료" in _mails(EMAIL, n)[0].subject
    h = {"X-Manage-Token": await manage_token(client, BRN)}
    subs = (await client.get("/navigator/manage/subscriptions", headers=h)).json()["subscriptions"]
    assert [(s["email"], s["is_active"], bool(s["email_confirmed_at"])) for s in subs] == [(EMAIL, True, True)]

    # 2. 회사 정보 입력
    r = await client.patch("/navigator/manage/profile", headers=h, json={
        "certifications": [{"cert_type_code": "RND_LAB", "cert_no": "2020-001", "issued_on": "2020-01-01"}],
        "credit_ratings": [{"agency": "SELF", "grade": "BB", "rated_on": "2026-04-01"}],
        "technologies": [{"tech_name": "항재밍 주파수 도약 데이터링크 모뎀", "trl": 6}],
        "products": [{"name": "전술 데이터링크 모뎀", "is_defense": True}],
        "tax_delinquent": False, "insolvent": False, "rnd_restricted": False})
    assert r.status_code == 200, r.text
    assert (await client.put("/navigator/manage/outreach-consent", headers=h, json={"consent": True})).status_code == 200

    # 3. 담당자: 공고문 붙여넣기 → 조건 뽑기 → 그대로 공개
    r = await client.post("/navigator/announcements/text", headers=staff, json={
        "title": "2027년 전술 데이터링크 모뎀 국산화 지원 공고(가상)", "announcement_no": "E2E-001", "body_text": _notice()})
    assert r.status_code == 201, r.text
    ann_id = r.json()["id"]
    ex = (await client.post(f"/navigator/announcements/{ann_id}/extract", headers=staff)).json()
    assert {s["req_type_code"] for s in ex["requirements"]} == {
        "COMPANY_SIZE", "REQUIRED_CERT", "MIN_CREDIT_GRADE", "NO_DISQUALIFICATION"}
    assert [t["tech_name"] for t in ex["tech_needs"]] == ["항재밍 주파수 도약 데이터링크 모뎀"]
    assert ex["fields"]["target_desc"].startswith("중소기업")

    n = len(mailer.OUTBOX)
    r = await client.put(f"/navigator/announcements/{ann_id}/review", headers=staff, json={
        "fields": ex["fields"], "publish": True,
        "requirements": [{k: s[k] for k in ("req_type_code", "rule", "is_mandatory", "description")}
                         for s in ex["requirements"]],
        "tech_needs": [{"tech_name": t["tech_name"]} for t in ex["tech_needs"]]})
    assert r.status_code == 204, r.text

    # 4. 알림: 메일과 화면 알림, 담당자 발송 현황
    alert = _mails(EMAIL, n)
    assert len(alert) == 1 and "(지원 가능)" in alert[0].subject
    assert "회사 정보 입력·수정" in alert[0].body and "받은 링크" not in alert[0].body
    assert re.search(r"/navigator/unsubscribe#t=\S+", alert[0].body)
    mine = (await client.get("/navigator/manage/alerts", headers=h)).json()
    assert mine["unread"] == 1 and mine["alerts"][0]["announcement_id"] == ann_id
    sent = (await client.get(f"/navigator/alerts/announcements/{ann_id}", headers=staff)).json()["notifications"]
    assert [(x["company_name"], x["email"], x["status"]) for x in sent] == [("(가상)단비통신", "o***@danbi.example", "SENT")]

    # 다시 공개해도 같은 공고 알림은 한 번만
    n = len(mailer.OUTBOX)
    await client.patch(f"/navigator/announcements/{ann_id}", headers=staff, json={"status": "PUBLISHED"})
    assert (await client.post(f"/navigator/alerts/announcements/{ann_id}", headers=staff)).json()["emails_sent"] == 0
    assert _mails(EMAIL, n) == []

    # 5. 담당자 매칭: 적합 1위
    r = (await client.post(f"/navigator/matching/announcements/{ann_id}", headers=staff)).json()
    top = r["recommendations"][0]
    assert (top["company_name"], top["verdict"]) == ("(가상)단비통신", "ELIGIBLE")
    org_id = top["organization_id"]

    # 6. 참여 권유 → 수신 거부 → 동의 해제
    n = len(mailer.OUTBOX)
    r = (await client.post(f"/navigator/matching/announcements/{ann_id}/outreach", headers=staff,
                           json={"organization_ids": [org_id], "note": "설명회는 대전에서 합니다"})).json()
    assert r["sent"] == 1, r
    mail = _mails(EMAIL, n)[0]
    assert "참여 권유" in mail.subject and "설명회는 대전에서 합니다" in mail.body and "받은 관리 링크" not in mail.body
    assert "BB" not in mail.body                                   # 신용등급 값은 넣지 않음
    token = re.search(r"/navigator/outreach/optout#t=(\S+)", mail.body).group(1)
    assert (await client.post("/navigator/outreach/optout", json={"token": token})).status_code == 200
    assert (await client.get("/navigator/manage/profile", headers=h)).json()["outreach_consent_at"] is None

    # 7. 기업 화면 추천과 공개 조회
    mine = (await client.post("/navigator/manage/matches?refresh=true", headers=h)).json()["recommendations"]
    assert next(x for x in mine if x["announcement_id"] == ann_id)["verdict"] == "ELIGIBLE"
    pub = (await client.get(f"/navigator/companies/{BRN}/matches")).json()["recommendations"]
    hit = next(x for x in pub if x["announcement_id"] == ann_id)
    assert hit["hidden_requirements"] and "받은 링크" not in hit["rationale"]

    # 8. 알림 수신 거부
    token = re.search(r"/navigator/unsubscribe#t=(\S+)", alert[0].body).group(1)
    assert (await client.post("/navigator/subscriptions/unsubscribe", json={"token": token})).status_code == 200
    subs = (await client.get("/navigator/manage/subscriptions", headers=h)).json()["subscriptions"]
    assert subs[0]["unsubscribed_at"]

