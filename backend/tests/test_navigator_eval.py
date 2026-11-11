from datetime import date

from app import navigator_eval as ev
from tests.test_navigator_matching import _seed


def test_corpus_is_consistent():
    c = ev.load_corpus()
    ids = {x["id"] for x in c["companies"]}
    assert len(ids) == len(c["companies"]) == 20
    types = {"COMPANY_SIZE", "BUSINESS_AGE", "REQUIRED_CERT", "MIN_CREDIT_GRADE", "REGION", "TRL",
             "EMPLOYEE_COUNT", "BUSINESS_STATUS", "RND_EXPERIENCE", "OTHER"}
    for x in c["companies"]:
        assert set(x["expected"]) == {str(a) for a in c["announcements"]}, x["id"]
        for v in x["expected"].values():
            verdict, why = ev.parse_expected(v)
            assert verdict in ev.VERDICT_KO and why <= types and (verdict == "ELIGIBLE") == (not why), (x["id"], v)
    for ann, major in c["major"].items():
        assert set(major) <= ids
        for o in major:      # 정답 기업은 적합 또는 정보부족
            comp = next(x for x in c["companies"] if x["id"] == o)
            assert ev.parse_expected(comp["expected"][ann])[0] != "INELIGIBLE", (ann, o)


def test_boundary_company_age():
    # 117 은 102 마감일 기준 업력 7년을 막 넘고, 103 마감일 기준으로는 7년이 안 되게 만든 기업
    opened = date(2019, 12, 20)
    assert (date(2026, 12, 31) - opened).days / 365.25 >= 7 > (date(2026, 11, 30) - opened).days / 365.25


async def test_eval_matches_ground_truth(client):
    _seed()
    c = ev.load_corpus()
    try:
        assert await ev.load(c) == 17
        assert await ev.load(c) == 17        # 다시 넣어도 같은 결과
        res = await ev.evaluate(c)
    finally:
        assert await ev.clean(c) == 17
    m = res["metrics"]
    wrong = [p for p in res["pairs"] if not p["why_ok"]]
    assert m["pairs"] == 100 and not wrong, wrong
    assert m["verdict_accuracy_pct"] == m["reason_accuracy_pct"] == 100.0
    assert m["major_total"] == 14 and m["candidate_recall_major_pct"] == 100.0
    assert res["eval_run_id"]
