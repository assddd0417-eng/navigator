"""해외 수요 정리 엑셀 읽기.

엑셀 양식 (시트 이름과 머리글은 정리 파일 그대로)
- 출처     : 출처 번호 · 발행 기관 · 문서 제목 · 발행일 · URL · 자료 종류 · 이용 조건 · 원문 저장 허용 · 확인한 날 · 비고
- 해외수요 : 수요 번호 · 출처 번호 · 국가/기관 · 수요 제목 · 기술분류 · 무기체계/품목 · 요구 성능 · 목표 시기 ·
             수요 종류 · 원문 인용 · 확신도 · 메모

한 칸이라도 잘못되면 전체를 거부한다 (행 번호와 이유를 모두 돌려준다).
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from openpyxl import load_workbook

SOURCE_KIND = {"해외 로드맵": "ROADMAP", "기술로드맵": "ROADMAP", "해외 공모": "CALL", "공모": "CALL",
               "수출 요구": "EXPORT_REQ", "수출요구": "EXPORT_REQ", "국내 근거": "DOMESTIC"}
DEMAND_KIND = {"기술로드맵": "ROADMAP", "공모": "CALL", "수출요구": "EXPORT_REQ",
               "ROADMAP": "ROADMAP", "CALL": "CALL", "EXPORT_REQ": "EXPORT_REQ"}
CONFIDENCE = {"높음": "HIGH", "보통": "MEDIUM", "낮음": "LOW", "HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}
YES_NO = {"예": True, "아니오": False, "Y": True, "N": False}


@dataclass
class SourceRow:
    source_no: str
    issuer: str
    title: str
    published_on: str | None
    url: str
    source_kind: str
    license_note: str
    allow_full_text: bool
    checked_on: date
    note: str | None


@dataclass
class DemandRow:
    demand_no: str
    source_nos: list[str]
    region: str
    title: str
    tech_area: str | None
    target_system: str | None
    requirement: str
    target_period: str | None
    demand_kind: str
    quote: str | None
    confidence: str
    note: str | None


@dataclass
class ImportResult:
    sources: list[SourceRow] = field(default_factory=list)
    demands: list[DemandRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class OverseasImportError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _s(v: object) -> str | None:
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    t = str(v).strip()
    return t or None


def _rows(ws) -> list[tuple[int, dict[str, object]]]:
    it = ws.iter_rows(values_only=True)
    try:
        header = [(_s(h) or "") for h in next(it)]
    except StopIteration:
        return []
    out = []
    for i, r in enumerate(it, start=2):
        if r is None or all(v is None or str(v).strip() == "" for v in r):
            continue
        out.append((i, {h: v for h, v in zip(header, r) if h}))
    return out


def _date(v: object) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    t = _s(v)
    if not t:
        return None
    m = re.fullmatch(r"(\d{4})[-.](\d{1,2})[-.](\d{1,2})\.?", t)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def parse_workbook(data: bytes) -> ImportResult:
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # 손상·다른 형식
        raise OverseasImportError([f"엑셀(xlsx) 파일을 열 수 없습니다: {type(e).__name__}"]) from e
    res = ImportResult()
    for name in ("출처", "해외수요"):
        if name not in wb.sheetnames:
            res.errors.append(f"'{name}' 시트가 없습니다")
    if res.errors:
        raise OverseasImportError(res.errors)

    seen: set[str] = set()
    for i, r in _rows(wb["출처"]):
        where = f"출처 {i}행"
        no, url = _s(r.get("출처 번호")), _s(r.get("URL"))
        kind = SOURCE_KIND.get(_s(r.get("자료 종류")) or "")
        allow = YES_NO.get(_s(r.get("원문 저장 허용")) or "")
        checked = _date(r.get("확인한 날"))
        lic = _s(r.get("이용 조건"))
        problems = []
        if not no:
            problems.append("출처 번호 없음")
        elif no in seen:
            problems.append(f"출처 번호 {no} 중복")
        if not _s(r.get("발행 기관")):
            problems.append("발행 기관 없음")
        if not _s(r.get("문서 제목")):
            problems.append("문서 제목 없음")
        if not url or not re.match(r"^https?://", url):
            problems.append("URL 없음 또는 http(s) 아님")
        if kind is None:
            problems.append(f"자료 종류 '{_s(r.get('자료 종류'))}' 를 알 수 없음")
        if not lic:
            problems.append("이용 조건 없음")
        if allow is None:
            problems.append("원문 저장 허용은 예/아니오")
        if checked is None:
            problems.append("확인한 날은 YYYY-MM-DD")
        if problems:
            res.errors.append(f"{where}: {', '.join(problems)}")
            continue
        seen.add(no)
        res.sources.append(SourceRow(no, _s(r["발행 기관"]), _s(r["문서 제목"]), _s(r.get("발행일")), url, kind,
                                     lic, allow, checked, _s(r.get("비고"))))

    dseen: set[str] = set()
    for i, r in _rows(wb["해외수요"]):
        where = f"해외수요 {i}행"
        no = _s(r.get("수요 번호"))
        src = [s.strip() for s in re.split(r"[,/·\s]+", _s(r.get("출처 번호")) or "") if s.strip()]
        kind = DEMAND_KIND.get(_s(r.get("수요 종류")) or "")
        conf = CONFIDENCE.get(_s(r.get("확신도")) or "보통")
        problems = []
        if not no:
            problems.append("수요 번호 없음")
        elif no in dseen:
            problems.append(f"수요 번호 {no} 중복")
        if not src:
            problems.append("출처 번호 없음")
        missing = [s for s in src if s not in seen]
        if missing:
            problems.append(f"출처 시트에 없는 출처 번호 {', '.join(missing)}")
        for col in ("국가/기관", "수요 제목", "요구 성능"):
            if not _s(r.get(col)):
                problems.append(f"{col} 없음")
        if kind is None:
            problems.append(f"수요 종류 '{_s(r.get('수요 종류'))}' 를 알 수 없음 (기술로드맵/공모/수출요구)")
        if conf is None:
            problems.append("확신도는 높음/보통/낮음")
        if problems:
            res.errors.append(f"{where}: {', '.join(problems)}")
            continue
        dseen.add(no)
        res.demands.append(DemandRow(no, src, _s(r["국가/기관"]), _s(r["수요 제목"]), _s(r.get("기술분류")),
                                     _s(r.get("무기체계/품목")), _s(r["요구 성능"]), _s(r.get("목표 시기")), kind,
                                     _s(r.get("원문 인용")), conf, _s(r.get("메모"))))
    if res.errors:
        raise OverseasImportError(res.errors)
    return res
