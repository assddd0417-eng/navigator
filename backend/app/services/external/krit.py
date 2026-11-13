"""국방기술진흥연구소 공지사항 게시판의 기업 대상 모집 공고.

게시판에는 공고·결과·설명회·채용이 섞여 있어 제목으로 기업 대상 모집 공고만 고른다.
신청기간과 자격요건은 첨부 공고문(HWP 가 대부분)에만 있는 경우가 많아 첨부도 받아 글자를 뽑는다.

live 는 www.krit.re.kr 를 직접 읽는다 (키 불필요). 상세·첨부는 목록에서 받은 세션 쿠키와 Referer 가 있어야
제대로 열리고, 동시에 여러 요청을 보내면 빈 페이지가 와서 한 건씩 천천히 받는다.
mock 은 fixtures/krit_mock.json.
"""
from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from datetime import date

from app.config import get_settings
from app.services.external.base import ConnectorUnavailable, load_fixture

SOURCE_CODE = "KRIT"
AGENCY_NAME = "국방기술진흥연구소"
BASE = "https://www.krit.re.kr"
LIST_URL = f"{BASE}/krit/bbs/notice_list.do"
VIEW_URL = f"{BASE}/krit/bbs/notice_view.do"
MENU_NO = "05010000"
READABLE_EXT = {"hwp", "hwpx", "pdf"}


@dataclass
class NoticeItem:
    ntt_id: str
    title: str
    posted_on: date | None
    has_attachment: bool

    @property
    def url(self) -> str:
        return f"{VIEW_URL}?bbsId=notice&nttId={self.ntt_id}&menu_no={MENU_NO}"


@dataclass
class AttachmentRef:
    file_name: str
    url: str

    @property
    def ext(self) -> str:
        return self.file_name.rsplit(".", 1)[-1].lower() if "." in self.file_name else ""


@dataclass
class NoticeDetail:
    body: str
    attachments: list[AttachmentRef] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 제목 분류
# ---------------------------------------------------------------------------
_RECRUIT = re.compile(r"모집|공모|공고|신청|접수")
_NOT_RECRUIT = re.compile(r"결과|선정 ?기업|합격|발표|설명회|교육|세미나|간담회")
# 기업이 지원하는 공고가 아닌 것 (대학·회계법인·인력 채용·포상·학술 등)
_NOT_COMPANY = re.compile(
    r"대학|학교|회계법인|정산기관|소장 모집|원장 모집|감사 모집|자문위원|특허사무소|학술대회|논문모집|공모전|포상|"
    r"모니터링단|수강생|워킹그룹|채용|박람회|어워드|위탁연구용역|연구주제 공모|개인정보|입찰")


def is_company_recruitment(title: str) -> bool:
    if not _RECRUIT.search(title) or _NOT_COMPANY.search(title):
        return False
    # "설명회 참여기업 모집"처럼 모집이 있으면 모집으로 본다
    return not _NOT_RECRUIT.search(title) or bool(re.search(r"모집|공모", title))


_SERIES_NOISE = [
    r"\[[^\]]*(재공고|연장|정정|수정|추가|변경)[^\]]*\]", r"\((재공고|연장|정정|수정|추가 ?연장|추가|변경|\d차)[^)]*\)",
    r"(추가 )?재공고(문)?", r"(추가 )?연장( 공고)?", r"정정( 공고)?", r"공고문?", r"안내",
    r"[\'’‘`]?\d{2}\s*-\s*\d+\s*차", r"[\'’‘`]?\d{2,4}\s*년(도)?", r"\d+\s*차", r"[\'’‘`「」『』\"“”()\[\]·:]",
]


def series_key(title: str) -> str:
    """재공고·연장·차수·연도를 지운 제목. 같은 사업의 여러 공고를 묶는 데 쓴다."""
    t = title
    for p in _SERIES_NOISE:
        t = re.sub(p, " ", t)
    return re.sub(r"\s+", "", t)[:200]


# ---------------------------------------------------------------------------
# 신청기간
# ---------------------------------------------------------------------------
_PERIOD_LABEL = re.compile(r"(신청|접수|공모|모집|제출|과제\s*접수)\s*(기간|기한|일정|마감|일시)\s*[:：]?")
_DATE = re.compile(r"(?:(\d{4})\s*[.\-년]\s*|[\'’‘`](\d{2})\s*[.\-]\s*)?(\d{1,2})\s*[.\-월]\s*(\d{1,2})\s*[.일]?")


def receipt_period(text: str, posted_on: date | None) -> tuple[date | None, date | None]:
    """본문·첨부에서 '신청기간 : '26. 11. 5.(목) ~ 11. 12.(목)' 같은 줄을 찾아 시작·마감을 돌려준다."""
    for m in _PERIOD_LABEL.finditer(text or ""):
        seg = text[m.end():m.end() + 140].split("\n※")[0]
        dates = _dates(seg, posted_on)
        if not dates:
            continue
        if len(dates) == 1:
            return None, dates[0]
        start, end = dates[0], dates[1]
        if end < start:
            return None, None
        return start, end
    return None, None


