"""운영규정·지침: 조문 나누기, 참여제한 후보, 등록·확인, 검색, 공통 참여제한 적용."""
from datetime import date, timedelta

import psycopg
import pytest

from app.services import regulation
from app.services.ratelimit import limiter
from tests.conftest import TEST_URL, as_user, manage_token

BRN = "9998700114"
TEXT = """제1조(목적) 이 규정은 방산 지원사업(가상)의 운영에 필요한 사항을 정한다.
제3조(참여제한) ① 국세 또는 지방세를 체납한 기업은 신청할 수 없다.
② 부정당업자로 제재를 받고 있는 기업은 신청할 수 없다.
제4조(중복지원 제한) 최근 2년 안에 동일 사업의 지원을 받은 기업은 같은 사업에 다시 신청할 수 없다.
제5조(평가) 평가는 서면평가와 발표평가로 한다."""


def test_split_and_guess():
    arts = regulation.split_articles(TEXT)
    assert [a["article_no"] for a in arts] == ["제1조", "제3조", "제4조", "제5조"]
    assert arts[1]["title"] == "참여제한" and "부정당업자" in arts[1]["body"]
    assert regulation.guess_checks(arts[1]["body"]) == (["TAX_DELINQUENT", "PROCUREMENT_SANCTIONED"], None)
    assert regulation.guess_checks(arts[2]["body"]) == (["DUPLICATE"], 2)
    assert regulation.guess_checks(arts[3]["body"]) == ([], None)
    assert [a["article_no"] for a in regulation.split_articles("첫 문단\n\n둘째 문단")] == ["1", "2"]


def _cleanup(c):
    c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))
    c.execute("DELETE FROM ax.announcement WHERE announcement_no LIKE 'RG-%%'")
    c.execute("DELETE FROM ax.regulation WHERE title LIKE '시험 운영규정%%'")
    c.execute("DELETE FROM ax.program WHERE program_code = 'RG-PROG'")


@pytest.fixture
async def setup(client):
    limiter.reset()
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        _cleanup(c)
        prog = c.execute("INSERT INTO ax.program (program_code, name, program_type_code) "
                         "VALUES ('RG-PROG', '규정시험 지원사업', 'OTHER') RETURNING id").fetchone()[0]
    r = await client.post("/navigator/companies", json={
        "business_reg_no": BRN, "company_name": "(가상)규정테크", "representative_name": "김가상",
        "opened_on": "2017-01-01", "email": f"{BRN}@example.com", "main_business": "방산 부품"})
    assert r.status_code == 201, r.text
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        org = c.execute("SELECT id FROM ax.organization WHERE business_reg_no = %s", (BRN,)).fetchone()[0]
    yield org, prog
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        _cleanup(c)


