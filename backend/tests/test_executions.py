"""연계 실행 결과와 순환: 채택 추천만 기록 · 과제 관계 · 검증 케이스 · 계보 · 지표 · 권한."""
import psycopg
import pytest

from tests.conftest import TEST_URL, as_user

PLANNER, REVIEWER, EXPERT, CURATOR, VIEWER, AGENCY = 1, 2, 3, 4, 5, 6
_s: dict = {}


async def _card(client, card_no, project_id, title, tech):
    r = await client.post("/documents", headers=as_user(CURATOR), json={
        "doc_type_code": "FINAL_REPORT", "title": f"{title} 결과보고서", "project_id": project_id,
        "external_ref": f"DOC-{card_no}", "chunks": [{"content": f"{tech} 시제 개발, 후속 성능 향상 필요", "page_start": 12}]})
    assert r.status_code == 201, r.text
    chunk = r.json()["chunk_ids"][0]
    r = await client.post("/cards", headers=as_user(CURATOR), json={
        "card_no": card_no, "project_id": project_id, "title": title, "core_achievement": title, "trl": 6,
        "technologies": [{"tech_name": tech, "is_primary": True, "evidence": [{"chunk_id": chunk}]}],
        "open_issues": [{"issue_type": "UNRESOLVED_TECH", "description": f"{tech} 성능 향상 필요"}]})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert (await client.post(f"/cards/{cid}/publish", headers=as_user(CURATOR))).status_code == 204
    return cid


@pytest.fixture
async def recs(client):
    """통신팀 과제 성과 → 기획수요 추천. 1위는 채택, 2위는 판정 전."""
    if _s:
        return _s
    card = await _card(client, "AC-EX-01", 1, "위성 통신 안테나 빔 조향", "위성 통신 위상배열 안테나 빔 조향")
    await _card(client, "AC-EX-03", 2, "위성 통신 단말 전원 관리", "위성 통신 단말 위상배열 전원 관리")
    r = await client.post("/demands", headers=as_user(PLANNER), json={
        "demand_no": "DM-EX-001", "title": "기동형 위성 통신 단말 안테나",
        "tech_need": "위성 통신 위상배열 안테나 빔 조향 성능 향상", "business_purpose": "미래 핵심기술 확보",
        "required_trl_min": 5, "technologies": [{"tech_name": "위성 통신 위상배열 안테나 빔 조향"}]})
    assert r.status_code == 201, r.text
    demand = r.json()["id"]
    run = (await client.post(f"/demands/{demand}/match", headers=as_user(PLANNER), json={"top_k": 5})).json()["id"]
    recs = (await client.get(f"/match-runs/{run}", headers=as_user(PLANNER))).json()["recommendations"]
    assert len(recs) >= 2, [(x["source_cards"], x["linkage_type_code"]) for x in recs]
    top = next(x for x in recs if x["source_cards"][0]["card_id"] == card and x["linkage_type_code"] != "CONVERGENCE")
    other = next(x for x in recs if x["recommendation_id"] != top["recommendation_id"])
    a = (await client.post(f"/recommendations/{top['recommendation_id']}/assignments", headers=as_user(PLANNER),
                           json={"review_role": "DEPT_OWNER", "assignee_dept_id": 3})).json()["id"]
    r = await client.post(f"/recommendations/{top['recommendation_id']}/decisions", headers=as_user(REVIEWER),
                          json={"decision_code": "ADOPT", "is_final": True, "assignment_id": a})
    assert r.status_code == 201, r.text
    _s.update(card=card, demand=demand, top=top["recommendation_id"], other=other)
    return _s


async def test_candidates_are_adopted_only(client, recs):
    rows = (await client.get("/executions/candidates", headers=as_user(PLANNER))).json()
    ids = {r["recommendation_id"] for r in rows}
    assert recs["top"] in ids and recs["other"]["recommendation_id"] not in ids
    assert (await client.get("/executions/candidates", headers=as_user(EXPERT))).status_code == 403


async def test_only_adopted_recommendation_can_be_executed(client, recs):
    r = await client.post("/executions", headers=as_user(PLANNER), json={
        "recommendation_id": recs["other"]["recommendation_id"], "execution_type": "NEW_PROJECT"})
    assert r.status_code == 422 and "채택" in r.json()["detail"]


async def test_reviewer_of_other_department_cannot_record(client, recs):
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute("INSERT INTO ax.app_user (id, login_id, name, department_id, clearance_code) "
                     "VALUES (20, 'rev2', '지휘정찰 검수자', 2, 'RESTRICTED') ON CONFLICT DO NOTHING")
        conn.execute("INSERT INTO ax.user_role (user_id, role_code) VALUES (20, 'DEPT_REVIEWER') ON CONFLICT DO NOTHING")
    r = await client.post("/executions", headers=as_user(20), json={
        "recommendation_id": recs["top"], "execution_type": "NEW_PROJECT"})
    assert r.status_code == 403


