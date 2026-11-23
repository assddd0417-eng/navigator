"""AI 판단: 근거 인용 검증, 계산 검증, 결과서 문장 다듬기, 프롬프트 관리, 호출 기록."""
import json
from datetime import date, timedelta

import psycopg
import pytest

from app.services import ai_gateway, ai_judge, consultation
from app.services.ratelimit import limiter
from tests.conftest import TEST_URL, as_user, manage_token

BRN = "9998700109"
NAME = "(가상)판단테크"


def _row(rid, code, result, mandatory=True, quote=None):
    return {"requirement_id": rid, "req_type_code": code, "req_type_name": code, "description": f"요건 {rid}",
            "is_mandatory": mandatory, "result": result, "result_label": "", "reason": "규칙 사유",
            "question": "확인 질문" if result == "UNKNOWN" else None, "self_declared": False,
            "source_quote": quote, "source_page": None, "has_basis": bool(quote), "bonus_points": None}


def test_merge_rules():
    basis = [{"source": "공고 조항", "text": "신청대상: 보안측정을 통과한 기업"}]
    facts = ["기업규모: 중소기업"]
    rows = [_row(1, "OTHER", "UNKNOWN", quote="신청대상: 보안측정을 통과한 기업"),
            _row(2, "COMPANY_SIZE", "MET"), _row(3, "EMPLOYEE_COUNT", "UNKNOWN"), _row(4, "OTHER", "UNKNOWN")]
    out = {"requirements": [
        {"requirement_id": 1, "result": "UNMET", "reason": "보안측정 이력 없음", "quote": "보안측정을 통과한 기업"},
        {"requirement_id": 2, "result": "UNMET", "reason": "x", "quote": "기업규모: 중소기업"},
        {"requirement_id": 3, "result": "MET", "reason": "x", "quote": "기업규모: 중소기업"},
        {"requirement_id": 4, "result": "MET", "reason": "근거 없음", "quote": "공고에 없는 문장입니다"}]}
    new, blocked = ai_judge.merge(rows, out, basis, facts)
    by = {r["requirement_id"]: r for r in new}
    assert by[1]["result"] == "UNMET" and by[1]["judged_by"] == "LLM" and by[1]["question"] is None
    assert by[2]["result"] == "MET" and by[2]["judged_by"] == "CALC" and by[2]["ai_quote"] is None   # 규칙 결과가 이김
    assert by[3]["result"] == "UNKNOWN"                                        # 값이 없으면 LLM 충족도 확인 필요
    assert by[4]["result"] == "UNKNOWN" and by[4]["judged_by"] == "RULE"      # 인용 실패는 버림
    assert {(b["requirement_id"], b["reason"]) for b in blocked} == {
        (2, "계산 검증 불일치"), (3, "수치 요건 값 확인 안 됨"), (4, "근거 인용 실패")}


def test_check_polished():
    draft = [{"key": "overview", "text": "[기업] | 종합 준비도 61점"},
             {"key": "diagnosis", "text": "기술 97점, 품질 25점"},
             {"key": "route", "text": "단기: 컨설팅 지원"}]
    got, blocked = consultation.check_polished(draft, {"sections": [
        {"key": "overview", "text": "[기업]의 종합 준비도는 61점임."},
        {"key": "diagnosis", "text": "기술 99점으로 우수함."},
        {"key": "route", "text": "단기에는 컨설팅 지원에 선정됩니다."},
        {"key": "notice", "text": "바꿈"}]})
    assert got == {"overview": "[기업]의 종합 준비도는 61점임."}
    assert [b["reason"] for b in blocked] == ["초안에 없는 숫자", "선정·지원 약속 표현"]


class FakeLLM:
    name = "test/fake"

    def __init__(self):
        self.calls = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        data = json.loads(user)
        if "sections" in data:
            return json.dumps({"sections": [
                {"key": s["key"], "text": s["text"].replace("\n", " ") + " 이상임."} for s in data["sections"]]
                + [{"key": "route", "text": "단기 사업에 반드시 선정됨."}]}, ensure_ascii=False)
        reqs = []
        for r in data["requirements"]:
            if r["type"] == "기타" or "보안" in r["description"]:
                reqs.append({"requirement_id": r["requirement_id"], "result": "MET", "reason": "보안측정 통과 확인",
                             "quote": "보안측정을 통과한 기업", "question": None})
            else:
                reqs.append({"requirement_id": r["requirement_id"], "result": "UNMET", "reason": "규모 다름",
                             "quote": "기업규모: 중소기업", "question": None})
        return json.dumps({"requirements": reqs, "purpose": {"level": "FULL", "reason": "품질체계 구축 목적과 맞음"}},
                          ensure_ascii=False)


@pytest.fixture
async def setup(client):
    limiter.reset()
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))
        c.execute("DELETE FROM ax.announcement WHERE announcement_no LIKE 'AJ-%%'")
    r = await client.post("/navigator/companies", json={
        "business_reg_no": BRN, "company_name": NAME, "representative_name": "김가상",
        "opened_on": "2018-05-01", "email": f"{BRN}@example.com", "main_business": "방산 통신 장비"})
    assert r.status_code == 201, r.text
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        org = c.execute("SELECT id FROM ax.organization WHERE business_reg_no = %s", (BRN,)).fetchone()[0]
    fake = FakeLLM()
    ai_gateway.set_client(fake)
    yield org, fake
    ai_gateway.set_client(None)
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))
        c.execute("DELETE FROM ax.announcement WHERE announcement_no LIKE 'AJ-%%'")


