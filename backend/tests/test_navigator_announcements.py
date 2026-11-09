"""Navigator 2단계: 공고 직접 입력 · PDF 업로드 · 자격요건 한 줄씩 · 가상 공고 5건 시드."""
import os
import subprocess

import psycopg
import pytest

from app.schemas.announcements import normalize_rule
from app.services.ratelimit import limiter
from tests.conftest import ROOT, TEST_URL, _psql_url, as_user
from tests.test_document_upload import make_pdf

PLANNER, REVIEWER, VIEWER = 1, 2, 5
state: dict = {}


@pytest.fixture(autouse=True)
def _fresh_limiter():
    limiter.reset()
    yield


def test_rule_formats():
    assert normalize_rule("COMPANY_SIZE", {"allowed": ["SME"]}) == {"allowed": ["SME"]}
    assert normalize_rule("BUSINESS_AGE", {"min_years": 3}) == {"min_years": 3.0}
    assert normalize_rule("RND_EXPERIENCE", {}) == {"min_count": 1}
    assert normalize_rule("OTHER", {"note": "보안측정"}) == {"note": "보안측정"}
    for bad_type, bad_rule, msg in [
        ("COMPANY_SIZE", {"allowed": ["HUGE"]}, "COMPANY_SIZE"),
        ("BUSINESS_AGE", {}, "최솟값"),
        ("TRL", {"min": 7, "max": 4}, "최솟값이 최댓값"),
        ("REGION", {"allowed": ["대전"], "extra": 1}, "extra"),
        ("NOPE", {}, "알 수 없는"),
    ]:
        with pytest.raises(ValueError, match=msg):
            normalize_rule(bad_type, bad_rule)


