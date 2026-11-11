"""기관 포트폴리오 API: 보는 역할 · 등급별 집계 · 정책 기획 후보 · 갭 → 기획수요 넘기기 · 엑셀."""
from io import BytesIO

import psycopg
import pytest
from openpyxl import load_workbook

from tests.conftest import ROOT, TEST_URL, as_user

PLANNER, REVIEWER, EXPERT, CURATOR, VIEWER, AGENCY = 1, 2, 3, 4, 5, 6
SEED_XLSX = ROOT / "seeds" / "overseas" / "전차파워팩_해외수요.xlsx"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
LOOSE = {"coverage_threshold": -1, "issue_threshold": -1}

_state: dict = {}


@pytest.fixture
async def gaps(client):
    """해외 수요·국내 성과 카드가 있고, 갭 하나는 확정·하나는 검수 전인 상태."""
    if _state:
        return _state
    demands = (await client.get("/overseas/demands", headers=as_user(PLANNER))).json()
    if not demands:
        r = await client.post("/overseas/import", headers=as_user(PLANNER),
                              files={"file": ("해외수요.xlsx", SEED_XLSX.read_bytes(), XLSX)})
        assert r.status_code == 200, r.text
    r = await client.post("/cards", headers=as_user(CURATOR), json={
        "card_no": "AC-PF-TM", "project_id": 2, "title": "포트폴리오 시험용 전차 변속기",
        "core_achievement": "전차 자동변속기 국산화", "trl": 8,
        "technologies": [{"tech_name": "전차용 자동변속기", "is_primary": True}],
        "performances": [{"metric_name": "내구도 검사 시간", "target_value": 320, "achieved_value": 306,
                          "unit": "h", "is_achieved": False}],
        "open_issues": [{"issue_type": "UNMET_TARGET", "description": "내구도 기준 미달", "priority": "HIGH"}]})
    assert r.status_code == 201, r.text
    card_id = r.json()["id"]
    assert (await client.post(f"/cards/{card_id}/publish", headers=as_user(CURATOR))).status_code == 204
    r = await client.post("/gaps/runs", headers=as_user(PLANNER), json={"rules": LOOSE, "note": "포트폴리오 시험"})
    assert r.status_code == 201, r.text
    found = (await client.get(f"/gaps/runs/{r.json()['id']}", headers=as_user(PLANNER))).json()["findings"]
    drafts = [f for f in found if f["status"] == "DRAFT"]
    assert len(drafts) >= 2
    confirmed, draft = drafts[0], drafts[1]
    r = await client.post(f"/gaps/findings/{confirmed['id']}/decision", headers=as_user(REVIEWER),
                          json={"decision": "CONFIRM"})
    assert r.status_code == 204, r.text
    _state.update(card=card_id, confirmed=confirmed, draft=draft)
    return _state


async def test_who_can_see(client, gaps):
    for uid in (PLANNER, REVIEWER, AGENCY, VIEWER):
        for path in ("/portfolio/overview", "/portfolio/areas", "/portfolio/domestic", "/portfolio/actions"):
            assert (await client.get(path, headers=as_user(uid))).status_code == 200, (uid, path)
    for uid in (EXPERT, CURATOR):
        assert (await client.get("/portfolio/overview", headers=as_user(uid))).status_code == 403


async def test_overview_and_areas_count_only_visible(client, gaps):
    ov = (await client.get("/portfolio/overview", headers=as_user(AGENCY))).json()
    assert ov["cards_published"] >= 1 and ov["overseas_demands"] >= 9
    assert ov["gaps_confirmed"] >= 1 and ov["gaps_draft"] >= 1
    # 열람 등급 '공개' 사용자: 내부 등급 카드를 근거로 한 갭은 건수에도 안 들어간다
    low = (await client.get("/portfolio/overview", headers=as_user(VIEWER))).json()
    assert low["cards_published"] == 0 and low["gaps_confirmed"] == 0 and low["gaps_draft"] == 0
    assert 9 <= low["overseas_demands"] <= ov["overseas_demands"]  # 시드 해외 수요 9건은 공개자료

    areas = (await client.get("/portfolio/areas", headers=as_user(AGENCY))).json()
    assert sum(a["demand_count"] for a in areas) == ov["overseas_demands"]
    assert sum(a["confirmed_count"] for a in areas) == ov["gaps_confirmed"]
    assert all(a["gap_count"] == a["confirmed_count"] for a in areas)  # 기본은 확정만
    wide = (await client.get("/portfolio/areas", headers=as_user(AGENCY), params={"include_draft": True})).json()
    assert sum(a["gap_count"] for a in wide) == ov["gaps_confirmed"] + ov["gaps_draft"]
    hit = next(a for a in areas if a["confirmed_count"])
    assert sum(hit["by_type"].values()) == hit["gap_count"] and hit["card_count"] >= 1


