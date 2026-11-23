"""성장경로: 연계 기준 관리, 단계별 추천·준비상태, 미추천 사유."""
from datetime import date, timedelta

import psycopg
import pytest

from app.services import route
from app.services.ratelimit import limiter
from tests.conftest import TEST_URL, as_user, manage_token

BRN = "9998700074"
CODES = ("RT-ENTRY", "RT-DONE", "RT-NOANN", "RT-TECH", "RT-SCALE")


def test_took_program_and_readiness():
    prog = {"id": 7, "name": "방산 중소기업 컨설팅 지원(가상)"}
    assert route.took_program([{"program_id": 7, "program_name": "x", "year": 2025}], prog)
    assert route.took_program([{"program_id": None, "program_name": "2025년 방산 중소기업 컨설팅 지원", "year": 2025}],
                              prog)
    assert route.took_program([{"program_id": None, "program_name": "수출 바우처", "year": 2025}], prog) is None
    ok = {"verdict": "ELIGIBLE"}
    assert route._readiness(0, ok, []) == "IMMEDIATE"
    assert route._readiness(0, ok, [{"area": "TECH"}]) == "AFTER_FIX"
    assert route._readiness(0, {"verdict": "NEEDS_INFO"}, []) == "AFTER_FIX"
    assert route._readiness(1, ok, []) == "PREPARE"
    assert route._readiness(0, None, []) == "PREPARE"


def _cleanup(c):
    c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))
    c.execute("DELETE FROM ax.announcement WHERE announcement_no LIKE 'RT-%%'")
    c.execute("DELETE FROM ax.program WHERE program_code = ANY(%s)", (list(CODES),))


@pytest.fixture
async def setup(client):
    limiter.reset()
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        _cleanup(c)
        ids = {}
        for code in CODES:
            ids[code] = c.execute(
                """INSERT INTO ax.program (program_code, name, program_type_code)
                   VALUES (%s, %s, 'OTHER') RETURNING id""", (code, f"경로시험 {code} 지원사업")).fetchone()[0]
    r = await client.post("/navigator/companies", json={
        "business_reg_no": BRN, "company_name": "(가상)경로테크", "representative_name": "김가상",
        "opened_on": "2019-03-01", "email": f"{BRN}@example.com", "main_business": "군용 센서 모듈"})
    assert r.status_code == 201, r.text
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        org = c.execute("SELECT id FROM ax.organization WHERE business_reg_no = %s", (BRN,)).fetchone()[0]
    yield org, ids
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        _cleanup(c)