def _dates(seg: str, posted_on: date | None) -> list[date]:
    year = posted_on.year if posted_on else date.today().year
    out: list[date] = []
    for y4, y2, mo, d in _DATE.findall(seg):
        if y4:
            year = int(y4)
        elif y2:
            year = 2000 + int(y2)
        try:
            dt = date(year, int(mo), int(d))
        except ValueError:
            continue
        if out and dt < out[-1] and not (y4 or y2):
            try:
                dt = date(year + 1, int(mo), int(d))
            except ValueError:
                continue
        out.append(dt)
        if len(out) == 2:
            break
    if len(out) == 1:
        # "’26. 11. 2.(월) ~ 13.(금)" 처럼 마감에 일만 쓴 경우
        m = re.search(r"~\s*(\d{1,2})\s*[.일]?\s*\(", seg)
        if m:
            s = out[0]
            try:
                end = date(s.year, s.month, int(m.group(1)))
                out.append(end if end >= s else date(s.year + (s.month == 12), s.month % 12 + 1, int(m.group(1))))
            except ValueError:
                pass
    return out


# ---------------------------------------------------------------------------
# HTML 해석
# ---------------------------------------------------------------------------
_LIST_ROW = re.compile(
    r"fnView\('notice','','(\d+)'[^>]*><span>\d+</span>(.*?)</a>\s*<ul class=\"writer\">\s*"
    r"<li class=\"date\">([\d-]+)</li>.*?</ul>\s*(<span class=\"file\">)?", re.S)
_ATTACH = re.compile(r'<a href="(/common/download\.do\?atchFileId=[^"]+)">\s*([^<]+?)\s*</a>')


def _plain(fragment: str) -> str:
    t = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", fragment, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in t.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def parse_list(page_html: str) -> list[NoticeItem]:
    out = []
    for ntt, title, posted, file_mark in _LIST_ROW.findall(page_html):
        try:
            d = date.fromisoformat(posted)
        except ValueError:
            d = None
        out.append(NoticeItem(ntt, _plain(title).replace("\n", " "), d, bool(file_mark)))
    return out


def parse_view(view_html: str) -> NoticeDetail:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", view_html, flags=re.S)
    m = re.search(r"<th[^>]*>\s*내용\s*</th>\s*<td[^>]*>(.*?)</td>", t, re.S)
    body = _plain(m.group(1)) if m else ""
    atts = [AttachmentRef(html.unescape(name).strip(), BASE + html.unescape(href))
            for href, name in _ATTACH.findall(t)]
    return NoticeDetail(body=body, attachments=atts)


# ---------------------------------------------------------------------------
# 연결 부품
# ---------------------------------------------------------------------------
class MockKritConnector:
    mode = "mock"

    def __init__(self, data: dict):
        self.items = data["items"]

    def list_page(self, page: int) -> list[NoticeItem]:
        per = 10
        rows = self.items[(page - 1) * per: page * per]
        return [NoticeItem(r["ntt_id"], r["title"], date.fromisoformat(r["posted_on"]), bool(r.get("attachments")))
                for r in rows]

    def view(self, item: NoticeItem) -> NoticeDetail:
        r = next(x for x in self.items if x["ntt_id"] == item.ntt_id)
        return NoticeDetail(r["body"], [AttachmentRef(a["file_name"], f"mock://{item.ntt_id}/{i}")
                                        for i, a in enumerate(r.get("attachments", []))])

    def download(self, ref: AttachmentRef) -> bytes:
        ntt, i = ref.url.removeprefix("mock://").split("/")
        r = next(x for x in self.items if x["ntt_id"] == ntt)
        return r["attachments"][int(i)]["text"].encode("utf-8")


class LiveKritConnector:
    mode = "live"

    def __init__(self, delay_s: float):
        import httpx
        self.delay_s = delay_s
        self.client = httpx.Client(timeout=30.0, follow_redirects=True,
                                   headers={"User-Agent": "Mozilla/5.0 (kd-ax-navigator)"})
        self.referer = f"{LIST_URL}?gotoMenuNo={MENU_NO}"
        self._get(self.referer)   # 세션 쿠키

    def _get(self, url: str, params: dict | None = None, retries: int = 4):
        import httpx
        last = ""
        for attempt in range(retries):
            try:
                r = self.client.get(url, params=params, headers={"Referer": self.referer})
                r.raise_for_status()
                time.sleep(self.delay_s)
                return r
            except httpx.HTTPError as e:
                last = type(e).__name__
                time.sleep(self.delay_s * (attempt + 2))
        raise ConnectorUnavailable(f"{url.split('?')[0]} 연결 실패: {last}")

    def list_page(self, page: int) -> list[NoticeItem]:
        r = self._get(LIST_URL, {"gotoMenuNo": MENU_NO, "page": page})
        return parse_list(r.text)

    def view(self, item: NoticeItem) -> NoticeDetail:
        params = {"bbsId": "notice", "article_category": "", "nttId": item.ntt_id, "page": 1, "searchCnd": "",
                  "searchWrd": "", "startd": "", "endd": "", "csrf": "", "menu_no": MENU_NO}
        for _ in range(3):
            detail = parse_view(self._get(VIEW_URL, params).text)
            if detail.body or detail.attachments:
                return detail
            self._get(self.referer)   # 세션이 풀리면 빈 페이지가 온다
        return detail

    def download(self, ref: AttachmentRef) -> bytes:
        return self._get(ref.url).content


def get_krit_connector() -> MockKritConnector | LiveKritConnector:
    s = get_settings()
    mode = s.source_krit.lower()
    if mode == "mock":
        return MockKritConnector(load_fixture("krit_mock.json"))
    if mode == "live":
        return LiveKritConnector(s.krit_request_delay_s)
    raise ValueError(f"SOURCE_KRIT={mode} (mock|live)")