async def test_ai_flow(client, setup):
    org, fake = setup
    h = {"X-Manage-Token": await manage_token(client, BRN)}
    assert (await client.patch("/navigator/manage/profile", headers=h, json={"company_size": "SME"})).status_code == 200
    r = await client.post("/navigator/announcements", headers=as_user(1), json={
        "announcement_no": "AJ-1", "title": "보안 통신 실증 지원(가상)", "agency_name": "(가상)기관",
        "summary": "방산 품질체계 구축 지원", "receipt_end": (date.today() + timedelta(days=30)).isoformat(),
        "requirements": [
            {"req_type_code": "COMPANY_SIZE", "rule": {"allowed": ["SME"]}, "description": "중소기업",
             "source_quote": "신청대상: 중소기업"},
            {"req_type_code": "OTHER", "description": "보안측정 통과 기업",
             "source_quote": "신청자격: 보안측정을 통과한 기업"}],
        "eval_items": [{"name": "목적성", "points": 20, "kind": "PURPOSE"}]})
    assert r.status_code == 201, r.text
    ann = r.json()["id"]

    body = {"announcement_ids": [ann], "concern": "품질체계 구축"}
    r = await client.post(f"/navigator/consult/companies/{org}/eligibility", headers=as_user(1), json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    res = d["results"][0]
    assert d["ai_mode"] == "llm"
    by = {c["req_type_code"]: c for c in res["checks"]}
    assert by["OTHER"]["result"] == "MET" and by["OTHER"]["judged_by"] == "LLM"
    assert by["COMPANY_SIZE"]["result"] == "MET" and by["COMPANY_SIZE"]["judged_by"] == "CALC"
    assert res["verdict"] == "ELIGIBLE"
    assert res["ai"]["status"] == "PARTIAL" and res["ai"]["blocked"][0]["reason"] == "계산 검증 불일치"
    assert next(i for i in res["fit"]["items"] if i["name"] == "목적성")["basis"].endswith("품질체계 구축 목적과 맞음")
    sent = fake.calls[0][1]
    assert NAME not in sent and BRN not in sent and "보안측정을 통과한 기업" in sent

    # 같은 입력은 캐시
    n = len(fake.calls)
    r = await client.post(f"/navigator/consult/companies/{org}/eligibility", headers=as_user(1), json=body)
    assert r.json()["results"][0]["ai"]["status"] == "CACHED" and len(fake.calls) == n

    # 결과서 다듬기: 약속 표현은 템플릿 문장 유지, 기업 이름은 보내지 않음
    r = await client.post(f"/navigator/consult/companies/{org}/consultations", headers=as_user(1),
                          json={"task": "B", "concern": "품질체계 구축"})
    assert r.status_code == 201, r.text
    rep = {s["key"]: s for s in r.json()["report"]}
    assert rep["overview"]["drafted_by"] == "LLM" and NAME in rep["overview"]["text"]
    assert rep["notice"]["drafted_by"] == "TEMPLATE"
    assert all(NAME not in u for _, u in fake.calls)

    # 호출 기록과 프롬프트 관리는 AX 주관부서
    assert (await client.get("/navigator/ai/calls", headers=as_user(1))).status_code == 403
    logs = (await client.get("/navigator/ai/calls", headers=as_user(4))).json()
    mine = [x for x in logs["items"] if x["organization_id"] == org]
    assert {x["status"] for x in mine} >= {"PARTIAL", "CACHED"}
    assert any(x["purpose"] == "REPORT_DRAFT" and x["blocked"] for x in mine)

    ps = (await client.get("/navigator/ai/prompts", headers=as_user(1))).json()["items"]
    v1 = next(p for p in ps if p["code"] == "ELIGIBILITY_JUDGE" and p["is_active"])
    assert (await client.post("/navigator/ai/prompts/ELIGIBILITY_JUDGE", headers=as_user(3),
                              json={"guide_text": "x"})).status_code == 403
    r = await client.post("/navigator/ai/prompts/ELIGIBILITY_JUDGE", headers=as_user(4),
                          json={"guide_text": "- 보안측정은 확인서로 본다", "note": "보안 기준 추가"})
    assert r.status_code == 201 and r.json()["version"] == v1["version"] + 1
    try:
        n = len(fake.calls)
        await client.post(f"/navigator/consult/companies/{org}/eligibility", headers=as_user(1), json=body)
        assert len(fake.calls) == n + 1 and "보안측정은 확인서로 본다" in fake.calls[-1][0]   # 새 버전은 캐시 안 씀
        assert (await client.post(f"/navigator/ai/prompts/REPORT_DRAFT/versions/{v1['id']}/activate",
                                  headers=as_user(4))).status_code == 404
    finally:
        r = await client.post(f"/navigator/ai/prompts/ELIGIBILITY_JUDGE/versions/{v1['id']}/activate",
                              headers=as_user(4))
        assert r.status_code == 200


async def test_rules_mode_without_llm(client, setup):
    org, _ = setup
    ai_gateway.set_client(None)
    r = await client.post(f"/navigator/consult/companies/{org}/eligibility", headers=as_user(1), json={})
    assert r.status_code == 200
    assert r.json().get("ai_mode", "rules") == "rules"
