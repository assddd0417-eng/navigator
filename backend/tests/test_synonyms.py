"""국방기술 동의어 사전: 넓혀 보기 규칙 · 등록·권한 · 엑셀 올리기 · 적용(다시 임베딩) · 매칭 가까워짐."""
from io import BytesIO

import numpy as np
import psycopg
import pytest
from openpyxl import Workbook

from app.services.embedding import HashEmbedder
from app.services.synonyms import Group, expand, matches
from tests.conftest import TEST_URL, as_user

PLANNER, REVIEWER, EXPERT, CURATOR, VIEWER = 1, 2, 3, 4, 5
G = [Group("능동위상배열 레이더", ("능동위상배열 레이더", "AESA 레이더", "AESA")),
     Group("인공지능", ("인공지능", "AI"))]


def test_expand_adds_other_terms_once():
    out = expand("소형 AESA 레이더 송수신 모듈 개발", G)
    assert out.startswith("소형 AESA 레이더 송수신 모듈 개발\n관련 용어: ")
    assert "능동위상배열 레이더" in out and out.count("AESA") == 1  # 이미 있는 말은 다시 붙이지 않는다


def test_ascii_terms_need_word_boundary():
    assert matches("MAIN 배터리 팩", G) == []                 # 'AI' 가 'MAIN' 안에서 잡히지 않음
    assert [g.canonical for g, _ in matches("AI 기반 표적 탐지", G)] == ["인공지능"]
    assert [g.canonical for g, _ in matches("인공지능을 쓴 탐지", G)] == ["인공지능"]  # 한글은 조사가 붙어도


def test_empty_dictionary_keeps_text():
    assert expand("AESA 레이더", []) == "AESA 레이더"
    assert expand(None, G) is None
    assert expand("열관리 배터리", G) == "열관리 배터리"


def test_expansion_brings_different_wordings_closer():
    e = HashEmbedder(1024)
    a, b = "함정용 AESA 레이더 송수신 모듈", "능동위상배열 레이더 국산화 수요"
    before = float(np.dot(*e.embed([a, b])))
    after = float(np.dot(*e.embed([expand(a, G), expand(b, G)])))
    assert after > before + 0.1, (before, after)


@pytest.fixture
async def cleanup():
    yield
    # 다른 테스트의 임베딩이 이 사전에 영향받지 않도록 끄고 원래대로 다시 계산한다
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute("DELETE FROM ax.term_synonym")


async def test_add_list_patch_and_roles(client, cleanup):
    body = {"canonical_term": "능동위상배열 레이더", "synonym": "AESA", "relation": "ABBREVIATION", "domain": "레이더"}
    assert (await client.post("/synonyms", headers=as_user(EXPERT), json=body)).status_code == 403
    r = await client.post("/synonyms", headers=as_user(CURATOR), json=body)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    r = await client.post("/synonyms", headers=as_user(PLANNER), json={"canonical_term": "AESA", "synonym": " aesa "})
    assert r.status_code == 422
    r = await client.post("/synonyms", headers=as_user(PLANNER),
                          json={"canonical_term": "레이더", "synonym": "능동위상배열 레이더", "relation": "NARROWER"})
    assert r.status_code == 201
    rows = (await client.get("/synonyms?q=AESA", headers=as_user(VIEWER))).json()
    assert [(x["synonym"], x["relation_name"], x["used_in_matching"]) for x in rows] == [("AESA", "약어", True)]
    # 좁은 말은 매칭에 쓰지 않는다
    p = (await client.get("/synonyms/expand", params={"text": "레이더 AESA 시험"}, headers=as_user(VIEWER))).json()
    assert p["expanded"].endswith("관련 용어: 능동위상배열 레이더")
    assert [m["canonical_term"] for m in p["matched"]] == ["능동위상배열 레이더"]
    assert (await client.patch(f"/synonyms/{sid}", headers=as_user(CURATOR), json={"is_active": False})).status_code == 204
    p = (await client.get("/synonyms/expand", params={"text": "AESA 시험"}, headers=as_user(VIEWER))).json()
    assert p["expanded"] == "AESA 시험" and p["matched"] == []
    assert len((await client.get("/synonyms?include_inactive=true&q=AESA", headers=as_user(VIEWER))).json()) == 1
    assert (await client.patch("/synonyms/999999", headers=as_user(CURATOR), json={"is_active": True})).status_code == 404
    assert (await client.delete(f"/synonyms/{sid}", headers=as_user(EXPERT))).status_code == 403
    assert (await client.delete(f"/synonyms/{sid}", headers=as_user(PLANNER))).status_code == 204
    assert (await client.delete(f"/synonyms/{sid}", headers=as_user(PLANNER))).status_code == 404


