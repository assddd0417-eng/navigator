"""A안 정렬(판정 후 벡터 관련도)과 기업 역량 레이더."""
import psycopg
import pytest

from app.config import get_settings
from app.services import company_radar as cr
from app.services import navigator_matching as nm
from app.services.ratelimit import limiter
from tests.conftest import TEST_URL, manage_token

BRN = "9998700036"


@pytest.fixture
def mode(monkeypatch):
    def set_mode(m: str):
        monkeypatch.setattr(get_settings(), "navigator_ranking", m)
    yield set_mode


def _s(tech=(0.8, "vec"), ipc=(0.5, "neutral:x"), purpose=(0.6, "vec"), pref=(1.0, "2/2")):
    return {"TECH": tech, "IPC": ipc, "PURPOSE": purpose, "PREFERENCE": pref}


def test_vector_mode_uses_relevance_only(mode):
    mode("vector")
    assert nm.combine(_s()) == pytest.approx(0.7 * 0.8 + 0.3 * 0.6)
    # 우대 충족은 관련도에 넣지 않음
    assert nm.combine(_s(pref=(0.0, "0/2"))) == nm.combine(_s(pref=(1.0, "2/2")))
    # 요구기술이 없으면 목적 유사도만으로
    assert nm.combine(_s(tech=(0.5, "neutral:요구기술 없음"))) == pytest.approx(0.6)
    assert nm.combine(_s(tech=(0.5, "neutral:a"), purpose=(0.5, "neutral:b"))) == nm.NEUTRAL


def test_weighted_mode_kept(mode):
    mode("weighted")
    assert nm.combine(_s()) == pytest.approx(0.45 * 0.8 + 0.15 * 0.5 + 0.2 * 0.6 + 0.2 * 1.0)
    mode("nope")
    with pytest.raises(ValueError):
        nm.ranking_mode()


def test_rank_verdict_first_then_relevance_then_preference(mode):
    mode("vector")

    class O:
        def __init__(self, i): self.organization_id = i

    class A:
        id = 1

    def sc(org, verdict, total, pref):
        x = nm.Scored.__new__(nm.Scored)
        x.org, x.ann, x.verdict, x.total = O(org), A(), verdict, total
        x.scores = _s(pref=(pref, ""))
        return x

    ranked = nm.rank([sc(1, "NEEDS_INFO", 0.95, 1.0), sc(2, "ELIGIBLE", 0.60, 0.0),
                      sc(3, "ELIGIBLE", 0.60, 1.0), sc(4, "ELIGIBLE", 0.70, 0.0),
                      sc(5, "INELIGIBLE", 0.99, 1.0)])
    assert [x.org.organization_id for x in ranked] == [4, 3, 2, 1, 5]


def test_radar_scores():
    row = {"credit_rank": 13, "pat_reg": 2, "pat_app": 1, "certs": 5, "techs": 1, "max_trl": 6,
           "products": 2, "defense_products": 1, "support": ["COMPLETED", "APPLIED"], "rnd": ["LEAD"]}
    assert cr.scores(row) == {"CREDIT": 59, "PATENT": 50, "CERT": 100, "TECH": 52,
                              "PRODUCT": 60, "PARTICIPATION": 55}
    empty = {**row, "credit_rank": None, "pat_reg": 0, "pat_app": 0, "certs": 0, "techs": 0, "max_trl": None,
             "products": 0, "defense_products": 0, "support": [], "rnd": []}
    assert cr.scores(empty) == cr.scores_empty()


async def test_radar_in_profile(client, database):
    limiter.reset()
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))
    try:
        r = await client.post("/navigator/companies", json={
            "business_reg_no": BRN, "company_name": "(가상)레이더정밀", "representative_name": "김가상",
            "opened_on": "2019-01-01", "email": f"{BRN}@example.com", "main_business": "RF 부품"})
        assert r.status_code == 201, r.text
        h = {"X-Manage-Token": await manage_token(client, BRN)}
        p = (await client.get("/navigator/manage/profile", headers=h)).json()
        axes = {a["code"]: a for a in p["radar"]["axes"]}
        assert [a["label"] for a in p["radar"]["axes"]] == ["신용", "특허", "인증", "기술", "제품", "사업참여"]
        assert axes["CREDIT"]["value"] is None and axes["PRODUCT"]["value"] == 0
        p = (await client.patch("/navigator/manage/profile", headers=h, json={
            "products": [{"name": "LNA", "category": "COMPONENT", "is_defense": True}],
            "technologies": [{"tech_name": "GaN 증폭", "trl": 9}]})).json()
        axes = {a["code"]: a for a in p["radar"]["axes"]}
        assert axes["PRODUCT"]["value"] == 40 and axes["TECH"]["value"] == 70
        assert p["radar"]["company_count"] >= 1 and axes["TECH"]["average"] is not None
    finally:
        with psycopg.connect(TEST_URL, autocommit=True) as c:
            c.execute("DELETE FROM ax.organization WHERE business_reg_no = %s", (BRN,))
