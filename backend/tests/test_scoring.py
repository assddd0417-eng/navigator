from app.services.scoring import (
    CardCandidate, DemandContext, FacetHit, Performance, classify, criterion_scores, performance_fit,
    plan_convergence, to_probabilities, trl_fit, weighted_total,
)


def test_performance_fit_ratio_and_gaps():
    req = [Performance("동기 유지 시간", "GTE", 10, unit="s"), Performance("지연시간", "LTE", 50, unit="ms")]
    got = [Performance("동기유지시간", value=6, unit="s"), Performance("지연 시간", value=40, unit="ms")]
    pf = performance_fit(req, got)
    assert pf is not None and pf.matched == 2
    assert abs(pf.score - (0.6 + 1.0) / 2) < 1e-9
    assert not pf.all_met
    assert pf.gaps == ["동기 유지 시간: 요구 10s, 달성 6s"]


def test_performance_fit_none_when_no_common_metric():
    assert performance_fit([Performance("탐지거리", value=5)], [Performance("무게", value=3)]) is None


def test_trl_fit():
    assert trl_fit(6, 5, 7) == 1.0
    assert trl_fit(3, 5, 7) == 0.5           # 2단계 미달
    assert abs(trl_fit(9, 5, 7) - 0.8) < 1e-9  # 2단계 초과
    assert trl_fit(None, 5, 7) is None
    assert trl_fit(5, None, None) is None


def test_plan_convergence_requires_two_distinct_cards():
    assert plan_convergence({1: [(10, 0.8)], 2: [(10, 0.7)]}, 0.5) == []
    assert plan_convergence({1: [(10, 0.8)], 2: [(10, 0.7), (20, 0.6)]}, 0.5) == [(1, 10, 0.8), (2, 20, 0.6)]
    assert plan_convergence({1: [(10, 0.8)], 2: [(20, 0.4)]}, 0.5) == []


def _card(**kw):
    base = dict(card_id=1, title="c", project_id=1, project_dept_id=1, program_type="CORE_TECH", trl=5)
    base.update(kw)
    return CardCandidate(**base)


def test_follow_up_wins_when_open_issue_matches():
    c = _card(open_issues={7: "동기 유지 부족"},
              hits={"OPEN_ISSUE": FacetHit(0.8, "card_open_issue", 7), "CORE_TECH": FacetHit(0.5)})
    d = DemandContext(1, "d", 5, 7)
    scores = criterion_scores(c, d, None)
    signals, _ = classify(c, d, scores, {"FOLLOW_UP": {"min_facet_similarity": 0.55}})
    assert max(signals, key=signals.get) == "FOLLOW_UP"
    assert scores["TECH"].method == "cosine:OPEN_ISSUE↔TECH_NEED"
    assert scores["TRL"].score == 1.0
    assert abs(sum(to_probabilities(signals).values()) - 1.0) < 1e-9


def test_transition_needs_different_weapon_system():
    hits = {"PRINCIPLE": FacetHit(0.7), "CORE_TECH": FacetHit(0.5)}
    same = _card(weapon_system_ids={1}, hits=hits)
    diff = _card(weapon_system_ids={2}, hits=hits)
    d = DemandContext(1, "d", None, None, weapon_system_ids={1}, target_program_type="CORE_TECH")
    s_same, _ = classify(same, d, criterion_scores(same, d, None), {})
    s_diff, _ = classify(diff, d, criterion_scores(diff, d, None), {})
    assert s_diff["TRANSITION"] > s_same["TRANSITION"]


def test_weighted_total_uses_rule_weights():
    c = _card(hits={"CORE_TECH": FacetHit(1.0)})
    scores = criterion_scores(c, DemandContext(1, "d", 5, 7), None)
    total = weighted_total(scores, {"tech": 1.0, "performance": 0, "trl": 0, "environment": 0, "purpose": 0})
    assert total == 1.0


def test_commercialization_bonus_rules():
    """사업화 가산: 국산화·수출·벤처 트랙만, 민군겸용 제외, 다른 무기체계 성과면 가산 없음 (전환형 신호)."""
    hits = {"PRINCIPLE": FacetHit(0.6), "CORE_TECH": FacetHit(0.6)}
    same_ws = _card(weapon_system_ids={1}, hits=hits, has_company_or_item=True)
    diff_ws = _card(weapon_system_ids={2}, hits=hits, has_company_or_item=True)

    def top(c, program):
        d = DemandContext(1, "d", None, None, weapon_system_ids={1}, target_program_type=program)
        s, _ = classify(c, d, criterion_scores(c, d, None), {})
        return max(s, key=s.get)

    assert top(same_ws, "PARTS_LOCALIZATION") == "COMMERCIALIZATION"
    assert top(diff_ws, "PARTS_LOCALIZATION") == "TRANSITION"
    assert top(same_ws, "CIVIL_MILITARY") != "COMMERCIALIZATION"
    # 규칙 표(linkage_rule.conditions)로 가산 트랙을 바꿀 수 있다
    d = DemandContext(1, "d", None, None, weapon_system_ids={1}, target_program_type="CIVIL_MILITARY")
    s, _ = classify(same_ws, d, criterion_scores(same_ws, d, None),
                    {"COMMERCIALIZATION": {"bonus_program_types": ["CIVIL_MILITARY"]}})
    assert max(s, key=s.get) == "COMMERCIALIZATION"


def test_utilization_when_performance_unknown():
    """TRL 충족·요구성능 비교 불가면 활용형이 고도화형(성능 격차 없음)보다 앞선다."""
    c = _card(trl=7, hits={"CORE_TECH": FacetHit(0.7)})
    d = DemandContext(1, "d", 6, 9)
    s, _ = classify(c, d, criterion_scores(c, d, None), {})
    assert s["UTILIZATION"] > s["ADVANCEMENT"]
