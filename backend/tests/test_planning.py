"""신규 과제 기획 API: 동향 입력 → 기획 참고서(관련 과거 과제·요구 성능 비교·새 기획에 넣을 것) → 기획수요."""
import psycopg
import pytest

from tests.conftest import TEST_URL, as_user

PLANNER, REVIEWER, EXPERT, CURATOR, VIEWER = 1, 2, 3, 4, 5
WIDE = {"min_sim": -1, "k": 20}   # 시험용 해시 임베딩은 유사도가 낮아 관련도 기준을 끈다
PROJECT = 3  # 시드 'EO/IR 영상 기반 표적 자동탐지' (다른 시험과 겹치지 않게)

_state: dict = {}


@pytest.fixture
async def ready(client):
    """과거 과제 하나(전환 실패 + 평가 의견 + 목표 미달 카드)와 그에 맞는 동향 하나."""
    if _state:
        return _state
    r = await client.post("/cards", headers=as_user(CURATOR), json={
        "card_no": "AC-PL-TRK", "project_id": PROJECT, "title": "기획시험 표적 추적 모듈",
        "core_achievement": "표적 추적 모듈 시제품", "trl": 5,
        "technologies": [{"tech_name": "영상 표적 추적", "is_primary": True}],
        "performances": [{"metric_name": "탐지거리", "target_value": 8, "achieved_value": 6, "unit": "km",
                          "is_achieved": False},
                         {"metric_name": "추적 유지율", "target_value": 90, "achieved_value": 95, "unit": "%",
                          "is_achieved": True}],
        "open_issues": [{"issue_type": "FOLLOW_UP_NEED", "description": "야간 저조도 환경 추적 성능 검증 필요",
                         "priority": "HIGH"},
                        {"issue_type": "UNMET_TARGET", "description": "탐지거리 목표 미달", "priority": "HIGH"}]})
    assert r.status_code == 201, r.text
    card_id = r.json()["id"]
    assert (await client.post(f"/cards/{card_id}/publish", headers=as_user(CURATOR))).status_code == 204

    url = f"/planning/projects/{PROJECT}"
    r = await client.put(f"{url}/outcome", headers=as_user(CURATOR), json={"outcome_code": "NOT_TRANSITIONED"})
    assert r.status_code == 422 and "원인" in r.json()["detail"]
    r = await client.put(f"{url}/outcome", headers=as_user(CURATOR), json={
        "outcome_code": "NOT_TRANSITIONED", "outcome_note": "탐지거리 목표 미달로 체계 적용 보류"})
    assert r.status_code == 204, r.text
    r = await client.post(f"{url}/evaluations", headers=as_user(CURATOR), json={
        "eval_kind": "RESULT", "eval_date": "2025-08-20", "grade": "미흡", "evaluator": "결과평가위원회",
        "opinion": "시제품 완성도는 있으나 탐지거리 목표에 못 미침",
        "suggestion": "후속 과제에서는 실운용 기상 조건의 탐지거리 시험을 포함할 것"})
    assert r.status_code == 201, r.text

    r = await client.post("/planning/trends", headers=as_user(CURATOR), json={
        "title": "정찰드론 EO/IR 탐지거리 성능개량", "demand_kind": "UPGRADE", "region": "육군",
        "requirement": "정찰드론 영상 표적 탐지거리를 10km 이상으로 높이고 야간 추적 유지",
        "source_note": "육군 성능개량 소요 검토 자료 (2026-10)", "target_period": "2028~2030",
        "performances": [{"metric_name": "탐지거리", "required_value": 10, "unit": "km"},
                         {"metric_name": "추적 유지율", "required_value": 90, "unit": "%"},
                         {"metric_name": "야간 탐지거리", "required_value": 5, "unit": "km"},
                         {"metric_name": "운용 고도", "required_text": "중고도 운용 가능"}]})
    assert r.status_code == 201, r.text
    _state.update(card=card_id, trend=r.json()["id"])
    return _state


async def test_trend_input_rules(client):
    base = {"title": "단종 부품 대체", "demand_kind": "SUPPLY", "region": "방위사업청",
            "requirement": "단종된 수입 부품 대체 개발", "source_note": "단종 통보 공문"}
    assert (await client.post("/planning/trends", headers=as_user(EXPERT), json=base)).status_code == 403
    bad_kind = await client.post("/planning/trends", headers=as_user(PLANNER), json={**base, "demand_kind": "RUMOR"})
    assert bad_kind.status_code == 422
    no_src = {k: v for k, v in base.items() if k != "source_note"}
    assert (await client.post("/planning/trends", headers=as_user(PLANNER), json=no_src)).status_code == 422
    empty_perf = await client.post("/planning/trends", headers=as_user(PLANNER),
                                   json={**base, "performances": [{"metric_name": "수명"}]})
    assert empty_perf.status_code == 422 and "수명" in empty_perf.json()["detail"]


