"""갭 판정 규칙 (DB 와 무관한 순수 함수).

해외 수요 하나와 가장 가까운 국내 성과 카드들을 받아 갭 후보를 만든다.
- NO_COVERAGE       가까운 카드의 유사도가 모두 기준(coverage_threshold) 미만
- PERFORMANCE_SHORT 비슷한 카드가 해외 요구 성능에 못 미치거나, 자기 목표를 달성하지 못함
- LOCALIZATION      비슷한 카드에 수입 부품이 남아 있거나, 수출 요구가 현지 생산·정비를 요구함
- MATURITY          비슷한 카드의 기술성숙도가 낮거나 이 수요와 관련된 미해결 과제가 남음
판정 결과는 모두 초안이고, 소관부서 검수자가 확정·기각한다.
기준값은 DEFAULT_RULES 에 모아 gap_run.rule_snapshot 으로 고정한다 (나중에 판정 결과로 조정).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.services.scoring import Performance, _norm, clamp01, performance_fit

RULES_VERSION = "gap-2026-11-11b"
DEFAULT_RULES: dict = {
    "version": RULES_VERSION,
    "coverage_threshold": 0.55,   # 가장 가까운 카드가 이보다 낮으면 공백
    "near_k": 10,                 # 볼 국내 성과 수
    "evidence_cards": 3,          # 공백일 때 참고로 붙일 가까운 카드 수
    "issue_threshold": 0.45,      # 카드의 미해결 과제가 이 수요와 관련 있다고 볼 유사도
    "min_trl": 7,                 # 비슷한 카드 중 최고 TRL 이 이보다 낮으면 성숙도부족
    "localization_keywords": ["현지", "조립", "기술이전", "정비", "MRO", "국산화", "수입", "절충교역", "offset"],
    "confidence_weight": {"HIGH": 1.0, "MEDIUM": 0.8, "LOW": 0.6},
}
MATURITY_ISSUE_TYPES = ("UNRESOLVED_TECH", "FOLLOW_UP_NEED")
GAP_TYPES = ("NO_COVERAGE", "PERFORMANCE_SHORT", "LOCALIZATION", "MATURITY")


@dataclass
class CardPerf:
    id: int
    metric_name: str
    comparator: str
    target: float | None
    achieved: float | None
    unit: str | None
    is_achieved: bool | None


@dataclass
class OpenIssue:
    id: int
    issue_type: str
    description: str
    priority: str | None = None
    similarity: float | None = None   # 해외 수요와의 유사도 (임베딩이 없으면 None)


@dataclass
class NearCard:
    card_id: int
    title: str
    similarity: float
    trl: int | None = None
    performances: list[CardPerf] = field(default_factory=list)
    open_issues: list[OpenIssue] = field(default_factory=list)
    imported_items: list[str] = field(default_factory=list)   # 해외 의존 품목명 (BOM 하위 포함)


@dataclass
class DemandInput:
    id: int
    title: str
    kind: str
    requirement: str
    confidence: str = "MEDIUM"
    target_period: str | None = None
    performances: list[Performance] = field(default_factory=list)


@dataclass
class FindingCard:
    card_id: int
    similarity: float | None
    role: str          # NEAREST | EVIDENCE
    note: str | None = None


@dataclass
class Pathway:
    linkage_type: str | None   # None = 신규 기획수요
    description: str
    card_ids: list[int] = field(default_factory=list)


@dataclass
class FindingDraft:
    gap_type: str
    severity: float
    score: float
    summary: str
    best_similarity: float | None
    detail: dict = field(default_factory=dict)
    cards: list[FindingCard] = field(default_factory=list)
    pathways: list[Pathway] = field(default_factory=list)


def merge_rules(override: dict | None) -> dict:
    rules = {**DEFAULT_RULES, "confidence_weight": dict(DEFAULT_RULES["confidence_weight"])}
    for k, v in (override or {}).items():
        if v is None:
            continue
        if k == "confidence_weight":
            rules[k].update(v)
        else:
            rules[k] = v
    return rules


def urgency(target_period: str | None, today: date) -> float:
    """목표 시기가 가까울수록 크다. '운용 중'·과거·2년 안 1.0, 5년 안 0.85, 그 뒤 0.7, 모름 0.8."""
    if not target_period:
        return 0.8
    if "운용" in target_period:
        return 1.0
    years = [int(y) for y in re.findall(r"(?<!\d)(20\d{2})(?!\d)", target_period)]
    if not years:
        return 0.8
    ahead = min(years) - today.year
    return 1.0 if ahead <= 2 else (0.85 if ahead <= 5 else 0.7)


def _has_keyword(text: str, keywords: list[str]) -> list[str]:
    low = text.lower()
    return [k for k in keywords if k.lower() in low]


def _unit_ok(a: str | None, b: str | None) -> bool:
    return not a or not b or _norm(a) == _norm(b)


def _shortfall_vs_demand(demand: DemandInput, card: NearCard) -> tuple[float, list[str], list[str]]:
    """해외 요구 성능 대비 부족분 (0 = 충족). 단위가 다르면 비교하지 않고 '확인 필요'로 돌려준다."""
    unchecked: list[str] = []
    pairs_req: list[Performance] = []
    pairs_got: list[Performance] = []
    by_name = {_norm(p.metric_name): p for p in card.performances if p.achieved is not None}
    for req in demand.performances:
        got = by_name.get(_norm(req.metric_name))
        if got is None or req.value is None:
            continue
        if not _unit_ok(req.unit, got.unit):
            unchecked.append(f"{req.metric_name}: 단위 다름 ({req.unit} / {got.unit}) — 확인 필요")
            continue
        pairs_req.append(req)
        pairs_got.append(Performance(got.metric_name, got.comparator, got.achieved, None, got.unit))
    fit = performance_fit(pairs_req, pairs_got)
    if fit is None or fit.all_met:
        return 0.0, [], unchecked
    return clamp01(1.0 - fit.score), fit.gaps, unchecked


def _own_shortfall(card: NearCard) -> tuple[float, list[str], list[int]]:
    """카드가 자기 목표를 달성하지 못한 지표 (예: 내구도 320시간 기준 중 306시간)."""
    worst, notes, perf_ids = 0.0, [], []
    for p in card.performances:
        if p.is_achieved is not False:
            continue
        if p.target is not None and p.achieved is not None and p.target and p.achieved:
            ratio = p.achieved / p.target if p.comparator != "LTE" else p.target / p.achieved
            gap = clamp01(1.0 - ratio)
            notes.append(f"{p.metric_name}: 목표 {p.target:g}{p.unit or ''}, 달성 {p.achieved:g}{p.unit or ''}"
                         f" ({100 * clamp01(ratio):.1f}%)")
        else:
            gap = 0.1
            notes.append(f"{p.metric_name}: 목표 미달 (수치 없음)")
        worst = max(worst, gap)
        perf_ids.append(p.id)
    return worst, notes, perf_ids


def assess(demand: DemandInput, near: list[NearCard], rules: dict, today: date | None = None) -> list[FindingDraft]:
    """해외 수요 하나의 갭 후보 목록 (점수 높은 순)."""
    today = today or date.today()
    thr = float(rules["coverage_threshold"])
    issue_thr = float(rules["issue_threshold"])
    keywords = list(rules["localization_keywords"])
    weight = float(rules["confidence_weight"].get(demand.confidence, 0.8)) * urgency(demand.target_period, today)
    near = sorted(near, key=lambda c: c.similarity, reverse=True)[: int(rules["near_k"])]
    best = near[0].similarity if near else None
    covering = [c for c in near if c.similarity >= thr]
    out: list[FindingDraft] = []

    def add(gap_type: str, severity: float, summary: str, detail: dict, cards: list[FindingCard],
            pathways: list[Pathway]) -> None:
        sev = round(clamp01(severity), 4)
        out.append(FindingDraft(gap_type, sev, round(clamp01(sev * weight), 4), summary,
                                round(best, 4) if best is not None else None, detail, cards, pathways))

    loc_hits = _has_keyword(f"{demand.title}\n{demand.requirement}", keywords)

    # 1) 공백: 비슷한 국내 성과가 없음 → 다른 판정은 하지 않는다
    #    예외: 수출국이 현지 생산·정비를 요구하고, 가까운 국내 성과의 미해결 과제가 바로 그 현지화 숙제이면
    #    (과제가 이 수요와 유사도 기준 이상 + 현지화 낱말 포함) 공백이 아니라 국산화·현지화 갭이다.
    #    성과 전체는 덜 비슷해도(엔진 개발 ↔ 현지 정비 요구) 남은 숙제가 요구와 맞는 경우다. (2026-11-11 정답 G02)
    if not covering and demand.kind == "EXPORT_REQ" and loc_hits:
        tied = [(c, [i for i in c.open_issues
                     if i.issue_type in MATURITY_ISSUE_TYPES and i.similarity is not None
                     and i.similarity >= issue_thr and _has_keyword(i.description, keywords)])
                for c in near]
        tied = [(c, issues) for c, issues in tied if issues]
        if tied:
            notes = [f"수출국 요구에 현지화 조건이 있음 ({', '.join(loc_hits)})"]
            notes += [f"{c.title} — 미해결: " + "; ".join(i.description for i in issues) for c, issues in tied]
            add("LOCALIZATION", 0.75, "국산화·현지화 대응이 필요합니다: " + " / ".join(notes),
                {"keywords": loc_hits, "items": notes, "via_open_issue": True, "threshold": thr},
                [FindingCard(c.card_id, round(c.similarity, 4), "EVIDENCE",
                             "미해결: " + "; ".join(i.description for i in issues)) for c, issues in tied],
                [Pathway("COMMERCIALIZATION", "수출국 현지 생산·정비 요구에 맞춘 기술 패키지로 사업화 연계",
                         [c.card_id for c, _ in tied])])
            return sorted(out, key=lambda f: f.score, reverse=True)

    if not covering:
        ref = near[: int(rules["evidence_cards"])]
        sev = 1.0 if best is None else 1.0 - 0.5 * clamp01(max(best, 0.0) / thr if thr > 0 else 1.0)
        partial = [c for c in ref if c.similarity >= thr * 0.8]
        paths = [Pathway(None, f"'{demand.title}'을(를) 새 기획수요로 검토")]
        if len(partial) >= 2:
            paths.insert(0, Pathway("CONVERGENCE", "부분적으로 가까운 국내 성과를 결합해 대응",
                                    [c.card_id for c in partial]))
        add("NO_COVERAGE", sev,
            "국내 성과 중 이 수요와 비슷한 것이 없습니다. "
            + ("가장 가까운 성과도 기준에 못 미칩니다." if best is not None else "비교할 국내 성과가 없습니다."),
            {"threshold": thr, "nearest": [{"card_id": c.card_id, "title": c.title, "similarity": round(c.similarity, 4)}
                                            for c in ref]},
            [FindingCard(c.card_id, round(c.similarity, 4), "NEAREST") for c in ref], paths)
        return sorted(out, key=lambda f: f.score, reverse=True)

    # 2) 성능미달
    perf_cards: list[FindingCard] = []
    perf_notes: list[str] = []
    unchecked: list[str] = []
    worst = 0.0
    for c in covering:
        s1, gaps1, unk = _shortfall_vs_demand(demand, c)
        s2, gaps2, _ = _own_shortfall(c)
        unchecked += unk
        if s1 > 0 or gaps2:
            notes = [f"해외 요구 대비 — {g}" for g in gaps1] + [f"자체 목표 미달 — {g}" for g in gaps2]
            perf_cards.append(FindingCard(c.card_id, round(c.similarity, 4), "EVIDENCE", "; ".join(notes)))
            perf_notes += [f"{c.title}: {n}" for n in notes]
            worst = max(worst, s1, s2)
    if perf_cards:
        add("PERFORMANCE_SHORT", 0.5 + 2.5 * worst,
            "비슷한 국내 성과가 있으나 성능이 모자랍니다: " + " / ".join(perf_notes),
            {"shortfall": round(worst, 4), "items": perf_notes, "unchecked": unchecked},
            perf_cards, [Pathway("ADVANCEMENT", "모자란 성능을 끌어올리는 고도화 과제",
                                 [fc.card_id for fc in perf_cards])])

    # 3) 국산화·현지화
    loc_issue_ids: set[int] = set()
    loc_cards: list[FindingCard] = []
    loc_notes: list[str] = []
    loc_sev = 0.0
    loc_paths: list[Pathway] = []
    imported = [c for c in covering if c.imported_items]
    if imported:
        loc_sev = 0.7
        for c in imported:
            note = "해외 의존 품목: " + ", ".join(c.imported_items)
            loc_cards.append(FindingCard(c.card_id, round(c.similarity, 4), "EVIDENCE", note))
            loc_notes.append(f"{c.title} — {note}")
        loc_paths.append(Pathway("TRANSITION", "해외 의존 부품에 국내 대체 성과를 적용하는 전환 과제",
                                 [c.card_id for c in imported]))
    if demand.kind == "EXPORT_REQ" and loc_hits:
        loc_sev = max(loc_sev, 0.6)
        export_cards: list[int] = []
        for c in covering:
            related = [i for i in c.open_issues
                       if _has_keyword(i.description, keywords)
                       or (i.similarity is not None and i.similarity >= issue_thr and i.issue_type in MATURITY_ISSUE_TYPES)]
            if not related:
                continue
            loc_sev = max(loc_sev, 0.75)
            loc_issue_ids.update(i.id for i in related)
            note = "미해결: " + "; ".join(i.description for i in related)
            if c.card_id not in {fc.card_id for fc in loc_cards}:
                loc_cards.append(FindingCard(c.card_id, round(c.similarity, 4), "EVIDENCE", note))
            loc_notes.append(f"{c.title} — {note}")
            export_cards.append(c.card_id)
        loc_notes.insert(0, f"수출국 요구에 현지화 조건이 있음 ({', '.join(loc_hits)})")
        if not loc_cards:  # 근거가 될 미해결 과제가 없으면 가장 가까운 카드를 참고로
            loc_cards.append(FindingCard(covering[0].card_id, round(covering[0].similarity, 4), "NEAREST"))
        loc_paths.append(Pathway("COMMERCIALIZATION", "수출국 현지 생산·정비 요구에 맞춘 기술 패키지로 사업화 연계",
                                 export_cards or [covering[0].card_id]))
    if loc_sev > 0:
        add("LOCALIZATION", loc_sev, "국산화·현지화 대응이 필요합니다: " + " / ".join(loc_notes),
            {"keywords": loc_hits, "items": loc_notes}, loc_cards, loc_paths)

    # 4) 성숙도부족
    mat_cards: list[FindingCard] = []
    mat_notes: list[str] = []
    mat_sev = 0.0
    min_trl = int(rules["min_trl"])
    trls = [c.trl for c in covering if c.trl is not None]
    if trls and max(trls) < min_trl:
        top = max(covering, key=lambda c: c.trl or 0)
        mat_sev = 0.5 + 0.1 * (min_trl - max(trls))
        mat_cards.append(FindingCard(top.card_id, round(top.similarity, 4), "EVIDENCE", f"TRL {top.trl}"))
        mat_notes.append(f"비슷한 국내 성과의 최고 TRL {max(trls)} (기준 {min_trl})")
    for c in covering:
        related = [i for i in c.open_issues
                   if i.issue_type in MATURITY_ISSUE_TYPES and i.id not in loc_issue_ids
                   and not _has_keyword(i.description, keywords)
                   and i.similarity is not None and i.similarity >= issue_thr]
        if not related:
            continue
        mat_sev = max(mat_sev, 0.7 if any(i.priority == "HIGH" for i in related) else 0.6)
        note = "미해결: " + "; ".join(i.description for i in related)
        existing = next((fc for fc in mat_cards if fc.card_id == c.card_id), None)
        if existing:
            existing.note = f"{existing.note}; {note}"
        else:
            mat_cards.append(FindingCard(c.card_id, round(c.similarity, 4), "EVIDENCE", note))
        mat_notes.append(f"{c.title} — {note}")
    if mat_sev > 0:
        add("MATURITY", mat_sev, "비슷한 국내 성과가 아직 무르익지 않았습니다: " + " / ".join(mat_notes),
            {"min_trl": min_trl, "items": mat_notes}, mat_cards,
            [Pathway("FOLLOW_UP", "미해결 기술을 이어 개발하는 후속 과제", [fc.card_id for fc in mat_cards])])

    return sorted(out, key=lambda f: f.score, reverse=True)


# ---------------------------------------------------------------------------
# 정답 사례(갭사례 시트)와 비교
# ---------------------------------------------------------------------------
ANSWER_TYPES = {"성능미달": {"PERFORMANCE_SHORT"}, "국산화·현지화": {"LOCALIZATION"}, "국산화": {"LOCALIZATION"},
                "현지화": {"LOCALIZATION"}, "공백": {"NO_COVERAGE"}, "성숙도부족": {"MATURITY"}}


def answer_types(label: str) -> set[str]:
    """'성숙도부족/공백(미정)' → {MATURITY, NO_COVERAGE}"""
    label = re.sub(r"\(.*?\)", "", label or "").strip()
    out: set[str] = set()
    for part in re.split(r"[/,]", label):
        out |= ANSWER_TYPES.get(part.strip(), set())
    return out


@dataclass
class AnswerCase:
    case_no: str
    demand_nos: list[str]
    gap_label: str
    content: str = ""


@dataclass
class FoundGap:
    demand_no: str
    gap_type: str
    score: float
    finding_id: int | None = None


def evaluate_cases(cases: list[AnswerCase], found: list[FoundGap], top_n: int = 10) -> dict:
    """정답 사례마다: 해당 해외 수요에 갭이 상위 N 안에 나왔는지(적중), 종류까지 맞았는지(종류 일치).

    정답에 없는 갭은 '전문가 확인 필요'로 따로 보여 준다 (정답집이 완전하지 않으므로 바로 헛갭으로 세지 않음).
    """
    ranked = sorted(found, key=lambda f: f.score, reverse=True)[:top_n]
    rows, used = [], set()
    for case in cases:
        want = answer_types(case.gap_label)
        on_demand = [f for f in ranked if f.demand_no in case.demand_nos]
        typed = [f for f in on_demand if f.gap_type in want]
        rows.append({"case_no": case.case_no, "demands": case.demand_nos, "expected": case.gap_label,
                     "expected_types": sorted(want), "hit": bool(on_demand), "type_match": bool(typed),
                     "found": [f"{f.demand_no}:{f.gap_type}" for f in on_demand]})
        used |= {id(f) for f in typed}
    extra = [f for f in ranked if id(f) not in used]
    n = len(cases)
    return {
        "cases": n, "top_n": top_n, "found_total": len(found),
        "hit_pct": round(100.0 * sum(r["hit"] for r in rows) / n, 1) if n else None,
        "type_match_pct": round(100.0 * sum(r["type_match"] for r in rows) / n, 1) if n else None,
        "rows": rows,
        "unmatched": [{"demand_no": f.demand_no, "gap_type": f.gap_type, "score": f.score} for f in extra],
    }
