"""PDF·텍스트 파일 업로드: 추출·청킹 단위 테스트 + /documents/parse·/documents/upload API.

테스트 PDF 는 reportlab 으로 즉석 생성한다. 한국어는 reportlab 내장 CID 글꼴(HYSMyeongJo,
Adobe-Korea1)로 써서 글꼴 파일 없이도 실제 한글 PDF 와 같은 추출 경로를 탄다.
"""
import io

import pytest
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from app.services.document_parser import ParseError, _pack, _page_ranges, parse_upload
from tests.conftest import as_user

PLANNER, REVIEWER, EXPERT, CURATOR, VIEWER = 1, 2, 3, 4, 5
KO_FONT = "HYSMyeongJo-Medium"
pdfmetrics.registerFont(UnicodeCIDFont(KO_FONT))

PAGE1 = [
    "- 1 -",
    "4.3 미해결 기술 및 후속 연구 필요사항",
    "광대역 재밍 환경에서 주파수 도약 동기 유지 시간이 목표 10초 대비",
    "6초로 부족하여 후속 연구가 필요함.",
    "• 시험은 실내 전파차폐실과 야외 시험장에서 수행하였음",
]
PAGE3 = ["5. 결론", "항재밍 데이터링크 모뎀의 국산화 가능성을 확인하였으며 체계 적용 시험이 남아 있음."]