async def test_brief(client, ready):
    for uid in (EXPERT, VIEWER):
        assert (await client.get(f"/planning/brief/{ready['trend']}", headers=as_user(uid))).status_code == 403
    r = await client.get(f"/planning/brief/{ready['trend']}", headers=as_user(PLANNER), params=WIDE)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["trend"]["demand_kind_name"] == "성능개량 요구" and b["trend"]["source_note"]

    proj = next(p for p in b["projects"] if p["project_id"] == PROJECT)
    assert proj["outcome_name"] == "전환 실패" and proj["outcome_is_failure"]
    assert proj["evaluations"][0]["grade"] == "미흡"
    card = next(c for c in proj["cards"] if c["card_id"] == ready["card"])
    assert {lim["issue_type_name"] for lim in card["limits"]} == {"후속 연구 필요", "목표 미달"}

    cmp = {row["metric_name"]: row for row in b["comparison"]}
    assert cmp["탐지거리"]["status"] == "SHORT" and cmp["탐지거리"]["ratio"] == pytest.approx(0.6)
    assert cmp["추적 유지율"]["status"] == "MET"
    assert cmp["야간 탐지거리"]["status"] == "NO_DATA"
    assert cmp["운용 고도"]["status"] == "TEXT"

    kinds = [s["kind"] for s in b["suggestions"]]
    assert kinds[0] == "CAUTION"  # 실패 원인이 맨 앞
    assert {"CAUTION", "UPGRADE", "RESOLVE", "EVAL", "NEW", "REUSE"} <= set(kinds)
    orders = [s["order"] for s in b["suggestions"]]
    assert orders == sorted(orders)
    titles = " ".join(s["title"] + s["detail"] for s in b["suggestions"])
    assert "탐지거리 목표 미달로 체계 적용 보류" in titles and "야간 저조도" in titles
    # 목표 미달 숙제는 '실패 원인 먼저' 로만 (남은 숙제로 또 넣지 않는다)
    assert not any(s["kind"] == "RESOLVE" and s["title"] == "탐지거리 목표 미달" for s in b["suggestions"])
    assert b["summary"]["short"] == 1 and b["summary"]["met"] == 1 and b["summary"]["no_data"] == 1
    assert b["summary"]["cautions"] >= 2 and b["planning_demand"] is None

    # 관련도 기준을 높이면 관련 과제가 없고 '새로 개발' 만 남는다
    none = (await client.get(f"/planning/brief/{ready['trend']}", headers=as_user(PLANNER),
                             params={"min_sim": 1.01})).json()
    assert none["projects"] == [] and any(s["title"] == "관련된 과거 과제가 없습니다" for s in none["suggestions"])
    assert (await client.get("/planning/brief/999999", headers=as_user(PLANNER))).status_code == 404


async def test_brief_to_demand(client, ready):
    url = f"/planning/brief/{ready['trend']}/to-demand"
    for uid in (CURATOR, REVIEWER, EXPERT):
        assert (await client.post(url, headers=as_user(uid), params=WIDE)).status_code == 403
    r = await client.post(url, headers=as_user(PLANNER), params=WIDE)
    assert r.status_code == 201, r.text
    made = r.json()
    assert made["created"] and made["demand_no"] == f"PD-TR-{ready['trend']:04d}" and made["draft_id"]
    again = await client.post(url, headers=as_user(PLANNER), params=WIDE)
    assert again.status_code == 200 and again.json()["demand_id"] == made["demand_id"] and not again.json()["created"]

    d = (await client.get(f"/demands/{made['demand_id']}", headers=as_user(PLANNER))).json()
    assert d["origin_overseas_demand_id"] == ready["trend"] and d["origin_gap_finding_id"] is None
    assert d["status"] == "OPEN" and "기획 참고:" in d["tech_need"] and "[실패 원인 먼저]" in d["tech_need"]
    assert [p["metric_name"] for p in d["performance_reqs"]] == ["탐지거리", "추적 유지율", "야간 탐지거리", "운용 고도"]

    doc = (await client.get(f"/planning/demands/{made['demand_id']}/brief", headers=as_user(REVIEWER))).json()
    assert doc["content_md"].startswith("# 기획 참고서: 정찰드론") and "전환 실패" in doc["content_md"]
    assert "AI" not in doc["content_md"] and "Claude" not in doc["content_md"]

    trends = (await client.get("/planning/trends", headers=as_user(PLANNER))).json()
    row = next(t for t in trends if t["id"] == ready["trend"])
    assert row["planning_demand_no"] == made["demand_no"] and row["demand_kind_name"] == "성능개량 요구"


async def test_db_rules(client, ready):
    with psycopg.connect(TEST_URL) as conn:
        with pytest.raises(psycopg.errors.CheckViolation, match="project_failure_needs_reason"):
            conn.execute("UPDATE ax.project SET outcome_code = 'STOPPED', outcome_note = ' ' WHERE id = %s", (PROJECT,))
        conn.rollback()
        with pytest.raises(psycopg.errors.CheckViolation, match="보안등급"):
            conn.execute("INSERT INTO ax.project_evaluation (project_id, eval_kind, opinion, security_code) "
                         "VALUES (%s, 'EXPERT', '의견', 'PUBLIC')", (PROJECT,))
        conn.rollback()
        names = dict(conn.execute("SELECT code, name_ko FROM ax.code_program_type").fetchall())
        assert names["DEFENSE_TECH_PLAN"] == "국방기술기획" and names["CORE_TECH"] == "핵심기술개발"
        assert names["EXPORT_COMPETITIVENESS"] == "전략적 수출경쟁력 강화" and names["FORCE_SUPPORT"] == "무기체계 전력지원"
