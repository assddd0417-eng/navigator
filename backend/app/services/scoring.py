"""매칭 점수 계산과 6대 연계유형 분류 (DB 와 무관한 순수 함수).

기준(criterion) 5개: TECH, PERFORMANCE, TRL, ENVIRONMENT, PURPOSE — 각 0~1.
유형별 가중치·조건은 ax.linkage_rule 에서 읽어 match_run.rule_snapshot 으로 고정한다.
값이 없어 판단할 수 없는 기준은 0.5(중립)로 두고 method 에 'neutral' 로 표시한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CRITERIA = ("TECH", "PERFORMANCE", "TRL", "ENVIRONMENT", "PURPOSE")
SINGLE_CARD_TYPES = ("FOLLOW_UP", "ADVANCEMENT", "TRANSITION", "UTILIZATION", "COMMERCIALIZATION")
# 사업화형 가산을 받는 사업트랙 (linkage_rule.conditions.COMMERCIALIZATION.bonus_program_types 로 바꿀 수 있음).
# 2026-11-01 BGE-M3 실측에서 전환형 정답 4건이 모두 사업화형으로 예측돼 조정:
# - 민군겸용(CIVIL_MILITARY)은 뺐다 (정답이 활용·후속형)
# - 성과가 수요와 다른 무기체계 소속이면 가산하지 않는다 (그건 전환형 신호다)
COMMERCIAL_PROGRAM_TYPES = ("PARTS_LOCALIZATION", "EXPORT_SUPPORT", "DEFENSE_VENTURE")
COMMERCIAL_TECH_FACTOR = 0.7   # 기업·품목이 있을 때 사업화형 = 기술유사도 × 이 값 (+ 트랙 가산)
COMMERCIAL_PROGRAM_BONUS = 0.3
UTILIZATION_UNKNOWN_PERF = 0.8  # TRL 충족·요구성능 비교 불가일 때 활용형 계수 (충족 1.0, 미달 0.2)
NEUTRAL = 0.5


@dataclass
class FacetHit:
    similarity: float
    source_table: str | None = None
    source_id: int | None = None


@dataclass
class Performance:
    metric_name: str
    comparator: str = "GTE"
    value: float | None = None        # 카드: 달성값 / 수요: 요구값
    value_max: float | None = None    # 수요 RANGE 상한
    unit: str | None = None


@dataclass
class CardCandidate:
    card_id: int
    title: str
    project_id: int
    project_dept_id: int | None
    program_type: str | None
    trl: int | None
    performances: list[Performance] = field(default_factory=list)
    open_issues: dict[int, str] = field(default_factory=dict)        # id → 설명
    weapon_system_ids: set[int] = field(default_factory=set)
    has_company_or_item: bool = False
    hits: dict[str, FacetHit] = field(default_factory=dict)          # 카드 패싯 → 최고 유사도


@dataclass
class DemandContext:
    demand_id: int
    title: str
    trl_min: int | None
    trl_max: int | None
    requirements: list[Performance] = field(default_factory=list)
    weapon_system_ids: set[int] = field(default_factory=set)
    target_program_type: str | None = None
    requesting_dept_id: int | None = None


@dataclass
class CriterionScore:
    score: float
    method: str
    detail: dict = field(default_factory=dict)


@dataclass
class PerformanceFit:
    score: float
    all_met: bool
    gaps: list[str]
    matched: int


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _norm(name: str) -> str:
    return re.sub(r"[\s\-_()\[\]·.,/]", "", name.lower())


def performance_fit(requirements: list[Performance], achieved: list[Performance]) -> PerformanceFit | None:
    """지표명이 같은 요구성능·달성성능을 비교한다. 비교 가능한 지표가 없으면 None."""
    by_name = {_norm(p.metric_name): p for p in achieved if p.value is not None}
    ratios: list[float] = []
    gaps: list[str] = []
    for req in requirements:
        got = by_name.get(_norm(req.metric_name))
        if got is None or req.value is None or got.value is None:
            continue
        r, a = req.value, got.value
        if req.comparator == "GTE":
            ratio = a / r if r else 1.0
        elif req.comparator == "LTE":
            ratio = r / a if a else 1.0
        elif req.comparator == "RANGE":
            hi = req.value_max if req.value_max is not None else r
            ratio = 1.0 if r <= a <= hi else (a / r if a < r else hi / a)
        else:  # EQ
            ratio = 1.0 - abs(a - r) / abs(r) if r else (1.0 if a == 0 else 0.0)
        ratios.append(clamp01(ratio))
        if ratio < 1.0:
            gaps.append(f"{req.metric_name}: 요구 {r:g}{req.unit or ''}, 달성 {a:g}{got.unit or ''}")
    if not ratios:
        return None
    return PerformanceFit(sum(ratios) / len(ratios), all(x >= 1.0 for x in ratios), gaps, len(ratios))


def trl_fit(trl: int | None, trl_min: int | None, trl_max: int | None) -> float | None:
    """요구 범위 안이면 1. 미달은 단계당 0.25, 초과(성숙도 과잉)는 단계당 0.1 감점."""
    if trl is None or (trl_min is None and trl_max is None):
        return None
    lo = trl_min if trl_min is not None else 1
    hi = trl_max if trl_max is not None else 9
    if trl < lo:
        return clamp01(1.0 - 0.25 * (lo - trl))
    if trl > hi:
        return clamp01(1.0 - 0.1 * (trl - hi))
    return 1.0


def _sim(c: CardCandidate, facet: str) -> float | None:
    h = c.hits.get(facet)
    return clamp01(h.similarity) if h else None


def criterion_scores(c: CardCandidate, d: DemandContext, purpose_sim: float | None) -> dict[str, CriterionScore]:
    out: dict[str, CriterionScore] = {}

    tech = {f: s for f in ("CORE_TECH", "PRINCIPLE", "OPEN_ISSUE", "SUMMARY") if (s := _sim(c, f)) is not None}
    if tech:
        best = max(tech, key=tech.get)
        out["TECH"] = CriterionScore(tech[best], f"cosine:{best}↔TECH_NEED", {"facets": tech})
    else:
        out["TECH"] = CriterionScore(0.0, "none")

    pf = performance_fit(d.requirements, c.performances)
    if pf:
        out["PERFORMANCE"] = CriterionScore(pf.score, "rule:metric_ratio",
                                            {"matched": pf.matched, "all_met": pf.all_met, "gaps": pf.gaps})
    elif (s := _sim(c, "PERFORMANCE")) is not None:
        out["PERFORMANCE"] = CriterionScore(s, "cosine:PERFORMANCE")
    else:
        out["PERFORMANCE"] = CriterionScore(NEUTRAL, "neutral")

    t = trl_fit(c.trl, d.trl_min, d.trl_max)
    out["TRL"] = (CriterionScore(t, "rule:trl_range", {"trl": c.trl, "min": d.trl_min, "max": d.trl_max})
                  if t is not None else CriterionScore(NEUTRAL, "neutral"))

    e = _sim(c, "APPLICATION_ENV")
    out["ENVIRONMENT"] = CriterionScore(e, "cosine:APPLICATION_ENV") if e is not None else CriterionScore(NEUTRAL, "neutral")

    out["PURPOSE"] = (CriterionScore(clamp01(purpose_sim), "cosine:PURPOSE↔SUMMARY")
                      if purpose_sim is not None else CriterionScore(NEUTRAL, "neutral"))
    return out


def classify(c: CardCandidate, d: DemandContext, scores: dict[str, CriterionScore],
             conditions: dict[str, dict]) -> tuple[dict[str, float], dict[str, str]]:
    """단일 카드 기준 5개 유형의 신호(0~1)와 판단 사유. 융합형은 plan_convergence 에서 따로 판정."""
    tech = scores["TECH"].score
    core = max(_sim(c, "CORE_TECH") or 0.0, _sim(c, "SUMMARY") or 0.0)
    principle = max(_sim(c, "PRINCIPLE") or 0.0, core)
    issue = _sim(c, "OPEN_ISSUE")
    perf = scores["PERFORMANCE"]
    gaps = perf.detail.get("gaps") or []
    all_met = perf.detail.get("all_met")

    signals: dict[str, float] = {}
    reasons: dict[str, str] = {}

    fu_min = conditions.get("FOLLOW_UP", {}).get("min_facet_similarity", 0.55)
    if issue is not None and c.open_issues:
        signals["FOLLOW_UP"] = issue if issue >= fu_min else issue * 0.5
        reasons["FOLLOW_UP"] = f"미해결 기술 유사도 {issue:.2f} (기준 {fu_min})"
    else:
        signals["FOLLOW_UP"] = 0.0
        reasons["FOLLOW_UP"] = "미해결 기술 항목 없음"

    signals["ADVANCEMENT"] = core * (1.0 if gaps else 0.6)
    reasons["ADVANCEMENT"] = f"핵심기술 유사도 {core:.2f}" + (f", 성능 격차 {len(gaps)}건" if gaps else "")

    diff_ws = bool(d.weapon_system_ids and c.weapon_system_ids and d.weapon_system_ids.isdisjoint(c.weapon_system_ids))
    diff_prog = bool(d.target_program_type and c.program_type and d.target_program_type != c.program_type)
    signals["TRANSITION"] = principle * (1.0 if (diff_ws or diff_prog) else 0.4)
    reasons["TRANSITION"] = (f"기술원리 유사도 {principle:.2f}"
                             + (", 다른 무기체계" if diff_ws else "") + (", 다른 사업트랙" if diff_prog else ""))

    min_trl = conditions.get("UTILIZATION", {}).get("min_trl", 6)
    mature = c.trl is not None and c.trl >= min_trl
    util = conditions.get("UTILIZATION", {})
    unknown = util.get("unknown_performance_factor", UTILIZATION_UNKNOWN_PERF)
    signals["UTILIZATION"] = tech * (1.0 if mature and all_met else unknown if mature and all_met is None else 0.2)
    reasons["UTILIZATION"] = f"TRL {c.trl} (기준 {min_trl})" + (", 요구성능 충족" if all_met else "")

    com = conditions.get("COMMERCIALIZATION", {})
    commercial = d.target_program_type in com.get("bonus_program_types", COMMERCIAL_PROGRAM_TYPES)
    if diff_ws and com.get("no_bonus_on_different_weapon_system", True):
        commercial = False
    bonus = com.get("program_bonus", COMMERCIAL_PROGRAM_BONUS) if commercial else 0.0
    signals["COMMERCIALIZATION"] = (tech * com.get("tech_factor", COMMERCIAL_TECH_FACTOR) + bonus) \
        if c.has_company_or_item else tech * 0.15
    reasons["COMMERCIALIZATION"] = ("관련 기업·품목 정보 있음" if c.has_company_or_item else "기업·품목 연계 없음") \
        + (", 사업화 성격 사업트랙" if commercial else "")

    signals["CONVERGENCE"] = 0.0
    reasons["CONVERGENCE"] = "단일 성과 (융합형은 기술요소별 판정)"
    return {k: clamp01(v) for k, v in signals.items()}, reasons


def to_probabilities(signals: dict[str, float]) -> dict[str, float]:
    total = sum(signals.values())
    if total <= 0:
        return {k: 1.0 / len(signals) for k in signals}
    return {k: v / total for k, v in signals.items()}


def weighted_total(scores: dict[str, CriterionScore], weights: dict[str, float]) -> float:
    key = {"TECH": "tech", "PERFORMANCE": "performance", "TRL": "trl", "ENVIRONMENT": "environment", "PURPOSE": "purpose"}
    wsum = sum(weights.get(key[c], 0.0) for c in CRITERIA)
    if wsum <= 0:
        return 0.0
    return clamp01(sum(weights.get(key[c], 0.0) * scores[c].score for c in CRITERIA) / wsum)


def plan_convergence(element_hits: dict[int, list[tuple[int, float]]], threshold: float) -> list[tuple[int, int, float]]:
    """수요 기술요소별 최적 카드를 골라, 서로 다른 카드 2개 이상이 요소를 나눠 충족하면 반환.

    element_hits: 기술요소 id → [(card_id, similarity), ...] (유사도 내림차순)
    반환: [(element_id, card_id, similarity)] — 카드가 2개 미만이면 빈 리스트
    """
    chosen: list[tuple[int, int, float]] = []
    used: set[int] = set()
    for element_id, hits in sorted(element_hits.items()):
        for card_id, sim in hits:
            if sim < threshold:
                break
            if card_id not in used:
                chosen.append((element_id, card_id, sim))
                used.add(card_id)
                break
    return chosen if len(used) >= 2 else []