async def _announce(client, no, program_id, end_days=30, mandatory=None):
    reqs = [{"req_type_code": "COMPANY_SIZE", "rule": {"allowed": ["SME"]}, "description": "중소기업",
             "source_quote": "신청대상: 중소기업"}]
    if mandatory:
        reqs.append(mandatory)
    r = await client.post("/navigator/announcements", headers=as_user(1), json={
        "announcement_no": no, "title": f"{no} 공고(가상)", "agency_name": "(가상)기관", "program_id": program_id,
        "summary": "방산 진입 지원", "receipt_end": (date.today() + timedelta(days=end_days)).isoformat(),
        "submit_documents": [{"name": "사업계획서"}, {"name": "협약서", "required": False}],
        "requirements": reqs})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_route_flow(client, setup):
    org, ids = setup
    h = {"X-Manage-Token": await manage_token(client, BRN)}
    r = await client.patch("/navigator/manage/profile", headers=h, json={
        "company_size": "SME", "support_history": [
            {"program_name": "경로시험 RT-DONE 지원사업", "year": date.today().year - 1, "result": "COMPLETED"}]})
    assert r.status_code == 200, r.text

    await _announce(client, "RT-1", ids["RT-ENTRY"])
    await _announce(client, "RT-2", ids["RT-DONE"])
    await _announce(client, "RT-3", ids["RT-TECH"])
    await _announce(client, "RT-4", ids["RT-SCALE"], mandatory={
        "req_type_code": "COMPANY_SIZE", "rule": {"allowed": ["LARGE"]}, "description": "대기업"})

    put = lambda pid, body: client.put(f"/navigator/consult/route/programs/{pid}", headers=as_user(1), json=body)
    assert (await put(ids["RT-ENTRY"], {"stage_code": "ENTRY", "next_program_ids": [ids["RT-TECH"]],
                                        "entry_min_scores": {}, "prep_tasks": ["협약 신청서 준비", " "],
                                        "expected_output": "협약"})).status_code == 200
    assert (await put(ids["RT-DONE"], {"stage_code": "ENTRY"})).status_code == 200
    assert (await put(ids["RT-NOANN"], {"stage_code": "ENTRY"})).status_code == 200
    r = await put(ids["RT-TECH"], {"stage_code": "TECH_DEV", "entry_min_scores": {"TECH": 99},
                                   "entry_condition": "기술 99점 이상"})
    assert r.status_code == 200
    assert (await put(ids["RT-SCALE"], {"stage_code": "SCALE"})).status_code == 200
    # 검증
    assert (await put(ids["RT-SCALE"], {"stage_code": "SCALE", "next_program_ids": [ids["RT-SCALE"]]})).status_code == 422
    assert (await put(ids["RT-SCALE"], {"stage_code": "SCALE", "entry_min_scores": {"TECH": 120}})).status_code == 422
    assert (await put(ids["RT-SCALE"], {"stage_code": "NOPE"})).status_code == 422
    assert (await put(99999999, {"stage_code": "SCALE"})).status_code == 404
    assert (await put(ids["RT-SCALE"], {"stage_code": "SCALE"})).status_code == 200

    rules = (await client.get("/navigator/consult/route/rules", headers=as_user(1))).json()
    entry = next(p for p in rules["programs"] if p["program_id"] == ids["RT-ENTRY"])
    assert entry["prep_tasks"] == ["협약 신청서 준비"] and entry["next_programs"][0]["program_id"] == ids["RT-TECH"]
    assert [s["code"] for s in rules["stages"]] == ["ENTRY", "TECH_DEV", "SCALE"]

    r = await client.post(f"/navigator/consult/companies/{org}/route", headers=as_user(1),
                          json={"concern": "방산 진입 준비"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["current_stage"] == "ENTRY" and [s["horizon"][:2] for s in d["steps"]] == ["단기", "중기", "장기"]
    short = d["steps"][0]
    assert short["is_current"]
    mine = {p["program_id"]: p for s in d["steps"] for p in s["programs"] + s["other_programs"]}
    p = mine[ids["RT-ENTRY"]]
    assert p["readiness"] == "IMMEDIATE" and p["readiness_label"] == "즉시 신청"
    assert p["submit_documents"][1]["required"] is False and p["basis_quotes"] == ["신청대상: 중소기업"]
    tech = mine[ids["RT-TECH"]]
    assert tech["readiness"] == "PREPARE" and tech["entry_unmet"][0]["area"] == "TECH"
    assert "진입조건 미달" in tech["reason"]
    nr = {n["program_id"]: n["reason"] for n in d["not_recommended"]}
    assert nr[ids["RT-DONE"]].startswith("이미 수혜")
    assert nr[ids["RT-NOANN"]].startswith("근거 공고 없음")
    assert ids["RT-SCALE"] in mine                  # 장기 단계의 신청 불가 공고는 준비 대상으로 둔다
    assert "경로시험 RT-ENTRY 지원사업" in d["summary"] and d["notice"]

    assert (await client.delete(f"/navigator/consult/route/programs/{ids['RT-NOANN']}",
                                headers=as_user(1))).status_code == 204
    assert (await client.post(f"/navigator/consult/companies/{org}/route", headers=as_user(2),
                              json={})).status_code == 403
