"""문서 ↔ 과제 연결: 문서 본문에서 과제번호(또는 다른 번호)·과제명을 찾아 과제에 붙인다.

사업 기획서 → 공모서 → 연구개발계획서 → 결과보고서·평가서 가 과제번호로 이어져야
'이 과제가 왜 기획됐고, 어떻게 끝났고, 무슨 평가를 받았는지'를 한 줄로 볼 수 있다.
- 번호: 대소문자·대시 모양을 맞추고, 앞뒤가 영문·숫자가 아닐 때만 맞은 것으로 본다 (PRJ-2022-001 ≠ PRJ-2022-0011).
- 과제명: 띄어쓰기·문장부호를 빼고 8글자 이상 그대로 나올 때만. 번호로 찾은 과제는 과제명으로 다시 찾지 않는다.
- 공모서·사업 기획서, 또는 과제가 여럿 나온 문서는 '실린 과제'(LISTED), 하나면 '대상 과제'(SUBJECT).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from psycopg import AsyncConnection

from app.repositories.sql import insert

PROGRAM_LEVEL_TYPES = ("PROGRAM_PLAN", "PROGRAM_NOTICE", "PROGRAM_RULE")
_DASHES = re.compile(r"[‐‑‒–—―−－]")
_TITLE_DROP = re.compile(r"[\s\-_()\[\]·.,/「」『』\"'“”‘’]")
MIN_TITLE_CHARS = 8


@dataclass
class ProjectKey:
    project_id: int
    project_no: str
    title: str
    identifiers: list[str] = field(default_factory=list)


@dataclass
class Match:
    project_id: int
    method: str          # PROJECT_NO | IDENTIFIER | TITLE
    matched_text: str


def _norm_no(s: str) -> str:
    return _DASHES.sub("-", s).upper().strip()


def _norm_title(s: str) -> str:
    return _TITLE_DROP.sub("", s).lower()


def find_projects(text: str, projects: list[ProjectKey]) -> list[Match]:
    """본문에 나온 과제 (처음 나온 순서)."""
    up = _DASHES.sub("-", text).upper()
    flat = _norm_title(text)
    found: dict[int, tuple[int, Match]] = {}
    for p in projects:
        for method, ident in [("PROJECT_NO", p.project_no), *(("IDENTIFIER", i) for i in p.identifiers)]:
            key = _norm_no(ident)
            if not key:
                continue
            m = re.search(rf"(?<![A-Z0-9]){re.escape(key)}(?![A-Z0-9])", up)
            if m and (p.project_id not in found or m.start() < found[p.project_id][0]):
                found[p.project_id] = (m.start(), Match(p.project_id, method, ident))
        if p.project_id in found:
            continue
        t = _norm_title(p.title)
        if len(t) >= MIN_TITLE_CHARS:
            pos = flat.find(t)
            if pos >= 0:
                # 과제명은 본문 위치를 대략 맞추려고 원래 글자 길이 비율로 환산
                found[p.project_id] = (int(pos * len(up) / max(len(flat), 1)), Match(p.project_id, "TITLE", p.title))
    return [m for _, m in sorted(found.values(), key=lambda x: x[0])]


def link_role(doc_type_code: str, match_count: int) -> str:
    return "LISTED" if doc_type_code in PROGRAM_LEVEL_TYPES or match_count > 1 else "SUBJECT"


async def link_document(conn: AsyncConnection, document_id: int) -> list[dict]:
    """문서 하나를 과제에 연결한다 (다시 돌려도 안전). 대상 과제가 하나면 문서의 과제와 소관부서(= 과제 소관부서)도 채운다."""
    doc = await (await conn.execute(
        "SELECT id, doc_type_code, title, project_id, program_id, owner_dept_id FROM ax.source_document WHERE id = %s",
        (document_id,))).fetchone()
    text = doc["title"] + "\n" + "\n".join(r["content"] for r in await (await conn.execute(
        "SELECT content FROM ax.document_chunk WHERE document_id = %s ORDER BY chunk_index", (document_id,))).fetchall())
    rows = await (await conn.execute(
        """SELECT p.id, p.project_no, p.title,
                  coalesce(array_agg(i.identifier) FILTER (WHERE i.identifier IS NOT NULL), '{}') AS idents
             FROM ax.project p LEFT JOIN ax.project_identifier i ON i.project_id = p.id
            GROUP BY p.id""")).fetchall()
    matches = find_projects(text, [ProjectKey(r["id"], r["project_no"], r["title"], list(r["idents"])) for r in rows])
    subject = doc["project_id"]
    if subject and all(m.project_id != subject for m in matches):
        matches.insert(0, Match(subject, "MANUAL", ""))
    # 대상 과제를 직접 지정했으면 나머지는 '실린(언급된) 과제', 아니면 문서 종류·찾은 수로 정한다
    role = "LISTED" if subject else link_role(doc["doc_type_code"], len(matches))
    roles = {m.project_id: ("SUBJECT" if m.project_id == subject else role) for m in matches}
    for m in matches:
        await conn.execute(
            """INSERT INTO ax.document_project_link (document_id, project_id, link_role, match_method, matched_text)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (document_id, project_id) DO UPDATE
                  SET link_role = EXCLUDED.link_role, match_method = EXCLUDED.match_method,
                      matched_text = EXCLUDED.matched_text""",
            (document_id, m.project_id, roles[m.project_id], m.method, m.matched_text or None))
    if not subject and role == "SUBJECT" and matches:
        await conn.execute(
            """UPDATE ax.source_document d SET project_id = p.id, owner_dept_id = coalesce(p.department_id, d.owner_dept_id)
                 FROM ax.project p WHERE p.id = %s AND d.id = %s""", (matches[0].project_id, document_id))
    if not subject and role == "LISTED" and doc["program_id"] is None and matches:
        # 실린 과제가 모두 한 사업이면 문서를 그 사업에 붙인다
        progs = await (await conn.execute(
            "SELECT DISTINCT program_id FROM ax.project WHERE id = ANY(%s) AND program_id IS NOT NULL",
            ([m.project_id for m in matches],))).fetchall()
        if len(progs) == 1:
            await conn.execute("UPDATE ax.source_document SET program_id = %s WHERE id = %s",
                               (progs[0]["program_id"], document_id))
    if not matches:
        return []
    names = {r["id"]: (r["project_no"], r["title"]) for r in rows}
    return [{"project_id": m.project_id, "project_no": names[m.project_id][0], "title": names[m.project_id][1],
             "link_role": roles[m.project_id], "match_method": m.method} for m in matches]


async def add_identifier(conn: AsyncConnection, project_id: int, identifier: str, source_system_code: str,
                         note: str | None) -> int:
    return await insert(conn, "project_identifier", {"project_id": project_id, "identifier": identifier.strip(),
                                                     "source_system_code": source_system_code, "note": note})
