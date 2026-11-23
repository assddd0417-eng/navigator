"""상담결과서 PDF.

화면에 보이는 결과서를 그대로 옮긴다. 내용은 화면과 같은 데이터에서 만든다.
  담당자 판본   consultation.get() 의 결과서 항목 (점수 병기, 담당자가 고친 문장 그대로)
  기업 판본     consultation.company_view() 의 확정 상담 (점수는 빼고 라벨만, 검토한 지원사업·성장 경로 포함)
한글 글꼴은 REPORT_FONT_PATH, 없으면 설치된 나눔고딕·맑은 고딕·애플고딕 순으로 찾는다. 다 없으면 PDF 기본 한글 글꼴
(HYGothic, 뷰어가 가진 글꼴로 표시)을 쓴다.
"""
from __future__ import annotations

import io
import os
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import get_settings

KST = ZoneInfo("Asia/Seoul")
FONT, FONT_BOLD = "NavKR", "NavKR-Bold"
CANDIDATES = [  # (보통, 굵게)
    ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
    ("/Library/Fonts/NanumGothic.ttf", "/Library/Fonts/NanumGothicBold.ttf"),
    (str(Path.home() / "Library/Fonts/NanumGothic.ttf"), str(Path.home() / "Library/Fonts/NanumGothicBold.ttf")),
    ("C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/malgunbd.ttf"),
    ("/System/Library/Fonts/Supplemental/AppleGothic.ttf", None),
]
_font: tuple[str, str] | None = None


def fonts() -> tuple[str, str]:
    """(보통, 굵게) 글꼴 이름. 처음 한 번 등록한다."""
    global _font
    if _font is not None:
        return _font
    custom = get_settings().report_font_path
    tries = ([(custom, None)] if custom else []) + CANDIDATES
    for regular, bold in tries:
        if not regular or not os.path.exists(regular):
            continue
        pdfmetrics.registerFont(TTFont(FONT, regular))
        if bold and os.path.exists(bold):
            pdfmetrics.registerFont(TTFont(FONT_BOLD, bold))
            _font = (FONT, FONT_BOLD)
        else:
            _font = (FONT, FONT)
        return _font
    pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
    _font = ("HYGothic-Medium", "HYGothic-Medium")
    return _font


def fmt_date(s: str | None) -> str:
    """화면 fmtDate(ko-KR, dateStyle short, timeStyle short) 와 같은 모양. 예: 26. 11. 23. 오후 6:57"""
    if not s:
        return "–"
    t = datetime.fromisoformat(s).astimezone(KST)
    ampm = "오전" if t.hour < 12 else "오후"
    h = t.hour % 12 or 12
    return f"{t:%y}. {t.month}. {t.day}. {ampm} {h}:{t.minute:02d}"


def _styles() -> dict[str, ParagraphStyle]:
    reg, bold = fonts()
    base = ParagraphStyle("base", fontName=reg, fontSize=10, leading=15, textColor=colors.HexColor("#1f2933"))
    return {
        "title": ParagraphStyle("title", base, fontName=bold, fontSize=16, leading=22, spaceAfter=4),
        "meta": ParagraphStyle("meta", base, fontSize=9, leading=13, textColor=colors.HexColor("#5f6b7a")),
        "h": ParagraphStyle("h", base, fontName=bold, fontSize=11.5, leading=16, spaceBefore=10, spaceAfter=3,
                        keepWithNext=1),   # 제목이 쪽 끝에 혼자 남지 않게 다음 내용과 같은 쪽에 둔다
        "body": base,
        "cell": ParagraphStyle("cell", base, fontSize=9, leading=13),
        "cellh": ParagraphStyle("cellh", base, fontName=bold, fontSize=9, leading=13),
        "small": ParagraphStyle("small", base, fontSize=8.5, leading=12, textColor=colors.HexColor("#5f6b7a")),
    }


def _p(text: str | None, style: ParagraphStyle) -> Paragraph:
    """줄바꿈을 지키는 문단 (화면 white-space: pre-wrap)."""
    t = escape(text or "").replace("\n", "<br/>")
    return Paragraph(t or "&nbsp;", style)


def _footer(label: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont(fonts()[0], 8)
        canvas.setFillColor(colors.HexColor("#8a94a3"))
        canvas.drawString(18 * mm, 10 * mm, label)
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"{doc.page}쪽")
        canvas.restoreState()
    return draw