async def test_create_announcement_manual(client):
    r = await client.post("/navigator/announcements", headers=as_user(PLANNER), json={
        "announcement_no": "T-2026-001", "title": "테스트 부품국산화 공고", "agency_name": "(가상)진흥원",
        "program_id": 1, "receipt_start": "2026-01-01", "receipt_end": "2099-12-31",
        "support_amount_krw": 1_000_000_000,
        "requirements": [
            {"req_type_code": "COMPANY_SIZE", "rule": {"allowed": ["SME"]}, "description": "중소기업"},
            {"req_type_code": "MIN_CREDIT_GRADE", "rule": {"min_grade": "BB-"}, "description": "BB- 이상",
             "source_quote": "신용평가등급 BB- 이상", "source_page": 3},
            {"req_type_code": "PATENT", "rule": {"min_count": 1, "ipc_prefixes": ["H04"]}, "is_mandatory": False,
             "description": "통신 특허 우대"},
        ],
        "tech_needs": [{"tech_name": "항재밍 모뎀", "ipc_codes": ["H04B 1/713"]}]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["requirement_ids"]) == 3 and len(body["tech_need_ids"]) == 1
    state["ann"] = body["id"]

    d = (await client.get(f"/navigator/announcements/{state['ann']}")).json()   # 로그인 없이 공개 조회
    assert d["receipt_state"] == "OPEN" and d["receipt_state_label"] == "접수중"
    assert d["program_code"] == "P-LOC" and d["domain"] == "DEFENSE_RND"
    assert [(x["req_type_code"], x["mandatory_label"]) for x in d["requirements"]] == [
        ("COMPANY_SIZE", "필수"), ("MIN_CREDIT_GRADE", "필수"), ("PATENT", "우대")]
    assert d["requirements"][1]["source_page"] == 3 and d["tech_needs"][0]["tech_name"] == "항재밍 모뎀"


async def test_create_requires_staff(client):
    body = {"announcement_no": "T-X", "title": "x", "agency_name": "x"}
    assert (await client.post("/navigator/announcements", json=body)).status_code == 401
    assert (await client.post("/navigator/announcements", headers=as_user(VIEWER), json=body)).status_code == 403


async def test_invalid_requirements_rejected(client):
    base = {"announcement_no": "T-BAD", "title": "x", "agency_name": "x"}
    for req, msg in [
        ({"req_type_code": "MIN_CREDIT_GRADE", "rule": {"min_grade": "Z+"}, "description": "x"}, "신용등급"),
        ({"req_type_code": "REQUIRED_CERT", "rule": {"any_of": ["NOPE"]}, "description": "x"}, "인증 종류"),
        ({"req_type_code": "TRL", "rule": {"min": 10}, "description": "x"}, "TRL"),
        ({"req_type_code": "UNKNOWN", "rule": {}, "description": "x"}, "알 수 없는"),
    ]:
        r = await client.post("/navigator/announcements", headers=as_user(PLANNER), json={**base, "requirements": [req]})
        assert r.status_code == 422 and msg in r.json()["detail"], r.text
    # 하나라도 틀리면 공고 자체가 저장되지 않음 (한 트랜잭션)
    with psycopg.connect(TEST_URL) as conn:
        assert conn.execute("SELECT count(*) FROM ax.announcement WHERE announcement_no = 'T-BAD'").fetchone()[0] == 0
    r = await client.post("/navigator/announcements", headers=as_user(PLANNER),
                          json={**base, "receipt_start": "2026-12-01", "receipt_end": "2026-11-01"})
    assert r.status_code == 422


async def test_requirement_line_edit(client):
    ann = state["ann"]
    r = await client.post(f"/navigator/announcements/{ann}/requirements", headers=as_user(PLANNER), json={
        "req_type_code": "REGION", "rule": {"allowed": ["대전", "충남"]}, "is_mandatory": False,
        "description": "대전·충남 소재 우대"})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    r = await client.patch(f"/navigator/announcements/{ann}/requirements/{rid}", headers=as_user(PLANNER),
                           json={"rule": {"allowed": ["대전"]}, "is_mandatory": True})
    assert r.status_code == 204, r.text
    r = await client.patch(f"/navigator/announcements/{ann}/requirements/{rid}", headers=as_user(PLANNER),
                           json={"rule": {"allowed": ["서울시"]}})
    assert r.status_code == 422
    reqs = (await client.get(f"/navigator/announcements/{ann}")).json()["requirements"]
    region = next(x for x in reqs if x["id"] == rid)
    assert region["rule"] == {"allowed": ["대전"]} and region["is_mandatory"] and region["sort_order"] == 3
    assert (await client.delete(f"/navigator/announcements/{ann}/requirements/{rid}",
                                headers=as_user(PLANNER))).status_code == 204
    assert (await client.delete(f"/navigator/announcements/{ann}/requirements/{rid}",
                                headers=as_user(PLANNER))).status_code == 404
    with psycopg.connect(TEST_URL) as conn:   # 바꾼 사람이 감사 로그에 남는다
        actor = conn.execute("""SELECT actor_user_id FROM ax.audit_log WHERE table_name = 'announcement_requirement'
                                ORDER BY id DESC LIMIT 1""").fetchone()[0]
    assert actor == PLANNER


async def test_pdf_upload_draft_then_publish(client):
    pdf = make_pdf([
        ["2027년 무인체계 통신 부품 국산화 지원 공고(가상)", "1. 사업 목적", "수입 통신 부품 국산화 개발 지원"],
        ["2. 신청자격", "가. 중소기업기본법에 따른 중소기업", "나. 신용평가등급 B 이상인 기업"],
    ])
    r = await client.post("/navigator/announcements/upload", headers=as_user(PLANNER),
                          files={"file": ("공고문.pdf", pdf, "application/pdf")},
                          data={"announcement_no": "T-PDF-001", "agency_name": "(가상)진흥원",
                                "receipt_end": "2099-01-31"})
    assert r.status_code == 201, r.text
    body = r.json()
    ann, doc_id = body["id"], body["document_id"]
    assert doc_id and body["chunk_count"] >= 1

    # 작성중(DRAFT) 공고는 로그인 없이 안 보이고, 담당자에게는 보인다
    assert (await client.get(f"/navigator/announcements/{ann}")).status_code == 404
    d = (await client.get(f"/navigator/announcements/{ann}", headers=as_user(PLANNER))).json()
    assert d["status"] == "DRAFT" and d["source_kind"] == "PDF" and d["title"] == "공고문"
    assert d["document"]["filename"] == "공고문.pdf"

    chunks = (await client.get(f"/navigator/announcements/{ann}/chunks", params={"q": "신용평가등급"},
                               headers=as_user(PLANNER))).json()
    assert chunks and chunks[0]["page_start"] == 2
    r = await client.post(f"/navigator/announcements/{ann}/requirements", headers=as_user(PLANNER), json={
        "req_type_code": "MIN_CREDIT_GRADE", "rule": {"min_grade": "B"}, "description": "신용등급 B 이상",
        "evidence": {"chunk_id": chunks[0]["chunk_id"], "quote": "신용평가등급 B 이상인 기업"}})
    assert r.status_code == 201, r.text
    # 다른 문서의 청크는 근거로 쓸 수 없다
    with psycopg.connect(TEST_URL) as conn:
        other = conn.execute("SELECT id FROM ax.document_chunk WHERE document_id <> %s LIMIT 1", (doc_id,)).fetchone()
    if other:
        r = await client.post(f"/navigator/announcements/{ann}/requirements", headers=as_user(PLANNER), json={
            "req_type_code": "OTHER", "description": "x", "evidence": {"chunk_id": other[0]}})
        assert r.status_code == 422

    assert (await client.patch(f"/navigator/announcements/{ann}", headers=as_user(PLANNER),
                               json={"status": "PUBLISHED", "title": "무인체계 통신 부품 국산화(가상)"})).status_code == 204
    d = (await client.get(f"/navigator/announcements/{ann}")).json()
    req = d["requirements"][0]
    assert d["title"] == "무인체계 통신 부품 국산화(가상)"
    assert req["evidence_chunk_id"] == chunks[0]["chunk_id"] and req["source_page"] == 2
    assert req["source_quote"] == "신용평가등급 B 이상인 기업"


async def test_update_announcement_dates_checked(client):
    r = await client.patch(f"/navigator/announcements/{state['ann']}", headers=as_user(PLANNER),
                           json={"receipt_end": "2025-12-31"})        # 시작일(2026-01-01)보다 빠름
    assert r.status_code == 422
    assert (await client.patch("/navigator/announcements/999999", headers=as_user(PLANNER),
                               json={"title": "x"})).status_code == 404


async def test_seed_announcements(client):
    env = {**os.environ, "PGPASSWORD": os.environ.get("PGPASSWORD", "")}
    for _ in range(2):   # 재실행 안전
        subprocess.run(["psql", _psql_url(TEST_URL), "-X", "-q", "-v", "ON_ERROR_STOP=1",
                        "-f", str(ROOT / "seeds" / "navigator_announcements.sql")],
                       check=True, capture_output=True, env=env)
    rows = (await client.get("/navigator/announcements", params={"q": "(가상)"})).json()
    seeded = {r["announcement_no"]: r for r in rows if r["announcement_no"].startswith("NAV-2026-")}
    assert len(seeded) == 5
    assert seeded["NAV-2026-105"]["receipt_state"] == "CLOSED"           # 마감 (2026-10-31)
    closed = (await client.get("/navigator/announcements", params={"receipt_state": "CLOSED"})).json()
    assert "NAV-2026-105" in {r["announcement_no"] for r in closed}

    # 시드의 rule 은 API 와 같은 형식이어야 한다 (3단계 판정기가 같은 형식을 읽음)
    with psycopg.connect(TEST_URL) as conn:
        for code, rule in conn.execute(
                "SELECT req_type_code, rule FROM ax.announcement_requirement WHERE announcement_id BETWEEN 101 AND 105"):
            assert normalize_rule(code, rule) == rule, (code, rule)
        # 정보부족 예시: 105 에는 규칙으로 판정 못 하는 '기타' 필수 요건, 103 에는 TRL 요건
        assert conn.execute("""SELECT count(*) FROM ax.announcement_requirement
                                WHERE (announcement_id, req_type_code) IN ((105,'OTHER'),(103,'TRL'))""").fetchone()[0] == 2
