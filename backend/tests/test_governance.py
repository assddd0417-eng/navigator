"""서비스 안내, 역할별 권한, 기업정보 열람 권한."""
import psycopg
import pytest

from app.services.ratelimit import limiter
from tests.conftest import TEST_URL, as_user

BRN = "9998700093"


@pytest.fixture
async def org(client):
    limiter.reset()
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))
    r = await client.post("/navigator/companies", json={
        "business_reg_no": BRN, "company_name": "(가상)권한테크", "representative_name": "김가상",
        "opened_on": "2016-01-01", "email": f"{BRN}@example.com", "main_business": "통신 모듈"})
    assert r.status_code == 201, r.text
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        oid = c.execute("SELECT id FROM ax.organization WHERE business_reg_no = %s", (BRN,)).fetchone()[0]
    yield oid
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))


async def test_service_info_roles(client):
    r = await client.get("/navigator/service/info", headers=as_user(3))
    assert r.status_code == 200
    d = r.json()
    assert d["service"]["name"] == "AI 기반 방산기업 성장경로 서비스"
    assert [l["code"] for l in d["levels"]] == ["L1", "L2", "L3"] and d["gates"]["route"]["level"] == "L2"
    assert len(d["raci"]) == 8
    assert (await client.get("/navigator/service/info", headers=as_user(2))).status_code == 403
    me = (await client.get("/me", headers=as_user(4))).json()
    assert "AX_ADMIN" in me["roles"]


async def test_role_split(client, org):
    # 상담은 기업지원 담당자만
    assert (await client.get(f"/navigator/consult/companies/{org}/dstate", headers=as_user(1))).status_code == 200
    assert (await client.get(f"/navigator/consult/companies/{org}/dstate", headers=as_user(3))).status_code == 403
    # 연계 기준 보기는 셋 다, 고치기는 소관부서·AX
    for u in (1, 3, 4):
        assert (await client.get("/navigator/consult/route/rules", headers=as_user(u))).status_code == 200
    assert (await client.put("/navigator/consult/route/programs/1", headers=as_user(1),
                             json={"stage_code": "TECH_DEV"})).status_code == 403
    assert (await client.put("/navigator/consult/route/programs/1", headers=as_user(3),
                             json={"stage_code": "TECH_DEV"})).status_code == 200
    assert (await client.delete("/navigator/consult/route/programs/1", headers=as_user(4))).status_code == 204
    # 이력 점검은 AX·담당자
    assert (await client.get("/navigator/consult/review-log", headers=as_user(4))).status_code == 200
    assert (await client.get("/navigator/consult/review-log", headers=as_user(3))).status_code == 403


async def test_company_access(client, org):
    a = (await client.get(f"/navigator/consult/companies/{org}/access", headers=as_user(1))).json()
    assert a["restricted"] is False and {d["id"] for d in a["departments"]} >= {1, 2, 3}
    assert (await client.put(f"/navigator/consult/companies/{org}/access", headers=as_user(1),
                             json={"department_ids": [2]})).status_code == 403
    assert (await client.put(f"/navigator/consult/companies/{org}/access", headers=as_user(4),
                             json={"department_ids": [999]})).status_code == 422
    r = await client.put(f"/navigator/consult/companies/{org}/access", headers=as_user(4), json={"department_ids": [2]})
    assert r.status_code == 200 and r.json()["restricted"] is True

    # 사업지원팀(1) 담당자는 이제 못 봄
    found = (await client.get("/navigator/consult/companies?q=권한테크", headers=as_user(1))).json()
    assert found == []
    assert (await client.get(f"/navigator/consult/companies/{org}/dstate", headers=as_user(1))).status_code == 403
    assert (await client.post(f"/navigator/consult/companies/{org}/consultations", headers=as_user(1),
                              json={"task": "A"})).status_code == 403
    # AX 는 모두 봄
    assert (await client.get(f"/navigator/consult/companies/{org}/access", headers=as_user(4))).status_code == 200

    r = await client.put(f"/navigator/consult/companies/{org}/access", headers=as_user(4), json={"department_ids": [1]})
    assert r.json()["restricted"] is True
    found = (await client.get("/navigator/consult/companies?q=권한테크", headers=as_user(1))).json()
    assert [f["organization_id"] for f in found] == [org]
    r = await client.post(f"/navigator/consult/companies/{org}/consultations", headers=as_user(1), json={"task": "A"})
    assert r.status_code == 201
    # 열람 권한을 풀어도 상담 기록은 그대로
    r = await client.put(f"/navigator/consult/companies/{org}/access", headers=as_user(4), json={"department_ids": []})
    assert r.json()["restricted"] is False