async def test_regulation_flow(client, setup):
    org, prog = setup
    body = {"title": "시험 운영규정(공통)", "kind": "COMMON", "version_label": "2026", "text": TEXT}
    assert (await client.post("/navigator/regulations", headers=as_user(1), json=body)).status_code == 403
    assert (await client.post("/navigator/regulations", headers=as_user(3),
                              json={**body, "kind": "PROGRAM"})).status_code == 422
    pv = (await client.post("/navigator/regulations/preview", headers=as_user(3), json={"text": TEXT})).json()
    assert [p["check_labels"] for p in pv][1:3] == [["국세·지방세 체납", "부정당제재"], ["중복지원 제한"]]

    r = await client.post("/navigator/regulations", headers=as_user(3), json=body)
    assert r.status_code == 201, r.text
    reg = r.json()
    assert reg["confirmed_at"] is None and reg["owner_dept_name"] == "방산사업팀"
    assert [a["ref"] for a in reg["articles"]][1] == "시험 운영규정(공통) 제3조(참여제한)"
    assert reg["articles"][2]["within_years"] == 2

    found = (await client.get("/navigator/regulations/search", headers=as_user(1),
                              params={"q": "부정당업자 제재 기업 신청"})).json()
    assert found[0]["ref"].endswith("제3조(참여제한)")

    # 기업: 체납 모름, 부정당 아님, 1년 전 같은 사업 수혜
    h = {"X-Manage-Token": await manage_token(client, BRN)}
    r = await client.patch("/navigator/manage/profile", headers=h, json={
        "company_size": "SME", "procurement_sanctioned": False,
        "support_history": [{"program_name": "규정시험 지원사업", "year": date.today().year - 1,
                             "result": "COMPLETED"}]})
    assert r.status_code == 200, r.text
    r = await client.post("/navigator/announcements", headers=as_user(3), json={
        "announcement_no": "RG-1", "title": "규정시험 지원사업 공고(가상)", "agency_name": "(가상)기관",
        "program_id": prog, "receipt_end": (date.today() + timedelta(days=20)).isoformat(),
        "requirements": [{"req_type_code": "COMPANY_SIZE", "rule": {"allowed": ["SME"]}, "description": "중소기업",
                          "source_quote": "신청대상: 중소기업"},
                         {"req_type_code": "NO_DISQUALIFICATION", "rule": {"checks": ["TAX_DELINQUENT"]},
                          "description": "체납 없음", "source_quote": "체납 기업 제외"}]})
    assert r.status_code == 201, r.text
    ann = r.json()["id"]

    res = (await client.post(f"/navigator/consult/companies/{org}/eligibility", headers=as_user(1),
                             json={"announcement_ids": [ann]})).json()["results"][0]
    common = [c for c in res["checks"] if c["requirement_id"] < 0]
    assert [c["description"] for c in common] == ["공통 참여제한: 부정당제재 없음",
                                                  "공통 참여제한: 최근 2년 같은 사업 중복지원 없음"]
    assert common[0]["result"] == "MET" and common[1]["result"] == "UNMET"
    assert common[1]["regulation_ref"].endswith("제4조(중복지원 제한)") and common[1]["has_basis"]
    assert res["verdict"] == "INELIGIBLE"
    assert any(g["ref"].endswith("제3조(참여제한)") for g in res["regulations"])
    assert res["criteria"]["regulations_confirmed_at"] is None
    assert res["criteria"]["unconfirmed_regulations"] == ["시험 운영규정(공통)"]

    # 소관부서 확인 후에는 확인일이 나온다. 조문을 고치면 다시 확인해야 한다
    assert (await client.post(f"/navigator/regulations/{reg['id']}/confirm", headers=as_user(1))).status_code == 403
    r = await client.post(f"/navigator/regulations/{reg['id']}/confirm", headers=as_user(3))
    assert r.json()["confirmed_at"] is not None
    res = (await client.post(f"/navigator/consult/companies/{org}/eligibility", headers=as_user(1),
                             json={"announcement_ids": [ann]})).json()["results"][0]
    assert res["criteria"]["regulations_confirmed_at"] and not res["criteria"]["unconfirmed_regulations"]

    arts = [{"article_no": "제3조", "title": "참여제한", "body": "부정당업자는 신청할 수 없다.", "checks": []}]
    r = await client.put(f"/navigator/regulations/{reg['id']}", headers=as_user(4), json={"articles": arts})
    assert r.status_code == 200 and r.json()["confirmed_at"] is None and r.json()["articles"][0]["checks"] == []
    res = (await client.post(f"/navigator/consult/companies/{org}/eligibility", headers=as_user(1),
                             json={"announcement_ids": [ann]})).json()["results"][0]
    assert not [c for c in res["checks"] if c["requirement_id"] < 0] and res["verdict"] == "NEEDS_INFO"

    lst = (await client.get("/navigator/regulations", headers=as_user(1))).json()
    assert any(x["id"] == reg["id"] and x["article_count"] == 1 for x in lst)
    assert (await client.delete(f"/navigator/regulations/{reg['id']}", headers=as_user(1))).status_code == 403
    assert (await client.delete(f"/navigator/regulations/{reg['id']}", headers=as_user(3))).status_code == 204
    assert (await client.get(f"/navigator/regulations/{reg['id']}", headers=as_user(1))).status_code == 404
