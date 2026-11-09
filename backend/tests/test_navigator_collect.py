"""Navigator 외부 수집 테스트 (mock 연결 부품)."""
import psycopg
import pytest

from app.config import get_settings
from app.services import collector
from app.services.external import nts
from app.services.ratelimit import limiter
from tests.conftest import TEST_URL, as_user
from tests.test_navigator_matching import _seed

PLANNER, VIEWER = 1, 5
HANBIT, NURI, SAEBOM = 101, 102, 103


@pytest.fixture(autouse=True)
def _fresh():
    limiter.reset()
    _seed()
    yield


def _q(sql: str, *args):
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        cur = conn.execute(sql, args)
        return cur.fetchall() if cur.description else []


async def _run(client, code: str, **params):
    r = await client.post(f"/navigator/sources/{code}/run", params=params, headers=as_user(PLANNER))
    assert r.status_code == 200, r.text
    return r.json()


async def test_nts_status_recheck(client, monkeypatch):
    r = await _run(client, "NTS_BIZ")
    assert r["status"] == "SUCCEEDED" and r["mode"] == "mock" and r["counts"]["records"] >= 3
    assert r["counts"].get("not_found", 0) >= 1                       # 새봄은 등록부에 없음
    rows = _q("""SELECT organization_id, value, is_verified FROM ax.company_field_source f
                  JOIN ax.external_source s ON s.id = f.external_source_id
                 WHERE s.code = 'NTS_BIZ' AND field_name = 'business_status' AND organization_id IN (101, 102)""")
    assert {(o, v, ok) for o, v, ok in rows} == {(HANBIT, "ACTIVE", True), (NURI, "ACTIVE", True)}

    # 누리가 폐업으로 바뀌면 프로필에 반영
    real = nts.MockNtsConnector.status
    monkeypatch.setattr(nts.MockNtsConnector, "status", lambda self, b: [
        {**x, "b_stt_cd": "03"} if x["b_no"] == "9998200026" else x for x in real(self, b)])
    r = await _run(client, "NTS_BIZ", organization_id=NURI)
    assert r["counts"] == {"records": 1, "changed": 1}
    assert _q("SELECT business_status FROM ax.company_profile WHERE organization_id = 102")[0][0] == "CLOSED"


async def test_kipris_patents(client):
    r = await _run(client, "KIPRIS")
    assert r["status"] == "SUCCEEDED", r
    assert r["counts"]["inserted"] == 1 and r["counts"]["updated"] == 3, r["counts"]   # 한빛 새 특허 1, 기존 3건 확인
    rows = _q("SELECT application_no, origin, verified_at IS NOT NULL FROM ax.company_patent "
              "WHERE organization_id = 101 ORDER BY application_no")
    assert len(rows) == 3 and all(o == "EXTERNAL" and v for _, o, v in rows)
    assert _q("""SELECT e.external_id FROM ax.company_external_id e JOIN ax.external_source s ON s.id = e.source_id
                  WHERE e.organization_id = 101 AND s.code = 'KIPRIS'""")[0][0] == "119990000151"
    # 누리 특허 중 KIPRIS 에 없는 것은 자가입력 그대로
    assert ("SELF",) in _q("SELECT origin FROM ax.company_patent WHERE organization_id = 102")

    again = await _run(client, "KIPRIS")
    assert "inserted" not in again["counts"] and "updated" not in again["counts"]     # 바뀐 것 없음

    # 기업 화면에도 외부 확인으로 보임
    prof = (await client.get(f"/navigator/matching/companies/{HANBIT}/profile", headers=as_user(PLANNER))).json()
    assert len(prof["patents"]) == 3 and all(p["origin"] == "EXTERNAL" for p in prof["patents"])


async def test_dart_financials(client):
    r = await _run(client, "DART", organization_id=NURI)
    assert r["status"] == "SUCCEEDED" and r["counts"] == {"records": 1, "updated": 1}
    rows = dict(_q("""SELECT field_name, preferred_value FROM ax.v_company_field_compare
                       WHERE organization_id = 102 AND field_name IN ('employee_count', 'annual_revenue_krw')"""))
    assert rows == {"employee_count": 318, "annual_revenue_krw": 119800000000}
    r = await _run(client, "DART", organization_id=SAEBOM)
    assert r["status"] == "SUCCEEDED" and r["counts"] == {"not_found": 1}               # 외감 대상 아님


