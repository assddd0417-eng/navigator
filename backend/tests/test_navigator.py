"""Navigator 기업 프로필·관리 링크 테스트."""
import os
import re
import subprocess

import psycopg
import pytest

from app.config import get_settings
from app.services import mailer
from app.services.bizno import InvalidBizNo, checksum_ok, normalize
from app.services.ratelimit import limiter
from tests.conftest import ROOT, TEST_URL, _psql_url

# 목업 등록부(app/services/external/fixtures/nts_mock.json): 9998400049 홍길동 2019-03-01 계속, 9998600058 폐업
VERIFIED_BRN = "999-84-00049"
UNKNOWN_BRN = "9998500051"      # 형식은 맞지만 목업 등록부에 없음 → 미확인
CLOSED_BRN = "9998600058"
state: dict = {}


@pytest.fixture(autouse=True)
def _fresh_limiter():
    limiter.reset()
    yield


def _token_from_last_mail(to: str) -> str:
    mail = next(m for m in reversed(mailer.OUTBOX) if m.to == to)
    return re.search(r"#t=(\S+)", mail.body).group(1)


def _manage(token: str) -> dict[str, str]:
    return {"X-Manage-Token": token}


def test_bizno_format():
    assert normalize("999-84-00049") == "9998400049"
    assert checksum_ok("9998100015")
    with pytest.raises(InvalidBizNo):
        normalize("999-84-00048")      # 검증번호 틀림
    with pytest.raises(InvalidBizNo):
        normalize("12345")


