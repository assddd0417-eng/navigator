"""상담결과서 PDF 내려받기: 화면과 같은 내용, 담당자·기업 판본, 권한."""
import io
import re
from datetime import date, timedelta
from urllib.parse import unquote

import pdfplumber
import psycopg
import pytest

from app.services import report_pdf
from app.services.ratelimit import limiter
from tests.conftest import TEST_URL, as_user, manage_token

BRN = "9998700147"
NAME = "(가상)결과서테크"


def _text(pdf: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return "\n".join(p.extract_text() or "" for p in doc.pages)


def _flat(s: str) -> str:
    return re.sub(r"\s+", "", s)


@pytest.fixture
async def consult(client):
    limiter.reset()
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))
        c.execute("DELETE FROM ax.announcement WHERE announcement_no LIKE 'RP-%%'")
    r = await client.post("/navigator/companies", json={
        "business_reg_no": BRN, "company_name": NAME, "representative_name": "김가상",
        "opened_on": "2016-04-01", "email": f"{BRN}@example.com", "main_business": "레이더 부품"})
    assert r.status_code == 201, r.text
    h = {"X-Manage-Token": await manage_token(client, BRN)}
    assert (await client.patch("/navigator/manage/profile", headers=h, json={"company_size": "SME"})).status_code == 200
    r = await client.post("/navigator/announcements", headers=as_user(1), json={
        "announcement_no": "RP-1", "title": "결과서 시험 공고(가상)", "agency_name": "(가상)기관", "summary": "방산 진입",
        "receipt_end": (date.today() + timedelta(days=20)).isoformat(),
        "requirements": [{"req_type_code": "COMPANY_SIZE", "rule": {"allowed": ["SME"]}, "description": "중소기업"}]})
    assert r.status_code == 201, r.text
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        org = c.execute("SELECT id FROM ax.organization WHERE business_reg_no = %s", (BRN,)).fetchone()[0]
    r = await client.post(f"/navigator/consult/companies/{org}/consultations", headers=as_user(1),
                          json={"task": "C", "concern": "품질체계 구축과 수요처 확보"})
    assert r.status_code == 201, r.text
    yield org, r.json(), h
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))
        c.execute("DELETE FROM ax.announcement WHERE announcement_no LIKE 'RP-%%'")


async def test_staff_pdf_matches_screen(client, consult):
    org, c, _ = consult
    cid = c["id"]
    edited = "담당자가 고친 의견\n둘째 줄: 품질 보통 · 41%"
    r = await client.put(f"/navigator/consult/consultations/{cid}", headers=as_user(1),
                         json={"report": {"opinion": edited}})
    assert r.status_code == 200, r.text
    c = r.json()

    r = await client.get(f"/navigator/consult/consultations/{cid}/report.pdf", headers=as_user(1))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert unquote(r.headers["content-disposition"].split("UTF-8''")[1]).startswith(f"상담결과서_{NAME}_")
    text = _flat(_text(r.content))
    assert _flat(f"{NAME} 상담결과서") in text and _flat(c["task_label"]) in text and "검토중" in text
    for s in c["report"]:                         # 결과서 항목 제목·문장이 화면과 같다 (점수 병기 그대로)
        assert _flat(s["title"]) in text and _flat(s["text"]) in text, s["key"]
    assert "41%" in text
    assert _flat("상담 내용: 품질체계 구축과 수요처 확보") in text

    # 열람 권한·역할
    assert (await client.get(f"/navigator/consult/consultations/{cid}/report.pdf", headers=as_user(2))).status_code == 403
    assert (await client.get("/navigator/consult/consultations/999999/report.pdf", headers=as_user(1))).status_code in (403, 404)


async def test_company_pdf_matches_company_view(client, consult):
    org, c, h = consult
    cid = c["id"]
    # 확정 전에는 기업 판본 없음
    assert (await client.get(f"/navigator/manage/consultations/{cid}/report.pdf", headers=h)).status_code == 404
    assert (await client.post(f"/navigator/consult/consultations/{cid}/confirm", headers=as_user(1),
                              json={"notify": False})).status_code == 200
    view = next(x for x in (await client.get("/navigator/manage/consultations", headers=h)).json()["consultations"]
                if x["id"] == cid)
    r = await client.get(f"/navigator/manage/consultations/{cid}/report.pdf", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    text = _flat(_text(r.content))
    assert _flat(f"{view['task_label']} 상담 결과") in text and _flat(f"상태유형 {view['state_label']}") in text
    for s in view["report"]:
        assert _flat(s["title"]) in text and _flat(s["text"]) in text, s["key"]
    for a in view["announcements"]:
        assert _flat(a["q1_label"]) in text
    for st in view["steps"]:
        assert _flat(f"{st['horizon']} · {st['stage_label']}") in text
    assert not re.search(r"\d+점", text)          # 기업 판본은 점수 없이 라벨만

    # 관리 링크 없이, 다른 상담 번호로는 못 받는다
    assert (await client.get(f"/navigator/manage/consultations/{cid}/report.pdf")).status_code in (401, 403)
    assert (await client.get("/navigator/manage/consultations/999999/report.pdf", headers=h)).status_code == 404


def test_korean_font_embedded():
    reg, _ = report_pdf.fonts()
    pdf = report_pdf.company_pdf("(가상)글꼴", {
        "task_label": "D-STATE 진단", "confirmed_at": "2026-11-23T09:57:00+00:00", "state_label": "방산진입 준비기업",
        "report": [{"key": "overview", "title": "기업 개요", "text": "한글 문장 확인"}], "announcements": [], "steps": []})
    assert "한글문장확인" in _flat(_text(pdf))
    assert report_pdf.fmt_date("2026-11-23T09:57:00+00:00") == "26. 11. 23. 오후 6:57"
    if reg == report_pdf.FONT:
        assert b"NavKR" in pdf or b"FontFile2" in pdf    # TTF 를 넣었다 (뷰어 글꼴에 기대지 않음)
