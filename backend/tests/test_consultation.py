"""상담 요청, 상담 실행·이력, 결과서 수정·확정, 기업 화면, 이력 점검."""
from datetime import date, timedelta
import re

import psycopg
import pytest

from app.services import consultation, mailer
from app.services.ratelimit import limiter
from tests.conftest import TEST_URL, as_user, manage_token

BRN = "9998700088"


def test_build_report_sections():
    diag = {"company_name": "(가상)A", "state_label": "방산진입 준비기업", "total_score": 48, "summary": "요약",
            "strengths": [{"label": "기술", "score": 89, "text": "TRL 7"}],
            "tasks": [{"label": "방산진입", "score": 12, "text": "수요처 확보"}], "missing_labels": ["수요 확인"]}
    rep = consultation.build_report(diag, None, None, " ")
    by = {s["key"]: s["text"] for s in rep}
    assert [s["key"] for s in rep] == [k for k, _ in consultation.SECTIONS]
    assert "상담 내용: 없음" in by["overview"] and "- 강점: 기술 89점" in by["diagnosis"]
    assert by["eligibility"] == "이번 상담에서는 검토하지 않음." and by["opinion"] == ""
    assert "수요 확인" in by["request"] and "보장하지 않습니다" in by["notice"]


@pytest.fixture
async def setup(client):
    limiter.reset()
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))
        c.execute("DELETE FROM ax.announcement WHERE announcement_no LIKE 'CN-%%'")
    r = await client.post("/navigator/companies", json={
        "business_reg_no": BRN, "company_name": "(가상)상담테크", "representative_name": "김가상",
        "opened_on": "2017-01-01", "email": f"{BRN}@example.com", "main_business": "레이더 부품"})
    assert r.status_code == 201, r.text
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        org = c.execute("SELECT id FROM ax.organization WHERE business_reg_no = %s", (BRN,)).fetchone()[0]
    yield org
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))
        c.execute("DELETE FROM ax.announcement WHERE announcement_no LIKE 'CN-%%'")