async def test_register_verified_company(client):
    r = await client.post("/navigator/companies", json={
        "business_reg_no": VERIFIED_BRN, "company_name": "(가상)길동정밀", "representative_name": "홍길동",
        "opened_on": "2019-03-01", "email": "ceo@gildong.example",
        "main_business": "유도무기 구동장치용 정밀 감속기", "company_size": "SME", "employee_count": 42,
        "annual_revenue_krw": 5_300_000_000, "revenue_year": 2025, "region": "충남",
        "patents": [{"application_no": "10-2022-0000001", "registration_no": "10-2500001",
                     "title": "백래시 저감 정밀 감속기", "ipc_codes": ["F16H 1/32"], "status": "REGISTERED",
                     "registered_on": "2024-02-01"}],
        "certifications": [{"cert_type_code": "INNOBIZ", "issued_on": "2025-01-01", "expires_on": "2028-01-01"}],
        "credit_ratings": [{"agency": "SELF", "grade": "BB+", "rated_on": "2026-03-01"}],
        "rnd_history": [{"project_no": "PRJ-2021-007", "title": "전술 배터리 열관리 기술 참여", "role": "PARTICIPANT"}],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["biz_verify_status"] == "VERIFIED" and body["biz_verify_label"] == "확인됨"
    assert body["business_reg_no"] == "999-84-00049" and body["business_status"] == "계속사업자"
    assert body["sent_to"] == "c***@gildong.example"
    assert body["dev_management_link"] is None          # 기본값: 응답에 링크를 싣지 않음
    state["org_id"] = body["organization_id"]
    # 등록 메일은 알림 주소 안내만 (링크 없음). 등록한 사람은 응답의 토큰으로 바로 연다
    assert "manage#t=" not in mailer.OUTBOX[-1].body
    state["token"] = body["manage_token"]
    # 사업자번호만으로는 못 연다
    assert (await client.post("/navigator/companies/999-84-00049/open")).status_code in (404, 405)


async def test_public_view_hides_private_fields(client):
    r = await client.get("/navigator/companies/9998400049")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["company_name"] == "(가상)길동정밀" and body["biz_verify_label"] == "확인됨"
    assert [p["title"] for p in body["patents"]] == ["백래시 저감 정밀 감속기"]
    for private in ("credit_ratings", "annual_revenue_krw", "employee_count", "registered_email", "main_business"):
        assert private not in body


async def test_manage_view_with_link(client):
    r = await client.get("/navigator/manage/profile", headers=_manage(state["token"]))
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["organization_id"] == state["org_id"] and p["visibility"] == "OWNER"
    assert p["credit_ratings"][0]["grade"] == "BB+" and p["annual_revenue_krw"] == 5_300_000_000
    assert p["certifications"][0]["cert_type_name"].startswith("이노비즈")
    fs = {f["field_name"]: f for f in p["field_sources"]}
    assert fs["business_status"]["any_verified"] and fs["business_status"]["preferred_value"] == "ACTIVE"
    assert fs["representative_name"]["any_verified"]               # 국세청이 확인
    assert not fs["employee_count"]["any_verified"]                # 자가입력 = 미확인
    with psycopg.connect(TEST_URL) as conn:
        hashed = conn.execute("SELECT token_hash, email_verified_at IS NOT NULL FROM ax.company_access_link "
                              "WHERE organization_id = %s AND revoked_at IS NULL", (state["org_id"],)).fetchone()
    assert hashed[0] != state["token"] and len(hashed[0]) == 64     # 비밀값 원문은 저장하지 않음
    assert hashed[1]                                                # 링크를 열면 이메일 확인


async def test_manage_requires_valid_link(client):
    assert (await client.get("/navigator/manage/profile")).status_code == 401
    assert (await client.get("/navigator/manage/profile", headers=_manage("wrong-token"))).status_code == 401


async def test_duplicate_registration_rejected(client):
    r = await client.post("/navigator/companies", json={
        "business_reg_no": "9998400049", "company_name": "가짜", "representative_name": "홍길동",
        "opened_on": "2019-03-01", "email": "attacker@example.com"})
    assert r.status_code == 409 and "관리 링크" in r.json()["detail"]


async def test_verification_mismatch_not_saved(client):
    r = await client.post("/navigator/companies", json={
        "business_reg_no": CLOSED_BRN, "company_name": "남의회사", "representative_name": "아무개",
        "opened_on": "2010-01-01", "email": "x@example.com"})
    assert r.status_code == 422 and "불일치" in r.json()["detail"]
    assert (await client.get(f"/navigator/companies/{CLOSED_BRN}")).status_code == 404
    with psycopg.connect(TEST_URL) as conn:   # 거절해도 수집 기록은 남는다
        n = conn.execute("""SELECT count(*) FROM ax.external_raw_record r JOIN ax.external_source s ON s.id = r.source_id
                             WHERE s.code = 'NTS_BIZ' AND r.external_key = %s""", (CLOSED_BRN,)).fetchone()[0]
    assert n == 1


async def test_closed_business_registers_with_status(client):
    r = await client.post("/navigator/companies", json={
        "business_reg_no": CLOSED_BRN, "company_name": "(가상)폐업상사", "representative_name": "최폐업",
        "opened_on": "2010-01-01", "email": "close@example.com"})
    assert r.status_code == 201, r.text
    assert r.json()["biz_verify_status"] == "VERIFIED" and r.json()["business_status"] == "폐업"


async def test_unknown_business_saved_as_unverified(client):
    r = await client.post("/navigator/companies", json={
        "business_reg_no": UNKNOWN_BRN, "company_name": "(가상)미확인테크", "representative_name": "김미확",
        "opened_on": "2024-01-01", "email": "who@example.com"})
    assert r.status_code == 201, r.text
    assert r.json()["biz_verify_label"] == "미확인"
    pub = (await client.get(f"/navigator/companies/{UNKNOWN_BRN}")).json()
    assert pub["biz_verify_label"] == "미확인" and pub["business_status_label"] == "모름"


async def test_invalid_input_rejected(client):
    base = {"company_name": "x", "representative_name": "x", "opened_on": "2020-01-01", "email": "a@b.co"}
    r = await client.post("/navigator/companies", json={**base, "business_reg_no": "999-84-00048"})
    assert r.status_code == 422 and "없는 사업자등록번호" in r.json()["detail"]
    r = await client.post("/navigator/companies", json={**base, "business_reg_no": UNKNOWN_BRN, "email": "no-at"})
    assert r.status_code == 422                     # 이메일 필수·형식
    assert (await client.get("/navigator/companies/12-34")).status_code == 422


async def test_update_profile_with_link(client):
    r = await client.patch("/navigator/manage/profile", headers=_manage(state["token"]), json={
        "employee_count": 45, "region": "대전",
        "patents": [{"application_no": "10-2026-0000009", "title": "새 출원", "status": "APPLIED"}]})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["employee_count"] == 45 and p["region"] == "대전"
    assert [x["title"] for x in p["patents"]] == ["새 출원"]          # 자가입력 목록은 통째로 바뀜
    assert p["credit_ratings"][0]["grade"] == "BB+"                    # 보내지 않은 목록은 그대로
    fs = {f["field_name"]: f for f in p["field_sources"]}
    assert fs["employee_count"]["preferred_value"] == 45
    with psycopg.connect(TEST_URL) as conn:   # 감사 로그에 어느 관리 링크로 바꿨는지 남는다
        rid = conn.execute("""SELECT request_id FROM ax.audit_log WHERE table_name = 'company_profile'
                               AND action = 'U' ORDER BY id DESC LIMIT 1""").fetchone()[0]
    assert "|company-link:" in rid
    # 진위확인 값(대표자명 등)과 사업자번호는 바꿀 수 없다 (모르는 칸은 무시)
    r = await client.patch("/navigator/manage/profile", headers=_manage(state["token"]),
                           json={"representative_name": "다른사람"})
    assert r.status_code == 200 and r.json()["representative_name"] == "홍길동"


async def test_resend_link_revokes_old(client):
    r = await client.post("/navigator/companies/999-84-00049/access-link")
    assert r.status_code == 202 and r.json()["sent_to"] == "c***@gildong.example"
    new_token = _token_from_last_mail("ceo@gildong.example")
    assert new_token != state["token"]
    assert (await client.get("/navigator/manage/profile", headers=_manage(state["token"]))).status_code == 401
    assert (await client.get("/navigator/manage/profile", headers=_manage(new_token))).status_code == 200
    state["token"] = new_token
    assert (await client.post("/navigator/companies/9998500077/access-link")).status_code in (404, 422)


async def test_expired_link(client):
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute("""UPDATE ax.company_access_link SET created_at = now() - interval '40 days',
                               expires_at = now() - interval '10 days'
                         WHERE organization_id = %s AND revoked_at IS NULL""", (state["org_id"],))
    r = await client.get("/navigator/manage/profile", headers=_manage(state["token"]))
    assert r.status_code == 401 and "만료" in r.json()["detail"]


async def test_dev_expose_link(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "navigator_dev_expose_link", True)
    r = await client.post("/navigator/companies/9998400049/access-link")
    assert r.status_code == 202 and "/navigator/manage#t=" in r.json()["dev_management_link"]


async def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "navigator_rate_limit_per_minute", 3)
    codes = [(await client.get(f"/navigator/companies/{UNKNOWN_BRN}")).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


async def test_seed_companies(client):
    env = {**os.environ, "PGPASSWORD": os.environ.get("PGPASSWORD", "")}
    for _ in range(2):   # 재실행 안전
        subprocess.run(["psql", _psql_url(TEST_URL), "-X", "-q", "-v", "ON_ERROR_STOP=1",
                        "-f", str(ROOT / "seeds" / "navigator_companies.sql")],
                       check=True, capture_output=True, env=env)
    seen = {}
    for brn in ("999-81-00015", "999-82-00026", "999-83-00038"):
        r = await client.get(f"/navigator/companies/{brn}")
        assert r.status_code == 200, r.text
        seen[brn] = r.json()
    assert [v["biz_verify_label"] for v in seen.values()] == ["확인됨", "확인됨", "미확인"]
    assert all(v["patents"] for v in seen.values())

    r = await client.post("/navigator/companies/999-82-00026/access-link")
    assert r.status_code == 202
    p = (await client.get("/navigator/manage/profile",
                          headers=_manage(_token_from_last_mail("rnd@nuri.example")))).json()
    rev = next(f for f in p["field_sources"] if f["field_name"] == "annual_revenue_krw")
    assert rev["differs"] and rev["preferred_value"] == 119_800_000_000   # 외부(DART 목업) 확인값을 앞에
    assert any(c["cert_type_code"] == "DEFENSE_COMPANY" for c in p["certifications"])
