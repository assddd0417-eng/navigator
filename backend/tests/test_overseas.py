"""해외 수요: 정리 엑셀 올리기 · 출처 규칙 · 보안등급 · 국내 성과 검색."""
import io

from openpyxl import Workbook

from tests.conftest import ROOT, as_user

PLANNER, REVIEWER, EXPERT, CURATOR, VIEWER = 1, 2, 3, 4, 5
SEED_XLSX = ROOT / "seeds" / "overseas" / "전차파워팩_해외수요.xlsx"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

SOURCE_HEAD = ["출처 번호", "발행 기관", "문서 제목", "발행일", "URL", "자료 종류", "이용 조건", "원문 저장 허용", "확인한 날", "비고"]
DEMAND_HEAD = ["수요 번호", "출처 번호", "국가/기관", "수요 제목", "기술분류", "무기체계/품목", "요구 성능", "목표 시기",
               "수요 종류", "원문 인용", "확신도", "메모"]


def _xlsx(sources: list[list], demands: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "출처"
    ws.append(SOURCE_HEAD)
    for r in sources:
        ws.append(r)
    ws2 = wb.create_sheet("해외수요")
    ws2.append(DEMAND_HEAD)
    for r in demands:
        ws2.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _upload(client, data: bytes, user=PLANNER, dry_run=False):
    return await client.post(f"/overseas/import?dry_run={'true' if dry_run else 'false'}", headers=as_user(user),
                             files={"file": ("해외수요.xlsx", data, XLSX)})


async def _count(client) -> int:
    return len((await client.get("/overseas/demands", headers=as_user(PLANNER))).json())


async def test_import_dry_run_saves_nothing(client):
    r = await _upload(client, SEED_XLSX.read_bytes(), dry_run=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True and body["sources_created"] == 9 and body["demands_created"] == 9
    assert await _count(client) == 0


async def test_import_seed_workbook(client):
    r = await _upload(client, SEED_XLSX.read_bytes())
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["sources_created"], body["demands_created"]) == (9, 9)
    assert body["embedded"] > 0

    demands = (await client.get("/overseas/demands", headers=as_user(VIEWER))).json()  # 공개자료라 열람자도 본다
    assert len(demands) == 9
    d06 = next(d for d in demands if d["demand_no"] == "D06")
    assert d06["demand_kind"] == "EXPORT_REQ" and d06["source_nos"][0] == "S4"

    detail = (await client.get(f"/overseas/demands/{d06['id']}", headers=as_user(VIEWER))).json()
    assert [s["is_primary"] for s in detail["sources"]].count(True) == 1
    assert all(s["url"].startswith("https://") and s["license_note"] for s in detail["sources"])

    sources = (await client.get("/overseas/sources", headers=as_user(PLANNER))).json()
    assert {s["source_no"] for s in sources} == {f"S{i}" for i in range(1, 10)}

    # 다시 올리면 갱신 (중복 생성 없음)
    again = (await _upload(client, SEED_XLSX.read_bytes())).json()
    assert (again["sources_updated"], again["demands_updated"], again["demands_created"]) == (9, 9, 0)
    assert again["embedded"] == 0  # 내용이 같으면 다시 임베딩하지 않는다


async def test_import_rejects_bad_rows_atomically(client):
    before = await _count(client)
    data = _xlsx(
        [["X1", "어느 기관", "제목", "2025", "ftp://bad", "해외 공모", "", "예", "2026-11-09", None],
         ["X2", "어느 기관", "제목", "2025", "https://example.org/a", "해외 공모", "표시 없음", "아니오", "어제", None]],
        [["XD1", "X9", "EU", "제목", "", "", "요구", "", "공모", "", "보통", ""],
         ["XD2", "X2", "EU", "제목", "", "", "", "", "기타", "", "아주높음", ""]])
    r = await _upload(client, data)
    assert r.status_code == 422
    errors = r.json()["detail"]["errors"]
    assert any("출처 2행" in e and "URL" in e and "이용 조건" in e for e in errors)
    assert any("출처 3행" in e and "확인한 날" in e for e in errors)
    assert any("해외수요 2행" in e and "X9" in e for e in errors)
    assert any("해외수요 3행" in e and "요구 성능" in e and "수요 종류" in e and "확신도" in e for e in errors)
    assert await _count(client) == before


async def test_import_requires_both_sheets_and_editor_role(client):
    wb = Workbook()
    wb.active.title = "다른시트"
    buf = io.BytesIO()
    wb.save(buf)
    r = await _upload(client, buf.getvalue())
    assert r.status_code == 422 and "'출처' 시트가 없습니다" in r.json()["detail"]["errors"]
    assert (await _upload(client, b"not an xlsx")).status_code == 422
    assert (await _upload(client, SEED_XLSX.read_bytes(), user=VIEWER)).status_code == 403
    assert (await _upload(client, SEED_XLSX.read_bytes(), user=REVIEWER)).status_code == 403


async def test_full_text_only_when_allowed(client):
    doc = await client.post("/documents", headers=as_user(CURATOR), json={
        "doc_type_code": "FINAL_REPORT", "title": "해외 공개 보고서", "source_system_code": "OVERSEAS_PUBLIC",
        "security_code": "PUBLIC", "chunks": [{"content": "공개 보고서 본문"}]})
    assert doc.status_code == 201, doc.text
    base = {"issuer": "기관", "title": "보고서", "url": "https://example.org/r", "source_kind": "ROADMAP",
            "license_note": "표시 없음", "checked_on": "2026-11-09", "document_id": doc.json()["id"]}
    r = await client.post("/overseas/sources", headers=as_user(PLANNER), json={**base, "source_no": "T1"})
    assert r.status_code == 422  # 원문 저장 허용 아님 → 원문 문서 연결 불가
    r = await client.post("/overseas/sources", headers=as_user(PLANNER),
                          json={**base, "source_no": "T1", "license_note": "CC BY 4.0", "allow_full_text": True})
    assert r.status_code == 201, r.text


async def test_demand_security_not_below_source(client):
    r = await client.post("/overseas/sources", headers=as_user(PLANNER), json={
        "source_no": "T2", "issuer": "기관", "title": "대외비 자료", "url": "https://example.org/x",
        "source_kind": "EXPORT_REQ", "license_note": "표시 없음", "checked_on": "2026-11-09",
        "security_code": "RESTRICTED"})
    assert r.status_code == 201
    demand = {"demand_no": "TD1", "title": "수요", "demand_kind": "EXPORT_REQ", "region": "어느 나라",
              "requirement": "요구", "source_nos": ["T2"]}
    r = await client.post("/overseas/demands", headers=as_user(PLANNER), json=demand)
    assert r.status_code == 422 and "보안등급" in r.json()["detail"]
    r = await client.post("/overseas/demands", headers=as_user(PLANNER), json={**demand, "security_code": "RESTRICTED"})
    assert r.status_code == 201
    # 공개 등급 열람자에게는 보이지 않는다
    assert all(d["demand_no"] != "TD1" for d in (await client.get("/overseas/demands", headers=as_user(VIEWER))).json())
    assert (await client.get(f"/overseas/demands/{r.json()['id']}", headers=as_user(VIEWER))).status_code == 404
    # 없는 출처 번호
    r = await client.post("/overseas/demands", headers=as_user(PLANNER), json={**demand, "demand_no": "TD2",
                                                                              "source_nos": ["없음"]})
    assert r.status_code == 422


async def test_similar_cards_finds_related_domestic_result(client):
    r = await client.post("/cards", headers=as_user(CURATOR), json={
        "card_no": "AC-OV-01", "project_id": 2, "title": "전차 파워팩 국산 자동변속기 내구도 개선",
        "core_achievement": "1,500마력급 전차 파워팩용 국산 자동변속기 내구도 시험 및 개선",
        "trl": 7, "technologies": [{"tech_name": "전차 파워팩 자동변속기", "is_primary": True}],
        "performances": [{"metric_name": "변속기 내구도 시험 시간", "target_value": 320, "achieved_value": 306,
                          "unit": "h", "is_achieved": False}]})
    assert r.status_code == 201, r.text
    card_id = r.json()["id"]
    assert (await client.post(f"/cards/{card_id}/publish", headers=as_user(CURATOR))).status_code == 204

    demands = (await client.get("/overseas/demands", headers=as_user(PLANNER))).json()
    d08 = next(d for d in demands if d["demand_no"] == "D08")  # 수출형 K2 파워팩 기준 제원
    hits = (await client.get(f"/overseas/demands/{d08['id']}/similar-cards?k=3", headers=as_user(PLANNER))).json()
    assert hits and hits[0]["card_id"] == card_id
    assert hits[0]["matched_facet"].count("→") == 1
    assert all(-1 <= h["similarity"] <= 1 for h in hits)


async def test_health_counts_overseas_vectors(client):
    emb = (await client.get("/health")).json()["embedding"]
    assert emb["overseas_demands_missing"] == 0
