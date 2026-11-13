"""기획서·공모서 ↔ 과제 연결 (과제번호·다른 번호·과제명) 과 자료 사슬."""
import pytest

from app.services.project_linker import ProjectKey, find_projects, link_role
from tests.conftest import as_user

PLANNER, REVIEWER, EXPERT, CURATOR, VIEWER = 1, 2, 3, 4, 5

KEYS = [ProjectKey(1, "PRJ-2022-001", "소형 무인기용 항재밍 데이터링크 개발", ["DT-2022-77"]),
        ProjectKey(2, "PRJ-2021-007", "전술 배터리 열관리 기술"),
        ProjectKey(3, "PRJ-2023-004", "EO/IR 영상 기반 표적 자동탐지")]


def test_find_projects_rules():
    text = "공모 과제: ① prj–2022–001 데이터링크  ② 전술배터리 열관리기술(가칭)  ③ PRJ-2023-0041 은 다른 과제"
    found = find_projects(text, KEYS)
    assert [(m.project_id, m.method) for m in found] == [(1, "PROJECT_NO"), (2, "TITLE")]  # 대시·대소문자 무시, 경계 확인
    assert find_projects("DTiMS 번호 DT-2022-77 결과", KEYS)[0].method == "IDENTIFIER"
    assert find_projects("열관리 기술", KEYS) == []  # 과제명은 8글자 이상 통째로 나와야
    assert link_role("PROGRAM_NOTICE", 1) == "LISTED" and link_role("FINAL_REPORT", 1) == "SUBJECT"
    assert link_role("FINAL_REPORT", 2) == "LISTED"


def _doc(doc_type: str, title: str, text: str, **kw) -> dict:
    return {"doc_type_code": doc_type, "title": title, "chunks": [{"content": text}], **kw}


async def test_notice_links_listed_projects_and_program(client):
    r = await client.post("/documents", headers=as_user(PLANNER), json=_doc(
        "PROGRAM_NOTICE", "2021년 핵심기술개발 공모서(시험)",
        "지원 과제\n1. PRJ-2022-001 소형 무인기용 항재밍 데이터링크 개발\n2. 전술 배터리 열관리 기술"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert [(p["project_id"], p["link_role"], p["match_method"]) for p in body["linked_projects"]] == \
        [(1, "LISTED", "PROJECT_NO"), (2, "LISTED", "TITLE")]
    docs = (await client.get("/documents", headers=as_user(PLANNER))).json()
    assert next(d for d in docs if d["id"] == body["id"])["project_id"] is None

    chain = (await client.get("/planning/projects/1/chain", headers=as_user(PLANNER))).json()["chain"]
    notice = next(s for s in chain if s["code"] == "PROGRAM_NOTICE")
    assert notice["name"] == "공모서" and notice["documents"][0]["via"] == "LISTED"
    assert [s["name"] for s in chain] == ["사업 기획서", "공모서", "연구개발계획서", "결과보고서", "평가서"]


async def test_report_without_project_finds_subject(client):
    r = await client.post("/documents", headers=as_user(CURATOR), json=_doc(
        "FINAL_REPORT", "표적 자동탐지 결과보고서(시험)", "본 보고서는 과제번호 PRJ-2023-004 의 최종 결과를 정리한다."))
    assert r.status_code == 201, r.text
    assert [(p["project_id"], p["link_role"]) for p in r.json()["linked_projects"]] == [(3, "SUBJECT")]
    # 문서의 대상 과제·소관부서가 채워짐 → 그 부서(지휘정찰기술팀) 사람이 과제로 찾아볼 수 있다
    docs = (await client.get("/documents", headers=as_user(EXPERT), params={"project_id": 3})).json()
    assert any(d["id"] == r.json()["id"] for d in docs)

    # 과제를 직접 고른 문서가 다른 과제를 언급하면 그쪽은 '실린 과제'
    r = await client.post("/documents", headers=as_user(CURATOR), json=_doc(
        "RND_PLAN", "후속 계획서(시험)", "선행 과제 PRJ-2022-001 의 성과를 이어받는다.", project_id=3, owner_dept_id=2))
    assert {p["project_id"]: p["link_role"] for p in r.json()["linked_projects"]} == {3: "SUBJECT", 1: "LISTED"}


async def test_identifier_and_relink(client):
    r = await client.post("/documents", headers=as_user(PLANNER), json=_doc(
        "EVALUATION", "결과평가서(시험)", "DTiMS 과제번호 DT-2022-55 결과평가 의견: 재밍 환경 시험 보완 필요"))
    doc_id = r.json()["id"]
    assert r.json()["linked_projects"] == []
    url = "/planning/projects/1/identifiers"
    assert (await client.post(url, headers=as_user(EXPERT), json={"identifier": "DT-2022-55"})).status_code == 403
    assert (await client.post(url, headers=as_user(CURATOR), json={"identifier": "DT-2022-55"})).status_code == 201
    dup = await client.post(url, headers=as_user(CURATOR), json={"identifier": "DT-2022-55"})
    assert dup.status_code == 409
    again = (await client.post(f"/planning/documents/{doc_id}/relink", headers=as_user(CURATOR))).json()
    assert [(p["project_id"], p["match_method"]) for p in again["linked_projects"]] == [(1, "IDENTIFIER")]
    got = (await client.get("/planning/projects/1/chain", headers=as_user(REVIEWER))).json()
    assert got["identifiers"][0]["identifier"] == "DT-2022-55"
    assert any(d["document_id"] == doc_id for d in next(s for s in got["chain"] if s["code"] == "EVALUATION")["documents"])
    assert (await client.get("/planning/projects/1/chain", headers=as_user(VIEWER))).status_code == 403


@pytest.mark.parametrize("uid", [EXPERT])
async def test_relink_needs_editor(client, uid):
    assert (await client.post("/planning/documents/1/relink", headers=as_user(uid))).status_code == 403
