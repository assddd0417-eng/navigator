"""갭 분석 실행: 해외 수요마다 가까운 국내 성과 카드를 모아 규칙(gap_rules)으로 판정하고 저장한다.

- 대상 카드: 검수 확정(PUBLISHED) 카드 전체. 열람 제한은 저장된 갭의 보안등급으로 건다
  (갭 등급 = 해외 수요·근거 카드 중 가장 높은 등급).
- 같은 해외 수요를 다시 보면 이전 초안(DRAFT)은 SUPERSEDED 로 바꾸고,
  확정(CONFIRMED)된 갭이 이번에 다시 나오지 않으면 maybe_resolved_at 에 "해소 후보" 시각을 남긴다.
"""
from __future__ import annotations

import logging

from psycopg import AsyncConnection

from app.config import get_settings
from app.db import transaction
from app.repositories.sql import insert
from app.services.embedding import active_model_id
from app.services.gap_rules import (
    CardPerf,
    DemandInput,
    FindingDraft,
    NearCard,
    OpenIssue,
    assess,
    merge_rules,
)
from app.services.scoring import Performance

log = logging.getLogger("app.gap")

# 해외 수요 패싯 → 국내 성과 카드 패싯 (routers/overseas.py 의 국내 성과 검색과 같은 짝)
PAIRS = [("TECH_NEED", "CORE_TECH"), ("TECH_NEED", "OPEN_ISSUE"), ("SUMMARY", "SUMMARY"),
         ("PERFORMANCE", "PERFORMANCE"), ("APPLICATION_ENV", "APPLICATION_ENV")]
_PAIRS_SQL = ", ".join(f"('{a}', '{b}')" for a, b in PAIRS)


def _f(x) -> float | None:
    return float(x) if x is not None else None


async def load_demand(conn: AsyncConnection, demand_id: int) -> DemandInput | None:
    d = await (await conn.execute(
        "SELECT id, title, demand_kind, requirement, confidence, target_period FROM ax.overseas_demand WHERE id = %s",
        (demand_id,))).fetchone()
    if d is None:
        return None
    perfs = await (await conn.execute(
        "SELECT metric_name, comparator, required_value, required_max, unit FROM ax.overseas_demand_performance "
        "WHERE overseas_demand_id = %s ORDER BY sort_order, id", (demand_id,))).fetchall()
    return DemandInput(d["id"], d["title"], d["demand_kind"], d["requirement"], d["confidence"], d["target_period"],
                       [Performance(p["metric_name"], p["comparator"], _f(p["required_value"]), _f(p["required_max"]),
                                    p["unit"]) for p in perfs])


