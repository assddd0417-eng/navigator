"""자격검토 확장: 적합도 상·중·하, 중복수혜·부정당제재, 평가항목·기업부담·제출서류, 상담 API."""
from datetime import date, timedelta

import psycopg
import pytest

from app.services import fit
from app.services.eligibility import CompanyFacts, Requirement, Support, judge
from app.services.ratelimit import limiter
from tests.conftest import TEST_URL, as_user, manage_token

BRN = "9998700069"
AREAS = {"TECH": 89, "QUALITY": 25, "PRODUCTION": 60, "BUSINESS": 57, "DEFENSE": 12, "EXPORT": 45}
# 설계서 23장 예시: '26-1차 방산 중소기업 컨설팅 지원사업
ITEMS = [
    {"id": 1, "name": "재무상황", "points": 10, "kind": "CAPABILITY", "areas": ["BUSINESS"]},
    {"id": 2, "name": "기술성", "points": 15, "kind": "CAPABILITY", "areas": ["TECH", "DEFENSE"]},
    {"id": 3, "name": "컨설팅 목적성", "points": 15, "kind": "PURPOSE", "areas": []},
    {"id": 4, "name": "수행방안·기대효과", "points": 60, "kind": "APPLICATION", "areas": []},
]


def test_fit_matches_design_example():
    purpose = {"similarity": 0.7, "level": "FULL", "label": "높음"}
    r = fit.evaluate(ITEMS, AREAS, purpose, [])
    levels = {x["name"]: x["level_label"] for x in r["items"]}
    assert levels == {"재무상황": "부분", "기술성": "부분", "컨설팅 목적성": "충분", "수행방안·기대효과": "-"}
    assert r["score"] == 69 and r["grade"] == "중"
    assert "평균 50점" in r["items"][1]["basis"] or "평균 51점" in r["items"][1]["basis"]
    assert r["hints"][0]["item"] == "기술성" and r["hints"][0]["after_score"] == 88
    assert r["hints"][0]["after_grade"] == "상"
    assert "적용 무기체계" in r["hints"][0]["task"]      # 기술성의 낮은 영역 = 방산진입


def test_fit_without_concern_or_items():
    r = fit.evaluate(ITEMS, AREAS, None, [])
    assert r["items"][2]["level"] is None and "상담 내용" in r["items"][2]["basis"]
    assert r["score"] == 50          # (5 + 7.5) / 25
    none = fit.evaluate([], AREAS, None, [])
    assert none["score"] is None and none["grade_label"] == "평가 기준 없음"
    bonus = fit.evaluate(ITEMS, AREAS, None, [{"description": "벤처", "points": 3}])
    assert bonus["score"] == 53


def _dup(**rule):
    return Requirement(1, "DUPLICATE_SUPPORT", {"within_years": 1, **rule}, True, "중복수혜 없음")


def test_duplicate_support():
    as_of = date(2026, 12, 1)
    c = CompanyFacts(1, "A")
    assert judge(_dup(), c, as_of).result == "UNKNOWN"
    c.support = [Support("국방벤처센터 협약기업 지원", 2026, "SELECTED", None, 7)]
    assert judge(_dup(_program_id=7), c, as_of).result == "UNMET"
    assert judge(_dup(_program_id=8), c, as_of).result == "MET"
    assert judge(_dup(_program_name="국방벤처센터 협약기업"), c, as_of).result == "UNMET"
    c.support = [Support("컨설팅", 2024, "COMPLETED", "series-x", None)]
    assert judge(_dup(_series_key="series-x"), c, as_of).result == "MET"          # 기간 밖
    assert judge(_dup(_series_key="series-x", within_years=3), c, as_of).result == "UNMET"
    c.support = [Support("컨설팅", 2026, "FAILED", "series-x", None)]
    assert judge(_dup(_series_key="series-x"), c, as_of).result == "MET"          # 탈락은 수혜 아님


def test_procurement_sanction():
    req = Requirement(1, "NO_DISQUALIFICATION", {"checks": ["PROCUREMENT_SANCTIONED"]}, True, "제재 없음")
    c = CompanyFacts(1, "A")
    assert judge(req, c, date(2026, 1, 1)).result == "UNKNOWN"
    c.procurement_sanctioned = True
    assert judge(req, c, date(2026, 1, 1)).result == "UNMET"
    c.procurement_sanctioned = False
    assert judge(req, c, date(2026, 1, 1)).result == "MET"


@pytest.fixture
async def setup(client):
    limiter.reset()
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))
        c.execute("DELETE FROM ax.announcement WHERE announcement_no LIKE 'ER-%%'")
    r = await client.post("/navigator/companies", json={
        "business_reg_no": BRN, "company_name": "(가상)검토테크", "representative_name": "김가상",
        "opened_on": "2018-05-01", "email": f"{BRN}@example.com", "main_business": "방산 전자부품 품질 컨설팅"})
    assert r.status_code == 201, r.text
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        org = c.execute("SELECT id FROM ax.organization WHERE business_reg_no = %s", (BRN,)).fetchone()[0]
    yield org
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))
        c.execute("DELETE FROM ax.announcement WHERE announcement_no LIKE 'ER-%%'")


