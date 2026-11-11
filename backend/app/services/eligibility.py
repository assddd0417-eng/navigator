"""자격요건 판정.

요건별 MET / UNMET / UNKNOWN. 필수 중 UNMET 있으면 INELIGIBLE, UNKNOWN 있으면 NEEDS_INFO, 나머지 ELIGIBLE.
값 자체가 없으면(목록이 비어 있어도) UNKNOWN 으로 보고 보완질문을 붙인다.
신용등급은 detail 에 등급을 넣지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

VERDICT_KO = {"ELIGIBLE": "적합", "NEEDS_INFO": "정보부족", "INELIGIBLE": "부적격"}
RESULT_KO = {"MET": "충족", "UNMET": "미충족", "UNKNOWN": "모름"}
SIZE_KO = {"LARGE": "대기업", "MIDSIZE": "중견기업", "SME": "중소기업", "STARTUP": "창업기업", "VENTURE": "벤처기업"}
STATUS_KO = {"ACTIVE": "계속사업자", "SUSPENDED": "휴업", "CLOSED": "폐업"}
DISQUALIFY_KO = {"TAX_DELINQUENT": "국세·지방세 체납", "INSOLVENT": "부도·자본잠식", "RND_RESTRICTED": "국가 R&D 참여제한"}
STARTUP_MAX_YEARS = 7   # 창업기업: 개업 7년 이내 (중소기업창업 지원법)


@dataclass
class Cert:
    code: str
    issued_on: date | None
    expires_on: date | None
    verified: bool


@dataclass
class Credit:
    rank: int | None          # code_credit_grade.rank (모르는 등급이면 None)
    rated_on: date | None
    valid_until: date | None
    verified: bool


@dataclass
class Rnd:
    role: str
    end_date: date | None
    title: str


@dataclass
class Patent:
    status: str
    ipc_codes: list[str]
    title: str


@dataclass
class CompanyFacts:
    organization_id: int
    name: str
    company_size: str | None = None
    opened_on: date | None = None
    region: str | None = None
    employee_count: int | None = None
    revenue_krw: int | None = None
    business_status: str = "UNKNOWN"
    is_defense_company: bool = False
    tax_delinquent: bool | None = None
    insolvent: bool | None = None
    rnd_restricted: bool | None = None
    defense_goods: bool | None = None
    military_supply_krw: int | None = None
    export_krw: int | None = None
    certs: list[Cert] = field(default_factory=list)
    credits: list[Credit] = field(default_factory=list)
    rnd: list[Rnd] = field(default_factory=list)
    patents: list[Patent] = field(default_factory=list)
    answers: dict[int, Any] = field(default_factory=dict)   # requirement_id: answer value


@dataclass
class Requirement:
    id: int
    req_type: str
    rule: dict[str, Any]
    is_mandatory: bool
    description: str


@dataclass
class Check:
    result: str
    reason: str
    question: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    self_declared: bool = False


def years_between(start: date, end: date) -> float:
    return (end - start).days / 365.25


def _range_text(lo: Any, hi: Any, unit: str) -> str:
    if lo is not None and hi is not None:
        return f"{lo}~{hi}{unit}"
    return f"{lo}{unit} 이상" if lo is not None else f"{hi}{unit} 이하"


def _in_range(v: float, lo: float | None, hi: float | None) -> bool:
    return (lo is None or v >= lo) and (hi is None or v <= hi)


def valid_certs(c: CompanyFacts, as_of: date) -> list[Cert]:
    return [x for x in c.certs if x.expires_on is None or x.expires_on >= as_of]


def effective_sizes(c: CompanyFacts, as_of: date) -> set[str]:
    # 창업·벤처는 SME 에 포함. 벤처확인 있으면 VENTURE, 7년 이내면 STARTUP
    sizes = {c.company_size} if c.company_size else set()
    if sizes & {"STARTUP", "VENTURE"}:
        sizes.add("SME")
    if any(x.code == "VENTURE" for x in valid_certs(c, as_of)) and sizes <= {"SME", "STARTUP", "VENTURE"}:
        sizes |= {"VENTURE", "SME"}
    if sizes & {"SME"} and c.opened_on and years_between(c.opened_on, as_of) <= STARTUP_MAX_YEARS:
        sizes.add("STARTUP")
    return sizes


def _answer(req: Requirement, c: CompanyFacts, question: str) -> Check:
    if req.id not in c.answers:
        return Check("UNKNOWN", "기업 정보에 없어 판단할 수 없음", question)
    v = c.answers[req.id]
    if req.req_type == "TRL":
        lo, hi = req.rule.get("min"), req.rule.get("max")
        try:
            trl = int(v)
        except (TypeError, ValueError):
            return Check("UNKNOWN", "TRL 답을 숫자로 읽을 수 없음", question)
        ok = _in_range(trl, lo, hi)
        return Check("MET" if ok else "UNMET", f"기업 답: TRL {trl} (요건 {_range_text(lo, hi, '')})",
                     detail={"trl": trl}, self_declared=True)
    if isinstance(v, bool):
        return Check("MET" if v else "UNMET", f"기업 답: {'충족' if v else '충족하지 않음'}",
                     detail={"answer": v}, self_declared=True)
    return Check("UNKNOWN", "기업 답을 해석할 수 없음 (예/아니오로 답해 주세요)", question)


def judge(req: Requirement, c: CompanyFacts, as_of: date) -> Check:
    r, t = req.rule, req.req_type

    if t == "COMPANY_SIZE":
        allowed = r["allowed"]
        if not c.company_size:
            return _answer(req, c, f"기업 규모를 알려 주세요 (요건: {', '.join(SIZE_KO[a] for a in allowed)})")
        sizes = effective_sizes(c, as_of)
        ok = bool(sizes & set(allowed))
        return Check("MET" if ok else "UNMET",
                     f"기업 규모 {SIZE_KO[c.company_size]}, 요건 {', '.join(SIZE_KO[a] for a in allowed)} "
                     f"{'해당' if ok else '해당 없음'}", detail={"sizes": sorted(sizes)})

    if t == "BUSINESS_AGE":
        lo, hi = r.get("min_years"), r.get("max_years")
        if not c.opened_on:
            return _answer(req, c, f"개업일을 알려 주세요 (요건: 업력 {_range_text(lo, hi, '년')})")
        age = years_between(c.opened_on, as_of)
        ok = _in_range(age, lo, hi)
        return Check("MET" if ok else "UNMET", f"업력 {age:.1f}년 (기준일 {as_of}), 요건 {_range_text(lo, hi, '년')}",
                     detail={"years": round(age, 1), "as_of": as_of.isoformat()})

    if t == "REQUIRED_CERT":
        want = r["any_of"]
        if not c.certs:
            return _answer(req, c, f"보유 인증을 입력해 주세요 (요건: {', '.join(want)} 중 하나)")
        have = [x for x in valid_certs(c, as_of) if x.code in want]
        if have:
            return Check("MET", f"인증 {have[0].code} 보유 (유효)",
                         detail={"cert": have[0].code, "verified": have[0].verified})
        expired = [x.code for x in c.certs if x.code in want]
        why = f"요구 인증 {', '.join(want)} 이(가) 만료됨" if expired else f"요구 인증 {', '.join(want)} 없음"
        return Check("UNMET", why, detail={"expired": expired})

    if t == "MIN_CREDIT_GRADE":
        q = "최근 신용평가등급(평가기관·등급·평가일)을 입력해 주세요"
        valid = [x for x in c.credits if x.rank is not None and (x.valid_until is None or x.valid_until >= as_of)]
        if not valid:
            return _answer(req, c, q)
        latest = max(valid, key=lambda x: (x.rated_on or date.min))
        ok = latest.rank >= r["min_rank"]
        return Check("MET" if ok else "UNMET", f"신용등급 요건 {r['min_grade']} 이상 {'충족' if ok else '미달'}"
                     f"{'' if latest.verified else ' (자가입력·미확인)'}", detail={"verified": latest.verified})

    if t == "REGION":
        if not c.region:
            return _answer(req, c, f"본사 소재 시·도를 알려 주세요 (요건: {', '.join(r['allowed'])})")
        ok = c.region in r["allowed"]
        return Check("MET" if ok else "UNMET", f"본사 {c.region}, 요건 {', '.join(r['allowed'])}",
                     detail={"region": c.region})

    if t == "TRL":
        return _answer(req, c, f"제안하실 기술의 TRL(1~9)을 알려 주세요 (요건: TRL {_range_text(r.get('min'), r.get('max'), '')})")

    if t == "EMPLOYEE_COUNT":
        lo, hi = r.get("min"), r.get("max")
        if c.employee_count is None:
            return _answer(req, c, f"상시 근로자 수를 알려 주세요 (요건: {_range_text(lo, hi, '명')})")
        ok = _in_range(c.employee_count, lo, hi)
        return Check("MET" if ok else "UNMET", f"직원 {c.employee_count}명, 요건 {_range_text(lo, hi, '명')}",
                     detail={"employee_count": c.employee_count})

    if t == "REVENUE":
        lo, hi = r.get("min_krw"), r.get("max_krw")
        if c.revenue_krw is None:
            return _answer(req, c, "최근 연매출을 알려 주세요")
        ok = _in_range(c.revenue_krw, lo, hi)
        return Check("MET" if ok else "UNMET", f"매출 요건 {'충족' if ok else '벗어남'}", detail={"meets": ok})

    if t == "BUSINESS_STATUS":
        if c.business_status == "UNKNOWN":
            return _answer(req, c, "휴·폐업 여부를 확인할 수 없습니다. 국세청 진위확인 정보(대표자명·개업일)를 확인해 주세요")
        ok = c.business_status in r["allowed"]
        return Check("MET" if ok else "UNMET", f"사업자 상태 {STATUS_KO[c.business_status]}",
                     detail={"business_status": c.business_status})

    if t == "DEFENSE_COMPANY":
        has = c.is_defense_company or any(x.code == "DEFENSE_COMPANY" for x in valid_certs(c, as_of))
        ok = has == bool(r.get("required", True))
        return Check("MET" if ok else "UNMET", "방산업체 지정" + (" 있음" if has else " 없음"), detail={"designated": has})

    if t == "RND_EXPERIENCE":
        role, n_min, within = r.get("role"), r.get("min_count", 1), r.get("within_years")
        what = f"R&D 과제 {'주관' if role == 'LEAD' else '수행'} 이력 {n_min}건 이상"
        if not c.rnd:
            return _answer(req, c, f"{what}이 필요합니다. 수행한 R&D 과제(과제명·기간·역할)가 있으면 입력해 주세요")
        hits = [x for x in c.rnd if (role is None or x.role == role)
                and (within is None or (x.end_date and years_between(x.end_date, as_of) <= within))]
        ok = len(hits) >= n_min
        return Check("MET" if ok else "UNMET", f"{what}: {len(hits)}건", detail={"count": len(hits)})

    if t == "PATENT":
        n_min, status, prefixes = r.get("min_count", 1), r.get("status"), r.get("ipc_prefixes") or []
        if not c.patents:
            return _answer(req, c, "보유(출원 포함) 특허가 있으면 입력해 주세요")
        hits = [p for p in c.patents if p.status != "LAPSED" and (status is None or p.status == status)
                and (not prefixes or any(code.replace(" ", "").startswith(px.replace(" ", ""))
                                         for code in p.ipc_codes for px in prefixes))]
        ok = len(hits) >= n_min
        cond = f"{'/'.join(prefixes)} 분야 " if prefixes else ""
        return Check("MET" if ok else "UNMET", f"{cond}특허 {len(hits)}건 (요건 {n_min}건 이상)",
                     detail={"count": len(hits), "titles": [p.title for p in hits][:3]})

    if t == "NO_DISQUALIFICATION":
        checks = r.get("checks") or list(DISQUALIFY_KO)
        vals = {k: getattr(c, k.lower()) for k in checks}
        hit = [DISQUALIFY_KO[k] for k, v in vals.items() if v]
        if hit:
            return Check("UNMET", f"결격사유 해당: {', '.join(hit)}", detail={"hit": hit})
        if any(v is None for v in vals.values()):
            return _answer(req, c, f"다음에 모두 해당하지 않나요? {', '.join(DISQUALIFY_KO[k] for k in checks)} (예/아니오)")
        return Check("MET", "결격사유 없음", detail={"checked": checks}, self_declared=True)

    if t == "DEFENSE_SUPPLY":
        need_goods, lo = r.get("defense_goods"), r.get("min_supply_krw")
        parts, unknown, ok = [], False, True
        if need_goods:
            if c.defense_goods is None:
                unknown = True
            else:
                ok &= c.defense_goods
                parts.append("방산물자 생산 " + ("함" if c.defense_goods else "안 함"))
        if lo is not None:
            if c.military_supply_krw is None:
                unknown = True
            else:
                ok &= c.military_supply_krw >= lo
                parts.append(f"군 납품 실적 {'충족' if c.military_supply_krw >= lo else '미달'}")
        if not ok:
            return Check("UNMET", ", ".join(parts), detail={"meets": False})
        if unknown:
            return _answer(req, c, f"다음을 충족하나요? {req.description} (예/아니오)")
        return Check("MET", ", ".join(parts) or "요건 없음", detail={"meets": True})

    if t == "EXPORT":
        lo = r.get("min_krw", 1)
        if c.export_krw is None:
            return _answer(req, c, "최근 연도 수출 실적(금액)을 알려 주세요")
        ok = c.export_krw >= lo
        return Check("MET" if ok else "UNMET", f"수출 실적 요건 {'충족' if ok else '미달'}", detail={"meets": ok})

    # OTHER
    return _answer(req, c, f"다음 요건을 충족하나요? {req.description} (예/아니오)")


def overall(checks: list[tuple[Requirement, Check]]) -> str:
    mandatory = [ch.result for req, ch in checks if req.is_mandatory]
    if "UNMET" in mandatory:
        return "INELIGIBLE"
    if "UNKNOWN" in mandatory:
        return "NEEDS_INFO"
    return "ELIGIBLE"
