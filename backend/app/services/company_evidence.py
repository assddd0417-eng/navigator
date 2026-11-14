"""기업이 올린 증빙(벤처기업확인서, 연구소 인정서, ISO 인증서, 신용평가 등급 확인서)에서 값을 뽑는다.

PDF·HWP·HWPX 는 글자를 읽어 종류·번호·날짜·등급을 찾는다. 이미지·스캔본은 글자를 읽지 않는다(서버에 OCR 없음).
뽑은 값은 입력란을 채우는 데만 쓰고, 저장은 기업이 확인한 뒤 프로필 저장으로 한다. 원본 파일은 두지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.services import hwp_text

TEXT_EXT = {"pdf", "hwp", "hwpx"}
IMAGE_EXT = {"jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "heic"}

# (코드, 찾을 말). 위에서부터 먼저 맞는 것
_CERT_PATTERNS = [
    ("RND_LAB", r"기업\s*부설\s*연구소"),
    ("RND_DEPT", r"연구\s*개발\s*전담\s*부서"),
    ("VENTURE", r"벤처\s*기업\s*(확인서|확인|인증)"),
    ("INNOBIZ", r"이노비즈|기술\s*혁신형\s*중소기업|INNO-?BIZ"),
    ("MAINBIZ", r"메인비즈|경영\s*혁신형\s*중소기업|MAIN-?BIZ"),
    ("DEFENSE_QMS", r"국방\s*품질\s*경영"),
    ("AS9100", r"AS\s*9100"),
    ("ISO9001", r"ISO\s*9001"),
    ("DEFENSE_COMPANY", r"방산\s*업체\s*지정"),
    ("SME_CONFIRM", r"중소\s*기업\s*(확인서|확인)"),
]
_GRADES = r"AAA|AA[+\-]?|A[+\-]?|BBB[+\-]?|BB[+\-]?|B[+\-0]?|CCC[+\-]?|CC|C|D"
_DATE = r"(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*[.일]?"


@dataclass
class Detected:
    kind: str                       # CERTIFICATION | CREDIT_RATING | UNKNOWN
    values: dict = field(default_factory=dict)


def _date(m: re.Match | tuple) -> str | None:
    y, mo, d = (m.groups() if isinstance(m, re.Match) else m)
    try:
        return date(int(y), int(mo), int(d)).isoformat()
    except ValueError:
        return None


def _labeled_date(text: str, labels: str) -> str | None:
    m = re.search(rf"(?:{labels})\s*(?:일자|일)?\s*[:：]?\s*{_DATE}", text)
    return _date(m) if m else None


def _period(text: str) -> tuple[str | None, str | None]:
    m = re.search(rf"(?:유효\s*기간|인증\s*기간|확인\s*기간|유효\s*기한)\s*[:：]?\s*{_DATE}\s*[~\-–부터]+\s*{_DATE}", text)
    if m:
        g = m.groups()
        return _date(g[:3]), _date(g[3:])
    m = re.search(rf"(?:유효\s*기한|만료\s*일|유효\s*일)\s*[:：]?\s*{_DATE}", text)
    return None, (_date(m) if m else None)


def detect(text: str) -> Detected:
    t = text or ""
    if re.search(r"신용\s*(평가|등급)|기업\s*신용", t):
        v: dict = {}
        if re.search(r"NICE|나이스", t, re.I):
            v["agency"] = "NICE"
        elif re.search(r"KED|한국\s*기업\s*데이터", t, re.I):
            v["agency"] = "KED"
        else:
            v["agency"] = "OTHER"
        if m := re.search(rf"(?:신용\s*등급|평가\s*등급|등급)\s*[:：]?\s*['\"“]?({_GRADES})(?![A-Za-z])", t):
            v["grade"] = m.group(1).replace("B0", "B")
        if d := _labeled_date(t, r"평가|평가\s*기준|기준"):
            v["rated_on"] = d
        _, until = _period(t)
        if until:
            v["valid_until"] = until
        if v.get("grade"):
            return Detected("CREDIT_RATING", v)
    for code, pat in _CERT_PATTERNS:
        if re.search(pat, t, re.I):
            v = {"cert_type_code": code}
            m = (re.search(r"(?:확인|인정|인증|지정|등록|증명|관리)\s*번호\s*[:：]?\s*(제?\s*[A-Za-z0-9][A-Za-z0-9\-]{2,}\s*호?)", t)
                 or re.search(r"제\s*([A-Za-z0-9\-]{4,})\s*호", t))
            if m:
                v["cert_no"] = re.sub(r"^제\s*|\s*호$|\s", "", m.group(1))
            start, end = _period(t)
            issued = _labeled_date(t, "발급|발행|인정|확인|지정|인증|등록") or start
            if issued:
                v["issued_on"] = issued
            if end:
                v["expires_on"] = end
            return Detected("CERTIFICATION", v)
    return Detected("UNKNOWN")


@dataclass
class Parsed:
    status: str                     # PARSED | UNSUPPORTED | FAILED
    note: str | None
    text: str | None
    detected: Detected


def parse(file_name: str, data: bytes) -> Parsed:
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if ext in IMAGE_EXT:
        return Parsed("UNSUPPORTED", "사진·스캔 파일은 글자를 읽지 않습니다. 값을 직접 입력하세요", None, Detected("UNKNOWN"))
    try:
        text = hwp_text.extract_text(file_name, data)
    except hwp_text.UnsupportedFile as e:
        return Parsed("UNSUPPORTED", str(e), None, Detected("UNKNOWN"))
    except Exception as e:  # noqa: BLE001  손상 파일
        return Parsed("FAILED", f"파일을 읽지 못했습니다 ({type(e).__name__})", None, Detected("UNKNOWN"))
    if not text.strip():
        return Parsed("UNSUPPORTED", "글자가 없는 파일입니다 (스캔본일 수 있음). 값을 직접 입력하세요", None, Detected("UNKNOWN"))
    return Parsed("PARSED", None, text, detect(text))
