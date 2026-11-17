"""담당자 공고 등록·지원 조건 확인 (규칙 추출, LLM 응답 검사, 저장)."""
import json

import psycopg
import pytest

from app.config import get_settings
from app.services import requirement_extract as rx
from app.services.llm import LLMError
from tests.conftest import TEST_URL, as_user

PLANNER, VIEWER = 1, 5

NOTICE = """’26-9차 방산 부품 시험평가 지원사업 참여기업 모집 공고
사업 개요
가. 사업목적 : 방산 중소기업의 부품 시험평가 비용을 지원하여 군 납품 기반을 넓힌다
나. 지원범위 : 기업당 최대 5,000만원 (총 예산 3억원)
다. 사업기간 : 협약 체결 후 12개월
신청자격
방위산업 분야 부품을 연구개발 또는 생산하는 중소기업으로서 기업부설연구소 또는 연구개발전담부서를 보유한 기업
기업신용등급 B 이상
신청제한
1. 국세·지방세 체납 중인 기업
2. 부도 또는 휴·폐업 중인 기업
3. 국가연구개발사업 참여제한 중인 기업
우대사항
- 관련 분야 특허 보유 기업
- 최근 1년 수출 실적 보유 기업
신청기간 : ’26. 11. 16.(월) ~ 11. 27.(금) 17:00
"""


def test_rules_extract_common_requirements():
    ex = rx.extract_rules(NOTICE)
    got = {s.req_type_code: (s.rule, s.is_mandatory) for s in ex.requirements}
    assert got["COMPANY_SIZE"] == ({"allowed": ["SME", "STARTUP", "VENTURE"]}, True)
    assert got["REQUIRED_CERT"] == ({"any_of": ["RND_LAB", "RND_DEPT"]}, True)
    assert got["MIN_CREDIT_GRADE"] == ({"min_grade": "B"}, True)
    assert got["BUSINESS_STATUS"] == ({"allowed": ["ACTIVE"]}, True)
    assert got["NO_DISQUALIFICATION"] == ({"checks": ["TAX_DELINQUENT", "INSOLVENT", "RND_RESTRICTED"]}, True)
    assert got["PATENT"][1] is False and got["EXPORT"][1] is False
    assert [s.is_mandatory for s in ex.requirements] == sorted([s.is_mandatory for s in ex.requirements], reverse=True)
    assert ex.fields["receipt_start"] == "2026-11-16" and ex.fields["receipt_end"] == "2026-11-27"
    assert ex.fields["support_amount_krw"] == 50_000_000          # 총 예산 3억은 아님
    assert ex.fields["support_period_months"] == 12
    assert ex.fields["target_desc"].startswith("방위산업 분야 부품을")
    assert ex.fields["summary"].startswith("방산 중소기업의 부품")
    assert all(s.source_quote and s.source_quote in NOTICE for s in ex.requirements)


def test_rules_extract_inline_headings():
    """'2. 지원대상: 중소기업 ...' 처럼 제목과 내용이 한 줄인 공고문."""
    text = ("1. 사업목적: 수입에 의존하는 전술 데이터링크 모뎀과 RF 모듈의 국산화\n"
            "2. 지원대상: 중소기업 (기업부설연구소 또는 연구개발전담부서 보유)\n"
            "3. 지원내용: 과제당 최대 5억원, 지원기간 24개월\n"
            "4. 요구기술: 항재밍 데이터링크 모뎀, 전술 무전기 RF 모듈\n"
            "5. 문의처: 연구소 기업부설연구소 담당 042-000-0000\n")
    ex = rx.extract_rules(text)
    got = {s.req_type_code: s for s in ex.requirements}
    assert got["COMPANY_SIZE"].rule == {"allowed": ["SME", "STARTUP", "VENTURE"]}
    assert got["REQUIRED_CERT"].rule == {"any_of": ["RND_LAB", "RND_DEPT"]} and got["REQUIRED_CERT"].is_mandatory
    assert ex.fields["target_desc"] == "중소기업 (기업부설연구소 또는 연구개발전담부서 보유)"
    assert ex.fields["summary"].startswith("수입에 의존하는")
    assert [t["tech_name"] for t in ex.tech_needs] == ["항재밍 데이터링크 모뎀", "전술 무전기 RF 모듈"]
    assert ex.tech_needs[0]["is_core"] and not ex.tech_needs[1]["is_core"]


