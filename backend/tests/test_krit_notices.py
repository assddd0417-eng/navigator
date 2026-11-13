"""국기원 공지사항 공고 수집 테스트 (mock 픽스처 + 실제 화면 모양의 HTML 조각)."""
import io
import struct
import zipfile
import zlib
from datetime import date

import psycopg
import pytest

from app.config import get_settings
from app.services import hwp_text
from app.services.external import krit
from app.services.ratelimit import limiter
from tests.conftest import TEST_URL, as_user

PLANNER = 1


def _q(sql: str, *args):
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        cur = conn.execute(sql, args)
        return cur.fetchall() if cur.description else []


@pytest.fixture
def clean(database):
    limiter.reset()
    _q("DELETE FROM ax.announcement WHERE announcement_no LIKE 'KRIT-%%'")
    yield
    _q("DELETE FROM ax.announcement WHERE announcement_no LIKE 'KRIT-%%'")


async def _run(client):
    r = await client.post("/navigator/sources/KRIT/run", headers=as_user(PLANNER))
    assert r.status_code == 200, r.text
    return r.json()


async def test_collect_company_recruitments_with_attachments(client, clean):
    r = await _run(client)
    assert r["status"] == "SUCCEEDED" and r["mode"] == "mock", r
    c = r["counts"]
    assert c["inserted"] == 4 and c["skipped"] == 3, c          # 결과·대학·설명회는 건너뜀
    assert c["attachments_parsed"] == 3 and c["attachments_skipped"] == 1, c   # zip 은 안 읽음

    rows = {no: (start, end, status, series) for no, start, end, status, series in _q(
        """SELECT announcement_no, receipt_start, receipt_end, status, series_key FROM ax.announcement
            WHERE announcement_no LIKE 'KRIT-%%'""")}
    assert rows["KRIT-90012"][:3] == (date(2026, 11, 5), date(2026, 11, 26), "DRAFT")      # 본문 신청기간
    assert rows["KRIT-90010"][:2] == (date(2026, 11, 2), date(2026, 11, 13))              # 첨부에만 있는 기간
    assert rows["KRIT-90008"][3] == rows["KRIT-90006"][3]                                  # 재공고와 원공고는 한 묶음

    att = _q("""SELECT t.file_ext, t.parse_status, t.text_content IS NOT NULL FROM ax.announcement_attachment t
                  JOIN ax.announcement a ON a.id = t.announcement_id WHERE a.announcement_no = 'KRIT-90010'
                 ORDER BY t.file_name""")
    assert att == [("hwpx", "PARSED", True), ("zip", "SKIPPED", False)]

    again = await _run(client)                                   # 이미 받은 공고는 다시 받지 않음
    assert again["counts"].get("inserted", 0) == 0 and again["counts"]["unchanged"] == 4


async def test_overview_lists_krit(client):
    ov = (await client.get("/navigator/sources", headers=as_user(PLANNER))).json()
    k = next(s for s in ov if s["code"] == "KRIT")
    assert k["implemented"] and not k["requires_key"] and k["mode"] == "mock"


def test_live_mode_name_check(monkeypatch):
    monkeypatch.setattr(get_settings(), "source_krit", "nope")
    with pytest.raises(ValueError):
        krit.get_krit_connector()


@pytest.mark.parametrize("title,expected", [
    ("’26-5차 방산 중소기업 컨설팅 지원사업 지원대상기업 모집 공고문", True),
    ("[전북·전주 방산혁신클러스터] (장비)사업 수행 기관 모집 (재공고)", True),
    ("「2026 美 FCT 온라인 설명회」참여기업 모집 공고", True),
    ("2026년 제5기 방산혁신기업 선정 결과(수정)", False),
    ("27-1차 방산수출 지원사업 통합설명회", False),
    ("2026년 방위산업 계약학과 지원사업 주관대학 모집 공고(2차)", False),
    ("국방기술품질원 부설 국방기술진흥연구소 소장 모집 공고", False),
])
def test_company_recruitment_titles(title, expected):
    assert krit.is_company_recruitment(title) is expected


