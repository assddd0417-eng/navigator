"""통합기획 검토: 후보 검토표 생성·권한·확정 · 통합기획 자료 초안 · 회의 결정 · 엑셀."""
from io import BytesIO

import psycopg
import pytest
from openpyxl import load_workbook

from tests.conftest import TEST_URL, as_user

PLANNER, REVIEWER, EXPERT, CURATOR, VIEWER, AGENCY = 1, 2, 3, 4, 5, 6
_s: dict = {}


@pytest.fixture
async def recs(client):
    """통신팀 종료과제 성과로 만든 추천이 있고, 그중 1위는 담당부서가 최종 판정한 상태."""
    if _s:
        return _s
    r = await client.post("/documents", headers=as_user(CURATOR), json={
        "doc_type_code": "FINAL_REPORT", "title": "검토표 시험용 결과보고서", "project_id": 1, "owner_dept_id": 3,
        "external_ref": "DOC-RS-1", "version_label": "최종", "authored_at": "2025-01-15",
        "chunks": [{"content": "수중 음향 통신 모뎀의 전송 거리가 목표 5km 대비 3km 로 부족하여 후속 연구가 필요함",
                    "page_start": 41}]})
    assert r.status_code == 201, r.text
    chunk = r.json()["chunk_ids"][0]
    r = await client.post("/cards", headers=as_user(CURATOR), json={
        "card_no": "AC-RS-01", "project_id": 1, "title": "수중 음향 통신 모뎀",
        "core_achievement": "수중 무인체용 음향 통신 모뎀 시제", "trl": 5,
        "technologies": [{"tech_name": "수중 음향 통신 모뎀", "is_primary": True, "evidence": [{"chunk_id": chunk}]}],
        "performances": [{"metric_name": "전송 거리", "target_value": 5, "achieved_value": 3, "unit": "km",
                          "is_achieved": False, "evidence": [{"chunk_id": chunk}]}],
        "open_issues": [{"issue_type": "UNRESOLVED_TECH", "description": "수중 음향 통신 전송 거리 부족",
                         "evidence": [{"chunk_id": chunk}]}]})
    assert r.status_code == 201, r.text
    card = r.json()["id"]
    assert (await client.post(f"/cards/{card}/publish", headers=as_user(CURATOR))).status_code == 204
    r = await client.post("/demands", headers=as_user(PLANNER), json={
        "demand_no": "DM-RS-001", "title": "무인잠수정 수중 통신 거리 확대",
        "tech_need": "수중 음향 통신 모뎀 전송 거리 5km 이상 확보", "business_purpose": "미래 핵심기술 확보",
        "required_trl_min": 5, "target_program_id": 1,
        "performance_reqs": [{"metric_name": "전송 거리", "required_value": 5, "unit": "km"}],
        "technologies": [{"tech_name": "수중 음향 통신 모뎀"}]})
    assert r.status_code == 201, r.text
    demand = r.json()["id"]
    run = (await client.post(f"/demands/{demand}/match", headers=as_user(PLANNER), json={"top_k": 5})).json()["id"]
    recs = (await client.get(f"/match-runs/{run}", headers=as_user(PLANNER))).json()["recommendations"]
    top = next(x for x in recs if x["source_cards"][0]["card_id"] == card and x["linkage_type_code"] != "CONVERGENCE")
    r = await client.post(f"/recommendations/{top['recommendation_id']}/assignments", headers=as_user(PLANNER),
                          json={"review_role": "DEPT_OWNER", "assignee_dept_id": 3})
    assert r.status_code == 201, r.text
    r = await client.post(f"/recommendations/{top['recommendation_id']}/decisions", headers=as_user(REVIEWER),
                          json={"decision_code": "ADOPT", "is_final": True, "assignment_id": r.json()["id"],
                                "opinion": "후속 과제로 추진 검토"})
    assert r.status_code == 201, r.text
    _s.update(card=card, demand=demand, run=run, top=top["recommendation_id"], recs=recs)
    return _s


async def test_only_planner_creates_and_readers_see(client, recs):
    body = {"sheet_scope": "DEMAND", "demand_id": recs["demand"]}
    for uid in (REVIEWER, EXPERT, CURATOR, VIEWER):
        assert (await client.post("/review-sheets", headers=as_user(uid), json=body)).status_code == 403
    assert (await client.get("/review-sheets", headers=as_user(EXPERT))).status_code == 403
    assert (await client.post("/review-sheets", headers=as_user(PLANNER),
                              json={"sheet_scope": "DEMAND"})).status_code == 422


