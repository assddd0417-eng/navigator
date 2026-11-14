"""기업·공고 facet 별 임베딩.

기업: SUMMARY, BUSINESS, TECH, PATENT, RND / 공고: SUMMARY, TECH_NEED, PURPOSE
"""
from __future__ import annotations

from psycopg import AsyncConnection

from app.services.embedding import FacetText, _join, _sync, active_model_id


async def rnd_facts(conn: AsyncConnection, org_id: int) -> list[dict]:
    """company_rnd_history + card_company 로 연결된 내부 과제 (중복이면 rnd_history 우선)."""
    return await (await conn.execute(
        """SELECT 'company_rnd_history' AS source_table, h.id AS source_id, h.title, h.summary, h.role,
                  h.start_date, h.end_date, h.origin, h.verified_at IS NOT NULL AS is_verified
             FROM ax.company_rnd_history h WHERE h.organization_id = %(org)s
           UNION ALL
           SELECT DISTINCT ON (p.id) 'project', p.id, p.title, ac.core_achievement,
                  CASE WHEN p.lead_org_id = %(org)s THEN 'LEAD' ELSE 'PARTICIPANT' END,
                  p.start_date, p.end_date, 'INTERNAL', true
             FROM ax.card_company cc
             JOIN ax.achievement_card ac ON ac.id = cc.card_id
             JOIN ax.project p ON p.id = ac.project_id
            WHERE cc.organization_id = %(org)s AND cc.relation_status = 'CONFIRMED'
              AND cc.relation_type IN ('DEVELOPER','TECH_HOLDER')
              AND NOT EXISTS (SELECT 1 FROM ax.company_rnd_history h2
                               WHERE h2.organization_id = %(org)s AND h2.internal_project_id = p.id)""",
        {"org": org_id})).fetchall()


async def company_facets(conn: AsyncConnection, org_id: int) -> list[FacetText]:
    p = await (await conn.execute(
        """SELECT o.name, cp.main_business FROM ax.organization o
             LEFT JOIN ax.company_profile cp ON cp.organization_id = o.id WHERE o.id = %s""",
        (org_id,))).fetchone()
    if p is None:
        return []
    facets = [FacetText("SUMMARY", _join(p["name"], p["main_business"]))]
    if p["main_business"]:
        facets.append(FacetText("BUSINESS", p["main_business"]))
    for t in await (await conn.execute(
            "SELECT id, tech_name, description FROM ax.company_technology WHERE organization_id = %s", (org_id,))).fetchall():
        facets.append(FacetText("TECH", _join(t["tech_name"], t["description"]), "company_technology", t["id"]))
    for pr in await (await conn.execute(
            "SELECT id, name, description, customers FROM ax.company_product WHERE organization_id = %s",
            (org_id,))).fetchall():
        facets.append(FacetText("TECH", _join(pr["name"], pr["description"], pr["customers"]),
                                "company_product", pr["id"]))
    for pt in await (await conn.execute(
            "SELECT id, title, abstract FROM ax.company_patent WHERE organization_id = %s AND status <> 'LAPSED'",
            (org_id,))).fetchall():
        facets.append(FacetText("PATENT", _join(pt["title"], pt["abstract"]), "company_patent", pt["id"]))
    for r in await rnd_facts(conn, org_id):
        facets.append(FacetText("RND", _join(r["title"], r["summary"]), r["source_table"], r["source_id"]))
    return facets


async def announcement_facets(conn: AsyncConnection, ann_id: int) -> list[FacetText]:
    a = await (await conn.execute(
        """SELECT a.title, a.summary, a.target_desc, p.purpose
             FROM ax.announcement a LEFT JOIN ax.program p ON p.id = a.program_id WHERE a.id = %s""",
        (ann_id,))).fetchone()
    if a is None:
        return []
    facets = [FacetText("SUMMARY", _join(a["title"], a["summary"], a["target_desc"]))]
    if a["purpose"] or a["summary"]:
        facets.append(FacetText("PURPOSE", _join(a["purpose"], a["summary"])))
    for t in await (await conn.execute(
            "SELECT id, tech_name, description FROM ax.announcement_tech_need WHERE announcement_id = %s",
            (ann_id,))).fetchall():
        facets.append(FacetText("TECH_NEED", _join(t["tech_name"], t["description"]), "announcement_tech_need", t["id"]))
    return facets


async def sync_company_embeddings(conn: AsyncConnection, org_id: int) -> int:
    return await _sync(conn, "company_embedding", "organization_id", org_id, await company_facets(conn, org_id), {})


async def sync_announcement_embeddings(conn: AsyncConnection, ann_id: int) -> int:
    return await _sync(conn, "announcement_embedding", "announcement_id", ann_id,
                       await announcement_facets(conn, ann_id), {})


async def ensure_embeddings(conn: AsyncConnection) -> dict[str, int]:
    """활성 모델 벡터가 없는 기업·공고만 임베딩 (SQL 로 넣은 데이터용)."""
    model_id = await active_model_id(conn)
    orgs = await (await conn.execute(
        """SELECT cp.organization_id AS id FROM ax.company_profile cp
            WHERE NOT EXISTS (SELECT 1 FROM ax.company_embedding e
                               WHERE e.organization_id = cp.organization_id AND e.model_id = %s)""",
        (model_id,))).fetchall()
    anns = await (await conn.execute(
        """SELECT a.id FROM ax.announcement a
            WHERE NOT EXISTS (SELECT 1 FROM ax.announcement_embedding e
                               WHERE e.announcement_id = a.id AND e.model_id = %s)""", (model_id,))).fetchall()
    return {"companies": sum([await sync_company_embeddings(conn, r["id"]) for r in orgs]),
            "announcements": sum([await sync_announcement_embeddings(conn, r["id"]) for r in anns])}
