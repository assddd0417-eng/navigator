"""Navigator 매칭·자격요건 판정 테스트."""
import os
import re
import subprocess
from datetime import date

import psycopg
import pytest

from app.services import mailer
from app.services.eligibility import (
    Cert,
    CompanyFacts,
    Credit,
    Requirement,
    Rnd,
    judge,
    overall,
)
from app.services.ratelimit import limiter
from tests.conftest import ROOT, TEST_URL, _psql_url, as_user

PLANNER, VIEWER = 1, 5
HANBIT, NURI, SAEBOM = 101, 102, 103            # 가상 기업 (seeds/navigator_companies.sql)
SEED_ANNS = {101, 102, 103, 104, 105}            # 가상 공고 (seeds/navigator_announcements.sql)
AS_OF = date(2026, 12, 15)

# 공고별 기대 판정 (docs/navigator.md 와 같음)
EXPECTED = {
    101: {HANBIT: "ELIGIBLE", NURI: "INELIGIBLE", SAEBOM: "INELIGIBLE"},
    102: {HANBIT: "INELIGIBLE", NURI: "ELIGIBLE", SAEBOM: "INELIGIBLE"},
    103: {HANBIT: "INELIGIBLE", NURI: "INELIGIBLE", SAEBOM: "NEEDS_INFO"},
    104: {HANBIT: "INELIGIBLE", NURI: "INELIGIBLE", SAEBOM: "INELIGIBLE"},
    105: {HANBIT: "NEEDS_INFO", NURI: "NEEDS_INFO", SAEBOM: "NEEDS_INFO"},
}


@pytest.fixture(autouse=True)
def _fresh_limiter():
    limiter.reset()
    yield


def _req(t: str, rule: dict, mandatory: bool = True, rid: int = 1) -> Requirement:
    return Requirement(rid, t, rule, mandatory, t)


def test_judge_basic_rules():
    c = CompanyFacts(1, "가", company_size="SME", opened_on=date(2020, 1, 1), region="대전", employee_count=30,
                     business_status="ACTIVE", certs=[Cert("VENTURE", date(2024, 1, 1), date(2027, 1, 1), True)])
    assert judge(_req("COMPANY_SIZE", {"allowed": ["VENTURE"]}), c, AS_OF).result == "MET"   # 벤처 인증 → 벤처
    assert judge(_req("COMPANY_SIZE", {"allowed": ["LARGE"]}), c, AS_OF).result == "UNMET"
    assert judge(_req("BUSINESS_AGE", {"min_years": 7}), c, AS_OF).result == "UNMET"
    assert judge(_req("BUSINESS_AGE", {"max_years": 7}), c, AS_OF).result == "MET"
    assert judge(_req("REGION", {"allowed": ["강원"]}), c, AS_OF).result == "UNMET"
    assert judge(_req("EMPLOYEE_COUNT", {"max": 10}), c, AS_OF).result == "UNMET"
    assert judge(_req("BUSINESS_STATUS", {"allowed": ["ACTIVE"]}), c, AS_OF).result == "MET"
    # 인증 만료
    assert judge(_req("REQUIRED_CERT", {"any_of": ["VENTURE"]}), c, date(2027, 6, 1)).result == "UNMET"


def test_judge_unknown_and_answers():
    c = CompanyFacts(1, "가")
    trl = _req("TRL", {"min": 6}, rid=7)
    ch = judge(trl, c, AS_OF)
    assert ch.result == "UNKNOWN" and "TRL" in ch.question
    assert judge(_req("RND_EXPERIENCE", {"min_count": 1}), c, AS_OF).result == "UNKNOWN"   # 이력 없음 = 모름
    c.answers[7] = 7
    ch = judge(trl, c, AS_OF)
    assert ch.result == "MET" and ch.self_declared and ch.question is None
    c.answers[7] = 4
    assert judge(trl, c, AS_OF).result == "UNMET"
    other = _req("OTHER", {"note": "보안측정"}, rid=8)
    assert judge(other, c, AS_OF).result == "UNKNOWN"
    c.answers[8] = True
    assert judge(other, c, AS_OF).result == "MET"


