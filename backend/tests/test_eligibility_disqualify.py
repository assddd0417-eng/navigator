from datetime import date

from app.services.eligibility import CompanyFacts, Requirement, judge

D = date(2026, 11, 1)


def req(t, rule):
    return Requirement(1, t, rule, True, "요건")


def test_no_disqualification_export_defense_supply():
    nd = req("NO_DISQUALIFICATION", {"checks": ["TAX_DELINQUENT", "INSOLVENT", "RND_RESTRICTED"]})
    assert judge(nd, CompanyFacts(1, "a"), D).result == "UNKNOWN"
    assert judge(nd, CompanyFacts(1, "a", tax_delinquent=False, insolvent=False, rnd_restricted=False), D).result == "MET"
    assert judge(nd, CompanyFacts(1, "a", tax_delinquent=True), D).result == "UNMET"   # 하나라도 해당이면 바로 부적격

    ex = req("EXPORT", {"min_krw": 1})
    assert judge(ex, CompanyFacts(1, "a"), D).result == "UNKNOWN"
    assert judge(ex, CompanyFacts(1, "a", export_krw=0), D).result == "UNMET"
    assert judge(ex, CompanyFacts(1, "a", export_krw=5), D).result == "MET"

    ds = req("DEFENSE_SUPPLY", {"defense_goods": True, "min_supply_krw": 100})
    assert judge(ds, CompanyFacts(1, "a", defense_goods=True), D).result == "UNKNOWN"
    assert judge(ds, CompanyFacts(1, "a", defense_goods=False), D).result == "UNMET"
    assert judge(ds, CompanyFacts(1, "a", defense_goods=True, military_supply_krw=100), D).result == "MET"
