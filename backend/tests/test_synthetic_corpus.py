"""검증용 합성 코퍼스(seeds/synthetic/corpus.json) 무결성과 API 본문 변환 (DB 불필요)."""
import json
import subprocess
import sys
from collections import defaultdict

from app import synthetic as syn
from app.schemas.cards import CardCreate
from app.schemas.demands import DemandCreate
from app.schemas.documents import DocumentCreate
from app.services.scoring import _norm

C = syn.load_corpus()


def _fake_ids():
    ids = defaultdict(dict)
    for i, p in enumerate(C["projects"], 1):
        ids["project"][p["key"]] = i
    ids["dept"] = {k: n for n, k in enumerate(C["dept_keys"], 1)}
    ids["program"] = {k: n for n, k in enumerate(C["program_keys"], 1)}
    ids["ws"] = {w["key"]: n for n, w in enumerate(C["weapon_systems"], 1)}
    ids["item"] = {i["key"]: n for n, i in enumerate(C["items"], 1)}
    ids["org"] = {o["key"]: n for n, o in enumerate(C["organizations"], 1)}
    return ids


def test_corpus_json_is_built_from_builder():
    """corpus.json 을 손으로 고치지 않았는지: 생성기를 다시 돌린 결과와 같아야 한다."""
    before = syn.CORPUS.read_text(encoding="utf-8")
    subprocess.run([sys.executable, str(syn.CORPUS.with_name("build_corpus.py"))], check=True, capture_output=True)
    assert syn.CORPUS.read_text(encoding="utf-8") == before


def test_corpus_references_and_bodies_validate():
    ids = _fake_ids()
    keys = {p["key"] for p in C["projects"]}
    assert len(keys) == len(C["projects"])
    for p in C["projects"]:
        doc = DocumentCreate(**syn.document_body(p, ids))
        assert doc.metadata["synthetic"] is True and len(doc.chunks) == sum(len(s["paragraphs"]) for s in p["report"])
        n, chunk_ids = 0, []
        for s in p["report"]:
            chunk_ids.append(list(range(n, n + len(s["paragraphs"]))))
            n += len(s["paragraphs"])
        card = CardCreate(**syn.card_body(p, ids, chunk_ids))
        assert card.card_no == f"SYN-AC-{p['key']}" and card.evidence
        assert all(perf.evidence for perf in card.performances)
    for d in C["demands"]:
        DemandCreate(**syn.demand_body(d, ids))
        assert d["expected"] and all(k in keys for k, _, _ in d["expected"])


def test_demand_metric_names_differ_from_answer_cards():
    """요구성능 지표명이 정답 카드와 글자까지 같으면 성능 점수만으로 정답이 1위가 되어 적중률이 부풀려진다."""
    cards = {p["key"]: {_norm(f["metric_name"]) for f in p["card"]["performances"]} for p in C["projects"]}
    for d in C["demands"]:
        req = {_norm(r["metric_name"]) for r in d["reqs"]}
        for k, _, _ in d["expected"]:
            assert not (req & cards[k]), (d["key"], k, req & cards[k])


def test_every_document_cites_public_source_or_says_none():
    for p in C["projects"]:
        assert p["public_facts"]
        assert p["sources"] or p["public_facts"].startswith("없음")
    assert json.dumps(C, ensure_ascii=False).count("(가상)") >= 9  # 기업명은 실존 기업과 구분