def test_judge_credit_has_no_grade_value():
    c = CompanyFacts(1, "가", credits=[Credit(8, date(2026, 4, 1), date(2027, 4, 1), True)])   # B
    ch = judge(_req("MIN_CREDIT_GRADE", {"min_grade": "BBB-", "min_rank": 13}), c, AS_OF)
    assert ch.result == "UNMET"
    assert "B " not in ch.reason.replace("BBB-", "") and set(ch.detail) == {"verified"}
    # 유효기간 지난 등급은 없는 것으로 봄
    c.credits = [Credit(20, date(2024, 1, 1), date(2025, 1, 1), True)]
    assert judge(_req("MIN_CREDIT_GRADE", {"min_grade": "B", "min_rank": 8}), c, AS_OF).result == "UNKNOWN"


def test_overall_verdict():
    m, p = _req("TRL", {}, True), _req("TRL", {}, False)
    from app.services.eligibility import Check
    met, unmet, unk = Check("MET", ""), Check("UNMET", ""), Check("UNKNOWN", "", "질문")
    assert overall([(m, met), (p, unmet)]) == "ELIGIBLE"          # 우대 미충족은 판정에 영향 없음
    assert overall([(m, met), (m, unk)]) == "NEEDS_INFO"
    assert overall([(m, unk), (m, unmet)]) == "INELIGIBLE"       # 미충족이 모름보다 우선
    assert overall([(m, met), (p, unk)]) == "ELIGIBLE"


def test_rnd_role_lead():
    c = CompanyFacts(1, "가", rnd=[Rnd("PARTICIPANT", date(2024, 1, 1), "x")])
    assert judge(_req("RND_EXPERIENCE", {"min_count": 1, "role": "LEAD"}), c, AS_OF).result == "UNMET"
    c.rnd.append(Rnd("LEAD", date(2025, 1, 1), "y"))
    assert judge(_req("RND_EXPERIENCE", {"min_count": 1, "role": "LEAD"}), c, AS_OF).result == "MET"


def _seed():
    env = {**os.environ, "PGPASSWORD": os.environ.get("PGPASSWORD", "")}
    for f in ("navigator_companies.sql", "navigator_announcements.sql"):
        subprocess.run(["psql", _psql_url(TEST_URL), "-X", "-q", "-v", "ON_ERROR_STOP=1",
                        "-f", str(ROOT / "seeds" / f)], check=True, capture_output=True, env=env)
    with psycopg.connect(TEST_URL, autocommit=True) as conn:   # 다른 테스트가 남긴 답은 지운다
        conn.execute("DELETE FROM ax.eligibility_answer WHERE organization_id IN (101, 102, 103)")


async def _token(client, bizno: str, email: str) -> dict[str, str]:
    r = await client.post(f"/navigator/companies/{bizno}/access-link")
    assert r.status_code == 202, r.text
    mail = next(m for m in reversed(mailer.OUTBOX) if m.to == email)
    return {"X-Manage-Token": re.search(r"#t=(\S+)", mail.body).group(1)}


async def test_announcement_to_company_matrix(client):
    _seed()
    for ann_id, want in EXPECTED.items():
        r = await client.post(f"/navigator/matching/announcements/{ann_id}", headers=as_user(PLANNER))
        assert r.status_code == 201, r.text
        body = r.json()
        got = {x["organization_id"]: x["verdict"] for x in body["recommendations"] if x["organization_id"] in want}
        assert got == want, (ann_id, got)
        assert body["run"]["direction"] == "ANNOUNCEMENT_TO_COMPANY"
        ranks = [x["rank"] for x in body["recommendations"]]
        assert ranks == list(range(1, len(ranks) + 1))
        order = [x["verdict"] for x in body["recommendations"]]
        assert order == sorted(order, key=["ELIGIBLE", "NEEDS_INFO", "INELIGIBLE"].index)   # 판정 순

    # 101 1순위는 한빛
    body = (await client.post("/navigator/matching/announcements/101", headers=as_user(PLANNER))).json()
    top = body["recommendations"][0]
    assert top["organization_id"] == HANBIT and top["verdict_label"] == "적합"
    assert set(top["scores"]) == {"TECH", "IPC", "PURPOSE", "PREFERENCE"}
    assert abs(sum(s["weight"] for s in top["scores"].values()) - 1) < 1e-6
    assert top["scores"]["IPC"]["score"] == 1.0
    assert any(e["kind"] == "TECH_MATCH" and e["tech_name"] for e in top["evidence"])
    assert "필수 요건 4/4개 충족" in top["rationale"]
    assert top["business_reg_no"] == "9998100015"        # 담당자에게는 보임
    credit = next(c for c in top["checks"] if c["req_type_code"] == "MIN_CREDIT_GRADE")
    assert credit["result"] == "MET" and "detail" in credit and "grade" not in credit["detail"]

    # 저장된 실행을 다시 읽기 + 판정 거르기
    run = (await client.get(f"/navigator/matching/runs/{body['run']['id']}", params={"verdict": "ELIGIBLE"},
                            headers=as_user(PLANNER))).json()
    assert {x["verdict"] for x in run["recommendations"]} == {"ELIGIBLE"}

    # 부적격 이유에 미충족 요건과 공고 원문 근거가 붙는다
    nuri = next(x for x in body["recommendations"] if x["organization_id"] == NURI)
    assert "미충족 필수 요건" in nuri["rationale"] and "중소기업" in nuri["rationale"]
    assert any(e["kind"] == "REQUIREMENT" and e["quote"] for e in nuri["evidence"])


