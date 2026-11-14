"""참여할 수 있었던 사업: 최근 마감 공고를 지금 회사 정보로 다시 판정."""
import os
import subprocess
from datetime import date

import psycopg
import pytest

from app.config import get_settings
from app.services import navigator_matching as nm
from app.services.ratelimit import limiter
from tests.conftest import ROOT, TEST_URL, _psql_url, as_user

HANBIT, HANBIT_BRN = 101, "9998100015"
PAST = 106          # seeds/navigator_past_announcements.sql — 101 의 이전 회차, 2025-12-15 마감


def _q(sql, *args):
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        cur = conn.execute(sql, args)
        return cur.fetchall() if cur.description else []


@pytest.fixture
def seeded(database):
    limiter.reset()
    env = {**os.environ, "PGPASSWORD": os.environ.get("PGPASSWORD", "")}
    for f in ("navigator_companies.sql", "navigator_announcements.sql", "navigator_past_announcements.sql"):
        subprocess.run(["psql", _psql_url(TEST_URL), "-X", "-q", "-v", "ON_ERROR_STOP=1",
                        "-f", str(ROOT / "seeds" / f)], check=True, capture_output=True, env=env)
    _q("DELETE FROM ax.eligibility_answer WHERE organization_id IN (101, 102, 103)")
    yield
    _q("DELETE FROM ax.company_support_history WHERE organization_id = %s AND announcement_id = %s", HANBIT, PAST)
    _q("DELETE FROM ax.company_recommendation WHERE announcement_id = %s", PAST)
    _q("DELETE FROM ax.announcement WHERE id = %s", PAST)
    _q("UPDATE ax.announcement SET series_key = NULL WHERE id = 101")


def test_past_since():
    assert nm.past_since(date(2026, 11, 14)) == date(2024, 11, 14)
    assert nm.past_since(date(2028, 2, 29)) == date(2026, 2, 28)


async def test_past_matches(client, seeded):
    h = {"X-Manage-Token": (await client.post(f"/navigator/companies/{HANBIT_BRN}/open")).json()["token"]}
    r = await client.post("/navigator/manage/past-matches", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    recs = {x["announcement_id"]: x for x in body["recommendations"]}
    assert all(x["receipt_state"] == "CLOSED" for x in recs.values())
    assert all(x["verdict"] in ("ELIGIBLE", "NEEDS_INFO") for x in recs.values())
    assert recs[PAST]["verdict"] == "ELIGIBLE"
    assert recs[PAST]["next_round"]["id"] == 101 and recs[PAST]["next_round"]["receipt_state"] == "OPEN"
    assert recs[PAST]["participated"] is False
    assert body["closed_since"] == nm.past_since().isoformat()

    # 현재 공고 목록에는 마감 공고가 섞이지 않음
    cur = (await client.post("/navigator/manage/matches", headers=h)).json()
    assert PAST not in {x["announcement_id"] for x in cur["recommendations"]}

    # 참여 이력에 그 공고를 적으면 '참여함'
    p = (await client.get("/navigator/manage/profile", headers=h)).json()
    _q("""INSERT INTO ax.company_support_history (organization_id, program_name, year, result, announcement_id)
          VALUES (%s, '전술통신 부품국산화', 2026, 'SELECTED', %s)""", p["organization_id"], PAST)
    again = (await client.post("/navigator/manage/past-matches", headers=h, params={"refresh": True})).json()
    assert next(x for x in again["recommendations"] if x["announcement_id"] == PAST)["participated"] is True


async def test_past_window_and_founding(client, seeded, monkeypatch):
    # 마감일이 기간 밖이면 빠짐
    monkeypatch.setattr(get_settings(), "navigator_past_years", 0)
    r = await client.post(f"/navigator/matching/companies/{HANBIT}", params={"past": True}, headers=as_user(1))
    assert r.status_code == 201, r.text
    assert PAST not in {x["announcement_id"] for x in r.json()["recommendations"]}
    monkeypatch.setattr(get_settings(), "navigator_past_years", 2)
    # 회사가 생기기 전에 마감된 공고는 빠짐
    old = _q("SELECT opened_on FROM ax.company_profile WHERE organization_id = %s", HANBIT)[0][0]
    _q("UPDATE ax.company_profile SET opened_on = '2026-01-01' WHERE organization_id = %s", HANBIT)
    try:
        r = await client.post(f"/navigator/matching/companies/{HANBIT}", params={"past": True}, headers=as_user(1))
        assert PAST not in {x["announcement_id"] for x in r.json()["recommendations"]}
    finally:
        _q("UPDATE ax.company_profile SET opened_on = %s WHERE organization_id = %s", old, HANBIT)
