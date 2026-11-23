"""공고문 글자에서 지원 조건·접수기간·지원금액 후보를 뽑는다. 저장하지 않고 담당자 확인 화면에 보여 준다.

- rules: 정규식으로 자주 나오는 조건(기업규모, 휴·폐업, 체납·부도·참여제한, 연구소 보유, 신용등급, 업력, 지역,
  TRL, 우대 특허·수출)만 뽑는다. 외부로 보내는 것 없음.
- llm: 공고문 글자를 LLM 에 보내 같은 형식(JSON)으로 받는다. 규칙 형식은 RULE_MODELS 로 다시 검사하고,
  형식이 틀리면 '기타'로 바꾼다. 원문 인용이 공고문에 없으면 quote_found=false 로 표시.
REQUIREMENT_EXTRACTOR=auto 면 LLM 자격증명이 있을 때만 llm, 실패하면 rules 로 대신한다.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date

from app.config import Settings
from app.schemas.announcements import RULE_MODELS, normalize_rule
from app.services.external.krit import receipt_period
from app.services.llm import LLMClient, LLMError, build_llm_client

log = logging.getLogger(__name__)

MAX_LLM_CHARS = 40_000


@dataclass
class Suggestion:
    req_type_code: str
    rule: dict
    is_mandatory: bool
    description: str
    source_quote: str | None = None
    quote_found: bool = True


@dataclass
class Extraction:
    extractor: str
    fields: dict = field(default_factory=dict)
    requirements: list[Suggestion] = field(default_factory=list)
    tech_needs: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def source_text(body: str | None, attachments: list[dict]) -> str:
    """본문과 읽은 첨부 글자를 한 덩어리로. 첨부마다 머리줄을 붙인다."""
    parts = [f"[본문]\n{body.strip()}"] if body and body.strip() else []
    for a in attachments:
        if a.get("text_content"):
            parts.append(f"[첨부: {a['file_name']}]\n{a['text_content'].strip()}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# 규칙
# ---------------------------------------------------------------------------
_SEC_QUALIFY = re.compile(r"(신청|지원|참여|모집)\s*(자격|대상)|자격\s*요건")
_SEC_LIMIT = re.compile(r"(신청|지원|참여)\s*(제한|제외)|제외\s*대상|결격")
_SEC_PREFER = re.compile(r"우대|가점")
_SEC_OTHER = re.compile(r"(지원|사업)\s*(내용|분야|범위|규모|기간|개요|목적)|요구\s*기술|신청\s*방법|제출\s*서류|평가|선정\s*절차|문의")

_REGIONS = {"서울": "서울", "부산": "부산", "대구": "대구", "인천": "인천", "광주": "광주", "대전": "대전",
            "울산": "울산", "세종": "세종", "경기": "경기", "강원": "강원", "충청북도": "충북", "충북": "충북",
            "충청남도": "충남", "충남": "충남", "전라북도": "전북", "전북": "전북", "전라남도": "전남", "전남": "전남",
            "경상북도": "경북", "경북": "경북", "경상남도": "경남", "경남": "경남", "제주": "제주"}
_CERTS = [(r"기업부설\s*연구소", "RND_LAB"), (r"연구개발\s*전담\s*부서", "RND_DEPT"), (r"이노비즈", "INNOBIZ"),
          (r"메인비즈", "MAINBIZ"), (r"벤처기업\s*(확인|인증)", "VENTURE"), (r"ISO\s*9001", "ISO9001"),
          (r"AS\s*9100", "AS9100"), (r"국방\s*품질\s*경영", "DEFENSE_QMS")]
_GRADE = re.compile(r"신용(?:평가)?\s*등급\s*(?:[:：]|이|은|가)?\s*['‘’\"“”]?([A-D]{1,3}[+\-]?)['‘’\"“”]?\s*(?:등급\s*)?이상")
_AGE_MAX = re.compile(r"(?:창업|설립|업력|개업)[^\n]{0,15}?(\d{1,2})\s*년\s*(?:이내|미만|이하)")
_AGE_MIN = re.compile(r"(?:창업|설립|업력|개업)[^\n]{0,15}?(\d{1,2})\s*년\s*이상")
_TRL = re.compile(r"TRL\s*(\d)\s*(?:단계)?\s*(?:(이상)|[~\-]\s*(\d))")


@dataclass
class _Line:
    text: str
    section: str   # QUALIFY | LIMIT | PREFER | OTHER | NONE


def _lines(text: str) -> list[_Line]:
    out, sec = [], "NONE"
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        # 짧은 줄은 제목으로 보고 구역을 바꾼다 ("2. 신청자격 및 제한", "나. 신청제한").
        # "2. 지원대상: 중소기업 ..." 처럼 제목 뒤에 내용이 붙은 줄은 콜론 앞을 제목으로 본다
        head = _inline_head(ln)
        if head is not None or len(ln) <= 30:
            sec = _section(head if head is not None else ln, sec)
        out.append(_Line(ln, sec))
    return out


_HEAD = re.compile(r"^\s*(?:\d{1,2}[.)]|[가-하][.)]|[①-⑳]|[□■○●◦▪-])?\s*([^:：]{2,15}?)\s*[:：]\s*\S")


def _inline_head(ln: str) -> str | None:
    m = _HEAD.match(ln)
    return m.group(1) if m and len(ln) > 30 else None


def _section(head: str, cur: str) -> str:
    if _SEC_LIMIT.search(head):
        return "LIMIT"
    if _SEC_PREFER.search(head) and not _SEC_QUALIFY.search(head):
        return "PREFER"
    if _SEC_QUALIFY.search(head):
        return "QUALIFY"
    if _SEC_OTHER.search(head) or head.startswith("[첨부"):
        return "OTHER"
    return cur


def _inline_body(ln: str) -> str:
    return re.split(r"[:：]", ln, maxsplit=1)[-1].strip() if _inline_head(ln) else ""


def _quote(ln: str) -> str:
    return ln[:300]


def _preferred(line: _Line) -> bool:
    return line.section == "PREFER" or bool(_SEC_PREFER.search(line.text))


def extract_rules(text: str, posted_on: date | None = None) -> Extraction:
    lines = _lines(text)
    found: dict[str, Suggestion] = {}

    def add(code: str, rule: dict, mandatory: bool, desc: str, quote: str) -> None:
        if code not in found:
            found[code] = Suggestion(code, rule, mandatory, desc, _quote(quote))

    sizes: list[str] = []
    certs: dict[str, tuple[bool, str]] = {}
    checks: dict[str, str] = {}
    for ln in lines:
        t = ln.text
        in_qualify = ln.section == "QUALIFY"
        if in_qualify and not sizes:
            if "대기업" in t and not re.search(r"대기업[^\n]{0,6}(?:제외|불가)", t):
                sizes = ["ANY"]   # "대기업·스타트업·중소기업 모두" 처럼 규모 제한이 없는 경우
            elif re.search(r"중소\s*[·ㆍ,]?\s*중견", t):
                sizes = ["MIDSIZE", "SME", "STARTUP", "VENTURE"]
            elif re.search(r"중소\s*기업|중소\s*[·ㆍ,]\s*벤처", t):
                sizes = ["SME", "STARTUP", "VENTURE"]
            elif "중견기업" in t:
                sizes = ["MIDSIZE"]
            if sizes and sizes != ["ANY"]:
                label = "중소·중견기업" if "MIDSIZE" in sizes and "SME" in sizes else (
                    "중견기업" if sizes == ["MIDSIZE"] else "중소기업(창업·벤처 포함)")
                add("COMPANY_SIZE", {"allowed": sizes}, True, label, t)
        if re.search(r"휴\s*[·ㆍ,]?\s*폐업|휴업|폐업", t):
            add("BUSINESS_STATUS", {"allowed": ["ACTIVE"]}, True, "휴·폐업 상태가 아닐 것", t)
        if ln.section in ("LIMIT", "QUALIFY", "NONE"):
            if "체납" in t:
                checks.setdefault("TAX_DELINQUENT", t)
            if re.search(r"부도|채무\s*불이행|자본\s*잠식|법정\s*관리|파산", t):
                checks.setdefault("INSOLVENT", t)
            if "부정당" in t:
                checks.setdefault("PROCUREMENT_SANCTIONED", t)
            elif re.search(r"참여\s*제한|입찰\s*참가\s*자격\s*제한", t):
                checks.setdefault("RND_RESTRICTED", t)
            if ln.section == "LIMIT" and re.search(r"중복\s*(지원|수혜|참여|선정)|동일\s*(사업|과제|분야)", t):
                add("DUPLICATE_SUPPORT", {"within_years": 1}, True, "같은 사업 중복 수혜 없음", t)
        # "본사, 기업부설연구소 또는 공장이 있는 기업" 은 소재지 설명이지 인증 조건이 아니다
        if (ln.section in ("QUALIFY", "PREFER") or _SEC_PREFER.search(t)) and not re.search(r"본사|공장|사업장", t):
            for pat, code in _CERTS:
                if re.search(pat, t) and code not in certs:
                    certs[code] = (not _preferred(ln), t)
        if m := _GRADE.search(t):
            add("MIN_CREDIT_GRADE", {"min_grade": m.group(1)}, not _preferred(ln),
                f"기업신용등급 {m.group(1)} 이상", t)
        doc_note = re.search(r"재무제표|회계감사|제출|서류|대체", t)   # "법인 설립 2년 이내 등은 회계감사보고서로 대체"
        if in_qualify and not doc_note and (m := _AGE_MAX.search(t)):
            add("BUSINESS_AGE", {"max_years": int(m.group(1))}, True, f"업력 {m.group(1)}년 이내", t)
        elif in_qualify and not doc_note and (m := _AGE_MIN.search(t)):
            add("BUSINESS_AGE", {"min_years": int(m.group(1))}, True, f"업력 {m.group(1)}년 이상", t)
        if in_qualify and re.search(r"본사|주\s*사무소|소재", t):
            regions = sorted({v for k, v in _REGIONS.items() if k in t})
            if regions:
                add("REGION", {"allowed": regions}, True, f"본사 소재지 {', '.join(regions)}", t)
        if m := _TRL.search(t):
            rule = {"min": int(m.group(1))} if m.group(2) else {"min": int(m.group(1)), "max": int(m.group(3))}
            add("TRL", rule, not _preferred(ln), f"TRL {m.group(0).removeprefix('TRL').strip()}", t)
        if _preferred(ln):
            if "특허" in t:
                add("PATENT", {"min_count": 1}, False, "특허 보유 우대", t)
            if re.search(r"수출\s*실적", t):
                add("EXPORT", {"min_krw": 1}, False, "수출 실적 보유 우대", t)

    if certs:
        mandatory = [c for c, (m, _) in certs.items() if m]
        preferred = [c for c, (m, _) in certs.items() if not m]
        if mandatory:
            add("REQUIRED_CERT", {"any_of": mandatory}, True, _cert_label(mandatory) + " 보유", certs[mandatory[0]][1])
        elif preferred:
            add("REQUIRED_CERT", {"any_of": preferred}, False, _cert_label(preferred) + " 보유 우대",
                certs[preferred[0]][1])
    if checks:
        names = {"TAX_DELINQUENT": "체납", "INSOLVENT": "부도·채무불이행", "RND_RESTRICTED": "참여제한",
                 "PROCUREMENT_SANCTIONED": "부정당제재"}
        order = [c for c in names if c in checks]
        add("NO_DISQUALIFICATION", {"checks": order}, True,
            "·".join(names[c] for c in order) + " 없음", checks[order[0]])

    reqs = sorted(found.values(), key=lambda s: (not s.is_mandatory, list(RULE_MODELS).index(s.req_type_code)))
    reqs += extract_preferences(text)
    ex = Extraction("rules", fields=extract_fields(text, posted_on), requirements=reqs,
                    tech_needs=extract_tech_needs(lines))
    for note in amount_notes(text):
        ex.warnings.append(f"지원 한도 예외가 있습니다. 한도 칸은 일반 금액으로 넣었습니다: {note[:120]}")
    ex.warnings.append("규칙으로는 자주 나오는 조건만 찾습니다. 원문을 보고 빠진 조건은 직접 추가하세요.")
    return ex


_TECH_HEAD = re.compile(r"요구\s*기술|개발\s*(?:대상\s*)?기술|대상\s*기술")


def extract_tech_needs(lines: list[_Line]) -> list[dict]:
    """'요구기술: A, B' 줄만 본다. 목록형 본문은 LLM 이나 담당자가 채운다."""
    out: list[dict] = []
    for ln in lines:
        head = re.split(r"[:：]", ln.text, maxsplit=1)[0] if re.search(r"[:：]", ln.text) else ""
        if len(head) > 20 or not _TECH_HEAD.search(head):
            continue
        body = re.split(r"[:：]", ln.text, maxsplit=1)[-1]
        for name in re.split(r"\s*(?:[,，;/]|\s및\s)\s*", body):
            name = name.strip(" .-·")
            if 2 <= len(name) <= 300 and name not in {t["tech_name"] for t in out}:
                out.append({"tech_name": name, "description": None, "is_core": not out})
    return out[:10]


def _cert_label(codes: list[str]) -> str:
    names = {"RND_LAB": "기업부설연구소", "RND_DEPT": "연구개발전담부서", "INNOBIZ": "이노비즈", "MAINBIZ": "메인비즈",
             "VENTURE": "벤처기업 확인", "ISO9001": "ISO 9001", "AS9100": "AS9100", "DEFENSE_QMS": "국방품질경영체제"}
    return " 또는 ".join(names.get(c, c) for c in codes)


# ---------------------------------------------------------------------------
# 공고 칸 (접수기간·지원금액·지원기간·대상·목적)
# ---------------------------------------------------------------------------
_KRW = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(억|천\s*만|백\s*만|만)?\s*원")
_UNIT = {"억": 100_000_000, "천만": 10_000_000, "백만": 1_000_000, "만": 10_000, None: 1, "": 1}


def parse_krw(s: str) -> list[int]:
    out = []
    for num, unit in _KRW.findall(s):
        try:
            v = float(num.replace(",", "")) * _UNIT[re.sub(r"\s", "", unit) or None]
        except ValueError:
            continue
        if 1_000_000 <= v <= 100_000_000_000:
            out.append(int(v))
    return out


_BURDEN = re.compile(r"(기업\s*부담\s*금?|민간\s*부담\s*금?|자부담)\s*(?:[:：은는이]\s*)?(?:사업비의\s*|총\s*사업비의\s*)?"
                     r"(\d{1,2}(?:\.\d)?)\s*%")


def _is_note(ln: str) -> bool:
    """'*', '※' 로 시작하거나 '~의 경우' 로 범위를 좁히는 주석 줄."""
    return bool(re.match(r"\s*[*※]", ln)) or bool(re.search(r"경우[^\n]{0,20}\d[\d,]*\s*(?:억|천\s*만|백\s*만|만)?\s*원", ln))


def amount_notes(text: str) -> list[str]:
    """본 금액과 다른 예외 금액 주석. 담당자가 확인하도록 경고로 보여 준다."""
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        note = ln.lstrip("*※ ").strip()
        if _is_note(ln) and re.search(r"한도|최대", ln) and parse_krw(ln) and note not in out:
            out.append(note)
    return out[:3]


_DOC_HEAD = re.compile(r"(신청|제출)\s*(서류|자료)")
_DOC_MARK = re.compile(r"(?:^|\s)([①-⑳➀-➉](?:\s*-\s*\d)?\.?|\d{1,2}\s*-\s*\d\.)\s*")
_DOC_CUT = re.compile(r"\s(?:공고문|국세청|중소기업현황|담당자가|사/세무사|각\s*\d|각자|또는\s*서명|컨설턴트\(|컨설턴트가|양식|\[첨부|\[붙임)")
_DOC_WORD = re.compile(r"서$|서\(|증$|증\(|증명|확인서|동영상|계획서|목록|사본|명세|재무제표|등본|서약")


def _doc_name(raw: str) -> str:
    name = _DOC_CUT.split(" " + raw, maxsplit=1)[0]
    name = re.sub(r"[*※]", "", name)
    return re.sub(r"\s+", " ", name).strip(" .,-·")


def extract_documents(text: str) -> list[dict]:
    """'신청 서류' 표의 ①②… 항목 이름만. 표가 PDF 에서 섞여 나오므로 서류 이름처럼 보이는 것만 남긴다."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if not _DOC_HEAD.search(ln) or len(ln) > 200 and not _DOC_MARK.search(ln):
            continue
        out: list[dict] = []
        for j, cur in enumerate(lines[i:i + 30]):
            if j > 0 and (re.match(r"^\d{1,2}\s+\S", cur) or re.match(r"^[가-하]\.\s", cur)) and not _DOC_HEAD.search(cur):
                break
            marks = list(_DOC_MARK.finditer(cur))
            for k, m in enumerate(marks):
                end = marks[k + 1].start() if k + 1 < len(marks) else len(cur)
                name = _doc_name(cur[m.end():end])
                if not name and k == 0:   # "… 지원 신청서 및 ➀ 공고문 [첨부1] 양식" 처럼 이름이 표시 앞에 있는 줄
                    before = re.split(r"내\s*용", cur[:m.start()])[-1]
                    name = _doc_name(re.sub(r"\s*(및|과|와)\s*$", "", before.strip())[-60:])
                if 2 <= len(name) <= 60 and _DOC_WORD.search(name) and name not in {d["name"] for d in out}:
                    out.append({"name": name, "required": True})
            if re.search(r"해당\s*시[^\n]{0,10}제출\s*서류", cur) and out:
                out.append({"name": "우대·감점 증빙 서류", "required": False})
        if len(out) >= 2:
            return out[:20]
    return []