async def test_domestic_distribution(client, gaps):
    rows = (await client.get("/portfolio/domestic", headers=as_user(AGENCY))).json()
    assert sum(r["card_count"] for r in rows) >= 1
    assert any(r["linked_gap_count"] > 0 for r in rows)
    assert all(r["avg_trl"] is None or 1 <= r["avg_trl"] <= 9 for r in rows)


async def test_actions_group_by_direction(client, gaps):
    rows = (await client.get("/portfolio/actions", headers=as_user(AGENCY))).json()
    assert rows and all(r["status"] == "CONFIRMED" for r in rows)
    row = next(r for r in rows if r["finding_id"] == gaps["confirmed"]["id"])
    expected = {"NO_COVERAGE": "NEW_PROJECT", "PERFORMANCE_SHORT": "FOLLOW_UP",
                "LOCALIZATION": "LOCALIZATION", "MATURITY": "PILOT"}[row["gap_type_code"]]
    assert row["direction"] == expected and row["direction_name"]
    assert row["cards"] and row["departments"] and row["pathways"]
    wide = (await client.get("/portfolio/actions", headers=as_user(AGENCY), params={"include_draft": True})).json()
    assert gaps["draft"]["id"] in {r["finding_id"] for r in wide}
    only = (await client.get("/portfolio/actions", headers=as_user(AGENCY),
                             params={"include_draft": True, "area": row["area"]})).json()
    assert only and {r["area"] for r in only} == {row["area"]}


async def test_to_demand(client, gaps):
    fid, draft_id = gaps["confirmed"]["id"], gaps["draft"]["id"]
    url = f"/portfolio/actions/{fid}/to-demand"
    for uid in (AGENCY, REVIEWER, EXPERT):
        assert (await client.post(url, headers=as_user(uid))).status_code == 403
    r = await client.post(f"/portfolio/actions/{draft_id}/to-demand", headers=as_user(PLANNER))
    assert r.status_code == 409 and "확정" in r.json()["detail"]
    assert (await client.post("/portfolio/actions/999999/to-demand", headers=as_user(PLANNER))).status_code == 404

    r = await client.post(url, headers=as_user(PLANNER))
    assert r.status_code == 201, r.text
    made = r.json()
    assert made["created"] and made["demand_no"] == f"PD-GAP-{fid:04d}"
    again = await client.post(url, headers=as_user(PLANNER))
    assert again.status_code == 200 and again.json() == {**made, "created": False}

    d = (await client.get(f"/demands/{made['demand_id']}", headers=as_user(PLANNER))).json()
    assert d["origin_gap_finding_id"] == fid and d["origin_overseas_demand_id"] == gaps["confirmed"]["overseas_demand_id"]
    assert d["status"] == "OPEN" and d["owner_user_id"] == PLANNER and d["title"].startswith("[")
    assert "갭 분석:" in d["tech_need"]

    ov = (await client.get("/portfolio/overview", headers=as_user(AGENCY))).json()
    assert ov["handed_off"] >= 1
    rows = (await client.get("/portfolio/actions", headers=as_user(AGENCY))).json()
    assert next(r for r in rows if r["finding_id"] == fid)["planning_demand_no"] == made["demand_no"]


async def test_db_blocks_unconfirmed_gap_and_lower_security(client, gaps):
    with psycopg.connect(TEST_URL) as conn:
        with pytest.raises(psycopg.errors.CheckViolation, match="확정되지 않아"):
            conn.execute("INSERT INTO ax.planning_demand (demand_no, title, tech_need, origin_gap_finding_id) "
                         "VALUES ('PD-X1', 't', 'n', %s)", (gaps["draft"]["id"],))
        conn.rollback()
        with pytest.raises(psycopg.errors.CheckViolation, match="보안등급"):
            conn.execute("UPDATE ax.planning_demand SET security_code = 'PUBLIC' WHERE origin_gap_finding_id = %s",
                         (gaps["confirmed"]["id"],))
        conn.rollback()
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("INSERT INTO ax.planning_demand (demand_no, title, tech_need, origin_gap_finding_id) "
                         "VALUES ('PD-X2', 't', 'n', %s)", (gaps["confirmed"]["id"],))


async def test_export_xlsx(client, gaps):
    r = await client.get("/portfolio/export.xlsx", headers=as_user(AGENCY))
    assert r.status_code == 200 and r.headers["content-type"].startswith(XLSX)
    assert "attachment" in r.headers["content-disposition"]
    wb = load_workbook(BytesIO(r.content))
    assert wb.sheetnames == ["분야별 대조", "국내 성과 분포", "기획 후보", "작성기준"]
    plan = wb["기획 후보"]
    assert plan.max_row >= 2 and plan["A1"].value == "대응 방향"
    text = " ".join(str(c.value) for row in wb.worksheets[0].iter_rows() for c in row if c.value)
    assert "Claude" not in text and "AI" not in text
    assert (await client.get("/portfolio/export.xlsx", headers=as_user(EXPERT))).status_code == 403
