"""갭 판정 규칙 (DB 불필요): 공백·성능미달·국산화/현지화·성숙도부족, 점수, 정답 사례 비교."""
from datetime import date

from app.services.gap_rules import (
    DEFAULT_RULES,
    AnswerCase,
    CardPerf,
    DemandInput,
    FoundGap,
    NearCard,
    OpenIssue,
    answer_types,
    assess,
    evaluate_cases,
    merge_rules,
    urgency,
)
from app.services.scoring import Performance

TODAY = date(2026, 11, 11)
RULES = merge_rules(None)


def _types(findings):
    return [f.gap_type for f in findings]


def _k2_transmission(sim=0.8):
    return NearCard(10, "K2전차 1,500마력급 국산 자동변속기", sim, trl=8,
                    performances=[CardPerf(1, "내구도 검사 시간", "GTE", 320, 306, "h", False)],
                    open_issues=[OpenIssue(1, "UNMET_TARGET", "내구도 검사 기준 320시간 미달", "HIGH", 0.7)])


def _k2_engine(sim=0.75, issue_sim=0.6):
    return NearCard(11, "K2전차 1,500마력급 국산 디젤엔진", sim, trl=9,
                    performances=[CardPerf(2, "최대출력", "GTE", 1500, 1500, "마력", True)],
                    open_issues=[OpenIssue(2, "FOLLOW_UP_NEED", "수출국 현지 조립생산·정비 요구에 맞춘 엔진 정비 문서·교육 패키지 필요",
                                           "HIGH", issue_sim)])


def test_no_coverage_when_nothing_close():
    d = DemandInput(1, "저소음 주행 모드", "CALL", "새 운용 모드: 저소음 주행", "MEDIUM", "공모 2023")
    out = assess(d, [_k2_engine(sim=0.30), _k2_transmission(sim=0.20)], RULES, TODAY)
    assert _types(out) == ["NO_COVERAGE"]
    f = out[0]
    assert 0.5 < f.severity <= 1 and f.best_similarity == 0.3
    assert [c.role for c in f.cards] == ["NEAREST", "NEAREST"]
    assert f.pathways[-1].linkage_type is None  # 신규 기획수요


def test_no_cards_at_all_is_full_gap():
    d = DemandInput(1, "수요", "ROADMAP", "요구", "HIGH", None)
    f = assess(d, [], RULES, TODAY)[0]
    assert f.gap_type == "NO_COVERAGE" and f.severity == 1.0 and f.best_similarity is None


def test_own_target_shortfall_is_performance_gap():
    """해외 수요에 수치가 없어도, 가까운 국내 성과가 자기 목표(국방규격)를 못 채웠으면 성능미달 (정답 G01)."""
    d = DemandInput(8, "수출형 K2 파워팩 기준 제원", "EXPORT_REQ", "디젤 1,500마력, 자동변속기", "HIGH", "운용 중")
    out = assess(d, [_k2_transmission(), _k2_engine()], RULES, TODAY)
    assert "PERFORMANCE_SHORT" in _types(out)
    perf = next(f for f in out if f.gap_type == "PERFORMANCE_SHORT")
    assert [c.card_id for c in perf.cards] == [10] and "306" in perf.summary and "95.6%" in perf.summary
    assert perf.pathways[0].linkage_type == "ADVANCEMENT"
    # 현지화 낱말이 없는 수요에는 엔진 카드의 '현지 정비' 미해결 과제로 갭을 만들지 않는다
    assert "LOCALIZATION" not in _types(out) and "MATURITY" not in _types(out)


def test_requirement_vs_achieved_and_unit_mismatch():
    d = DemandInput(1, "출력", "EXPORT_REQ", "출력 1,600마력", "HIGH", None,
                    [Performance("최대출력", "GTE", 1600, None, "마력"), Performance("최대출력", "GTE", 1.2, None, "MW")])
    out = assess(d, [_k2_engine()], RULES, TODAY)
    perf = next(f for f in out if f.gap_type == "PERFORMANCE_SHORT")
    assert "요구 1600마력, 달성 1500마력" in perf.summary
    d2 = DemandInput(2, "출력", "EXPORT_REQ", "출력", "HIGH", None, [Performance("최대출력", "GTE", 1.2, None, "MW")])
    assert "PERFORMANCE_SHORT" not in _types(assess(d2, [_k2_engine()], RULES, TODAY))  # 단위가 다르면 비교 안 함


def test_export_localization_uses_related_open_issue():
    """수출국 현지 생산·정비 요구 + 국내 성과의 미해결 현지화 과제 → 국산화·현지화, 사업화형 경로 (정답 G02)."""
    d = DemandInput(9, "현지 정비(MRO)와 부체계 수리 문서 이전", "EXPORT_REQ", "K2GF 정비 1~4단계 현지 수행", "HIGH",
                    "2차 계약 이행 기간")
    out = assess(d, [_k2_engine(), _k2_transmission()], RULES, TODAY)
    loc = next(f for f in out if f.gap_type == "LOCALIZATION")
    assert loc.severity == 0.75 and {"현지", "정비", "MRO"} <= set(loc.detail["keywords"])
    assert [c.card_id for c in loc.cards] == [11] and loc.cards[0].role == "EVIDENCE"
    assert [p.linkage_type for p in loc.pathways] == ["COMMERCIALIZATION"]
    assert "MATURITY" not in _types(out)  # 같은 미해결 과제를 두 번 세지 않음


