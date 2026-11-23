"""판정기준 설정, 진단 변수사전 관리, 상담 보완자료 첨부."""
import psycopg
import pytest

from app.services import fit
from app.services.ratelimit import limiter
from tests.conftest import TEST_URL, as_user, manage_token
from tests.test_company_products import VENTURE, _hwpx
from tests.test_eligibility_review import AREAS, ITEMS

BRN = "9998700133"


def test_fit_with_criteria():
    purpose = {"similarity": 0.7, "level": "FULL", "label": "높음"}
    base = fit.evaluate(ITEMS, AREAS, purpose, [])
    assert base["score"] == 69 and base["grade"] == "중"
    # 부분 경계를 60 으로 올리면 재무상황(57)·기술성(평균 51) 이 미흡: 15/40 = 38점, 중 경계 30 이면 중
    r = fit.evaluate(ITEMS, AREAS, purpose, [], {"capability_partial": 60, "grade_high": 60, "grade_mid": 30})
    levels = {x["name"]: x["level"] for x in r["items"]}
    assert levels["재무상황"] == "LOW" and levels["기술성"] == "LOW" and r["score"] == 38 and r["grade"] == "중"
    assert fit.evaluate(ITEMS, AREAS, purpose, [], {"partial_ratio": 60})["score"] == 75


@pytest.fixture
async def org(client):
    limiter.reset()
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))
    r = await client.post("/navigator/companies", json={
        "business_reg_no": BRN, "company_name": "(가상)기준테크", "representative_name": "김가상",
        "opened_on": "2019-01-01", "email": f"{BRN}@example.com", "main_business": "방산 부품"})
    assert r.status_code == 201, r.text
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        oid = c.execute("SELECT id FROM ax.organization WHERE business_reg_no = %s", (BRN,)).fetchone()[0]
    yield oid
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))


async def test_criteria_versions(client, org):
    v = (await client.get("/navigator/consult/criteria", headers=as_user(1))).json()
    first = v["active"]["version"]
    assert v["active"]["grade_high"] == 70 and len(v["active"]["check_items"]) == 6
    body = {"capability_full": 70, "capability_partial": 40, "grade_high": 75, "grade_mid": 50, "partial_ratio": 50,
            "check_items": v["active"]["check_items"][:5] + [{"item": "제출서류", "content": "필수 서류", "kind": "GUIDE"}],
            "note": "상 등급 경계 조정 (소관부서 협의)"}
    assert (await client.put("/navigator/consult/criteria", headers=as_user(1), json=body)).status_code == 403
    assert (await client.put("/navigator/consult/criteria", headers=as_user(3),
                             json={**body, "grade_mid": 80})).status_code == 422
    r = await client.put("/navigator/consult/criteria", headers=as_user(3), json=body)
    assert r.status_code == 200, r.text
    try:
        assert r.json()["active"]["grade_high"] == 75 and r.json()["active"]["version"] == first + 1
        e = (await client.post(f"/navigator/consult/companies/{org}/eligibility", headers=as_user(1),
                               json={})).json()
        assert e.get("fit_rule", {"grade_high": 75})["grade_high"] == 75
    finally:
        r = await client.post(f"/navigator/consult/criteria/versions/{first}/activate", headers=as_user(4))
        assert r.status_code == 200 and r.json()["active"]["grade_high"] == 70


async def test_variable_edit(client):
    vs = (await client.get("/navigator/consult/dstate/variables", headers=as_user(3))).json()
    dq = next(v for v in vs if v["code"] == "DQMS")
    assert (await client.put("/navigator/consult/dstate/variables/DQMS", headers=as_user(3),
                             json={"question": "x"})).status_code == 403
    r = await client.put("/navigator/consult/dstate/variables/DQMS", headers=as_user(4), json={
        "question": "국방품질경영체제 인증을 받았습니까?", "option_labels": {"PREPARING": "인증 준비"}})
    assert r.status_code == 200, r.text
    try:
        assert r.json()["updated_by_name"] and r.json()["question"].startswith("국방품질")
        assert next(o for o in r.json()["options"] if o["code"] == "PREPARING")["label"] == "인증 준비"
        assert (await client.put("/navigator/consult/dstate/variables/DQMS", headers=as_user(4),
                                 json={"option_labels": {"NOPE": "x"}})).status_code == 422
        assert (await client.put("/navigator/consult/dstate/variables/REVENUE", headers=as_user(4),
                                 json={"question": "매출?"})).status_code == 422
        assert (await client.put("/navigator/consult/dstate/variables/NOPE", headers=as_user(4),
                                 json={})).status_code == 404
    finally:
        await client.put("/navigator/consult/dstate/variables/DQMS", headers=as_user(4), json={
            "question": dq["question"], "option_labels": {o["code"]: o["label"] for o in dq["options"]}})


async def test_consult_evidence(client, org):
    h = {"X-Manage-Token": await manage_token(client, BRN)}
    mine = await client.post("/navigator/manage/evidence", headers=h,
                             files={"file": ("인정서.png", b"\x89PNG", "image/png")})
    assert mine.status_code == 201
    r = await client.post(f"/navigator/consult/companies/{org}/evidence", headers=as_user(1),
                          files={"file": ("벤처기업확인서.hwpx", _hwpx(VENTURE), "application/octet-stream")},
                          data={"note": "상담 중 받은 확인서"})
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["origin_label"] == "담당자 첨부" and e["kind_label"] == "인증·확인서" and e["note"] == "상담 중 받은 확인서"
    assert e["detected"]["cert_no"] == "20250301-0123"
    assert (await client.post(f"/navigator/consult/companies/{org}/evidence", headers=as_user(3),
                              files={"file": ("a.hwpx", b"x", "application/octet-stream")})).status_code == 403

    lst = (await client.get(f"/navigator/consult/companies/{org}/evidence", headers=as_user(1))).json()
    assert {x["origin_label"] for x in lst} == {"담당자 첨부", "기업 제출"}

    r = await client.post(f"/navigator/consult/companies/{org}/consultations", headers=as_user(1),
                          json={"task": "A", "evidence_ids": [e["id"], 99999999]})
    assert r.status_code == 201, r.text
    c = r.json()
    assert [x["id"] for x in c["evidence"]] == [e["id"]]

    assert (await client.delete(f"/navigator/consult/companies/{org}/evidence/{mine.json()['id']}",
                                headers=as_user(1))).status_code == 403
    assert (await client.delete(f"/navigator/consult/companies/{org}/evidence/{e['id']}",
                                headers=as_user(1))).status_code == 204
    c = (await client.get(f"/navigator/consult/consultations/{c['id']}", headers=as_user(1))).json()
    assert c["evidence"] == []