async def test_create_demand_sheet_with_snapshot_and_summary(client, recs):
    r = await client.post("/review-sheets", headers=as_user(PLANNER),
                          json={"sheet_scope": "DEMAND", "demand_id": recs["demand"], "per_target": 3})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    _s["sheet"] = sid
    s = (await client.get(f"/review-sheets/{sid}", headers=as_user(REVIEWER))).json()
    assert s["status"] == "DRAFT" and s["security_code"] == "INTERNAL" and "신규 기획수요" in s["title"]
    assert 1 <= len(s["items"]) <= 3
    first = s["items"][0]
    assert first["recommendation_id"] == recs["top"]
    snap = first["snapshot"]
    assert snap["demand_title"] == "무인잠수정 수중 통신 거리 확대"
    assert snap["source_cards"][0]["project_no"] == "PRJ-2022-001"
    assert snap["owner_departments"] == ["무인미래통신기술팀"]
    assert snap["evidence"] and snap["evidence"][0]["page_start"] == 41
    assert snap["rationale"]
    assert first["live"]["final_decision_name"] == "채택"
    summ = s["summary"]
    assert summ["candidates"] == len(s["items"]) and summ["decided"] >= 1 and summ["adopted"] >= 1
    assert 0 < summ["final_review_rate_pct"] <= 100
    lst = (await client.get("/review-sheets", headers=as_user(PLANNER))).json()
    assert any(x["id"] == sid and x["decided_count"] >= 1 for x in lst)


async def test_department_and_scope_filters(client, recs):
    # 다른 부서(지휘정찰팀) 대상이면 통신팀 과제 성과 추천은 빠진다
    r = await client.post("/review-sheets", headers=as_user(PLANNER),
                          json={"sheet_scope": "DEMAND", "demand_id": recs["demand"], "department_id": 2})
    if r.status_code == 201:
        s = (await client.get(f"/review-sheets/{r.json()['id']}", headers=as_user(PLANNER))).json()
        assert all(i["recommendation_id"] != recs["top"] for i in s["items"])
    else:
        assert r.status_code == 409
    r = await client.post("/review-sheets", headers=as_user(PLANNER),
                          json={"sheet_scope": "COMPLETED_PROJECT_UTILIZATION", "department_id": 3})
    assert r.status_code == 201, r.text
    s = (await client.get(f"/review-sheets/{r.json()['id']}", headers=as_user(PLANNER))).json()
    assert all(c["project_status"] == "COMPLETED" for i in s["items"] for c in i["snapshot"]["source_cards"])
    assert "무인미래통신기술팀" in s["title"]
    # 부품국산화 사업 대상 수요 ← 핵심기술 사업 과제 성과: 사업트랙 간 연계
    r = await client.post("/review-sheets", headers=as_user(PLANNER),
                          json={"sheet_scope": "CROSS_PROGRAM", "demand_id": recs["demand"]})
    assert r.status_code == 201, r.text


async def test_low_clearance_cannot_see_sheet(client, recs):
    # 공개 등급 사용자에게 검토 역할이 있어도 '내부' 등급 검토표는 안 보인다
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute("INSERT INTO ax.user_role (user_id, role_code) VALUES (5, 'DEPT_REVIEWER') ON CONFLICT DO NOTHING")
    try:
        assert (await client.get(f"/review-sheets/{_s['sheet']}", headers=as_user(VIEWER))).status_code == 404
        assert all(x["id"] != _s["sheet"] for x in (await client.get("/review-sheets", headers=as_user(VIEWER))).json())
    finally:
        with psycopg.connect(TEST_URL, autocommit=True) as conn:
            conn.execute("DELETE FROM ax.user_role WHERE user_id = 5 AND role_code = 'DEPT_REVIEWER'")