def test_export_localization_even_when_card_is_not_close_overall():
    """성과 전체 유사도는 기준 미만이어도, 미해결 현지화 과제가 수출 요구와 맞으면 공백이 아니라 국산화·현지화 (G02 실측)."""
    d = DemandInput(9, "현지 정비(MRO)와 부체계 수리 문서 이전", "EXPORT_REQ", "K2GF 정비 1~4단계 현지 수행", "HIGH", None)
    out = assess(d, [_k2_engine(sim=0.48, issue_sim=0.6), _k2_transmission(sim=0.40)], RULES, TODAY)
    assert _types(out) == ["LOCALIZATION"]
    assert [c.card_id for c in out[0].cards] == [11] and out[0].detail["via_open_issue"] is True
    # 과제가 요구와 덜 비슷하면 그대로 공백
    assert _types(assess(d, [_k2_engine(sim=0.48, issue_sim=0.3)], RULES, TODAY)) == ["NO_COVERAGE"]
    # 현지화 요구가 아닌 수출 요구는 그대로 공백
    d2 = DemandInput(8, "기준 제원", "EXPORT_REQ", "디젤 1,500마력", "HIGH", None)
    assert _types(assess(d2, [_k2_engine(sim=0.48, issue_sim=0.6)], RULES, TODAY)) == ["NO_COVERAGE"]


def test_imported_parts_are_localization():
    card = NearCard(12, "포탑 구동장치", 0.7, trl=8, imported_items=["정밀 베어링"])
    out = assess(DemandInput(1, "포탑", "ROADMAP", "포탑 구동", "MEDIUM", None), [card], RULES, TODAY)
    loc = next(f for f in out if f.gap_type == "LOCALIZATION")
    assert "정밀 베어링" in loc.summary and loc.pathways[0].linkage_type == "TRANSITION"


def test_maturity_by_trl_and_related_issue():
    low = NearCard(13, "하이브리드 구동 시험장치", 0.7, trl=4,
                   open_issues=[OpenIssue(3, "UNRESOLVED_TECH", "고전압 배터리 열관리 미해결", "MEDIUM", 0.5),
                                OpenIssue(4, "UNRESOLVED_TECH", "관련 없는 과제", "HIGH", 0.1)])
    d = DemandInput(2, "저소음 주행 모드", "CALL", "하이브리드 저소음 주행", "MEDIUM", None)
    f = next(f for f in assess(d, [low], RULES, TODAY) if f.gap_type == "MATURITY")
    assert f.severity == 0.8  # 0.5 + 0.1 × (7 − 4)
    assert "고전압 배터리" in f.summary and "관련 없는" not in f.summary
    assert f.pathways[0].linkage_type == "FOLLOW_UP"
    # 비슷한 성과 중 하나라도 성숙하면 TRL 로는 갭이 아님
    ready = NearCard(14, "양산 하이브리드 구동", 0.65, trl=8)
    no_issue = NearCard(13, "하이브리드 구동 시험장치", 0.7, trl=4)
    assert "MATURITY" not in _types(assess(d, [no_issue, ready], RULES, TODAY))


def test_score_uses_confidence_and_urgency():
    near = [_k2_transmission()]
    hi = assess(DemandInput(1, "a", "EXPORT_REQ", "b", "HIGH", "운용 중"), near, RULES, TODAY)[0]
    lo = assess(DemandInput(1, "a", "EXPORT_REQ", "b", "LOW", "2035~2040"), near, RULES, TODAY)[0]
    assert hi.severity == lo.severity and hi.score > lo.score
    assert lo.score == round(lo.severity * 0.6 * 0.7, 4)
    assert urgency("2028~2030 인도", TODAY) == 1.0 and urgency("2030", TODAY) == 0.85
    assert urgency(None, TODAY) == urgency("날짜 없음", TODAY) == 0.8


def test_threshold_override():
    d = DemandInput(1, "a", "ROADMAP", "b", "MEDIUM", None)
    near = [_k2_transmission(sim=0.5)]
    assert _types(assess(d, near, RULES, TODAY)) == ["NO_COVERAGE"]
    assert "NO_COVERAGE" not in _types(assess(d, near, merge_rules({"coverage_threshold": 0.4}), TODAY))
    assert merge_rules({"min_trl": 5, "near_k": None})["near_k"] == DEFAULT_RULES["near_k"]


def test_answer_types_and_evaluation():
    assert answer_types("성숙도부족/공백(미정)") == {"MATURITY", "NO_COVERAGE"}
    assert answer_types("국산화·현지화") == {"LOCALIZATION"}
    cases = [AnswerCase("G01", ["D08"], "성능미달"), AnswerCase("G02", ["D06", "D09"], "국산화·현지화"),
             AnswerCase("G03", ["D02", "D04"], "성숙도부족/공백(미정)")]
    found = [FoundGap("D08", "PERFORMANCE_SHORT", 0.6), FoundGap("D09", "MATURITY", 0.5),
             FoundGap("D02", "NO_COVERAGE", 0.4), FoundGap("D07", "NO_COVERAGE", 0.3)]
    res = evaluate_cases(cases, found)
    assert res["hit_pct"] == 100.0 and res["type_match_pct"] == round(200 / 3, 1)
    assert [r["type_match"] for r in res["rows"]] == [True, False, True]
    assert {(u["demand_no"], u["gap_type"]) for u in res["unmatched"]} == {("D09", "MATURITY"), ("D07", "NO_COVERAGE")}
    assert evaluate_cases(cases, found, top_n=1)["hit_pct"] == round(100 / 3, 1)


def test_seed_answer_cases_read():
    from app.gap_eval import read_cases

    cases = read_cases()
    assert [c.case_no for c in cases] == ["G01", "G02", "G03", "G04"]
    assert cases[0].demand_nos == ["D08"] and answer_types(cases[0].gap_label) == {"PERFORMANCE_SHORT"}
    assert cases[1].demand_nos == ["D06", "D09"] and answer_types(cases[1].gap_label) == {"LOCALIZATION"}
    assert all(answer_types(c.gap_label) for c in cases)