async def test_bizinfo_announcements(client):
    _q("DELETE FROM ax.announcement WHERE announcement_no LIKE 'BIZINFO-%%'")
    r = await _run(client, "BIZINFO")
    assert r["counts"] == {"records": 2, "inserted": 2, "skipped": 1}, r
    rows = _q("SELECT announcement_no, status, source_kind, source_url IS NOT NULL FROM ax.announcement "
              "WHERE announcement_no LIKE 'BIZINFO-%%' ORDER BY 1")
    assert [x[0] for x in rows] == ["BIZINFO-PBLN_MOCK_0001", "BIZINFO-PBLN_MOCK_0002"]
    assert all(s == "DRAFT" and k == "EXTERNAL" and u for _, s, k, u in rows)
    again = await _run(client, "BIZINFO")
    assert "inserted" not in again["counts"] and "updated" not in again["counts"]
    # 작성중이라 공개 목록에는 없음
    pub = (await client.get("/navigator/announcements", params={"q": "부품국산화 개발지원 사업"})).json()
    assert not any(a["announcement_no"].startswith("BIZINFO-") for a in pub)
    assert (await client.post("/navigator/sources/BIZINFO/run", params={"organization_id": HANBIT},
                              headers=as_user(PLANNER))).status_code == 422


async def test_live_without_key_fails_and_is_recorded(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "source_kipris", "live")
    monkeypatch.setattr(get_settings(), "kipris_access_key", None)
    r = await _run(client, "KIPRIS")
    assert r["status"] == "FAILED" and "KIPRIS_ACCESS_KEY" in r["error"] and r["mode"] == "live"
    jobs = (await client.get("/navigator/sources/jobs", params={"source": "KIPRIS", "limit": 1},
                             headers=as_user(PLANNER))).json()
    assert jobs[0]["status"] == "FAILED" and jobs[0]["mode"] == "LIVE"


async def test_registration_with_live_nts_without_key_is_unverified(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "source_nts_biz", "live")
    monkeypatch.setattr(get_settings(), "nts_service_key", None)
    _q("DELETE FROM ax.organization WHERE business_reg_no = '9998400049'")
    r = await client.post("/navigator/companies", json={
        "business_reg_no": "999-84-00049", "company_name": "(가상)길동정밀", "representative_name": "홍길동",
        "opened_on": "2019-03-01", "email": "me@gildong.example"})
    assert r.status_code == 201, r.text
    assert r.json()["biz_verify_label"] == "미확인" and "NTS_SERVICE_KEY" in r.json()["message"]


async def test_due_sources_and_overview(client):
    _q("DELETE FROM ax.external_fetch_job WHERE trigger_kind = 'SCHEDULED'")
    first = await collector.run_due()
    assert {r["source"] for r in first} == {"NTS_BIZ", "KIPRIS", "DART", "BIZINFO"}
    assert all(r["status"] == "SUCCEEDED" for r in first)
    assert await collector.run_due() == []                                  # 주기 안에는 다시 안 돎

    ov = (await client.get("/navigator/sources", headers=as_user(PLANNER))).json()
    by = {s["code"]: s for s in ov}
    assert by["KIPRIS"]["implemented"] and by["KIPRIS"]["mode"] == "mock" and by["KIPRIS"]["next_due_at"]
    assert not by["NICE"]["implemented"] and by["NICE"]["mode"] is None
    assert (await client.post("/navigator/sources/NICE/run", headers=as_user(PLANNER))).status_code == 404


async def test_staff_only_and_external_id(client):
    assert (await client.get("/navigator/sources")).status_code == 401
    assert (await client.post("/navigator/sources/KIPRIS/run", headers=as_user(VIEWER))).status_code == 403
    r = await client.put(f"/navigator/sources/companies/{SAEBOM}/external-ids/dart", headers=as_user(PLANNER),
                         json={"external_id": "99900038"})
    assert r.status_code == 204
    ids = (await client.get(f"/navigator/sources/companies/{SAEBOM}/external-ids", headers=as_user(PLANNER))).json()
    assert ids == [{"source": "DART", "external_id": "99900038", "set_by": "STAFF", "updated_at": ids[0]["updated_at"]}]
    r = await _run(client, "DART", organization_id=SAEBOM)
    assert r["counts"] == {"not_found": 1}                                   # 목업에 없는 고유번호


# live 연결 부품의 응답 해석 (네트워크 없이, 공개 문서의 응답 모양으로)

