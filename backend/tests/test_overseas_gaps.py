"""갭 분석 API: 자동 실행 · 판정 결과 · 보안등급 · 검수 판정 · 재실행 (해외 수요 테스트 뒤에 돈다)."""
import psycopg
import pytest

from tests.conftest import ROOT, TEST_URL, as_user

PLANNER, REVIEWER, EXPERT, CURATOR, VIEWER = 1, 2, 3, 4, 5
SEED_XLSX = ROOT / "seeds" / "overseas" / "전차파워팩_해외수요.xlsx"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# hash 임베더는 뜻을 모르므로 판정 흐름 검사에서는 유사도 기준을 끈다 (모든 확정 카드를 '비슷함'으로)
LOOSE = {"coverage_threshold": -1, "issue_threshold": -1}

_state: dict = {}


async def _publish(client, body: dict) -> int:
    r = await client.post("/cards", headers=as_user(CURATOR), json=body)
    assert r.status_code == 201, r.text
    card_id = r.json()["id"]
    assert (await client.post(f"/cards/{card_id}/publish", headers=as_user(CURATOR))).status_code == 204
    return card_id


@pytest.fixture
async def seeded(client):
    if _state:
        return _state
    r = await client.post("/overseas/import", headers=as_user(PLANNER),
                          files={"file": ("해외수요.xlsx", SEED_XLSX.read_bytes(), XLSX)})
    assert r.status_code == 200, r.text
    _state["import_run"] = r.json()["gap_run_id"]
    _state["tm"] = await _publish(client, {
        "card_no": "AC-GAP-TM", "project_id": 2, "title": "전차 파워팩 국산 자동변속기",
        "core_achievement": "1,500마력급 전차 자동변속기 국산화", "trl": 8,
        "technologies": [{"tech_name": "전차용 고출력 자동변속기", "is_primary": True}],
        "performances": [{"metric_name": "내구도 검사 시간", "target_value": 320, "achieved_value": 306,
                          "unit": "h", "is_achieved": False}],
        "open_issues": [{"issue_type": "UNMET_TARGET", "description": "내구도 기준 320시간 미달", "priority": "HIGH"}]})
    _state["eng"] = await _publish(client, {
        "card_no": "AC-GAP-ENG", "project_id": 2, "title": "전차 파워팩 국산 디젤엔진",
        "core_achievement": "1,500마력급 전차 디젤엔진 국산화", "trl": 9,
        "technologies": [{"tech_name": "전차용 고출력 디젤엔진", "is_primary": True}],
        "performances": [{"metric_name": "최대출력", "target_value": 1500, "achieved_value": 1500, "unit": "마력",
                          "is_achieved": True}],
        "open_issues": [{"issue_type": "FOLLOW_UP_NEED", "priority": "HIGH",
                         "description": "수출국 현지 조립생산·정비 요구에 맞춘 엔진 정비 문서·교육 패키지 필요"}]})
    demands = (await client.get("/overseas/demands", headers=as_user(PLANNER))).json()
    _state["d"] = {d["demand_no"]: d["id"] for d in demands}
    return _state


async def _findings(client, run_id: int, user=PLANNER) -> list[dict]:
    r = await client.get(f"/gaps/runs/{run_id}", headers=as_user(user))
    assert r.status_code == 200, r.text
    return r.json()["findings"]


async def test_runs_automatically_on_import_and_publish(client, seeded):
    assert seeded["import_run"] is not None
    runs = (await client.get("/gaps/runs", headers=as_user(VIEWER))).json()
    kinds = {r["trigger_kind"] for r in runs}
    assert {"NEW_DEMAND", "NEW_CARD"} <= kinds
    assert all(r["rules_version"] for r in runs)


async def test_manual_run_finds_expected_gap_types(client, seeded):
    r = await client.post("/gaps/runs", headers=as_user(PLANNER), json={"rules": LOOSE, "note": "흐름 검사"})
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["demand_count"] >= 9 and run["finding_count"] > 0
    found = await _findings(client, run["id"])
    by = {(f["demand_no"], f["gap_type_code"]): f for f in found}

    # D08 수출형 파워팩 제원 ↔ 국산 변속기 내구도 306/320h → 성능미달, 고도화형 경로 (정답 G01)
    perf = by[("D08", "PERFORMANCE_SHORT")]
    detail = (await client.get(f"/gaps/findings/{perf['id']}", headers=as_user(PLANNER))).json()
    ev = {c["card_id"]: c for c in detail["cards"] if c["role"] == "EVIDENCE"}
    assert seeded["tm"] in ev and "306" in ev[seeded["tm"]]["note"]
    assert detail["pathways"][0]["linkage_type_code"] == "ADVANCEMENT"
    assert detail["sources"] and detail["sources"][0]["url"].startswith("https://")
    assert detail["security_code"] != "PUBLIC"  # 국내 카드(대내 이상)가 근거라 공개자료보다 높다

    # D09 현지 정비 요구 ↔ 엔진 카드의 미해결 현지화 과제 → 국산화·현지화, 사업화형 (정답 G02)
    loc = by[("D09", "LOCALIZATION")]
    detail = (await client.get(f"/gaps/findings/{loc['id']}", headers=as_user(PLANNER))).json()
    assert seeded["eng"] in {c["card_id"] for c in detail["cards"] if c["role"] == "EVIDENCE"}
    assert "COMMERCIALIZATION" in {p["linkage_type_code"] for p in detail["pathways"]}

    # 모두 초안, 점수 순
    assert {f["status"] for f in found} == {"DRAFT"}
    assert [f["score"] for f in found] == sorted((f["score"] for f in found), reverse=True)
    _state["loose_run"] = run["id"]