async def test_api_flow(client, setup):
    org = setup
    h = {"X-Manage-Token": await manage_token(client, BRN)}
    r = await client.patch("/navigator/manage/profile", headers=h, json={
        "company_size": "SME", "tax_delinquent": False, "insolvent": False, "rnd_restricted": False,
        "procurement_sanctioned": False, "employee_count": 30,
        "support_history": [{"program_name": "다른 사업", "year": 2025, "result": "COMPLETED"}]})
    assert r.status_code == 200, r.text
    assert r.json()["procurement_sanctioned"] is False

    body = {
        "announcement_no": "ER-1", "title": "방산 중소기업 컨설팅 지원(가상)", "agency_name": "(가상)기관",
        "summary": "방산 중소기업 품질체계 구축과 수요처 확보 컨설팅", "receipt_end": (date.today() + timedelta(days=30)).isoformat(),
        "company_burden": "컨설팅 비용 25%",
        "submit_documents": [{"name": "중소기업확인서"}, {"name": "재무제표(2개년)"},
                             {"name": "부정수급 확인서", "required": False}],
        "requirements": [
            {"req_type_code": "COMPANY_SIZE", "rule": {"allowed": ["SME"]}, "description": "중소기업",
             "source_quote": "신청대상: 중소기업"},
            {"req_type_code": "DUPLICATE_SUPPORT", "rule": {"within_years": 1}, "description": "전년도 동일 사업 수혜 없음",
             "source_quote": "신청제한: 전년도 동일분야 수혜기업"},
            {"req_type_code": "NO_DISQUALIFICATION",
             "rule": {"checks": ["TAX_DELINQUENT", "PROCUREMENT_SANCTIONED"]}, "description": "체납·부정당제재 없음"},
            {"req_type_code": "REQUIRED_CERT", "rule": {"any_of": ["VENTURE"]}, "is_mandatory": False,
             "description": "벤처 우대", "bonus_points": 3}],
        "eval_items": [
            {"name": "재무상황", "points": 10, "areas": ["BUSINESS"]},
            {"name": "기술성", "points": 15, "areas": ["TECH", "DEFENSE"], "source_quote": "기술성 15점"},
            {"name": "컨설팅 목적성", "points": 15, "kind": "PURPOSE"},
            {"name": "수행방안·기대효과", "points": 60, "kind": "APPLICATION"}],
    }
    r = await client.post("/navigator/announcements", json=body, headers=as_user(1))
    assert r.status_code == 201, r.text
    ann = r.json()["id"]
    bad = {**body, "announcement_no": "ER-2", "eval_items": [{"name": "기술성", "points": 10}]}
    assert (await client.post("/navigator/announcements", json=bad, headers=as_user(1))).status_code == 422

    a = (await client.get(f"/navigator/announcements/{ann}")).json()
    assert [e["name"] for e in a["eval_items"]][:2] == ["재무상황", "기술성"]
    assert a["company_burden"] == "컨설팅 비용 25%" and len(a["submit_documents"]) == 3
    assert next(r for r in a["requirements"] if r["req_type_code"] == "REQUIRED_CERT")["bonus_points"] == 3

    r = await client.post(f"/navigator/consult/companies/{org}/eligibility", headers=as_user(1),
                          json={"announcement_ids": [ann], "concern": "품질체계 구축과 수요처 확보가 어렵습니다"})
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]
    assert res["verdict"] == "ELIGIBLE" and res["q1_text"] == "필수요건 3건 모두 충족: 신청 가능"
    assert res["fit"]["grade"] in ("상", "중", "하") and res["fit"]["score"] is not None
    assert {x["name"]: x["level"] for x in res["fit"]["items"]}["수행방안·기대효과"] is None
    assert res["guide"]["text"] == "기업부담: 컨설팅 비용 25% | 제출서류: 중소기업확인서, 재무제표(2개년), 부정수급 확인서(해당 시)"
    nd = next(c for c in res["checks"] if c["req_type_code"] == "NO_DISQUALIFICATION")
    assert nd["has_basis"] is False and nd["requirement_id"] in res["unsupported"]

    # 같은 사업 수혜 이력이 생기면 신청 불가
    r = await client.patch("/navigator/manage/profile", headers=h, json={
        "support_history": [{"program_name": "방산 중소기업 컨설팅 지원(가상)", "year": date.today().year,
                             "result": "SELECTED", "announcement_id": ann}]})
    assert r.status_code == 200, r.text
    res = (await client.post(f"/navigator/consult/companies/{org}/eligibility", headers=as_user(1),
                             json={"announcement_ids": [ann]})).json()["results"][0]
    assert res["verdict"] == "INELIGIBLE" and res["q1_label"] == "신청 불가"
    assert any("같은 사업 수혜" in t["text"] for t in res["todo"])
    purpose = next(x for x in res["fit"]["items"] if x["kind"] == "PURPOSE")
    assert purpose["level"] is None      # 상담 내용 없음

    # 확인 화면에서 평가항목 교체, 생략하면 유지
    r = await client.put(f"/navigator/announcements/{ann}/review", headers=as_user(1), json={
        "requirements": body["requirements"], "eval_items": [{"name": "기술성", "points": 20, "areas": ["TECH"]}],
        "fields": {"company_burden": "없음", "submit_documents": []}})
    assert r.status_code == 204, r.text
    r = await client.put(f"/navigator/announcements/{ann}/review", headers=as_user(1),
                         json={"requirements": body["requirements"]})
    a = (await client.get(f"/navigator/announcements/{ann}", headers=as_user(1))).json()
    assert [e["name"] for e in a["eval_items"]] == ["기술성"] and a["submit_documents"] == []
    assert a["company_burden"] == "없음"

    assert (await client.post(f"/navigator/consult/companies/{org}/eligibility", headers=as_user(2),
                              json={})).status_code == 403