_PREFER_LINE = re.compile(r"^\W*우\s*대\s*(?:사\s*항)?\s*[:：]\s*(.+)$")
_PREFER_ITEM = re.compile(r"([^,，;()]{3,80}?)\s*\((\d+(?:\.\d+)?)\s*(%|점)\)")


def extract_preferences(text: str) -> list[Suggestion]:
    """'우대 : A(2%), B(1.5%)' 줄에서 우대 항목을 기타 조건(우대)으로 뽑는다."""
    out: list[Suggestion] = []
    for ln in text.splitlines():
        m = _PREFER_LINE.match(ln.strip())
        if not m:
            continue
        body = re.sub(r"\((?![\d.]+\s*(?:%|점)\))[^)]*\)", "", m.group(1))   # 설명 괄호는 뺀다
        for it in _PREFER_ITEM.finditer(body):
            name = re.sub(r"\s+", " ", it.group(1)).strip(" ,·∙-")
            desc = f"{name} 우대 (가점 {it.group(2)}{it.group(3)})"
            if name and desc not in {s.description for s in out}:
                out.append(Suggestion("OTHER", {}, False, desc, _quote(ln.strip())))
    return out[:10]


def extract_fields(text: str, posted_on: date | None = None) -> dict:
    fields: dict = {}
    start, end = receipt_period(text, posted_on)
    if start:
        fields["receipt_start"] = start.isoformat()
    if end:
        fields["receipt_end"] = end.isoformat()
    # 총 예산이 아니라 한 기업이 받을 수 있는 금액
    # "* 기술분야 컨설팅의 경우 5천만 원 한도" 같은 예외 주석 줄은 본 금액이 없을 때만 쓴다
    amounts, note_amounts = [], []
    for ln in text.splitlines():
        ln = re.split(r"[(（]?\s*(?:총\s*)?(?:예산|사업비)", ln)[0]   # "(총 예산 3억원)" 앞까지만
        if re.search(r"한도|최대|과제당|기업당|업체당", ln):
            (note_amounts if _is_note(ln) else amounts).extend(parse_krw(ln))
    if amounts or note_amounts:
        fields["support_amount_krw"] = max(amounts or note_amounts)
    if m := _BURDEN.search(text):
        fields["company_burden"] = f"{m.group(1).replace(' ', '')} {m.group(2)}%"
    docs = extract_documents(text)
    if docs:
        fields["submit_documents"] = docs
    if m := re.search(r"(?:사업|협약|지원|수행|개발)\s*기간\s*[:：]?[^\n]{0,40}?(\d{1,2})\s*(개월|년)", text):
        n = int(m.group(1)) * (12 if m.group(2) == "년" else 1)
        if 0 < n <= 120:
            fields["support_period_months"] = n
    lines = _lines(text)
    def _target(desc: str) -> bool:
        return len(desc) >= 4 and not re.search(r"첨부|붙임|참조|참고", desc)

    for i, ln in enumerate(lines):
        m = _HEAD.match(ln.text)   # 짧은 줄 "○ 참여대상 : 산·학·연" 도 제목·내용으로 본다
        head = m.group(1) if m else None
        if head and _SEC_QUALIFY.search(head) and not re.search(r"모집|공고", head):
            desc = re.split(r"[:：]", ln.text, maxsplit=1)[-1].strip()
            if _target(desc):
                fields["target_desc"] = desc[:500]
                break
            continue
        if (ln.section == "QUALIFY" and _SEC_QUALIFY.search(ln.text) and len(ln.text) <= 30
                and not re.search(r"모집|공고|[:：]", ln.text)):
            nxt = next((x.text for x in lines[i + 1:i + 4] if len(x.text) > 15 and x.section == "QUALIFY"), None)
            if nxt and _target(nxt):
                fields["target_desc"] = nxt[:500]
                break
    for i, ln in enumerate(lines):
        if re.search(r"사업\s*목적", ln.text):
            rest = re.split(r"사업\s*목적\s*[:：]?", ln.text, maxsplit=1)[-1].strip()
            fields["summary"] = (rest if len(rest) > 15 else (lines[i + 1].text if i + 1 < len(lines) else ""))[:1000]
            break
    return {k: v for k, v in fields.items() if v}


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
_SYSTEM = """너는 국방 R&D·방산 지원사업 공고문에서 기업이 지원할 수 있는 조건을 뽑는 담당자를 돕는다.
JSON 하나만 답한다. 설명 문장, 코드 블록 표시는 쓰지 않는다.

형식:
{"fields": {"receipt_start": "YYYY-MM-DD"|null, "receipt_end": "YYYY-MM-DD"|null,
            "support_amount_krw": 정수|null, "support_period_months": 정수|null,
            "target_desc": "지원 대상 한두 문장"|null, "summary": "사업 목적 한두 문장"|null},
 "requirements": [{"req_type_code": "코드", "rule": {...}, "is_mandatory": true|false,
                   "description": "사람이 읽는 조건 한 줄", "source_quote": "공고문에서 그대로 옮긴 근거 문장"}],
 "tech_needs": [{"tech_name": "요구 기술", "description": "설명"|null, "is_core": true|false}]}

규칙:
- 기업이 신청할 때 지켜야 하는 조건만 넣는다. 수행기관·컨설턴트·평가위원 조건은 넣지 않는다.
- 신청제한(이런 기업은 신청 불가)은 반대로 바꿔 조건으로 쓴다. 예: "휴·폐업 중인 기업" → BUSINESS_STATUS {"allowed":["ACTIVE"]}.
- 우대·가점 조건은 is_mandatory=false.
- 여러 항목 중 하나만 맞으면 되는 조건(예: 방산업체 지정 또는 협력업체 또는 ...)은 OTHER 하나로 묶는다.
- 코드 목록에 맞는 것이 없으면 OTHER, rule 은 {}.
- source_quote 는 공고문 글자를 바꾸지 말고 그대로 옮긴다. 공고문에 없는 내용은 만들지 않는다.
- 금액은 원 단위 정수. 접수기간 연도가 없으면 게시일 연도를 쓴다.
"""