@pytest.mark.parametrize("s,expected", [("최대 5,000만원", [50_000_000]), ("3천만 원 한도", [30_000_000]),
                                        ("1.5억원", [150_000_000]), ("757,000원", [])])
def test_parse_krw(s, expected):
    assert rx.parse_krw(s) == expected


def test_llm_answer_checked_against_rule_models():
    answer = {"fields": {"receipt_end": "2026-11-27", "support_amount_krw": 50000000, "summary": "부품 시험평가 지원"},
              "requirements": [
                  {"req_type_code": "COMPANY_SIZE", "rule": {"allowed": ["SME"]}, "is_mandatory": True,
                   "description": "중소기업이어야 한다.", "source_quote": "생산하는 중소기업으로서"},
                  {"req_type_code": "MIN_CREDIT_GRADE", "rule": {"grade": "B"}, "is_mandatory": True,
                   "description": "신용등급 B 이상", "source_quote": "기업신용등급 B 이상"},
                  {"req_type_code": "REQUIRED_CERT", "rule": {"any_of": ["NOPE"]}, "is_mandatory": True,
                   "description": "없는 인증", "source_quote": "지어낸 문장"},
              ],
              "tech_needs": [{"tech_name": "환경시험", "is_core": True}]}
    raw = "```json\n" + json.dumps(answer, ensure_ascii=False) + "\n```"
    ex = rx.parse_llm_answer(raw, NOTICE, {"RND_LAB", "RND_DEPT"}, "llm:test")
    assert [(s.req_type_code, s.quote_found) for s in ex.requirements] == [
        ("COMPANY_SIZE", True), ("OTHER", True), ("OTHER", False)]
    assert ex.requirements[0].description == "중소기업이어야 한다"     # 목록으로 이을 때 "한다., " 안 생기게
    assert ex.fields == {"receipt_end": "2026-11-27", "support_amount_krw": 50000000, "summary": "부품 시험평가 지원"}
    assert ex.tech_needs[0]["tech_name"] == "환경시험"
    assert len(ex.warnings) == 3     # 형식 2건 + 근거 못 찾음 1건


class _Fake:
    name = "fake/model"

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, 0

    async def complete(self, system, user):
        self.calls += 1
        if self.error:
            raise self.error
        assert "공고문:" in user and "COMPANY_SIZE" in user
        return self.reply


async def test_extract_llm_then_fallback():
    codes = [{"code": "COMPANY_SIZE", "name_ko": "기업규모", "rule_example": {"allowed": ["SME"]}, "description": ""}]
    ok = _Fake(json.dumps({"requirements": [], "fields": {}}))
    ex = await rx.extract(NOTICE, None, get_settings(), codes, [], client=ok)
    assert ex.extractor == "llm:fake/model" and ex.fields["receipt_end"] == "2026-11-27"   # 비면 규칙으로 채움
    bad = _Fake(error=LLMError("429"))
    ex = await rx.extract(NOTICE, None, get_settings(), codes, [], client=bad)
    assert ex.extractor == "rules" and "AI 추출에 실패" in ex.warnings[0] and ex.requirements


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@pytest.fixture
def clean(database, monkeypatch):
    monkeypatch.setattr(get_settings(), "requirement_extractor", "rules")
    yield
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute("DELETE FROM ax.announcement WHERE announcement_no LIKE 'TXT-%%'")


