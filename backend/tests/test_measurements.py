"""PoC 효과 측정: 업무시간 입력·본인 것만 삭제 · 단축률·목표 달성 · 만족도 · 엑셀 · 권한."""
from io import BytesIO

from openpyxl import load_workbook

from tests.conftest import as_user

PLANNER, REVIEWER, EXPERT, CURATOR, VIEWER = 1, 2, 3, 4, 5


async def _wt(client, uid, **body):
    r = await client.post("/measurements/work-time", headers=as_user(uid), json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_record_and_reduction(client):
    await _wt(client, PLANNER, task_type="RESEARCH", method="MANUAL", minutes=300, candidates_found=2)
    await _wt(client, EXPERT, task_type="RESEARCH", method="MANUAL", minutes=240, candidates_found=3)
    await _wt(client, PLANNER, task_type="RESEARCH", method="AX", minutes=60, candidates_found=5)
    await _wt(client, PLANNER, task_type="REVIEW_MATERIAL", method="MANUAL", minutes=180)
    await _wt(client, REVIEWER, task_type="REVIEW_MATERIAL", method="AX", minutes=90, note="검토표·초안 사용")
    s = (await client.get("/measurements/summary", headers=as_user(REVIEWER))).json()
    research = next(t for t in s["tasks"] if t["task_type"] == "RESEARCH")
    assert research["manual_avg"] == 270 and research["ax_avg"] == 60
    assert research["reduction_pct"] == 77.8 and research["target_pct"] == 70 and research["met"] is True
    assert research["ax_candidates"] == 5 and research["manual_candidates"] == 2.5
    review = next(t for t in s["tasks"] if t["task_type"] == "REVIEW_MATERIAL")
    assert review["reduction_pct"] == 50 and review["met"] is False
    reading = next(t for t in s["tasks"] if t["task_type"] == "DOCUMENT_READING")
    assert reading["reduction_pct"] is None and reading["met"] is None
    assert s["overall_reduction_pct"] == round(100 * (1 - 150 / 450), 1)


async def test_only_own_records_deleted_and_listed(client):
    mid = await _wt(client, CURATOR, task_type="CANDIDATE_LIST", method="MANUAL", minutes=45)
    mine = (await client.get("/measurements/work-time", headers=as_user(CURATOR))).json()
    assert [m["id"] for m in mine] == [mid] and mine[0]["task_name"] == "후보목록 작성"
    # 큐레이터는 mine=false 여도 본인 것만
    assert len((await client.get("/measurements/work-time?mine=false", headers=as_user(CURATOR))).json()) == 1
    assert len((await client.get("/measurements/work-time?mine=false", headers=as_user(PLANNER))).json()) >= 6
    assert (await client.delete(f"/measurements/work-time/{mid}", headers=as_user(PLANNER))).status_code == 404
    assert (await client.delete(f"/measurements/work-time/{mid}", headers=as_user(CURATOR))).status_code == 204


async def test_validation_and_roles(client):
    r = await client.post("/measurements/work-time", headers=as_user(PLANNER),
                          json={"task_type": "RESEARCH", "method": "AX", "minutes": 0})
    assert r.status_code == 422
    r = await client.post("/measurements/work-time", headers=as_user(VIEWER),
                          json={"task_type": "RESEARCH", "method": "AX", "minutes": 10})
    assert r.status_code == 403
    assert (await client.get("/measurements/summary", headers=as_user(EXPERT))).status_code == 403


async def test_survey(client):
    for uid, score, asp in ((PLANNER, 4, {"usefulness": 5, "evidence": 4}), (EXPERT, 3, {"usefulness": 3, "ease": 4}),
                            (CURATOR, 5, {})):
        r = await client.post("/measurements/surveys", headers=as_user(uid),
                              json={"score": score, "aspects": asp, "comment": "시험"})
        assert r.status_code == 201, r.text
    assert (await client.post("/measurements/surveys", headers=as_user(PLANNER),
                              json={"score": 4, "aspects": {"ease": 9}})).status_code == 422
    sv = (await client.get("/measurements/summary", headers=as_user(PLANNER))).json()["survey"]
    assert sv["n"] == 3 and sv["avg_score"] == 4.0
    assert sv["by_role"] == {"PLANNER": 4.0, "EXPERT": 3.0, "OTHER": 5.0}
    use = next(a for a in sv["aspects"] if a["key"] == "usefulness")
    assert use["avg"] == 4.0 and use["n"] == 2 and use["name"] == "추천이 쓸모 있음"


async def test_export(client):
    r = await client.get("/measurements/export.xlsx", headers=as_user(PLANNER))
    assert r.status_code == 200
    wb = load_workbook(BytesIO(r.content))
    assert wb.sheetnames == ["업무시간 요약", "업무시간 기록", "만족도"]
    rows = list(wb["업무시간 요약"].values)
    research = next(x for x in rows if x[0] == "관련 성과·과제 조사")
    assert research[6] == 77.8 and research[7] == "달성"