def _xlsx(rows) -> bytes:
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def test_import_xlsx(client, cleanup):
    data = _xlsx([["표준 용어", "동의어", "관계", "분야", "출처"],
                  ["전자광학/적외선", "EO/IR", "약어", "감시정찰", "기술전문가"],
                  ["무인항공기", "UAV", "영문·한글", None, None],
                  ["무인항공기", "드론", None, None, None],
                  ["무인항공기", "무인항공기", None, None, None],
                  ["항재밍", "anti-jamming", "이상한 관계", None, None],
                  [None, None, None, None, None]])
    files = {"file": ("사전.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = await client.post("/synonyms/import?dry_run=true", headers=as_user(CURATOR), files=files)
    assert r.status_code == 200, r.text
    assert r.json()["would_add"] == 3 and [e["row"] for e in r.json()["errors"]] == [5, 6]
    assert (await client.get("/synonyms", headers=as_user(VIEWER))).json() == []  # 미리 보기는 넣지 않는다
    r = (await client.post("/synonyms/import", headers=as_user(CURATOR), files=files)).json()
    assert (r["added"], r["skipped"]) == (3, 0)
    r = (await client.post("/synonyms/import", headers=as_user(CURATOR), files=files)).json()
    assert (r["added"], r["skipped"]) == (0, 3)
    rows = (await client.get("/synonyms?q=EO", headers=as_user(VIEWER))).json()
    assert rows[0]["relation"] == "ABBREVIATION" and rows[0]["domain"] == "감시정찰"
    bad = {"file": ("x.xlsx", b"not excel", "application/octet-stream")}
    assert (await client.post("/synonyms/import", headers=as_user(CURATOR), files=bad)).status_code == 422
    nohead = {"file": ("h.xlsx", _xlsx([["용어", "말"]]), "application/octet-stream")}
    assert (await client.post("/synonyms/import", headers=as_user(CURATOR), files=nohead)).status_code == 422


async def test_apply_re_embeds_changed_facets(client, cleanup):
    r = await client.post("/cards", headers=as_user(CURATOR), json={
        "card_no": "AC-SYN-01", "project_id": 3, "title": "함정용 AESA 레이더 송수신 모듈",
        "core_achievement": "AESA 레이더 송수신 모듈 시제", "trl": 5,
        "technologies": [{"tech_name": "AESA 송수신 모듈", "is_primary": True}]})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert (await client.post("/synonyms/apply", headers=as_user(EXPERT))).status_code == 403
    await client.post("/synonyms", headers=as_user(CURATOR),
                      json={"canonical_term": "능동위상배열 레이더", "synonym": "AESA", "relation": "ABBREVIATION"})
    r = await client.post("/synonyms/apply", headers=as_user(PLANNER))
    assert r.status_code == 200 and r.json()["re_embedded"]["cards"] >= 1, r.text
    with psycopg.connect(TEST_URL) as conn:
        texts = [t for (t,) in conn.execute(
            "SELECT source_text FROM ax.card_embedding WHERE card_id = %s AND facet = 'SUMMARY'", (cid,))]
    assert texts and "관련 용어: 능동위상배열 레이더" in texts[0]
    # 다시 적용하면 바뀐 게 없어 다시 계산하지 않는다
    assert (await client.post("/synonyms/apply", headers=as_user(PLANNER))).json()["re_embedded"]["cards"] == 0
    # 사전을 비우고 적용하면 원래 글로 돌아간다
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute("DELETE FROM ax.term_synonym")
    assert (await client.post("/synonyms/apply", headers=as_user(PLANNER))).json()["re_embedded"]["cards"] >= 1