def _build(story: list, label: str, title: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm,
                            bottomMargin=18 * mm, title=title, author="Navigator")
    doc.build(story, onFirstPage=_footer(label), onLaterPages=_footer(label))
    return buf.getvalue()


def _sections(report: list[dict], st: dict, skip_empty: bool) -> list:
    """항목마다 제목과 본문을 한 덩어리로 둔다. 본문이 빈 항목(담당자 의견 등)은 다음 항목과 같은 쪽에 둔다."""
    out, pending = [], []
    for s in report:
        if skip_empty and not s["text"]:
            continue
        block = pending + [_p(s["title"], st["h"]), _p(s["text"], st["body"])]
        if not s["text"].strip():
            pending = block
            continue
        out.append(KeepTogether(block))
        pending = []
    if pending:
        out.append(KeepTogether(pending))
    return out


def staff_pdf(c: dict) -> bytes:
    """담당자 화면 '상담결과서' 그대로 (작성·확정 정보, 상담 내용, 결과서 항목)."""
    st = _styles()
    meta = f"{c['task_label']} · 작성 {fmt_date(c['created_at'])}" + (
        f" {c['created_by_name']}" if c.get("created_by_name") else "")
    if c["status"] == "CONFIRMED":
        meta += f" · 확정 {fmt_date(c['confirmed_at'])}" + (
            f" {c['confirmed_by_name']}" if c.get("confirmed_by_name") else "")
        if c.get("notified_at"):
            meta += f" · 안내 {fmt_date(c['notified_at'])}"
    title = f"{c['company_name']} 상담결과서"
    story = [_p(title, st["title"]), _p(f"{meta} · {c['status_label']}", st["meta"])]
    if c.get("concern"):
        story.append(_p(f"상담 내용: {c['concern']}", st["body"]))
    story.append(Spacer(1, 4))
    story += _sections(c["report"], st, skip_empty=False)
    return _build(story, f"상담결과서 · {c['company_name']}", title)


def _table(head: list[str], rows: list[list], widths: list[float], st: dict) -> Table:
    data = [[_p(h, st["cellh"]) for h in head]] + [
        [x if not isinstance(x, (str, type(None))) else _p(x or "–", st["cell"]) for x in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d2dd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def company_pdf(company_name: str, c: dict) -> bytes:
    """기업 화면 '상담·결과 안내'의 상담 결과 하나 그대로 (점수 없이 라벨만)."""
    st = _styles()
    title = f"{c['task_label']} 상담 결과"
    story = [_p(title, st["title"]), _p(f"{company_name} · {fmt_date(c['confirmed_at'])}", st["meta"])]
    if c.get("state_label"):
        story.append(_p(f"상태유형 {c['state_label']}", st["meta"]))
    story += _sections(c["report"], st, skip_empty=True)
    if c["announcements"]:
        story.append(_p("검토한 지원사업", st["h"]))
        rows = []
        for a in c["announcements"]:
            cell = [_p(a["title"], st["cell"])] + [_p(f"· {t}", st["small"]) for t in a["todo"]]
            rows.append([cell, a["agency_name"], a["receipt_end"], a["q1_label"],
                         f"적합도 {a['fit_grade']}" if a["fit_grade"] else "–"])
        w = A4[0] - 36 * mm
        story.append(_table(["공고", "기관", "마감일", "신청 가능 여부", "적합도"], rows,
                            [w * 0.42, w * 0.18, w * 0.13, w * 0.15, w * 0.12], st))
    if c["steps"]:
        head = [_p("성장 경로", st["h"])]
        for s in c["steps"]:
            block = [_p(f"{s['horizon']} · {s['stage_label']}", st["cellh"]), _p(s["goal"], st["body"])]
            if s["programs"]:
                block.append(_p(", ".join(f"{p['name']} · {p['readiness_label']}" for p in s["programs"]), st["cell"]))
            block += [_p(f"· {t}", st["small"]) for t in s["tasks"]]
            block.append(Spacer(1, 5))
            story.append(KeepTogether(head + block))   # 제목은 첫 단계와 같은 쪽에
            head = []
    return _build(story, f"상담 결과 · {company_name}", title)


def filename(company_name: str, kind: str, when: str | None) -> str:
    day = datetime.fromisoformat(when).astimezone(KST).strftime("%Y%m%d") if when else ""
    safe = "".join(ch for ch in company_name if ch not in '\\/:*?"<>|').strip()
    return f"{kind}_{safe}_{day}.pdf" if day else f"{kind}_{safe}.pdf"