async def test_no_coverage_when_threshold_is_strict(client, seeded):
    r = await client.post("/gaps/runs", headers=as_user(CURATOR),
                          json={"demand_ids": [seeded["d"]["D02"]], "rules": {"coverage_threshold": 1}})
    assert r.status_code == 201, r.text
    found = await _findings(client, r.json()["id"])
    assert [f["gap_type_code"] for f in found] == ["NO_COVERAGE"]
    detail = (await client.get(f"/gaps/findings/{found[0]['id']}", headers=as_user(PLANNER))).json()
    assert {p["linkage_type_code"] for p in detail["pathways"]} >= {None}  # 신규 기획수요 경로
    assert all(c["role"] == "NEAREST" for c in detail["cards"])


async def test_security_hides_gaps_from_lower_clearance(client, seeded):
    found = await _findings(client, _state["loose_run"])
    internal = next(f for f in found if f["security_code"] != "PUBLIC")
    assert (await client.get(f"/gaps/findings/{internal['id']}", headers=as_user(VIEWER))).status_code == 404
    seen = (await client.get("/gaps/findings?status=all", headers=as_user(VIEWER))).json()
    assert all(f["security_code"] == "PUBLIC" for f in seen)
    # DB 규칙: 근거 카드보다 낮은 등급으로 내릴 수 없다
    with psycopg.connect(TEST_URL) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE ax.gap_finding SET security_code = 'PUBLIC' WHERE id = %s", (internal["id"],))
        conn.commit()


async def test_roles_and_validation(client, seeded):
    assert (await client.post("/gaps/runs", headers=as_user(VIEWER), json={})).status_code == 403
    r = await client.post("/gaps/runs", headers=as_user(PLANNER), json={"demand_ids": [987654]})
    assert r.status_code == 422
    r = await client.post("/gaps/runs", headers=as_user(PLANNER), json={"rules": {"min_trl": 12}})
    assert r.status_code == 422


async def test_decision_flow_and_rerun(client, seeded):
    found = await _findings(client, _state["loose_run"])
    perf = next(f for f in found if (f["demand_no"], f["gap_type_code"]) == ("D08", "PERFORMANCE_SHORT"))
    url = f"/gaps/findings/{perf['id']}/decision"
    # 최종판정은 소관부서 검수자만
    assert (await client.post(url, headers=as_user(PLANNER), json={"decision": "CONFIRM"})).status_code == 403
    assert (await client.post(url, headers=as_user(REVIEWER), json={"decision": "REJECT"})).status_code == 422
    assert (await client.post(url, headers=as_user(REVIEWER), json={"decision": "CONFIRM"})).status_code == 204
    r = await client.post(url, headers=as_user(REVIEWER), json={"decision": "REJECT", "reason": "다시"})
    assert r.status_code == 422  # 이미 확정
    # DB 규칙: 권한 없는 사람의 판정은 DB 가 막는다
    other = next(f for f in found if f["id"] != perf["id"] and f["status"] == "DRAFT")
    with psycopg.connect(TEST_URL) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE ax.gap_finding SET status = 'CONFIRMED', decided_by = %s, decided_at = now() "
                     "WHERE id = %s", (PLANNER, other["id"]))

    d08 = seeded["d"]["D08"]
    # 같은 기준으로 다시 돌리면: 확정된 종류는 다시 초안으로 올리지 않고, 예전 초안은 대체된다
    rerun = (await client.post("/gaps/runs", headers=as_user(PLANNER),
                               json={"demand_ids": [d08], "rules": LOOSE})).json()
    new_types = {f["gap_type_code"] for f in await _findings(client, rerun["id"])}
    assert "PERFORMANCE_SHORT" not in new_types
    all_d08 = (await client.get(f"/gaps/findings?status=all&demand_id={d08}", headers=as_user(PLANNER))).json()
    confirmed = next(f for f in all_d08 if f["id"] == perf["id"])
    assert confirmed["status"] == "CONFIRMED" and confirmed["maybe_resolved_at"] is None
    assert all(f["status"] in ("SUPERSEDED", "CONFIRMED") for f in all_d08 if f["gap_run_id"] == _state["loose_run"])

    # 엄격한 기준에서는 성능미달이 안 나온다 → 확정된 갭에 '해소 후보' 표시
    await client.post("/gaps/runs", headers=as_user(PLANNER), json={"demand_ids": [d08], "rules": {"coverage_threshold": 1}})
    confirmed = (await client.get(f"/gaps/findings/{perf['id']}", headers=as_user(PLANNER))).json()
    assert confirmed["status"] == "CONFIRMED" and confirmed["maybe_resolved_at"] is not None
    assert confirmed["decided_by"] == REVIEWER

    summary = (await client.get("/gaps/summary", headers=as_user(PLANNER))).json()
    row = next(s for s in summary if s["demand_no"] == "D08")
    assert row["gaps"]["PERFORMANCE_SHORT"]["status"] == "CONFIRMED"