async def near_cards(conn: AsyncConnection, demand_id: int, model_id: int, k: int) -> list[NearCard]:
    rows = await (await conn.execute(
        f"""WITH pairs(dfacet, cfacet) AS (VALUES {_PAIRS_SQL}),
            scored AS (
                SELECT ce.card_id, 1 - (ce.embedding <=> oe.embedding) AS similarity
                  FROM pairs p
                  JOIN ax.overseas_demand_embedding oe
                    ON oe.facet = p.dfacet AND oe.overseas_demand_id = %(id)s AND oe.model_id = %(m)s
                  JOIN ax.card_embedding ce ON ce.facet = p.cfacet AND ce.model_id = %(m)s
            ), best AS (SELECT card_id, max(similarity) AS similarity FROM scored GROUP BY card_id)
            SELECT b.card_id, ac.title, ac.trl, b.similarity
              FROM best b JOIN ax.achievement_card ac ON ac.id = b.card_id AND ac.status = 'PUBLISHED'
             ORDER BY b.similarity DESC LIMIT %(k)s""", {"id": demand_id, "m": model_id, "k": k})).fetchall()
    cards = {r["card_id"]: NearCard(r["card_id"], r["title"], float(r["similarity"]), r["trl"]) for r in rows}
    if not cards:
        return []
    ids = list(cards)
    for p in await (await conn.execute(
            "SELECT id, card_id, metric_name, comparator, target_value, achieved_value, unit, is_achieved "
            "FROM ax.card_performance WHERE card_id = ANY(%s) ORDER BY sort_order, id", (ids,))).fetchall():
        cards[p["card_id"]].performances.append(CardPerf(p["id"], p["metric_name"], p["comparator"], _f(p["target_value"]),
                                                         _f(p["achieved_value"]), p["unit"], p["is_achieved"]))
    # 미해결 과제 + 이 수요와의 유사도 (OPEN_ISSUE 패싯 ↔ 해외 수요 TECH_NEED·SUMMARY 중 큰 값)
    for i in await (await conn.execute(
            """SELECT oi.id, oi.card_id, oi.issue_type, oi.description, oi.priority,
                      (SELECT max(1 - (ce.embedding <=> oe.embedding))
                         FROM ax.card_embedding ce
                         JOIN ax.overseas_demand_embedding oe
                           ON oe.overseas_demand_id = %(id)s AND oe.model_id = %(m)s AND oe.facet IN ('TECH_NEED','SUMMARY')
                        WHERE ce.card_id = oi.card_id AND ce.facet = 'OPEN_ISSUE' AND ce.model_id = %(m)s
                          AND ce.source_table = 'card_open_issue' AND ce.source_id = oi.id) AS similarity
                 FROM ax.card_open_issue oi
                WHERE oi.card_id = ANY(%(ids)s) AND NOT oi.is_resolved ORDER BY oi.sort_order, oi.id""",
            {"id": demand_id, "m": model_id, "ids": ids})).fetchall():
        cards[i["card_id"]].open_issues.append(OpenIssue(i["id"], i["issue_type"], i["description"], i["priority"],
                                                         _f(i["similarity"])))
    # 해외 의존 품목: 카드 품목이 수입품이거나, 그 품목의 BOM 하위에 수입품이 있음
    for r in await (await conn.execute(
            """SELECT DISTINCT ci.card_id, it.name
                 FROM ax.card_item ci
                 JOIN ax.item it ON it.id = ci.item_id
                WHERE ci.card_id = ANY(%(ids)s) AND ci.relation_status <> 'REJECTED' AND it.is_imported
               UNION
               SELECT DISTINCT ci.card_id, ch.name
                 FROM ax.card_item ci
                 JOIN ax.item_bom b ON b.parent_item_id = ci.item_id
                 JOIN ax.item ch ON ch.id = b.child_item_id
                WHERE ci.card_id = ANY(%(ids)s) AND ci.relation_status <> 'REJECTED' AND ch.is_imported
                ORDER BY 1, 2""", {"ids": ids})).fetchall():
        cards[r["card_id"]].imported_items.append(r["name"])
    return list(cards.values())


async def _save(conn: AsyncConnection, run_id: int, demand_id: int, f: FindingDraft) -> int:
    card_ids = [c.card_id for c in f.cards]
    # 보안등급 = 해외 수요·근거 카드 중 가장 높은 등급
    sec = (await (await conn.execute(
        """SELECT l.code FROM ax.code_security_level l
            WHERE l.level_rank = (SELECT max(x.r) FROM (
                    SELECT sl.level_rank AS r FROM ax.overseas_demand d
                      JOIN ax.code_security_level sl ON sl.code = d.security_code WHERE d.id = %s
                    UNION ALL
                    SELECT sl.level_rank FROM ax.achievement_card ac
                      JOIN ax.code_security_level sl ON sl.code = ac.security_code WHERE ac.id = ANY(%s::bigint[])) x)
            LIMIT 1""", (demand_id, card_ids))).fetchone())["code"]
    finding_id = await insert(conn, "gap_finding", {
        "gap_run_id": run_id, "overseas_demand_id": demand_id, "gap_type_code": f.gap_type,
        "severity": f.severity, "score": f.score, "best_similarity": f.best_similarity, "summary": f.summary,
        "detail": f.detail, "security_code": sec})
    for c in f.cards:
        await conn.execute(
            "INSERT INTO ax.gap_finding_card (finding_id, card_id, similarity, role, note) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING", (finding_id, c.card_id, c.similarity, c.role, c.note))
    for n, p in enumerate(f.pathways):
        await insert(conn, "gap_pathway", {"finding_id": finding_id, "linkage_type_code": p.linkage_type,
                                           "description": p.description, "card_ids": p.card_ids, "sort_order": n})
    return finding_id