async def test_register_extract_review_publish(client, clean):
    r = await client.post("/navigator/announcements/text", headers=as_user(PLANNER), json={
        "announcement_no": "TXT-1", "title": "방산 부품 시험평가 지원사업", "body_text": NOTICE})
    assert r.status_code == 201, r.text
    ann = r.json()["id"]
    dup = await client.post("/navigator/announcements/text", headers=as_user(PLANNER), json={
        "announcement_no": "TXT-1", "title": "x", "body_text": NOTICE})
    assert dup.status_code == 409
    assert (await client.post("/navigator/announcements/text", headers=as_user(VIEWER), json={
        "title": "x", "body_text": NOTICE})).status_code == 403

    src = (await client.get(f"/navigator/announcements/{ann}/source", headers=as_user(PLANNER))).json()
    assert src["body_text"] == NOTICE and src["attachments"] == []

    ex = (await client.post(f"/navigator/announcements/{ann}/extract", headers=as_user(PLANNER))).json()
    assert ex["extractor"] == "rules" and len(ex["requirements"]) == 7

    pending = (await client.get("/navigator/announcements", headers=as_user(PLANNER),
                                params={"review": "PENDING", "q": "시험평가"})).json()
    assert [a["id"] for a in pending] == [ann]

    reqs = [{k: s[k] for k in ("req_type_code", "rule", "is_mandatory", "description", "source_quote")}
            | {"origin": "AI_EXTRACTED"} for s in ex["requirements"]]
    no_req = await client.put(f"/navigator/announcements/{ann}/review", headers=as_user(PLANNER),
                              json={"requirements": [], "publish": True})
    assert no_req.status_code == 422
    r = await client.put(f"/navigator/announcements/{ann}/review", headers=as_user(PLANNER), json={
        "fields": ex["fields"], "requirements": reqs, "tech_needs": [{"tech_name": "환경시험"}], "publish": True})
    assert r.status_code == 204, r.text

    a = (await client.get(f"/navigator/announcements/{ann}")).json()     # 공개됐으니 로그인 없이 보임
    assert a["status"] == "PUBLISHED" and a["support_amount_krw"] == 50_000_000 and "body_text" not in a
    assert len(a["requirements"]) == 7 and {x["origin"] for x in a["requirements"]} == {"AI_EXTRACTED"}
    assert a["requirements_confirmed_at"] and a["tech_need_count"] == 1
    done = (await client.get("/navigator/announcements", headers=as_user(PLANNER),
                             params={"review": "DONE", "q": "시험평가"})).json()
    assert [x["id"] for x in done] == [ann]

    # 다시 저장하면 통째로 바뀜
    r = await client.put(f"/navigator/announcements/{ann}/review", headers=as_user(PLANNER),
                         json={"requirements": reqs[:2], "confirm": False})
    assert r.status_code == 204
    a = (await client.get(f"/navigator/announcements/{ann}")).json()
    assert len(a["requirements"]) == 2 and a["tech_need_count"] == 0


async def test_requirement_types(client, database):
    r = await client.get("/navigator/announcements/requirement-types", headers=as_user(PLANNER))
    assert r.status_code == 200
    body = r.json()
    assert {"COMPANY_SIZE", "NO_DISQUALIFICATION", "OTHER"} <= {t["code"] for t in body["types"]}
    assert any(c["code"] == "RND_LAB" for c in body["certifications"])
    assert (await client.get("/navigator/announcements/requirement-types")).status_code == 401


@pytest.mark.parametrize("text,absent,present", [
    # 국방벤처센터 공고: 연구소는 소재지 설명이지 인증 조건이 아님
    ("○ 모집대상 : 경기도에 소재(본사, 기업부설연구소, 공장 또는 사업장)한 중소·벤처기업", {"REQUIRED_CERT"},
     {"COMPANY_SIZE", "REGION"}),
    # 제출서류 설명의 '설립 2년 이내' 는 업력 조건이 아님
    ("2. 신청자격\n- 중소기업\n* 재무제표 제출이 제한될 경우(법인 설립 2년 이내 등) 회계감사보고서로 대체 가능",
     {"BUSINESS_AGE"}, {"COMPANY_SIZE"}),
    # 대기업까지 모두 되면 규모 조건 없음
    ("○ 신청자격 : 대기업 · 스타트업 · 중소기업 모두 포함", {"COMPANY_SIZE"}, set()),
    ("가. 신청자격 : 국내 全 중소ㆍ벤처기업이 개발한 제품(기술)", set(), {"COMPANY_SIZE"}),
])
def test_rules_real_notice_lines(text, absent, present):
    codes = {s.req_type_code for s in rx.extract_rules(text).requirements}
    assert not (codes & absent) and present <= codes, codes


@pytest.mark.parametrize("text,target", [
    ("다. 지원대상 : 국내 중소ㆍ중견기업\n지원대상 지원항목\n1. 사전 해외 바이어 정보제공, 온라인 상담", "국내 중소ㆍ중견기업"),
    ("○ 참여대상 : 산·학·연·공공기관 및 군 관련기관\n○ 접수방법 (2가지 중 택1)", "산·학·연·공공기관 및 군 관련기관"),
    ("○ 신청자격 및 신청서류 : 세부 내용은 첨부 파일 참조\n[첨부: 공고.hwp]\n가. 신청자격 : 중소ㆍ중견기업", "중소ㆍ중견기업"),
])
def test_target_desc_real_notices(text, target):
    assert rx.extract_fields(text)["target_desc"] == target