def _user_prompt(text: str, posted_on: date | None, codes: list[dict], certs: list[dict]) -> str:
    code_lines = "\n".join(f"- {c['code']} ({c['name_ko']}): rule 예 {json.dumps(c['rule_example'], ensure_ascii=False)}"
                           f" — {c['description'] or ''}" for c in codes)
    cert_lines = ", ".join(f"{c['code']}={c['name_ko']}" for c in certs)
    return (f"게시일: {posted_on.isoformat() if posted_on else '모름'}\n\n"
            f"조건 코드:\n{code_lines}\n\n"
            f"REQUIRED_CERT any_of 에 쓸 인증 코드: {cert_lines}\n"
            f"COMPANY_SIZE allowed 값: LARGE, MIDSIZE, SME, STARTUP, VENTURE (중소기업이면 SME·STARTUP·VENTURE 모두)\n"
            f"NO_DISQUALIFICATION checks 값: TAX_DELINQUENT(체납), INSOLVENT(부도·채무불이행·자본잠식), "
            f"RND_RESTRICTED(국가 R&D·입찰 참여제한), PROCUREMENT_SANCTIONED(부정당제재)\n\n"
            f"공고문:\n{text[:MAX_LLM_CHARS]}")


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _json_block(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("JSON 이 없음")
    return json.loads(raw[start:end + 1])


def parse_llm_answer(raw: str, text: str, cert_codes: set[str], extractor: str) -> Extraction:
    data = _json_block(raw)
    ex = Extraction(extractor)
    squashed = _squash(text)
    for r in data.get("requirements") or []:
        code = str(r.get("req_type_code") or "OTHER").upper()
        desc = str(r.get("description") or "").strip().rstrip(". ")[:1000]   # 목록으로 이어 붙이므로 끝 마침표 뺌
        if not desc:
            continue
        rule = r.get("rule") if isinstance(r.get("rule"), dict) else {}
        try:
            if code not in RULE_MODELS:
                raise ValueError(f"알 수 없는 조건 종류 {code}")
            rule = normalize_rule(code, rule)
            if code == "REQUIRED_CERT":
                rule["any_of"] = [c for c in rule["any_of"] if c in cert_codes]
                if not rule["any_of"]:
                    raise ValueError("인증 코드가 목록에 없음")
        except ValueError as e:
            ex.warnings.append(f"'{desc[:40]}' 은(는) 규칙 형식이 맞지 않아 기타로 바꿨습니다 ({e})")
            code, rule = "OTHER", {}
        quote = (str(r.get("source_quote") or "").strip() or None)
        ex.requirements.append(Suggestion(code, rule, bool(r.get("is_mandatory", True)), desc,
                                          quote[:2000] if quote else None,
                                          bool(quote) and _squash(quote) in squashed))
    f = data.get("fields") or {}
    for k in ("receipt_start", "receipt_end"):
        try:
            if f.get(k):
                ex.fields[k] = date.fromisoformat(str(f[k])).isoformat()
        except ValueError:
            pass
    for k in ("support_amount_krw", "support_period_months"):
        if isinstance(f.get(k), (int, float)) and f[k] > 0:
            ex.fields[k] = int(f[k])
    for k, n in (("target_desc", 500), ("summary", 1000)):
        if isinstance(f.get(k), str) and f[k].strip():
            ex.fields[k] = f[k].strip()[:n]
    for t in data.get("tech_needs") or []:
        name = str(t.get("tech_name") or "").strip()
        if name:
            ex.tech_needs.append({"tech_name": name[:300], "description": (t.get("description") or None),
                                  "is_core": bool(t.get("is_core", True))})
    missing = sum(1 for s in ex.requirements if s.source_quote and not s.quote_found)
    if missing:
        ex.warnings.append(f"근거 문장 {missing}개는 공고문에서 그대로 찾지 못했습니다. 원문과 대조하세요.")
    return ex


async def extract_llm(client: LLMClient, text: str, posted_on: date | None,
                      codes: list[dict], certs: list[dict]) -> Extraction:
    raw = await client.complete(_SYSTEM, _user_prompt(text, posted_on, codes, certs))
    return parse_llm_answer(raw, text, {c["code"] for c in certs}, f"llm:{client.name}")


def wants_llm(settings: Settings) -> bool:
    from app.services.llm import llm_credentials_configured
    mode = settings.requirement_extractor.lower()
    return mode == "llm" or (mode == "auto" and llm_credentials_configured(settings))


async def extract(text: str, posted_on: date | None, settings: Settings, codes: list[dict], certs: list[dict],
                  client: LLMClient | None = None) -> Extraction:
    if not text.strip():
        ex = Extraction("rules")
        ex.warnings.append("공고문 글자가 없습니다. 본문을 붙여 넣거나 첨부를 확인하세요.")
        return ex
    if client is None and wants_llm(settings):
        client = build_llm_client(settings)
    if client is not None:
        try:
            ex = await extract_llm(client, text, posted_on, codes, certs)
            if not ex.fields.get("receipt_end"):   # 접수기간은 규칙이 더 정확한 편이라 비면 채운다
                ex.fields.update({k: v for k, v in extract_fields(text, posted_on).items()
                                  if k.startswith("receipt_") and k not in ex.fields})
            return ex
        except (LLMError, ValueError) as e:
            log.warning("LLM 조건 추출 실패, 규칙으로 대신함: %s", e)
            ex = extract_rules(text, posted_on)
            ex.warnings.insert(0, f"AI 추출에 실패해 규칙으로 뽑았습니다 ({str(e)[:120]})")
            return ex
    return extract_rules(text, posted_on)