async def run_gap_analysis(conn: AsyncConnection, user_id: int | None, demand_ids: list[int] | None = None,
                           trigger: str = "MANUAL", rules_override: dict | None = None, note: str | None = None) -> int:
    """해외 수요들(없으면 보관되지 않은 전체)에 대해 갭을 판정·저장하고 gap_run id 를 돌려준다."""
    rules = merge_rules(rules_override)
    if demand_ids is None:
        demand_ids = [r["id"] for r in await (await conn.execute(
            "SELECT id FROM ax.overseas_demand WHERE status <> 'ARCHIVED' ORDER BY id")).fetchall()]
    model_id = await active_model_id(conn)
    run_id = await insert(conn, "gap_run", {"trigger_kind": trigger, "demand_ids": demand_ids, "model_id": model_id,
                                            "rule_snapshot": rules, "note": note, "started_by": user_id})
    total = 0
    for demand_id in demand_ids:
        demand = await load_demand(conn, demand_id)
        if demand is None:
            continue
        findings = assess(demand, await near_cards(conn, demand_id, model_id, int(rules["near_k"])), rules)
        found_types = [f.gap_type for f in findings]
        # 이미 검수자가 판정한 종류(확정·기각)는 다시 초안으로 올리지 않는다
        decided = {r["gap_type_code"] for r in await (await conn.execute(
            "SELECT DISTINCT gap_type_code FROM ax.gap_finding "
            "WHERE overseas_demand_id = %s AND status IN ('CONFIRMED','REJECTED')", (demand_id,))).fetchall()}
        await conn.execute("UPDATE ax.gap_finding SET status = 'SUPERSEDED' "
                           "WHERE overseas_demand_id = %s AND status = 'DRAFT' AND gap_run_id <> %s", (demand_id, run_id))
        await conn.execute(
            "UPDATE ax.gap_finding SET maybe_resolved_at = now() "
            "WHERE overseas_demand_id = %s AND status = 'CONFIRMED' AND maybe_resolved_at IS NULL "
            "AND NOT (gap_type_code = ANY(%s::text[]))", (demand_id, found_types))
        await conn.execute(
            "UPDATE ax.gap_finding SET maybe_resolved_at = NULL "
            "WHERE overseas_demand_id = %s AND status = 'CONFIRMED' AND gap_type_code = ANY(%s::text[])",
            (demand_id, found_types))
        for f in findings:
            if f.gap_type not in decided:
                await _save(conn, run_id, demand_id, f)
                total += 1
    await conn.execute("UPDATE ax.gap_run SET finding_count = %s, finished_at = now() WHERE id = %s", (total, run_id))
    log.info("갭 분석 %s: 해외 수요 %d건 → 갭 %d건 (run %d)", trigger, len(demand_ids), total, run_id)
    return run_id


async def auto_run(user_id: int | None, trigger: str, demand_ids: list[int] | None = None,
                   request_id: str | None = None) -> int | None:
    """새 해외 수요·새 국내 성과가 들어온 뒤 별도 트랜잭션으로 갭 분석을 돌린다.

    GAP_AUTO_RUN=false 면 건너뛴다. 실패해도 원래 요청(올리기·검수 확정)은 이미 저장됐으므로 기록만 남긴다.
    """
    if not get_settings().gap_auto_run:
        return None
    try:
        async with transaction(user_id, request_id) as conn:
            if demand_ids is None and not await (await conn.execute(
                    "SELECT 1 FROM ax.overseas_demand WHERE status <> 'ARCHIVED' LIMIT 1")).fetchone():
                return None
            return await run_gap_analysis(conn, user_id, demand_ids, trigger)
    except Exception:  # noqa: BLE001 — 자동 실행 실패가 원래 요청을 깨지 않게
        log.exception("갭 분석 자동 실행 실패 (%s)", trigger)
        return None