async def test_matching_staff_only(client):
    assert (await client.post("/navigator/matching/announcements/101")).status_code == 401
    assert (await client.post("/navigator/matching/announcements/101", headers=as_user(VIEWER))).status_code == 403
    assert (await client.post("/navigator/matching/announcements/999999",
                              headers=as_user(PLANNER))).status_code == 404
    assert (await client.post("/navigator/matching/announcements/101", params={"verdict": "GOOD"},
                              headers=as_user(PLANNER))).status_code == 422


async def test_company_to_announcement(client):
    _seed()
    for org, col in ((HANBIT, HANBIT), (NURI, NURI), (SAEBOM, SAEBOM)):
        r = await client.post(f"/navigator/matching/companies/{org}", params={"include_closed": True},
                              headers=as_user(PLANNER))
        assert r.status_code == 201, r.text
        got = {x["announcement_id"]: x["verdict"] for x in r.json()["recommendations"]
               if x["announcement_id"] in SEED_ANNS}
        assert got == {a: EXPECTED[a][col] for a in SEED_ANNS}, (org, got)
    # 기본은 마감 공고 빼고
    r = await client.post(f"/navigator/matching/companies/{HANBIT}", headers=as_user(PLANNER))
    assert 105 not in {x["announcement_id"] for x in r.json()["recommendations"]}


async def test_company_link_questions_and_answers(client):
    _seed()
    h = await _token(client, "9998300038", "hello@saebom.example")
    r = await client.post("/navigator/manage/matches", headers=h)
    assert r.status_code == 200, r.text
    rec = next(x for x in r.json()["recommendations"] if x["announcement_id"] == 103)
    assert rec["verdict"] == "NEEDS_INFO" and rec["questions"]

    qs = (await client.get("/navigator/manage/questions", headers=h)).json()["questions"]
    trl = next(q for q in qs if q["announcement_id"] == 103 and q["answer_type"] == "integer")
    assert "TRL" in trl["question"]

    bad = await client.post("/navigator/manage/answers", headers=h,
                            json={"answers": [{"requirement_id": trl["requirement_id"], "value": True}]})
    assert bad.status_code == 422
    r = await client.post("/navigator/manage/answers", headers=h,
                          json={"answers": [{"requirement_id": trl["requirement_id"], "value": 7}]})
    assert r.status_code == 200, r.text
    rec = next(x for x in r.json()["recommendations"] if x["announcement_id"] == 103)
    assert rec["verdict"] == "ELIGIBLE"
    check = next(c for c in rec["checks"] if c["requirement_id"] == trl["requirement_id"])
    assert check["self_declared"] and check["result"] == "MET"

    # 변경 없으면 같은 run 재사용
    a = (await client.post("/navigator/manage/matches", headers=h)).json()["run"]["id"]
    b = (await client.post("/navigator/manage/matches", headers=h)).json()["run"]["id"]
    assert a == b
    # 프로필을 고치면 새로 판정한다
    assert (await client.patch("/navigator/manage/profile", headers=h, json={"employee_count": 41})).status_code == 200
    c = (await client.post("/navigator/manage/matches", headers=h)).json()["run"]["id"]
    assert c != b

    with psycopg.connect(TEST_URL) as conn:
        n = conn.execute("SELECT count(*) FROM ax.audit_log WHERE table_name = 'eligibility_answer'").fetchone()[0]
    assert n >= 1
    assert (await client.post("/navigator/manage/answers", json={"answers": []})).status_code in (401, 422)


