"""공고문 점검 항목·판정 기준 설정. 소관부서 협의로 정하고 모든 공고에 공통 적용한다.

  settings  capability_full·capability_partial  역량 항목 충족도 경계 (D-STATE 영역 평균)
            grade_high·grade_mid                 적합도 등급 경계
            partial_ratio                        '부분' 충족 비율 (%)
            check_items                          공고문 점검 항목 [{item, content, kind MANDATORY|FIT|GUIDE}]
바꾸면 새 버전을 만들고 바로 쓴다. 이전 버전은 남는다.
"""
from __future__ import annotations

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.services import fit

KIND_KO = {"MANDATORY": "필수요건", "FIT": "적합도", "GUIDE": "안내"}
NUMBERS = ("capability_full", "capability_partial", "grade_high", "grade_mid", "partial_ratio")


def validate(s: dict) -> dict:
    out = {k: int(s[k]) for k in NUMBERS}
    if not 0 < out["capability_partial"] < out["capability_full"] <= 100:
        raise ValueError("역량 경계는 0 < 부분 < 충분 <= 100 이어야 합니다")
    if not 0 < out["grade_mid"] < out["grade_high"] <= 100:
        raise ValueError("등급 경계는 0 < 중 < 상 <= 100 이어야 합니다")
    if not 0 < out["partial_ratio"] < 100:
        raise ValueError("부분 충족 비율은 1~99 사이여야 합니다")
    items = []
    for x in s.get("check_items") or []:
        item, content = (x.get("item") or "").strip(), (x.get("content") or "").strip()
        if not item or x.get("kind") not in KIND_KO:
            raise ValueError("점검 항목에는 이름과 판정 구분(필수요건·적합도·안내)이 있어야 합니다")
        items.append({"item": item[:50], "content": content[:300], "kind": x["kind"]})
    if not items:
        raise ValueError("점검 항목이 없습니다")
    out["check_items"] = items
    return out


async def active(conn: AsyncConnection) -> dict:
    row = await (await conn.execute(
        "SELECT version, settings FROM ax.review_criteria WHERE is_active")).fetchone()
    if row is None:
        return {**fit.DEFAULT, "version": None, "check_items": []}
    return {**fit.DEFAULT, **row["settings"], "version": row["version"]}


async def view(conn: AsyncConnection) -> dict:
    cur = await active(conn)
    for x in cur["check_items"]:
        x["kind_label"] = KIND_KO[x["kind"]]
    hist = await (await conn.execute(
        """SELECT c.id, c.version, c.is_active, c.note, c.created_at, u.name AS created_by_name, c.settings
             FROM ax.review_criteria c LEFT JOIN ax.app_user u ON u.id = c.created_by
            ORDER BY c.version DESC""")).fetchall()
    return {"active": cur, "history": hist, "kinds": KIND_KO}


async def save(conn: AsyncConnection, settings: dict, note: str | None, user_id: int) -> dict:
    s = validate(settings)
    nv = (await (await conn.execute("SELECT coalesce(max(version), 0) + 1 AS v FROM ax.review_criteria")).fetchone())["v"]
    await conn.execute("UPDATE ax.review_criteria SET is_active = false WHERE is_active")
    await conn.execute(
        "INSERT INTO ax.review_criteria (version, settings, is_active, note, created_by) VALUES (%s, %s, true, %s, %s)",
        (nv, Jsonb(s), note, user_id))
    return await view(conn)


async def activate(conn: AsyncConnection, version: int) -> dict:
    if not await (await conn.execute("SELECT 1 FROM ax.review_criteria WHERE version = %s", (version,))).fetchone():
        raise LookupError(version)
    await conn.execute("UPDATE ax.review_criteria SET is_active = false WHERE is_active")
    await conn.execute("UPDATE ax.review_criteria SET is_active = true WHERE version = %s", (version,))
    return await view(conn)
