"""D-STATE 6대 성장준비도 진단: 산정식, 상태유형, 미확보 처리, 담당자·기업 API."""
from datetime import date

import psycopg
import pytest

from app.services import dstate as ds
from app.services.ratelimit import limiter
from tests.conftest import TEST_URL, as_user, manage_token

BRN = "9998700055"


def _inp(**vals) -> ds.DiagnosisInput:
    inp = ds.DiagnosisInput(name="A테크", as_of=date(2026, 11, 23))
    for code in [*ds.LEVELS, "TRL", "RND_STAFF", "EMPLOYEE_COUNT", "REVENUE", "BUSINESS_AGE"]:
        inp.values[code] = ds.VarValue(code, vals.get(code), "SELF" if code in vals else None)
    return inp


def test_empty_input_gives_base_scores_and_missing():
    r = ds.diagnose(_inp())
    assert {a["code"]: a["score"] for a in r["areas"]} == ds.BASE
    assert r["state_type"] == "FOUNDATION"
    assert r["weakest_area"] == "EXPORT"
    assert "TRL" in r["missing"] and "DEMAND" in r["missing"]
    assert r["strengths"] == []      # 50점 미만은 강점으로 안 씀


def test_ppt_example_defense_entry():
    # 기술은 높고 방산진입·품질 실적이 없는 A테크
    inp = _inp(TRL=7, PROTOTYPE="HAVE", RND_STAFF=3, EMPLOYEE_COUNT=30, REVENUE=4_000_000_000,
               BUSINESS_AGE="2019-03-01", DQMS="NONE", DEFENSE_HISTORY="NONE", WEAPON_SYSTEM="NONE",
               DEMAND="NONE", EXPORT_EXPERIENCE="CIVIL", TARGET_MARKET="NONE")
    r = ds.diagnose(inp)
    s = {a["code"]: a["score"] for a in r["areas"]}
    # 22 + 49 + 16 + 7(비율 10% → 0.7)
    assert s["TECH"] == 94
    assert s["QUALITY"] == 25 and s["DEFENSE"] == 12
    assert s["EXPORT"] == 45
    assert r["state_type"] == "DEFENSE_ENTRY" and r["state_label"] == "방산진입 준비기업"
    assert r["weakest_area"] == "DEFENSE"
    assert r["strengths"][0]["area"] == "TECH" and "TRL 7단계" in r["strengths"][0]["text"]
    assert r["tasks"][0]["area"] == "DEFENSE"
    assert "방산진입 준비 단계" in r["summary"] and "강점 영역은 기술(94점)" in r["summary"]
    assert r["missing"] == []
    # 같은 입력이면 같은 결과
    assert ds.diagnose(inp) == r


def test_state_rules_order():
    base = {"TECH": 0, "QUALITY": 0, "PRODUCTION": 0, "BUSINESS": 0, "DEFENSE": 0, "EXPORT": 0}
    assert ds.state_type({**base, "EXPORT": 80, "DEFENSE": 70, "QUALITY": 70, "PRODUCTION": 80})[0] == "EXPORT_EXPAND"
    assert ds.state_type({**base, "QUALITY": 65, "PRODUCTION": 70, "DEFENSE": 60})[0] == "MASS_PRODUCTION"
    assert ds.state_type({**base, "TECH": 70, "DEFENSE": 49})[0] == "DEFENSE_ENTRY"
    assert ds.state_type({**base, "TECH": 70, "DEFENSE": 50})[0] == "TECH_TRANSITION"
    assert ds.state_type({**base, "TECH": 59, "DEFENSE": 50})[0] == "FOUNDATION"


def test_scores_capped_at_100():
    r = ds.diagnose(_inp(TRL=9, PROTOTYPE="HAVE", RND_STAFF=10, EMPLOYEE_COUNT=20,
                         DEFENSE_HISTORY="DELIVERY", WEAPON_SYSTEM="SPECIFIED", DEMAND="CONFIRMED"))
    s = {a["code"]: a["score"] for a in r["areas"]}
    assert s["TECH"] == 100 and s["DEFENSE"] == 100


def test_rnd_ratio_missing_without_employee_count():
    r = ds.diagnose(_inp(RND_STAFF=3))
    tech = next(a for a in r["areas"] if a["code"] == "TECH")
    assert "RND_STAFF" in tech["missing"]


def test_validate_value():
    lvl = {"code": "DQMS", "name_ko": "DQMS", "value_type": "LEVEL",
           "options": [{"code": "NONE"}, {"code": "PREPARING"}, {"code": "HAVE"}]}
    assert ds.validate_value(lvl, "HAVE") == "HAVE"
    with pytest.raises(ValueError):
        ds.validate_value(lvl, "YES")
    trl = {"code": "TRL", "name_ko": "TRL", "value_type": "INTEGER", "options": []}
    with pytest.raises(ValueError):
        ds.validate_value(trl, 10)
    with pytest.raises(ValueError):
        ds.validate_value({**trl, "value_type": "PROFILE"}, 3)