async def test_public_matches_hide_credit(client):
    _seed()
    r = await client.get("/navigator/companies/999-82-00026/matches")
    assert r.status_code == 200, r.text
    body = r.json()
    for x in body["recommendations"]:
        assert "business_reg_no" not in x and x["questions"] == []
        for c in x["checks"]:
            if c["req_type_code"] in ("MIN_CREDIT_GRADE", "REVENUE"):
                assert c["result"] is None and c["detail"] == {} and c["result_label"] == "관리 링크로 확인"
        assert not re.search(r"\b(A|B|C)+[+-]?\b", x["rationale"])
    assert (await client.get("/navigator/companies/9998999990/matches")).status_code in (404, 422)


async def test_public_verdict_ignores_hidden_credit(client):
    # 신용등급만 미달이면 공개 조회에서는 부적격으로 안 보여야 함
    _seed()
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        orig = conn.execute("SELECT id, grade FROM ax.company_credit_rating WHERE organization_id = 101").fetchall()
        conn.execute("UPDATE ax.company_credit_rating SET grade = 'CCC' WHERE organization_id = 101")
    try:
        h = await _token(client, "9998100015", "contact@hanbit.example")
        full = (await client.post("/navigator/manage/matches", headers=h, params={"refresh": True})).json()
        rec = next(x for x in full["recommendations"] if x["announcement_id"] == 101)
        assert rec["verdict"] == "INELIGIBLE"
        pub = (await client.get("/navigator/companies/9998100015/matches")).json()
        rec = next(x for x in pub["recommendations"] if x["announcement_id"] == 101)
        assert rec["verdict"] == "ELIGIBLE" and rec["hidden_requirements"] == 1
    finally:
        with psycopg.connect(TEST_URL, autocommit=True) as conn:
            for rid, grade in orig:
                conn.execute("UPDATE ax.company_credit_rating SET grade = %s WHERE id = %s", (grade, rid))


async def test_internal_project_counts_as_rnd(client):
    # card_company(CONFIRMED) 로 연결된 내부 과제도 R&D 이력에 포함
    from psycopg import AsyncConnection
    from psycopg.rows import dict_row

    from app.services.navigator_embedding import rnd_facts

    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        card = conn.execute("SELECT id, project_id FROM ax.achievement_card WHERE project_id IS NOT NULL LIMIT 1").fetchone()
    if card is None:
        pytest.skip("성과카드 없음")
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute("""INSERT INTO ax.card_company (card_id, organization_id, relation_type, relation_status)
                        VALUES (%s, 103, 'DEVELOPER', 'CONFIRMED') ON CONFLICT DO NOTHING""", (card[0],))
    try:
        async with await AsyncConnection.connect(TEST_URL, row_factory=dict_row) as conn:
            facts = await rnd_facts(conn, SAEBOM)
        assert any(f["source_table"] == "project" and f["source_id"] == card[1] for f in facts)
    finally:
        with psycopg.connect(TEST_URL, autocommit=True) as conn:
            conn.execute("DELETE FROM ax.card_company WHERE card_id = %s AND organization_id = 103", (card[0],))


async def test_staff_latest_run_and_profile(client):
    _seed()
    r = await client.get("/navigator/matching/announcements/104", headers=as_user(PLANNER))
    assert r.status_code == 200
    await client.post("/navigator/matching/announcements/104", headers=as_user(PLANNER))
    latest = (await client.get("/navigator/matching/announcements/104", headers=as_user(PLANNER))).json()
    assert latest["run"]["announcement_id"] == 104 and latest["recommendations"]
    assert (await client.get("/navigator/matching/announcements/104")).status_code == 401

    p = await client.get(f"/navigator/matching/companies/{HANBIT}/profile", headers=as_user(PLANNER))
    assert p.status_code == 200
    body = p.json()
    assert body["visibility"] == "STAFF" and body["credit_ratings"] and "***" in body["registered_email"]
    assert (await client.get(f"/navigator/matching/companies/{HANBIT}/profile",
                             headers=as_user(VIEWER))).status_code == 403