async def test_consultation_flow(client, setup):
    org = setup
    h = {"X-Manage-Token": await manage_token(client, BRN)}
    assert (await client.patch("/navigator/manage/profile", headers=h,
                               json={"company_size": "SME"})).status_code == 200
    r = await client.post("/navigator/announcements", headers=as_user(1), json={
        "announcement_no": "CN-1", "title": "상담 시험 공고(가상)", "agency_name": "(가상)기관", "summary": "방산 진입",
        "receipt_end": (date.today() + timedelta(days=20)).isoformat(),
        "requirements": [{"req_type_code": "COMPANY_SIZE", "rule": {"allowed": ["SME"]}, "description": "중소기업"}]})
    assert r.status_code == 201, r.text
    ann = r.json()["id"]

    # 기업 상담 요청
    r = await client.post("/navigator/manage/consult-requests", headers=h,
                          json={"concern": "방산 진입 방법이 궁금합니다", "interest": "국방벤처"})
    assert r.status_code == 201, r.text
    req = r.json()["id"]
    assert (await client.post("/navigator/manage/consult-requests", headers=h, json={"concern": ""})).status_code == 422
    reqs = (await client.get("/navigator/consult/requests?status=REQUESTED", headers=as_user(1))).json()
    assert any(x["id"] == req and x["company_name"] == "(가상)상담테크" for x in reqs)

    # 상담 실행 (요청의 애로사항을 상담 내용으로 씀)
    r = await client.post(f"/navigator/consult/companies/{org}/consultations", headers=as_user(1),
                          json={"task": "B", "request_id": req})
    assert r.status_code == 201, r.text
    c1 = r.json()
    assert c1["status"] == "DRAFT" and c1["concern"] == "방산 진입 방법이 궁금합니다" and c1["compare"] is None
    assert c1["diagnosis_id"] and any(x["announcement_id"] == ann for x in c1["eligibility"]["results"])
    assert c1["report"] == c1["draft"] and c1["route"] is None
    reqs = (await client.get("/navigator/consult/requests", headers=as_user(1))).json()
    assert next(x for x in reqs if x["id"] == req)["status"] == "IN_PROGRESS"

    # 다른 기업 요청은 못 씀
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        other = c.execute("INSERT INTO ax.consult_request (organization_id, concern) "
                          "SELECT id, 'x' FROM ax.organization WHERE id <> %s AND org_type = 'COMPANY' LIMIT 1 "
                          "RETURNING id", (org,)).fetchone()
    if other:
        assert (await client.post(f"/navigator/consult/companies/{org}/consultations", headers=as_user(1),
                                  json={"task": "A", "request_id": other[0]})).status_code == 422
        with psycopg.connect(TEST_URL, autocommit=True) as c:
            c.execute("DELETE FROM ax.consult_request WHERE id = %s", (other[0],))

    # 담당자 수정
    put = lambda body: client.put(f"/navigator/consult/consultations/{c1['id']}", headers=as_user(1), json=body)
    assert (await put({"report": {"nope": "x"}})).status_code == 409
    assert (await put({"overrides": [{"announcement_id": 999999999, "verdict": "ELIGIBLE", "reason": "x"}]})).status_code == 409
    assert (await put({"overrides": [{"announcement_id": ann, "verdict": "INELIGIBLE"}]})).status_code == 422
    r = await put({"report": {"opinion": "DQMS 준비 후 재상담 권고"}, "feedback": "중소기업 확인서 확인함",
                   "overrides": [{"announcement_id": ann, "verdict": "INELIGIBLE", "reason": "확인서 기간 만료"}]})
    assert r.status_code == 200, r.text
    c1 = r.json()
    assert c1["edited_sections"] == ["opinion"] and c1["overrides"][0]["from"] in ("ELIGIBLE", "NEEDS_INFO")
    assert c1["draft"][5]["text"] == ""

    # 확정 전에는 기업 화면에 없음
    assert (await client.get("/navigator/manage/consultations", headers=h)).json()["consultations"] == []

    n = len(mailer.OUTBOX)
    r = await client.post(f"/navigator/consult/consultations/{c1['id']}/confirm", headers=as_user(1),
                          json={"notify": True})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CONFIRMED" and r.json()["notify"]["sent"] is True
    assert len(mailer.OUTBOX) == n + 1 and "점" not in mailer.OUTBOX[-1].body.split("\n\n")[1]
    assert (await put({"feedback": "x"})).status_code == 409
    assert (await client.post(f"/navigator/consult/consultations/{c1['id']}/confirm", headers=as_user(1),
                              json={})).status_code == 409

    view = (await client.get("/navigator/manage/consultations", headers=h)).json()
    v = view["consultations"][0]
    assert v["id"] == c1["id"] and any(s["key"] == "opinion" for s in v["report"])
    assert not re.search(r"\d+\s*점(?![가-힣])", " ".join(s["text"] for s in v["report"]))   # 기업 판본엔 점수 없음
    staff = (await client.get(f"/navigator/consult/consultations/{c1['id']}", headers=as_user(1))).json()
    assert "종합 준비도" in staff["report"][0]["text"] and "점" in staff["report"][0]["text"]
    assert all(a["announcement_id"] != ann for a in v["announcements"])      # 신청 불가로 바꾼 공고는 안내 안 함
    assert view["requests"][0]["status"] == "DONE"

    # 재상담: 직전 상담과 비교
    r = await client.post(f"/navigator/consult/companies/{org}/consultations", headers=as_user(1),
                          json={"task": "C", "concern": "수출 준비"})
    assert r.status_code == 201, r.text
    c2 = r.json()
    assert c2["compare"]["consultation_id"] == c1["id"] and len(c2["compare"]["areas"]) == 6
    assert any(x["announcement_id"] == ann and x["before"] == "신청 불가" for x in c2["compare"]["verdict_changes"])
    assert c2["route"] is not None and "추천 성장경로" in [s["title"] for s in c2["report"]]
    # 입력값이 그대로면 진단은 새로 쌓지 않고 직전 진단을 쓴다
    assert c2["diagnosis_id"] == c1["diagnosis_id"]
    assert len((await client.get(f"/navigator/consult/companies/{org}/diagnoses", headers=as_user(1))).json()) == 1

    hist = (await client.get(f"/navigator/consult/companies/{org}/consultations", headers=as_user(1))).json()
    assert [x["id"] for x in hist] == [c2["id"], c1["id"]] and hist[1]["override_count"] == 1

    log = (await client.get("/navigator/consult/review-log", headers=as_user(1))).json()
    item = next(i for i in log["items"] if i["consultation_id"] == c1["id"])
    assert item["overrides"][0]["verdict_label"] == "신청 불가" and item["edited_sections"] == ["담당자 의견"]

    assert (await client.get("/navigator/consult/review-log", headers=as_user(2))).status_code == 403
    assert (await client.get(f"/navigator/consult/consultations/{c2['id']}", headers=as_user(2))).status_code == 403
