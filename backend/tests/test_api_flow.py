"""API 전체 흐름: 문서 등록 → 성과카드 → 수요 → 매칭 → 검토 배정 → 의견 → 최종판정 → 이력·KPI."""
import pytest

from tests.conftest import as_user

PLANNER, REVIEWER, EXPERT, CURATOR, VIEWER = 1, 2, 3, 4, 5
state: dict = {}


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["schema_version"] == "0015"


async def test_auth_required(client):
    assert (await client.get("/cards")).status_code == 401
    r = await client.post("/demands", headers=as_user(VIEWER), json={"demand_no": "x", "title": "x", "tech_need": "x"})
    assert r.status_code == 403


async def test_register_document(client):
    r = await client.post("/documents", headers=as_user(CURATOR), json={
        "doc_type_code": "FINAL_REPORT", "title": "항재밍 데이터링크 결과보고서", "project_id": 1,
        "owner_dept_id": 3, "external_ref": "DOC-1", "version_label": "최종", "authored_at": "2025-01-15",
        "sections": [{"key": "s43", "section_no": "4.3", "heading": "미해결 기술 및 후속 연구 필요사항",
                      "page_start": 87, "page_end": 89}],
        "chunks": [
            {"content": "광대역 재밍 환경에서 주파수 도약 동기 유지 시간이 목표 10초 대비 6초로 부족하여 후속 연구가 필요함",
             "section_key": "s43", "page_start": 88, "location": {"paragraph": 2}},
            {"content": "시험은 실내 전파차폐실과 야외 시험장에서 수행하였으며 재밍 전력 30dBm 조건을 적용함",
             "section_key": "s43", "page_start": 89},
        ]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["embedded"] == 2
    state["chunk_ids"] = body["chunk_ids"]


async def _create_card(client, payload):
    r = await client.post("/cards", headers=as_user(CURATOR), json=payload)
    assert r.status_code == 201, r.text
    card_id = r.json()["id"]
    assert (await client.post(f"/cards/{card_id}/publish", headers=as_user(CURATOR))).status_code == 204
    return card_id


async def test_create_cards(client):
    state["card_a"] = await _create_card(client, {
        "card_no": "AC-0001", "project_id": 1, "title": "항재밍 주파수 도약 데이터링크",
        "core_achievement": "소형 무인기용 주파수 도약 기반 항재밍 데이터링크 시제 개발",
        "trl": 5, "dev_stage_code": "PROTOTYPE", "application_env": "소형 무인기 탑재, 야외 시험장 재밍 환경",
        "technologies": [{"tech_name": "주파수 도약 항재밍 데이터링크", "principle": "고속 주파수 도약과 적응형 채널 선택",
                          "is_primary": True, "evidence": [{"chunk_id": state["chunk_ids"][0]}]}],
        "performances": [{"metric_name": "동기 유지 시간", "target_value": 10, "achieved_value": 6, "unit": "s",
                          "is_achieved": False, "evidence": [{"chunk_id": state["chunk_ids"][0]}]}],
        "open_issues": [{"issue_type": "UNRESOLVED_TECH", "source": "REPORT",
                         "description": "광대역 재밍 환경에서 주파수 도약 동기 유지 시간 부족",
                         "evidence": [{"chunk_id": state["chunk_ids"][0], "quote": "동기 유지 시간이 목표 10초 대비 6초"}]}],
        "weapon_systems": [{"id": 1}],
        "companies": [{"id": 1, "relation_type": "TECH_HOLDER", "confidence": 0.6}],
    })
    state["card_b"] = await _create_card(client, {
        "card_no": "AC-0002", "project_id": 2, "title": "전술 배터리 열관리",
        "core_achievement": "상변화물질 기반 배터리 열관리 모듈", "trl": 6,
        "technologies": [{"tech_name": "상변화물질 열관리", "is_primary": True}],
    })
    state["card_c"] = await _create_card(client, {
        "card_no": "AC-0003", "project_id": 3, "title": "EO/IR 영상 표적 자동탐지",
        "core_achievement": "딥러닝 기반 EO/IR 영상 표적 자동탐지 알고리즘", "trl": 6,
        "technologies": [{"tech_name": "EO/IR 영상 딥러닝 표적 자동탐지", "is_primary": True}],
    })
    r = await client.get(f"/cards/{state['card_a']}", headers=as_user(PLANNER))
    card = r.json()
    assert card["status"] == "PUBLISHED" and len(card["evidence"]) == 3
    assert card["evidence"][0]["section_no"] == "4.3"


async def test_create_demand_and_match(client):
    r = await client.post("/demands", headers=as_user(PLANNER), json={
        "demand_no": "DM-2026-001", "title": "광대역 재밍 대응 정찰드론 데이터링크",
        "tech_need": "광대역 재밍 환경에서 드론 데이터링크 주파수 도약 동기 유지 시간 확보",
        "business_purpose": "미래 핵심기술 확보", "required_trl_min": 5, "required_trl_max": 7,
        "target_program_id": 2,
        "performance_reqs": [{"metric_name": "동기 유지 시간", "required_value": 10, "unit": "s"}],
        "technologies": [{"tech_name": "주파수 도약 항재밍 데이터링크"}, {"tech_name": "EO/IR 영상 딥러닝 표적 자동탐지"}],
        "weapon_system_ids": [1],
    })
    assert r.status_code == 201, r.text
    state["demand"] = r.json()["id"]

    r = await client.post(f"/demands/{state['demand']}/match", headers=as_user(PLANNER), json={"top_k": 10})
    assert r.status_code == 201, r.text
    run = (await client.get(f"/match-runs/{r.json()['id']}", headers=as_user(PLANNER))).json()
    assert run["status"] == "SUCCEEDED"
    recs = run["recommendations"]

    # 단일 성과 추천 중 1위는 미해결 기술이 수요와 직결되는 카드 A (후속형)
    top = next(x for x in recs if x["linkage_type_code"] != "CONVERGENCE")
    assert top["source_cards"][0]["card_id"] == state["card_a"]
    assert top["linkage_type_code"] == "FOLLOW_UP"
    assert top["evidence_count"] >= 2           # 카드 필드 근거 + RAG 근거
    assert top["owner_department"] == "무인미래통신기술팀"
    assert "동기 유지" in top["development_needs"]
    state["rec"] = top["recommendation_id"]

    conv = [x for x in recs if x["linkage_type_code"] == "CONVERGENCE"]
    assert conv and {c["card_id"] for c in conv[0]["source_cards"]} == {state["card_a"], state["card_c"]}

    detail = (await client.get(f"/recommendations/{state['rec']}", headers=as_user(PLANNER))).json()
    assert {s["criterion"] for s in detail["score_details"]} == {"TECH", "PERFORMANCE", "TRL", "ENVIRONMENT", "PURPOSE"}
    assert any(e["section_no"] == "4.3" and e["page_start"] == 88 for e in detail["evidence"])
    perf = next(s for s in detail["score_details"] if s["criterion"] == "PERFORMANCE")
    assert perf["method"] == "rule:metric_ratio" and float(perf["score"]) == pytest.approx(0.6)


async def test_evidence_hidden_without_document_access(client):
    # 전문가(지휘정찰팀)는 통신팀 소관 문서 열람권이 없다
    detail = (await client.get(f"/recommendations/{state['rec']}", headers=as_user(EXPERT))).json()
    assert detail["evidence_count"] >= 2 and detail["evidence"] == []


async def test_review_workflow(client):
    rec = state["rec"]
    r = await client.post(f"/recommendations/{rec}/assignments", headers=as_user(PLANNER),
                          json={"review_role": "EXPERT", "assignee_user_id": EXPERT})
    assert r.status_code == 201
    expert_assignment = r.json()["id"]
    r = await client.post(f"/recommendations/{rec}/assignments", headers=as_user(PLANNER),
                          json={"review_role": "DEPT_OWNER", "assignee_dept_id": 3})
    owner_assignment = r.json()["id"]

    queue = (await client.get("/reviews/queue", headers=as_user(EXPERT))).json()
    assert [q["assignment_id"] for q in queue] == [expert_assignment]

    r = await client.post(f"/recommendations/{rec}/decisions", headers=as_user(EXPERT), json={
        "decision_code": "ADOPT", "assignment_id": expert_assignment, "opinion": "후속형 적절",
        "relevance_rating": 5, "evidence_adequacy": 4, "dev_needs_accuracy": "CORRECT"})
    assert r.status_code == 201

    r = await client.post(f"/recommendations/{rec}/decisions", headers=as_user(EXPERT),
                          json={"decision_code": "ADOPT", "is_final": True})
    assert r.status_code == 403 and "최종판정 권한" in r.json()["detail"]

    r = await client.post(f"/recommendations/{rec}/decisions", headers=as_user(REVIEWER), json={
        "decision_code": "ADOPT", "is_final": True, "assignment_id": owner_assignment,
        "linkage_type_override": "ADVANCEMENT", "opinion": "성능 향상 성격이 강해 고도화형으로 조정"})
    assert r.status_code == 201

    detail = (await client.get(f"/recommendations/{rec}", headers=as_user(PLANNER))).json()
    assert detail["status"] == "DECIDED" and detail["final_decision_code"] == "ADOPT"
    assert detail["final_linkage_type_code"] == "ADVANCEMENT"
    assert {a["status"] for a in detail["assignments"]} == {"SUBMITTED"}

    hist = (await client.get(f"/recommendations/{rec}/history", headers=as_user(PLANNER))).json()
    assert [h["to_status"] for h in hist["status_history"]] == ["GENERATED", "ASSIGNED", "IN_REVIEW", "DECIDED"]
    assert hist["status_history"][-1]["changed_by"] == REVIEWER
    assert hist["status_history"][-1]["reason"] == "성능 향상 성격이 강해 고도화형으로 조정"
    assert any(a["table_name"] == "review_decision" for a in hist["audit"])


async def test_commercialization_candidates_and_confirmation(client):
    # 카드 A 의 기업 관계는 AI 추정(기본 '추가 확인 필요') → 사업화형 추천 시 확인사항이 생긴다
    r = await client.post("/demands", headers=as_user(PLANNER), json={
        "demand_no": "DM-2026-002", "title": "항재밍 데이터링크 모뎀 국산화",
        "tech_need": "주파수 도약 항재밍 데이터링크 모뎀 국산화", "business_purpose": "수입 부품의 국산화",
        "required_trl_min": 5, "target_program_id": 1})
    demand = r.json()["id"]
    run_id = (await client.post(f"/demands/{demand}/match", headers=as_user(PLANNER))).json()["id"]
    recs = (await client.get(f"/match-runs/{run_id}", headers=as_user(PLANNER))).json()["recommendations"]
    com = next(x for x in recs if x["source_cards"][0]["card_id"] == state["card_a"])
    assert com["linkage_type_code"] == "COMMERCIALIZATION"
    detail = (await client.get(f"/recommendations/{com['recommendation_id']}", headers=as_user(PLANNER))).json()
    assert detail["companies"][0]["name"] == "(주)테스트방산"
    item = detail["confirmations"][0]
    assert item["subject_type"] == "COMPANY" and item["status"] == "OPEN"
    r = await client.patch(f"/confirmations/{item['id']}", headers=as_user(PLANNER),
                           json={"status": "RESOLVED", "resolution_note": "기술보유 확인"})
    assert r.status_code == 204


async def test_kpi(client):
    rows = (await client.get("/kpi/recommendations", headers=as_user(PLANNER))).json()
    first = rows[0]
    assert first["finally_reviewed"] == 1 and first["adopted"] == 1
    assert float(first["evidence_coverage_pct"]) > 0
