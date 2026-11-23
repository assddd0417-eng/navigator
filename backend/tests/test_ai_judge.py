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
        return json.dumps({"announcements": [
            {"announcement_id": a["announcement_id"], "requirements": self._reqs(a["requirements"]),
             "purpose": {"level": "FULL", "reason": "품질체계 구축 목적과 맞음"}}
            for a in data["announcements"]]}, ensure_ascii=False)

    @staticmethod
    def _reqs(requirements):
        reqs = []
        for r in requirements:
            if r["type"] == "기타" or "보안" in r["description"]:
                reqs.append({"requirement_id": r["requirement_id"], "result": "MET", "reason": "보안측정 통과 확인",
                             "quote": "보안측정을 통과한 기업", "question": None})
            else:
                reqs.append({"requirement_id": r["requirement_id"], "result": "UNMET", "reason": "규모 다름",
                             "quote": "기업규모: 중소기업", "question": None})
        return reqs


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

    # 결과서 다듬기(종합 상담): 약속 표현은 템플릿 문장 유지, 기업 이름은 보내지 않음
    r = await client.post(f"/navigator/consult/companies/{org}/consultations", headers=as_user(1),
                          json={"task": "C", "concern": "품질체계 구축"})
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


async def _two_announcements(client):
    ids = []
    for no, title in (("AJ-11", "보안 통신 실증 지원(가상)"), ("AJ-12", "보안 부품 국산화 지원(가상)")):
        r = await client.post("/navigator/announcements", headers=as_user(1), json={
            "announcement_no": no, "title": title, "agency_name": "(가상)기관", "summary": "방산 품질체계 구축 지원",
            "receipt_end": (date.today() + timedelta(days=30)).isoformat(),
            "requirements": [{"req_type_code": "OTHER", "description": "보안측정 통과 기업",
                              "source_quote": "신청자격: 보안측정을 통과한 기업"}]})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    return ids


async def test_calls_per_consult_task(client, setup):
    """ISP 처리구조: 상담 업무별 LLM 호출 진단 0회, 자격 1회, 종합 2회. 공고가 여러 건이어도 자격 판단은 1회."""
    org, fake = setup
    anns = await _two_announcements(client)
    want = {"A": [], "B": ["ELIGIBILITY_JUDGE"], "C": ["ELIGIBILITY_JUDGE", "REPORT_DRAFT"]}
    for task, purposes in want.items():
        n = len(fake.calls)
        r = await client.post(f"/navigator/consult/companies/{org}/consultations", headers=as_user(1),
                              json={"task": task, "concern": f"품질체계 구축 {task}"})
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        assert len(fake.calls) - n == len(purposes), task
        with psycopg.connect(TEST_URL) as c:
            logs = c.execute("SELECT purpose, input_refs FROM ax.ai_call_log WHERE consultation_id = %s ORDER BY id",
                             (cid,)).fetchall()
        assert [p for p, _ in logs] == purposes, task
        if purposes:
            assert set(anns) <= set(logs[0][1]["announcement_ids"])          # 공고를 묶어 한 번에 보냄
            sent = json.loads(fake.calls[n][1])
            assert {a["announcement_id"] for a in sent["announcements"]} >= set(anns)
        if task != "A":
            res = {x["announcement_id"]: x for x in r.json()["eligibility"]["results"]}
            assert all(res[a]["ai"]["status"] == "OK" and res[a]["verdict"] == "ELIGIBLE" for a in anns)
    assert r.json()["report"][0]["drafted_by"] == "LLM"          # 종합 상담만 결과서 문장 다듬기

    per = {x["task"]: x for x in (await client.get("/navigator/ai/calls", headers=as_user(4))).json()["per_task"]}
    assert {t: per[t]["standard"] for t in per} == {"A": 0, "B": 1, "C": 2}
    assert per["A"]["max_calls"] == 0 and per["B"]["max_calls"] == 1 and per["C"]["max_calls"] == 2


class DropLast(FakeLLM):
    """응답에서 마지막 공고를 빠뜨린다."""

    async def complete(self, system: str, user: str) -> str:
        out = json.loads(await super().complete(system, user))
        if "announcements" in out:
            out["announcements"] = out["announcements"][:-1]
        return json.dumps(out, ensure_ascii=False)


async def test_batch_missing_announcement_falls_back(client, setup):
    org, _ = setup
    anns = await _two_announcements(client)
    fake = DropLast()
    ai_gateway.set_client(fake)
    r = await client.post(f"/navigator/consult/companies/{org}/eligibility", headers=as_user(1),
                          json={"announcement_ids": anns, "concern": "품질체계"})
    assert r.status_code == 200, r.text
    assert len(fake.calls) == 1
    res = {x["announcement_id"]: x for x in r.json()["results"]}
    first, last = res[anns[0]], res[anns[1]]
    assert first["checks"][0]["judged_by"] == "LLM" and first["ai"]["status"] == "OK"
    assert last["checks"][0]["judged_by"] == "RULE" and last["verdict"] == "NEEDS_INFO"
    assert last["ai"]["status"] == "PARTIAL" and last["ai"]["blocked"][0]["reason"] == "응답에 공고 없음"
    assert first["ai"]["log_id"] == last["ai"]["log_id"]


async def test_max_announcements_per_call(client, setup, monkeypatch):
    """AI_JUDGE_MAX_ANNOUNCEMENTS 를 넘는 공고는 규칙 결과. 호출은 그래도 1회."""
    from app.config import get_settings
    org, fake = setup
    anns = await _two_announcements(client)
    monkeypatch.setattr(get_settings(), "ai_judge_max_announcements", 1)
    r = await client.post(f"/navigator/consult/companies/{org}/eligibility", headers=as_user(1),
                          json={"announcement_ids": anns, "concern": "품질체계 상한"})
    assert len(fake.calls) == 1
    res = {x["announcement_id"]: x for x in r.json()["results"]}
    assert res[anns[0]]["ai"] is not None and res[anns[1]]["ai"] is None


async def test_staff_flow_two_calls_for_full_consult(client, setup):
    """화면 흐름 (실행: 자격요건 검토 → 성장경로 미리보기, 결과 저장) 전체에서 종합 상담 LLM 호출은 2회."""
    org, fake = setup
    await _two_announcements(client)
    body = {"concern": "수요처 확보 화면 흐름"}
    n = len(fake.calls)
    assert (await client.post(f"/navigator/consult/companies/{org}/eligibility", headers=as_user(1),
                              json=body)).status_code == 200
    assert (await client.post(f"/navigator/consult/companies/{org}/route", headers=as_user(1),
                              json=body)).status_code == 200
    r = await client.post(f"/navigator/consult/companies/{org}/consultations", headers=as_user(1),
                          json={"task": "C", **body})
    assert r.status_code == 201, r.text
    purposes = [("sections" in json.loads(u)) and "REPORT_DRAFT" or "ELIGIBILITY_JUDGE" for _, u in fake.calls[n:]]
    assert purposes == ["ELIGIBILITY_JUDGE", "REPORT_DRAFT"]