@pytest.fixture
async def company(client):
    limiter.reset()
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))
    r = await client.post("/navigator/companies", json={
        "business_reg_no": BRN, "company_name": "(가상)진단전자", "representative_name": "김가상",
        "opened_on": "2016-05-01", "email": f"{BRN}@example.com", "main_business": "RF 모듈"})
    assert r.status_code == 201, r.text
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        org = c.execute("SELECT id FROM ax.organization WHERE business_reg_no = %s", (BRN,)).fetchone()[0]
    yield org
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))


async def test_api_flow(client, company):
    org = company
    h = {"X-Manage-Token": await manage_token(client, BRN)}
    # 회사 정보에서 읽는 값
    await client.patch("/navigator/manage/profile", headers=h, json={
        "employee_count": 40, "annual_revenue_krw": 6_000_000_000, "military_supply_krw": 300_000_000,
        "technologies": [{"tech_name": "X밴드 송수신 모듈", "trl": 6}],
        "certifications": [{"cert_type_code": "DEFENSE_QMS", "issued_on": "2025-01-01"}]})

    r = await client.get("/navigator/manage/dstate", headers=h)
    assert r.status_code == 200, r.text
    rows = {v["code"]: v for v in r.json()["variables"]}
    assert rows["TRL"]["value"] == 6 and rows["TRL"]["source"] == "PROFILE"
    assert rows["DQMS"]["value"] == "HAVE" and rows["DQMS"]["source"] == "CERT"
    assert rows["DEFENSE_HISTORY"]["value"] == "DELIVERY"
    assert rows["DEMAND"]["missing"] and "DEMAND" in r.json()["missing"]
    assert "score" not in r.text      # 기업 화면엔 점수 없음

    # 기업 보완 답변: 회사 정보보다 낮은 단계는 쓰지 않음
    r = await client.put("/navigator/manage/dstate", headers=h,
                         json={"values": {"DEMAND": "DISCUSSING", "DQMS": "PREPARING", "RND_STAFF": 8}})
    assert r.status_code == 200, r.text
    rows = {v["code"]: v for v in r.json()["variables"]}
    assert rows["DEMAND"]["value"] == "DISCUSSING" and rows["DEMAND"]["source"] == "SELF"
    assert rows["DQMS"]["value"] == "HAVE"
    r = await client.put("/navigator/manage/dstate", headers=h, json={"values": {"EMPLOYEE_COUNT": 3}})
    assert r.status_code == 422

    # 담당자: 저장 안 하는 미리보기, 담당자 값 우선, 실행 저장, 이력
    r = await client.get(f"/navigator/consult/companies/{org}/dstate", headers=as_user(1))
    assert r.status_code == 200, r.text
    before = r.json()
    assert before["diagnosis_id"] is None and len(before["areas"]) == 6
    r = await client.put(f"/navigator/consult/companies/{org}/dstate/values", headers=as_user(1),
                         json={"values": {"DEMAND": "CONFIRMED", "WEAPON_SYSTEM": "SPECIFIED"}})
    assert r.status_code == 200, r.text
    rows = {v["code"]: v for v in r.json()["variables"]}
    assert rows["DEMAND"]["value"] == "CONFIRMED" and rows["DEMAND"]["source"] == "STAFF"
    defense = next(a for a in r.json()["areas"] if a["code"] == "DEFENSE")
    assert defense["score"] == 100     # 12 + 48 + 25 + 25, 100 에서 자름

    r1 = await client.post(f"/navigator/consult/companies/{org}/dstate", headers=as_user(1))
    assert r1.status_code == 201, r1.text
    assert r1.json()["diagnosis_id"] and r1.json()["previous"] is None
    r2 = await client.post(f"/navigator/consult/companies/{org}/dstate", headers=as_user(1))
    assert r2.json()["previous"]["diagnosis_id"] == r1.json()["diagnosis_id"]
    hist = (await client.get(f"/navigator/consult/companies/{org}/diagnoses", headers=as_user(1))).json()
    assert len(hist) == 2 and hist[0]["created_by_name"] == "공고담당"

    found = (await client.get("/navigator/consult/companies", params={"q": "진단전자"}, headers=as_user(1))).json()
    assert [c["organization_id"] for c in found] == [org] and found[0]["last_diagnosed_at"]
    found = (await client.get("/navigator/consult/companies", params={"q": BRN[:5]}, headers=as_user(1))).json()
    assert org in [c["organization_id"] for c in found]

    rules = (await client.get("/navigator/consult/dstate/rules", headers=as_user(1))).json()
    assert len(rules["areas"]) == 6 and len(rules["state_types"]) == 5 and len(rules["variables"]) == 12

    assert (await client.get(f"/navigator/consult/companies/{org}/dstate", headers=as_user(2))).status_code == 403
    assert (await client.get("/navigator/consult/companies/999999/dstate", headers=as_user(1))).status_code == 404