def test_live_parsers(monkeypatch):
    import io
    import zipfile

    from app.services.external import bizinfo, dart, kipris

    calls = []

    def fake_post(url, body, params=None):
        calls.append(url)
        if url.endswith("/validate"):
            return {"data": [{"b_no": body["businesses"][0]["b_no"], "valid": "02"}]}
        return {"data": [{"b_no": b, "b_stt_cd": "01" if b == "1234567890" else ""} for b in body["b_no"]]}
    monkeypatch.setattr(nts, "http_post_json", fake_post)
    live = nts.LiveNtsConnector("k")
    from datetime import date
    assert live.verify("1234567890", "가", date(2020, 1, 1)).verify_status == "FAILED"     # 번호는 있음
    assert live.verify("1111111111", "가", date(2020, 1, 1)).verify_status == "UNVERIFIED"
    assert len(live.status([str(i).zfill(10) for i in range(150)])) == 150 and calls[-2:] == [
        f"{nts.LIVE_BASE}/status"] * 2                                                       # 100건씩 나눠 호출

    xml = """<response><body><items>
      <item><applicationNumber>1020240031877</applicationNumber><inventionTitle>적응형 변조 장치</inventionTitle>
        <ipcNumber>H04L 1/00|H04B 7/185</ipcNumber><registerStatus>등록</registerStatus><registerNumber>1023456780000</registerNumber>
        <applicationDate>20240308</applicationDate><registerDate>20250601</registerDate><applicantName>주식회사 한빛전자통신</applicantName></item>
      <item><applicationNumber>1020230000001</applicationNumber><inventionTitle>다른 회사</inventionTitle>
        <ipcNumber>G06N 3/08</ipcNumber><registerStatus>공개</registerStatus><applicantName>한빛전자통신연구소</applicantName></item>
    </items></body></response>"""
    monkeypatch.setattr(kipris, "http_get_text", lambda url, params=None: xml)
    ps = kipris.LiveKiprisConnector("k").patents("(주)한빛전자통신", "9998100015")
    assert [(p.application_no, p.status, p.ipc_codes) for p in ps] == [
        ("10-2024-0031877", "REGISTERED", ["H04L 1/00", "H04B 7/185"])]                     # 이름이 다른 출원인 제외

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CORPCODE.xml", "<result><list><corp_code>00000001</corp_code><corp_name>누리복합소재(주)</corp_name></list>"
                                   "<list><corp_code>00000002</corp_code><corp_name>누리복합소재</corp_name></list></result>")
    monkeypatch.setattr(dart, "http_get_bytes", lambda url, params=None: buf.getvalue())

    def fake_get(url, params=None):
        if url.endswith("company.json"):
            return {"status": "000", "bizr_no": "999-82-00026" if params["corp_code"] == "00000002" else "1"}
        if url.endswith("fnlttSinglAcnt.json"):
            return {"status": "000", "list": [
                {"fs_div": "OFS", "account_nm": "매출액", "thstrm_amount": "100"},
                {"fs_div": "CFS", "account_nm": "매출액", "thstrm_amount": "119,800,000,000"}]}
        return {"status": "000", "list": [{"sm": "300"}, {"sm": "18"}]}
    monkeypatch.setattr(dart, "http_get_json", fake_get)
    d = dart.LiveDartConnector("k")
    assert d.find_corp_code("(가상)누리복합소재", "9998200026") == "00000002"              # 사업자번호로 동명 구분
    fin = d.financials("00000002", 2025)
    assert (fin.revenue_krw, fin.employee_count) == (119_800_000_000, 318)                   # 연결 재무 우선

    monkeypatch.setattr(bizinfo, "http_get_json", lambda url, params=None: {"jsonArray": [
        {"pblancId": "P1", "pblancNm": "국방 과제", "jrsdInsttNm": "방사청", "reqstBeginEndDe": "2026-12-01 ~ 2027-01-15",
         "bsnsSumryCn": "<p>요약</p>"}]})
    a = bizinfo.LiveBizinfoConnector("k").announcements()[0]
    assert (a.receipt_start.isoformat(), a.receipt_end.isoformat(), a.summary) == ("2026-12-01", "2027-01-15", "요약")


def test_bizinfo_keyword_filter():
    from app.services.external.bizinfo import _record, matches_keywords

    kw = [k.strip() for k in get_settings().navigator_announcement_keywords.split(",")]
    hit = _record({"pblancId": "A", "pblancNm": "2026년 방위산업 육성 기술협업 프로그램 참가기업 모집"})
    miss = _record({"pblancId": "B", "pblancNm": "[경남] 밀양시 2026년 2차 주방위생환경개선 사업 모집 공고"})
    assert matches_keywords(hit, kw) and not matches_keywords(miss, kw)