async def test_record_execution_creates_project_relation(client, recs):
    # 담당부서(통신팀) 검수자가 기록: 새 과제(임시 번호)로 이어짐
    r = await client.post("/executions", headers=as_user(REVIEWER), json={
        "recommendation_id": recs["top"], "execution_type": "NEW_PROJECT", "status": "IN_PROGRESS",
        "executed_on": "2026-11-20", "note": "후속 과제 기획 착수",
        "new_project": {"project_no": "PRJ-2027-EX1", "title": "기동형 위성 통신 단말 안테나 후속 개발"}})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["project_relation_id"] and body["eval_case_id"] is None   # 아직 진행 중
    _s["ex"] = body["id"]
    rows = (await client.get("/executions", headers=as_user(PLANNER))).json()
    ex = next(x for x in rows if x["id"] == body["id"])
    assert ex["source_project_no"] == "PRJ-2022-001" and ex["resulting_project_no"] == "PRJ-2027-EX1"
    assert ex["discovered_by_ax"] is True and ex["status_name"] == "진행 중" and ex["execution_type_name"] == "신규 과제"
    _s["new_project"] = ex["resulting_project_id"]
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        rel = conn.execute("SELECT from_project_id, relation_type, is_actual_relay, linkage_type_code "
                           "FROM ax.project_relation WHERE id = %s", (body["project_relation_id"],)).fetchone()
        assert rel[0] == 1 and rel[1] == "PRECEDES" and rel[2] is True and rel[3]
        st = conn.execute("SELECT status_code, source_system_code FROM ax.project WHERE project_no = 'PRJ-2027-EX1'").fetchone()
        assert st == ("PLANNING", "MANUAL")


async def test_complete_creates_eval_case_once(client, recs):
    r = await client.patch(f"/executions/{_s['ex']}", headers=as_user(PLANNER),
                           json={"status": "COMPLETED", "result_note": "후속 과제 선정 (3년)"})
    assert r.status_code == 200, r.text
    case = r.json()["eval_case_id"]
    assert case
    r = await client.patch(f"/executions/{_s['ex']}", headers=as_user(PLANNER), json={"result_note": "예산 확정"})
    assert r.json()["eval_case_id"] == case
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        row = conn.execute("""SELECT c.case_type, c.demand_id, g.expected_card_id, g.expected_project_id, g.importance
                                FROM ax.eval_case c JOIN ax.eval_ground_truth g ON g.case_id = c.id
                               WHERE c.id = %s""", (case,)).fetchone()
        assert row == ("HISTORICAL_RELAY", recs["demand"], recs["card"], _s["new_project"], "MAJOR")


async def test_lineage_and_cycle(client, recs):
    # 이어진 과제가 끝나 새 성과카드가 생기면, 그 카드가 다시 '기존 성과'가 된다
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute("UPDATE ax.project SET status_code = 'COMPLETED' WHERE id = %s", (_s["new_project"],))
    child = await _card(client, "AC-EX-02", _s["new_project"], "기동형 위성 통신 안테나 2세대", "저궤도 위성 추적 빔 조향")
    lin = (await client.get(f"/executions/lineage/cards/{recs['card']}", headers=as_user(PLANNER))).json()
    assert lin["card"]["project_no"] == "PRJ-2022-001"
    first = lin["descendants"][0]
    assert first["level"] == 1 and first["resulting_project_no"] == "PRJ-2027-EX1"
    assert [c["card_id"] for c in first["next_cards"]] == [child]
    up = (await client.get(f"/executions/lineage/cards/{child}", headers=as_user(REVIEWER))).json()
    assert up["ancestors"][0]["project_no"] == "PRJ-2022-001" and up["ancestors"][0]["linkage_type_name"]
    assert any(c["card_id"] == recs["card"] for c in up["ancestors"][0]["cards"])


async def test_manual_execution_without_recommendation(client, recs):
    # AI 추천 없이 사람이 찾은 연계: 출처 성과·연계유형 필수, AX 발굴로 세지 않음
    r = await client.post("/executions", headers=as_user(PLANNER), json={"execution_type": "TECH_TRANSFER"})
    assert r.status_code == 422
    r = await client.post("/executions", headers=as_user(PLANNER), json={
        "source_card_id": recs["card"], "linkage_type_code": "COMMERCIALIZATION", "execution_type": "TECH_TRANSFER",
        "organization_id": 1, "status": "PLANNED"})
    assert r.status_code == 201, r.text
    # 출처 성과의 과제로 이어질 수는 없다
    r = await client.post("/executions", headers=as_user(PLANNER), json={
        "source_card_id": recs["card"], "linkage_type_code": "FOLLOW_UP", "execution_type": "NEW_PROJECT",
        "resulting_project_id": 1})
    assert r.status_code == 422


async def test_kpi(client, recs):
    k = (await client.get("/executions/kpi", headers=as_user(PLANNER))).json()
    assert k["adopted"] >= 1 and k["adopted_executed"] >= 1 and 0 < k["conversion_pct"] <= 100
    assert k["executions"] >= 2 and k["completed"] >= 1 and k["eval_cases"] >= 1
    assert k["discovered_by_ax"] >= 1 and k["discovered_by_ax"] < k["executions"]
    assert k["resulting_projects"] >= 1 and k["resulting_cards"] >= 1
    assert k["by_type"]["신규 과제"] >= 1 and k["by_type"]["기술이전"] >= 1


async def test_low_clearance_sees_nothing(client, recs):
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute("INSERT INTO ax.user_role (user_id, role_code) VALUES (5, 'DEPT_REVIEWER') ON CONFLICT DO NOTHING")
    try:
        assert (await client.get("/executions", headers=as_user(VIEWER))).json() == []
        assert (await client.get("/executions/kpi", headers=as_user(VIEWER))).json()["executions"] == 0
        assert (await client.get(f"/executions/lineage/cards/{recs['card']}", headers=as_user(VIEWER))).status_code == 404
    finally:
        with psycopg.connect(TEST_URL, autocommit=True) as conn:
            conn.execute("DELETE FROM ax.user_role WHERE user_id = 5 AND role_code = 'DEPT_REVIEWER'")