@pytest.mark.parametrize("text,expected", [
    ("가. 신청기간 : ’26. 11. 5.(목) ~ 11. 12.(목) 12:00까지", (date(2026, 11, 5), date(2026, 11, 12))),
    ("○ 모집기간 및 신청방법 : ’26. 11. 2.(월) ~ 13.(금) 17:00", (date(2026, 11, 2), date(2026, 11, 13))),
    ("신청기한 : 2026년 11월 9일(월) 17시까지", (None, date(2026, 11, 9))),
    ("접수기간 : 12. 26.(금) ~ 1. 9.(금)", (date(2026, 12, 26), date(2027, 1, 9))),
    ("2026. 11. 2. 국방기술진흥연구소장", (None, None)),          # 게시일만 있고 기간 표시는 없음
])
def test_receipt_period(text, expected):
    assert krit.receipt_period(text, date(2026, 11, 2)) == expected


def test_series_key_groups_reannouncements():
    a = krit.series_key("[추가 재공고] 26-2차 무기체계 부품국산화개발 지원사업 연구개발기관 모집(3차)")
    b = krit.series_key("26-6차 무기체계 부품국산화개발 지원사업 연구개발기관 모집")
    assert a == b == "무기체계부품국산화개발지원사업연구개발기관모집"


def test_parse_list_and_view():
    page = """<li><a href="#" onclick="fnView('notice','','6574','1','','');"><span>605</span>’26-2차 유망수출품목발굴
      지원사업 참여기업 모집 연장 공고(추가연장)</a>
      <ul class="writer"> <li class="date">2026-11-05</li> <li class="hits">506</li> </ul>
      <span class="file">첨부파일 있음</span></li>"""
    items = krit.parse_list(page)
    assert len(items) == 1 and items[0].ntt_id == "6574" and items[0].posted_on == date(2026, 11, 5)
    assert items[0].title.startswith("’26-2차 유망수출품목발굴 지원사업") and items[0].has_attachment

    view = """<table><tr><th scope="row">내용</th><td><p>가. 신청기간 : ’26. 11. 5.(목) ~ 11. 12.(목)</p>
      <p>&nbsp;나. 신청방법 : 전산접수</p></td></tr>
      <tr><th>첨부파일</th><td><p class="file"><a href="/common/download.do?atchFileId=F1&amp;fileSn=0">
      [공고문] 연장 공고.hwp</a></p></td></tr></table>"""
    d = krit.parse_view(view)
    assert d.body.splitlines() == ["가. 신청기간 : ’26. 11. 5.(목) ~ 11. 12.(목)", "나. 신청방법 : 전산접수"]
    assert d.attachments[0].file_name == "[공고문] 연장 공고.hwp" and d.attachments[0].ext == "hwp"
    assert d.attachments[0].url == "https://www.krit.re.kr/common/download.do?atchFileId=F1&fileSn=0"


# ---------------------------------------------------------------------------
# 첨부 글자 추출
# ---------------------------------------------------------------------------
def test_hwpx_text():
    sec = ('<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
           'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
           '<hp:p><hp:run><hp:t>1. 신청기간 : </hp:t><hp:t>’26. 11. 2.(월) ~ 13.(금)</hp:t></hp:run></hp:p>'
           '<hp:p><hp:run><hp:t>2. 지원대상 : 중소기업</hp:t></hp:run></hp:p></hs:sec>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", sec)
    text = hwp_text.extract_text("공고.hwpx", buf.getvalue())
    assert text == "1. 신청기간 : ’26. 11. 2.(월) ~ 13.(금)\n2. 지원대상 : 중소기업"


def test_hwp5_records_skip_controls():
    def rec(tag: int, payload: bytes) -> bytes:
        return struct.pack("<I", tag | (len(payload) << 20)) + payload
    # 표 컨트롤(확장 제어문자 11, 8 글자 차지) 뒤에 본문, 문단 끝 13
    para = struct.pack("<H", 11) + b"\x00" * 14 + "신청기간".encode("utf-16-le") + struct.pack("<H", 13)
    body = rec(66, b"\x00" * 8) + rec(hwp_text.HWPTAG_PARA_TEXT, para) + rec(hwp_text.HWPTAG_PARA_TEXT,
                                                                             "지원대상".encode("utf-16-le"))
    assert hwp_text._hwp_records(body) == "신청기간\n\n지원대상"
    assert zlib.decompress(zlib.compress(body)[2:-4], -15) == body    # 본문 스트림은 raw deflate


def test_pdf_text_and_unsupported():
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "Application period 2026-11-02 ~ 2026-11-13")
    c.save()
    assert "2026-11-13" in hwp_text.extract_text("a.pdf", buf.getvalue())
    with pytest.raises(hwp_text.UnsupportedFile):
        hwp_text.extract_text("form.xlsx", b"PK\x03\x04not-a-real-zip")
