"""기업 입력 확장: 제품·보유 기술·지원사업 이력, 증빙 업로드에서 값 뽑기."""
import io
import zipfile

import psycopg
import pytest

from app.services import company_evidence as ev
from app.services.ratelimit import limiter
from tests.conftest import TEST_URL, manage_token

BRN_A, BRN_B = "9998700002", "9998700017"

VENTURE = """벤처기업확인서
확인번호 : 제 20250301-0123 호
기업명 : (가상)새빛정밀
유효기간 : 2025. 3. 1. ~ 2028. 2. 28.
위 기업은 벤처기업육성에 관한 특별법에 따라 벤처기업임을 확인합니다."""
RND_LAB = """기업부설연구소 인정서
인정번호: 2023112345
연구소명 : 새빛정밀 기술연구소
인정일자 : 2023년 11월 2일
한국산업기술진흥협회장"""
CREDIT = """기업신용평가 등급확인서
평가기관 : NICE평가정보
신용등급 : BBB-
평가일 : 2026.04.10
유효기간 : 2026.04.10 ~ 2027.04.09"""


@pytest.mark.parametrize("text,kind,values", [
    (VENTURE, "CERTIFICATION", {"cert_type_code": "VENTURE", "cert_no": "20250301-0123",
                                "issued_on": "2025-03-01", "expires_on": "2028-02-28"}),
    (RND_LAB, "CERTIFICATION", {"cert_type_code": "RND_LAB", "cert_no": "2023112345", "issued_on": "2023-11-02"}),
    (CREDIT, "CREDIT_RATING", {"agency": "NICE", "grade": "BBB-", "rated_on": "2026-04-10",
                               "valid_until": "2027-04-09"}),
    ("회의록\n참석자 3명", "UNKNOWN", {}),
])
def test_detect(text, kind, values):
    d = ev.detect(text)
    assert d.kind == kind and d.values == values


def test_image_not_read():
    p = ev.parse("확인서.jpg", b"\xff\xd8\xff")
    assert p.status == "UNSUPPORTED" and "직접 입력" in p.note


def _hwpx(text: str) -> bytes:
    paras = "".join(f"<hp:p><hp:run><hp:t>{ln}</hp:t></hp:run></hp:p>" for ln in text.splitlines())
    sec = ('<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
           f'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">{paras}</hs:sec>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", sec)
    return buf.getvalue()


def _q(sql, *args):
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        cur = conn.execute(sql, args)
        return cur.fetchall() if cur.description else []


@pytest.fixture
def companies(database):
    limiter.reset()
    _q("DELETE FROM ax.organization WHERE business_reg_no IN (%s, %s)", BRN_A, BRN_B)
    yield
    _q("DELETE FROM ax.organization WHERE business_reg_no IN (%s, %s)", BRN_A, BRN_B)


async def _open(client, brn: str, name: str) -> dict:
    r = await client.post("/navigator/companies", json={
        "business_reg_no": brn, "company_name": name, "representative_name": "김가상", "opened_on": "2018-05-01",
        "email": f"{brn}@example.com", "main_business": "전술 통신 장비용 RF 부품"})
    assert r.status_code == 201, r.text
    token = await manage_token(client, brn)
    return {"X-Manage-Token": token}


async def test_products_technologies_support_history(client, companies):
    h = await _open(client, BRN_A, "(가상)새빛정밀")
    r = await client.patch("/navigator/manage/profile", headers=h, json={
        "products": [{"name": "Ku 밴드 저잡음 증폭기", "category": "COMPONENT", "is_defense": True,
                      "customers": "육군 전술통신 체계업체"}],
        "technologies": [{"tech_name": "GaN 고출력 증폭 설계", "trl": 6}],
        "support_history": [{"program_name": "방산 중소기업 컨설팅 지원사업", "agency": "국방기술진흥연구소",
                             "year": 2025, "result": "COMPLETED", "amount_krw": 22_000_000}],
    })
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["products"][0]["name"] == "Ku 밴드 저잡음 증폭기" and p["products"][0]["is_defense"]
    assert p["technologies"][0]["trl"] == 6 and p["technologies"][0]["origin"] == "SELF"
    assert p["support_history"][0]["result"] == "COMPLETED"
    org = p["organization_id"]
    facets = {(f, t) for f, t in _q("SELECT facet, source_table FROM ax.company_embedding WHERE organization_id = %s", org)}
    assert ("TECH", "company_product") in facets and ("TECH", "company_technology") in facets

    bad = await client.patch("/navigator/manage/profile", headers=h, json={"technologies": [{"tech_name": "x", "trl": 10}]})
    assert bad.status_code == 422
    # 목록을 보내면 직접 입력한 행만 통째로 바뀜
    r = await client.patch("/navigator/manage/profile", headers=h, json={"products": []})
    assert r.json()["products"] == [] and len(r.json()["technologies"]) == 1


async def test_evidence_upload_and_link(client, companies):
    h = await _open(client, BRN_A, "(가상)새빛정밀")
    other = await _open(client, BRN_B, "(가상)다른회사")
    r = await client.post("/navigator/manage/evidence", headers=h,
                          files={"file": ("벤처기업확인서.hwpx", _hwpx(VENTURE), "application/octet-stream")})
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["parse_status"] == "PARSED" and e["detected_kind"] == "CERTIFICATION"
    assert e["detected"]["cert_no"] == "20250301-0123" and "벤처기업확인서" in e["text_excerpt"]
    again = await client.post("/navigator/manage/evidence", headers=h,
                              files={"file": ("다시.hwpx", _hwpx(VENTURE), "application/octet-stream")})
    assert again.json()["id"] == e["id"]                          # 같은 파일은 한 번만

    photo = await client.post("/navigator/manage/evidence", headers=h, files={"file": ("인정서.png", b"\x89PNG", "image/png")})
    assert photo.status_code == 201 and photo.json()["parse_status"] == "UNSUPPORTED"
    assert (await client.post("/navigator/manage/evidence",
                              files={"file": ("a.pdf", b"%PDF", "application/pdf")})).status_code == 401

    cert = {**{k: e["detected"][k] for k in ("cert_type_code", "cert_no", "issued_on", "expires_on")},
            "company_evidence_id": e["id"]}
    p = (await client.patch("/navigator/manage/profile", headers=h, json={"certifications": [cert]})).json()
    assert p["certifications"][0]["company_evidence_id"] == e["id"]
    assert {x["id"] for x in p["evidence"]} == {e["id"], photo.json()["id"]}
    # 다른 회사 증빙 번호는 연결되지 않음
    q = (await client.patch("/navigator/manage/profile", headers=other, json={"certifications": [cert]})).json()
    assert q["certifications"][0]["company_evidence_id"] is None and q["evidence"] == []

    assert (await client.delete(f"/navigator/manage/evidence/{e['id']}", headers=other)).status_code == 404
    assert (await client.delete(f"/navigator/manage/evidence/{e['id']}", headers=h)).status_code == 204
    p = (await client.get("/navigator/manage/profile", headers=h)).json()
    assert p["certifications"][0]["company_evidence_id"] is None
