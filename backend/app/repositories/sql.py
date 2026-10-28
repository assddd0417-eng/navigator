"""작은 SQL 헬퍼. 컬럼명은 코드에서만 오고 값은 항상 바인딩한다."""
import json
from typing import Any

from psycopg import AsyncConnection, sql

from app.errors import NotFound


def _adapt(v: Any) -> Any:
    return json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v


async def insert(conn: AsyncConnection, table: str, data: dict[str, Any], returning: str = "id") -> Any:
    cols = list(data)
    q = sql.SQL("INSERT INTO ax.{} ({}) VALUES ({}) RETURNING {}").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, cols)),
        sql.SQL(", ").join(sql.Placeholder() * len(cols)),
        sql.Identifier(returning),
    )
    row = await (await conn.execute(q, [_adapt(data[c]) for c in cols])).fetchone()
    return row[returning]


async def update(conn: AsyncConnection, table: str, row_id: int, data: dict[str, Any],
                 extra_sql: str = "") -> None:
    if not data and not extra_sql:
        return
    sets = [sql.SQL("{} = {}").format(sql.Identifier(c), sql.Placeholder()) for c in data]
    if extra_sql:
        sets.append(sql.SQL(extra_sql))
    q = sql.SQL("UPDATE ax.{} SET {} WHERE id = {}").format(
        sql.Identifier(table), sql.SQL(", ").join(sets), sql.Placeholder())
    cur = await conn.execute(q, [*(_adapt(v) for v in data.values()), row_id])
    if cur.rowcount == 0:
        raise NotFound(table, row_id)


async def evidence_from_chunk(conn: AsyncConnection, chunk_id: int, quote: str | None,
                              page_start: int | None, page_end: int | None, created_by: str = "HUMAN") -> int:
    row = await (await conn.execute(
        """INSERT INTO ax.evidence (document_id, section_id, chunk_id, page_start, page_end, quote, location, created_by)
           SELECT c.document_id, c.section_id, c.id, COALESCE(%s, c.page_start), COALESCE(%s, c.page_end, %s, c.page_start),
                  COALESCE(%s, left(c.content, 300)), c.location, %s
             FROM ax.document_chunk c WHERE c.id = %s
           RETURNING id""",
        (page_start, page_end, page_start, quote, created_by, chunk_id))).fetchone()
    if row is None:
        raise NotFound("청크", chunk_id)
    return row["id"]


# 사용자 등급으로 열람 가능한 보안등급인지 (카드·수요 등 문서 외 객체용)
CLEARANCE_OK = """(SELECT ul.level_rank FROM ax.app_user u JOIN ax.code_security_level ul ON ul.code = u.clearance_code
                    WHERE u.id = %(uid)s)
                  >= (SELECT level_rank FROM ax.code_security_level WHERE code = {col})"""
