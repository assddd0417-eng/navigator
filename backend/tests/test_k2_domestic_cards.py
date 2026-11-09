"""K2 파워팩 국내 성과(seeds/overseas/국내성과_K2파워팩.json): 본문 변환과 출처 규칙 (DB 불필요)."""
from urllib.parse import urlparse

from app import synthetic as syn
from app.schemas.cards import CardCreate
from app.schemas.documents import DocumentCreate
from tests.conftest import ROOT

PATH = ROOT / "seeds" / "overseas" / "국내성과_K2파워팩.json"
OFFICIAL_HOSTS = {"dapa.go.kr", "www.gov.pl", "api.sejm.gov.pl"}  # 방위사업청, 폴란드 국방부, 폴란드 하원


def test_bodies_validate():
    c = syn.load_corpus(PATH)
    ids = {"project": {}, "dept": {"PLAN": 1, "MOBF": 2}, "program": {"LOC": 1}}
    ids["ws"] = {w["key"]: n for n, w in enumerate(c["weapon_systems"], 1)}
    ids["item"] = {i["key"]: n for n, i in enumerate(c["items"], 1)}
    ids["org"] = {o["key"]: n for n, o in enumerate(c["organizations"], 1)}
    for n, p in enumerate(c["projects"], 1):
        ids["project"][p["key"]] = n
        doc = DocumentCreate(**syn.document_body(p, ids))
        assert doc.metadata["synthetic"] is True
        chunk_ids, k = [], 0
        for s in p["report"]:
            chunk_ids.append(list(range(k, k + len(s["paragraphs"]))))
            k += len(s["paragraphs"])
        card = CardCreate(**syn.card_body(p, ids, chunk_ids))
        assert card.performances and all(f.evidence for f in card.performances)
    assert {p["key"] for p in c["projects"]} == {"K2T", "K2E"}


def test_sources_are_official_only():
    c = syn.load_corpus(PATH)
    for p in c["projects"]:
        assert p["sources"] and p["public_facts"]
        assert {urlparse(u).hostname for u in p["sources"]} <= OFFICIAL_HOSTS, p["key"]
    assert all(o["name"].startswith("(가상)") for o in c["organizations"])


def test_keys_do_not_clash_with_synthetic_corpus():
    main, k2 = syn.load_corpus(), syn.load_corpus(PATH)
    for key in ("projects", "organizations", "items", "weapon_systems"):
        assert not {x["key"] for x in main[key]} & {x["key"] for x in k2[key]}, key
    assert not {p["project_no"] for p in main["projects"]} & {p["project_no"] for p in k2["projects"]}