async def test_meeting_decisions_and_draft(client, recs):
    sid = _s["sheet"]
    r = await client.post("/meetings", headers=as_user(PLANNER),
                          json={"title": "11월 통합기획 회의", "department_ids": [1, 3]})
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    # 회의에 올리지 않은 추천은 결정에 연결할 수 없다
    r = await client.post(f"/meetings/{mid}/decisions", headers=as_user(PLANNER),
                          json={"decision": "후속 과제 기획", "recommendation_id": recs["top"]})
    assert r.status_code == 422
    assert (await client.patch(f"/review-sheets/{sid}", headers=as_user(PLANNER),
                               json={"meeting_id": mid})).status_code == 204
    r = await client.post(f"/meetings/{mid}/decisions", headers=as_user(PLANNER), json={
        "decision": "수중 통신 후속 과제 기획 착수", "recommendation_id": recs["top"],
        "follow_up_action": "기획서 초안 작성", "owner_dept_id": 3, "due_date": "2026-12-15"})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    assert (await client.post(f"/meetings/{mid}/decisions", headers=as_user(REVIEWER),
                              json={"decision": "x 결정"})).status_code == 403
    # 담당 부서 검수자는 후속조치 상태를 바꿀 수 있다
    assert (await client.patch(f"/meeting-decisions/{did}", headers=as_user(REVIEWER),
                               json={"status": "DONE"})).status_code == 204
    m = (await client.get(f"/meetings/{mid}", headers=as_user(REVIEWER))).json()
    assert [x["id"] for x in m["sheets"]] == [sid] and m["decisions"][0]["status"] == "DONE"
    assert {d["name"] for d in m["departments"]} == {"과제기획팀", "무인미래통신기술팀"}

    r = await client.post(f"/review-sheets/{sid}/drafts", headers=as_user(PLANNER))
    assert r.status_code == 201, r.text
    d = (await client.get(f"/planning-drafts/{r.json()['id']}", headers=as_user(REVIEWER))).json()
    assert d["version"] == 1 and d["evidence_count"] >= 1
    md = d["content_md"]
    for part in ("## 2. 후보 요약", "## 3. 후보별 검토 내용", "## 4. 회의 상정 사항", "## 5. 회의 결정·후속조치",
                 "## 원문 근거", "수중 통신 후속 과제 기획 착수", "채택", "[1]"):
        assert part in md, part
    assert d["content_struct"]["decided"] >= 1
    r2 = await client.post(f"/review-sheets/{sid}/drafts", headers=as_user(PLANNER))
    assert (await client.get(f"/planning-drafts/{r2.json()['id']}", headers=as_user(PLANNER))).json()["version"] == 2
    r = await client.get(f"/planning-drafts/{d['id']}/export.md", headers=as_user(PLANNER))
    assert r.status_code == 200 and r.text.startswith("# 통합기획 검토자료")
    assert (await client.patch(f"/planning-drafts/{d['id']}", headers=as_user(PLANNER),
                               json={"status": "REVIEWED"})).status_code == 204


async def test_export_xlsx(client, recs):
    r = await client.get(f"/review-sheets/{_s['sheet']}/export.xlsx", headers=as_user(REVIEWER))
    assert r.status_code == 200, r.text
    wb = load_workbook(BytesIO(r.content))
    assert wb.sheetnames == ["검토표", "회의 결정", "작성기준"]
    ws = wb["검토표"]
    header = [c.value for c in ws[1]]
    assert header[:3] == ["번호", "연계 대상", "기존 성과 (과제번호)"] and "원문 근거" in header
    row = [c.value for c in ws[2]]
    assert row[1] == "무인잠수정 수중 통신 거리 확대" and row[header.index("최종 판정")] == "채택"
    assert "p.41" in row[header.index("원문 근거")]


async def test_finalize_locks_items(client, recs):
    sid = _s["sheet"]
    s = (await client.get(f"/review-sheets/{sid}", headers=as_user(PLANNER))).json()
    if len(s["items"]) > 1:
        last = s["items"][-1]["recommendation_id"]
        assert (await client.delete(f"/review-sheets/{sid}/items/{last}", headers=as_user(PLANNER))).status_code == 204
    assert (await client.post(f"/review-sheets/{sid}/finalize", headers=as_user(PLANNER))).status_code == 204
    assert (await client.post(f"/review-sheets/{sid}/finalize", headers=as_user(PLANNER))).status_code == 409
    keep = s["items"][0]["recommendation_id"]
    r = await client.delete(f"/review-sheets/{sid}/items/{keep}", headers=as_user(PLANNER))
    assert r.status_code == 422 and "확정된 검토표" in r.json()["detail"]
    s = (await client.get(f"/review-sheets/{sid}", headers=as_user(PLANNER))).json()
    assert s["status"] == "FINALIZED" and s["finalized_by_name"] == "기획담당"
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        n = conn.execute("SELECT count(*) FROM ax.audit_log WHERE table_name = 'relay_review_sheet' "
                         "AND row_pk = jsonb_build_object('id', %s::bigint)", (sid,)).fetchone()[0]
        assert n >= 2  # 생성 + 회의 연결 + 확정
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE ax.relay_review_sheet SET status = 'DRAFT' WHERE id = %s", (sid,))


async def test_sheet_cannot_hold_higher_classified_recommendation(client, recs):
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        sid = conn.execute("INSERT INTO ax.relay_review_sheet (title, sheet_scope, security_code) "
                           "VALUES ('공개 검토표', 'CUSTOM', 'PUBLIC') RETURNING id").fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("INSERT INTO ax.relay_review_sheet_item (sheet_id, recommendation_id, sort_order, snapshot) "
                         "VALUES (%s, %s, 1, '{}')", (sid, recs["top"]))
