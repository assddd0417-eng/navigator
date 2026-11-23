"""상담 보완자료. 담당자가 상담 중 기업에게 받은 인증·수출실적·보유기술 자료를 올린다.

기업이 관리 링크로 올리는 증빙과 같은 표 (company_evidence) 에 담고, 올린 담당자와 상담을 남긴다.
글자와 뽑은 값만 두고 원본 파일은 두지 않는다. 뽑은 값은 담당자가 확인해 진단 변수·회사 정보에 넣는다.
"""
from __future__ import annotations

import hashlib

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.services import company_evidence

KIND_KO = {"CERTIFICATION": "인증·확인서", "CREDIT_RATING": "신용평가", "UNKNOWN": "기타 자료"}
COLS = """e.id, e.file_name, e.file_ext, e.byte_size, e.parse_status, e.parse_note, e.detected_kind, e.detected,
          e.note, e.consultation_id, e.created_at, e.uploaded_by, u.name AS uploaded_by_name,
          left(e.text_content, 600) AS text_excerpt"""


def _out(r: dict) -> dict:
    r["kind_label"] = KIND_KO.get(r["detected_kind"] or "UNKNOWN", "기타 자료")
    r["origin_label"] = "담당자 첨부" if r["uploaded_by"] else "기업 제출"
    return r


async def add(conn: AsyncConnection, org_id: int, name: str, data: bytes, note: str | None, user_id: int) -> dict:
    p = company_evidence.parse(name, data)
    row = await (await conn.execute(
        """INSERT INTO ax.company_evidence (organization_id, file_name, file_ext, byte_size, content_hash, text_content,
                                           parse_status, parse_note, detected_kind, detected, uploaded_by, note)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (organization_id, content_hash) DO UPDATE
               SET file_name = EXCLUDED.file_name, note = coalesce(EXCLUDED.note, ax.company_evidence.note)
           RETURNING id""",
        (org_id, name, name.rsplit(".", 1)[-1].lower() if "." in name else None, len(data),
         hashlib.sha256(data).hexdigest(), p.text, p.status, p.note, p.detected.kind, Jsonb(p.detected.values),
         user_id, note))).fetchone()
    return (await list_for(conn, org_id, ids=[row["id"]]))[0]


async def list_for(conn: AsyncConnection, org_id: int, *, ids: list[int] | None = None,
                   consultation_id: int | None = None) -> list[dict]:
    rows = await (await conn.execute(
        f"""SELECT {COLS} FROM ax.company_evidence e LEFT JOIN ax.app_user u ON u.id = e.uploaded_by
             WHERE e.organization_id = %(org)s AND (%(ids)s::bigint[] IS NULL OR e.id = ANY(%(ids)s))
               AND (%(cid)s::bigint IS NULL OR e.consultation_id = %(cid)s)
             ORDER BY e.id DESC""", {"org": org_id, "ids": ids, "cid": consultation_id})).fetchall()
    return [_out(r) for r in rows]


async def link(conn: AsyncConnection, org_id: int, cid: int, ids: list[int]) -> int:
    """상담에 쓴 보완자료를 상담에 묶는다. 다른 기업 자료는 무시."""
    if not ids:
        return 0
    return (await conn.execute(
        "UPDATE ax.company_evidence SET consultation_id = %s WHERE organization_id = %s AND id = ANY(%s)",
        (cid, org_id, ids))).rowcount


async def delete(conn: AsyncConnection, org_id: int, evidence_id: int) -> None:
    """담당자가 올린 자료만 지운다. 기업이 올린 증빙은 기업이 지운다."""
    row = await (await conn.execute(
        "SELECT uploaded_by FROM ax.company_evidence WHERE id = %s AND organization_id = %s",
        (evidence_id, org_id))).fetchone()
    if row is None:
        raise LookupError(evidence_id)
    if row["uploaded_by"] is None:
        raise PermissionError("기업이 올린 증빙은 기업 화면에서 지웁니다")
    await conn.execute("DELETE FROM ax.company_evidence WHERE id = %s", (evidence_id,))