def make_pdf(pages: list[list[str]], encrypt: str | None = None) -> bytes:
    """pages: 쪽마다 줄 목록. 빈 목록은 텍스트 없는 쪽(스캔본 쪽 흉내)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, encrypt=encrypt)
    for lines in pages:
        if not lines:
            c.rect(72, 300, 400, 300, fill=1)  # 그림만 있는 쪽
        c.setFont(KO_FONT, 11)
        for i, line in enumerate(lines):
            c.drawString(72, 780 - 18 * i, line)
        c.showPage()
    c.save()
    return buf.getvalue()


def parse(data: bytes, name: str = "보고서.pdf", **kw):
    return parse_upload(data, name, max_pages=kw.get("max_pages", 100), chunk_max_chars=kw.get("chunk_max_chars", 1000))


# ---- 단위 --------------------------------------------------------------------
def test_korean_pdf_pages_and_paragraphs():
    doc = parse(make_pdf([PAGE1, [], PAGE3]))
    assert doc.file_type == "pdf" and doc.parser == "pdfplumber" and doc.page_count == 3
    assert doc.pages_without_text == [2] and "2쪽" in doc.warnings[0]
    p1 = [c for c in doc.chunks if c.page_start == 1]
    text1 = "\n".join(c.content for c in p1)
    assert "- 1 -" not in text1                                    # 쪽 번호 줄 제거
    assert "목표 10초 대비 6초로 부족하여" in text1                    # 시각적 줄바꿈은 이어 붙임
    assert "광대역 재밍 환경에서" in text1                             # 어절 공백 보존
    assert all(c.page_start == c.page_end for c in doc.chunks)     # 청크는 쪽을 넘지 않음
    assert doc.chunks[-1].page_start == 3 and doc.chunks[-1].location["page"] == 3


def test_long_paragraph_split_by_max_chars():
    long_line = "항재밍 데이터링크의 동기 유지 성능을 개선하였다. " * 8
    doc = parse(make_pdf([[long_line[i:i + 60] for i in range(0, len(long_line), 60)]]), chunk_max_chars=120)
    assert len(doc.chunks) > 1 and all(len(c.content) <= 120 for c in doc.chunks)


def test_pack_and_page_ranges():
    assert _pack(["가" * 5, "나" * 5, "다" * 5], 11) == ["가" * 5 + "\n" + "나" * 5, "다" * 5]
    assert _pack(["라" * 25], 10) == ["라" * 10, "라" * 10, "라" * 5]
    assert _page_ranges([1, 2, 3, 5, 7, 8]) == "1–3, 5, 7–8"


def test_scanned_pdf_rejected():
    with pytest.raises(ParseError) as e:
        parse(make_pdf([[], []]))
    assert e.value.kind == "no_text_layer" and e.value.status_code == 422 and "OCR" in e.value.detail


def test_encrypted_pdf_rejected():
    with pytest.raises(ParseError) as e:
        parse(make_pdf([PAGE1], encrypt="secret"))
    assert e.value.kind == "encrypted_pdf" and e.value.status_code == 422


@pytest.mark.parametrize("data", [b"%PDF-1.7\n garbage only", make_pdf([PAGE1])[:400]])
def test_corrupt_pdf_rejected(data):
    with pytest.raises(ParseError) as e:
        parse(data)
    assert e.value.kind == "corrupt_pdf" and e.value.status_code == 422


def test_pdf_extension_without_signature_rejected():
    with pytest.raises(ParseError) as e:
        parse("그냥 텍스트".encode(), "가짜.pdf")
    assert e.value.kind == "corrupt_pdf"


def test_too_many_pages():
    with pytest.raises(ParseError) as e:
        parse(make_pdf([PAGE3, PAGE3, PAGE3]), max_pages=2)
    assert e.value.kind == "too_many_pages" and e.value.status_code == 413


def test_text_utf8_and_cp949():
    body = "첫 문단 첫 줄\n첫 문단 둘째 줄\n\n둘째 문단"
    for enc in ("utf-8", "cp949"):
        doc = parse(body.encode(enc), "메모.txt")
        assert doc.file_type == "text" and doc.page_count is None
        assert [c.content for c in doc.chunks] == ["첫 문단 첫 줄 첫 문단 둘째 줄\n둘째 문단"]


def test_unsupported_and_empty():
    with pytest.raises(ParseError) as e:
        parse(b"PK\x03\x04...", "보고서.hwp")
    assert e.value.kind == "unsupported_type" and e.value.status_code == 415
    with pytest.raises(ParseError) as e:
        parse(b"", "빈.pdf")
    assert e.value.kind == "empty_file"


# ---- API ---------------------------------------------------------------------
def pdf_file(data: bytes, name: str = "항재밍_결과보고서.pdf"):
    return {"file": (name, data, "application/pdf")}


async def test_parse_preview_does_not_store(client):
    before = len((await client.get("/documents", headers=as_user(CURATOR))).json())
    r = await client.post("/documents/parse", headers=as_user(CURATOR), files=pdf_file(make_pdf([PAGE1, [], PAGE3])))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["page_count"] == 3 and body["pages_without_text"] == [2] and body["warnings"]
    assert body["filename"] == "항재밍_결과보고서.pdf" and body["chunks"][0]["page_start"] == 1
    assert len((await client.get("/documents", headers=as_user(CURATOR))).json()) == before


async def test_upload_pdf_registers_and_is_searchable(client):
    r = await client.post("/documents/upload", headers=as_user(CURATOR), files=pdf_file(make_pdf([PAGE1, [], PAGE3])),
                          data={"doc_type_code": "FINAL_REPORT", "project_id": "1", "owner_dept_id": "3",
                                "version_label": "최종"})
    assert r.status_code == 201, r.text
    up = r.json()
    assert up["file_type"] == "pdf" and up["page_count"] == 3 and up["embedded"] == len(up["chunk_ids"]) > 0
    docs = (await client.get("/documents", headers=as_user(CURATOR))).json()
    row = next(d for d in docs if d["id"] == up["id"])
    assert row["title"] == "항재밍_결과보고서" and row["parse_status"] == "EMBEDDED"   # 제목 비우면 파일 이름

    hits = (await client.post("/documents/search", headers=as_user(CURATOR), json={
        "query": "항재밍 데이터링크 모뎀의 국산화 가능성을 확인하였으며 체계 적용 시험이 남아 있음.", "k": 3,
        "project_id": 1})).json()
    assert any(h["document_id"] == up["id"] and h["page_start"] == 3 for h in hits)


@pytest.mark.parametrize("data,kind,status", [
    (make_pdf([[], []]), "no_text_layer", 422),
    (make_pdf([PAGE1], encrypt="secret"), "encrypted_pdf", 422),
    (b"%PDF-1.4 broken", "corrupt_pdf", 422),
])
async def test_upload_rejects_bad_pdf(client, data, kind, status):
    r = await client.post("/documents/upload", headers=as_user(CURATOR), files=pdf_file(data),
                          data={"doc_type_code": "FINAL_REPORT", "project_id": "1", "owner_dept_id": "3"})
    assert r.status_code == status and r.json()["kind"] == kind and r.headers["X-Request-Id"]


async def test_upload_unsupported_type_415(client):
    r = await client.post("/documents/parse", headers=as_user(CURATOR),
                          files={"file": ("보고서.hwp", b"HWP Document File", "application/x-hwp")})
    assert r.status_code == 415 and r.json()["kind"] == "unsupported_type"


async def test_upload_requires_role(client):
    r = await client.post("/documents/upload", headers=as_user(EXPERT), files=pdf_file(make_pdf([PAGE1])),
                          data={"doc_type_code": "FINAL_REPORT", "project_id": "1"})
    assert r.status_code == 403
