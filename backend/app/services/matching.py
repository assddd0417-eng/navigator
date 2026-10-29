"""신규 기획수요 → 기존 성과 매칭 엔진 (DEMAND_TO_CARD).

1) 수요 임베딩 확인  2) 패싯별 HNSW 후보 생성 (ax.match_cards)
3) 후보 카드에 대해 모든 패싯 유사도를 정확히 재계산  4) 5개 기준 점수 → 6대 유형 분류
5) 융합형(기술요소별로 서로 다른 성과) 판정  6) 순위·제외 판정 후 추천·점수·근거·부서/기업 후보 저장
결과는 하나의 match_run 으로 묶이며, 규칙 스냅샷을 함께 남겨 재현할 수 있다.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from psycopg import AsyncConnection

from app.config import get_settings
from app.errors import NotFound
from app.services import embedding as emb
from app.services.rationale import (
    EvidenceSnippet, LLMError, LLMRationaleWriter, RationaleGenerator, RationaleRejected, TemplateRationale,
    get_llm_writer,
)
from app.services.scoring import (
    SINGLE_CARD_TYPES, CardCandidate, CriterionScore, DemandContext, FacetHit, Performance,
    classify, criterion_scores, plan_convergence, to_probabilities, weighted_total,
)

# ANN 후보 생성에 쓰는 (수요 패싯, 카드 패싯)
CANDIDATE_PAIRS = [("TECH_NEED", "OPEN_ISSUE"), ("TECH_NEED", "CORE_TECH"),
                   ("TECH_NEED", "PRINCIPLE"), ("SUMMARY", "SUMMARY")]
# 후보 카드에 대한 정확 유사도 계산 대응표 (카드 패싯, 수요 패싯, 결과 키)
EXACT_PAIRS = [("OPEN_ISSUE", "TECH_NEED", "OPEN_ISSUE"), ("CORE_TECH", "TECH_NEED", "CORE_TECH"),
               ("PRINCIPLE", "TECH_NEED", "PRINCIPLE"), ("SUMMARY", "SUMMARY", "SUMMARY"),
               ("PERFORMANCE", "PERFORMANCE", "PERFORMANCE"),
               ("APPLICATION_ENV", "APPLICATION_ENV", "APPLICATION_ENV"),
               ("SUMMARY", "PURPOSE", "PURPOSE")]
CONVERGENCE_THRESHOLD = 0.5

log = logging.getLogger(__name__)


@dataclass
class Draft:
    linkage: str
    cards: list[CardCandidate]
    scores: dict[str, CriterionScore]
    probabilities: dict[str, float]
    reasons: dict[str, str]
    total: float
    rationale: str
    needs: str | None
    open_issue_id: int | None = None
    contributions: dict[int, str] | None = None


async def load_rules(conn: AsyncConnection) -> dict[str, dict]:
    rows = await (await conn.execute(
        "SELECT linkage_type_code, version, weights, conditions FROM ax.linkage_rule WHERE is_active")).fetchall()
    return {r["linkage_type_code"]: {"version": r["version"], "weights": r["weights"], "conditions": r["conditions"]}
            for r in rows}


async def load_demand(conn: AsyncConnection, demand_id: int) -> DemandContext:
    d = await (await conn.execute(
        """SELECT d.id, d.title, d.required_trl_min, d.required_trl_max, d.requesting_dept_id,
                  p.program_type_code
             FROM ax.planning_demand d LEFT JOIN ax.program p ON p.id = d.target_program_id
            WHERE d.id = %s""", (demand_id,))).fetchone()
    if d is None:
        raise NotFound("기획수요", demand_id)
    reqs = await (await conn.execute(
        "SELECT metric_name, comparator, required_value, required_max, unit FROM ax.demand_performance_req "
        "WHERE demand_id = %s", (demand_id,))).fetchall()
    ws = await (await conn.execute(
        "SELECT weapon_system_id FROM ax.demand_weapon_system WHERE demand_id = %s", (demand_id,))).fetchall()
    return DemandContext(
        demand_id=d["id"], title=d["title"], trl_min=d["required_trl_min"], trl_max=d["required_trl_max"],
        requirements=[Performance(r["metric_name"], r["comparator"], _f(r["required_value"]), _f(r["required_max"]), r["unit"])
                      for r in reqs],
        weapon_system_ids={r["weapon_system_id"] for r in ws},
        target_program_type=d["program_type_code"], requesting_dept_id=d["requesting_dept_id"])


def _f(x) -> float | None:
    return float(x) if x is not None else None


async def candidate_card_ids(conn: AsyncConnection, demand_id: int, k: int) -> set[int]:
    ids: set[int] = set()
    for dfacet, cfacet in CANDIDATE_PAIRS:
        rows = await (await conn.execute("SELECT card_id FROM ax.match_cards(%s, %s, %s, %s)",
                                         (demand_id, dfacet, cfacet, k))).fetchall()
        ids.update(r["card_id"] for r in rows)
    return ids


async def load_candidates(conn: AsyncConnection, demand_id: int, card_ids: list[int]) -> dict[int, CardCandidate]:
    rows = await (await conn.execute(
        """SELECT ac.id, ac.title, ac.trl, p.id AS project_id, p.department_id, pg.program_type_code,
                  EXISTS (SELECT 1 FROM ax.card_company cc WHERE cc.card_id = ac.id AND cc.relation_status <> 'REJECTED')
               OR EXISTS (SELECT 1 FROM ax.card_item ci WHERE ci.card_id = ac.id AND ci.relation_status <> 'REJECTED')
                  AS has_company_or_item
             FROM ax.achievement_card ac
             JOIN ax.project p ON p.id = ac.project_id
             LEFT JOIN ax.program pg ON pg.id = p.program_id
            WHERE ac.id = ANY(%s)""", (card_ids,))).fetchall()
    cards = {r["id"]: CardCandidate(r["id"], r["title"], r["project_id"], r["department_id"],
                                    r["program_type_code"], r["trl"], has_company_or_item=r["has_company_or_item"])
             for r in rows}

    for r in await (await conn.execute(
            "SELECT card_id, metric_name, comparator, achieved_value, unit FROM ax.card_performance "
            "WHERE card_id = ANY(%s)", (card_ids,))).fetchall():
        cards[r["card_id"]].performances.append(
            Performance(r["metric_name"], r["comparator"], _f(r["achieved_value"]), None, r["unit"]))
    for r in await (await conn.execute(
            "SELECT id, card_id, description FROM ax.card_open_issue WHERE card_id = ANY(%s) AND NOT is_resolved",
            (card_ids,))).fetchall():
        cards[r["card_id"]].open_issues[r["id"]] = r["description"]
    for r in await (await conn.execute(
            "SELECT card_id, weapon_system_id FROM ax.card_weapon_system WHERE card_id = ANY(%s) "
            "AND relation_status <> 'REJECTED'", (card_ids,))).fetchall():
        cards[r["card_id"]].weapon_system_ids.add(r["weapon_system_id"])

    pairs = ", ".join(f"('{c}', '{d}', '{key}')" for c, d, key in EXACT_PAIRS)
    for r in await (await conn.execute(
            f"""SELECT DISTINCT ON (ce.card_id, m.key)
                       ce.card_id, m.key, ce.source_table, ce.source_id,
                       1 - (ce.embedding <=> de.embedding) AS sim
                  FROM (VALUES {pairs}) AS m(card_facet, demand_facet, key)
                  JOIN ax.card_embedding ce ON ce.facet = m.card_facet AND ce.card_id = ANY(%s)
                  JOIN ax.demand_embedding de ON de.facet = m.demand_facet AND de.demand_id = %s
                                              AND de.model_id = ce.model_id
                                              AND de.source_table IS NULL  -- 기술요소별 행은 융합형 전용
                 WHERE ce.model_id = (SELECT id FROM ax.embedding_model WHERE is_active)
                 ORDER BY ce.card_id, m.key, sim DESC""", (card_ids, demand_id))).fetchall():
        cards[r["card_id"]].hits[r["key"]] = FacetHit(float(r["sim"]), r["source_table"], r["source_id"])
    return cards


async def convergence_hits(conn: AsyncConnection, demand_id: int, k: int) -> tuple[dict[int, list[tuple[int, float]]], dict[int, str]]:
    """수요 기술요소(demand_technology)별로 CORE_TECH 최근접 카드를 찾는다."""
    elements = await (await conn.execute(
        """SELECT de.source_id AS element_id, dt.tech_name, de.embedding
             FROM ax.demand_embedding de JOIN ax.demand_technology dt ON dt.id = de.source_id
            WHERE de.demand_id = %s AND de.facet = 'TECH_NEED' AND de.source_table = 'demand_technology'
              AND de.model_id = (SELECT id FROM ax.embedding_model WHERE is_active)""", (demand_id,))).fetchall()
    hits: dict[int, list[tuple[int, float]]] = {}
    names: dict[int, str] = {}
    for e in elements:
        names[e["element_id"]] = e["tech_name"]
        rows = await (await conn.execute(
            """SELECT h.card_id, max(h.sim) AS sim FROM (
                   SELECT ce.card_id, 1 - (ce.embedding <=> %(v)s) AS sim
                     FROM ax.card_embedding ce
                    WHERE ce.facet = 'CORE_TECH'
                    ORDER BY ce.embedding <=> %(v)s LIMIT %(k)s) h
                 JOIN ax.achievement_card ac ON ac.id = h.card_id AND ac.status = 'PUBLISHED'
                GROUP BY h.card_id ORDER BY sim DESC""", {"v": e["embedding"], "k": k})).fetchall()
        hits[e["element_id"]] = [(r["card_id"], float(r["sim"])) for r in rows]
    return hits, names


def build_drafts(demand: DemandContext, cards: dict[int, CardCandidate], rules: dict[str, dict],
                 conv: list[tuple[int, int, float]], element_names: dict[int, str],
                 rationale: RationaleGenerator) -> list[Draft]:
    conditions = {k: v["conditions"] for k, v in rules.items()}
    drafts: list[Draft] = []
    per_card_scores: dict[int, dict[str, CriterionScore]] = {}

    for c in cards.values():
        purpose = c.hits.get("PURPOSE")
        scores = criterion_scores(c, demand, purpose.similarity if purpose else None)
        per_card_scores[c.card_id] = scores
        signals, reasons = classify(c, demand, scores, conditions)
        probs = to_probabilities(signals)
        linkage = max(SINGLE_CARD_TYPES, key=lambda t: signals[t])
        total = weighted_total(scores, rules[linkage]["weights"])
        text, needs = rationale.single(linkage, c, demand, scores, reasons[linkage])
        issue = c.hits.get("OPEN_ISSUE")
        drafts.append(Draft(linkage, [c], scores, probs, reasons, total, text, needs,
                            open_issue_id=issue.source_id if linkage == "FOLLOW_UP" and issue else None))

    if conv and all(card_id in cards for _, card_id, _ in conv):
        members = [cards[card_id] for _, card_id, _ in conv]
        merged: dict[str, CriterionScore] = {}
        for crit in ("PERFORMANCE", "TRL", "ENVIRONMENT", "PURPOSE"):
            vals = [per_card_scores[m.card_id][crit].score for m in members]
            merged[crit] = CriterionScore(sum(vals) / len(vals), "mean_of_members")
        sims = [s for _, _, s in conv]
        merged["TECH"] = CriterionScore(sum(sims) / len(sims), "cosine:CORE_TECH↔기술요소(평균)",
                                        {"elements": {element_names[e]: s for e, _, s in conv}})
        total = weighted_total(merged, rules["CONVERGENCE"]["weights"])
        text, needs = rationale.convergence(
            [(cards[cid], element_names[e], s) for e, cid, s in conv], demand)
        drafts.append(Draft("CONVERGENCE", members, merged, {"CONVERGENCE": 1.0},
                            {"CONVERGENCE": f"기술요소 {len(conv)}개를 서로 다른 성과가 충족"}, total, text, needs,
                            contributions={cid: element_names[e] for e, cid, _ in conv}))

    drafts.sort(key=lambda d: d.total, reverse=True)
    return drafts


async def _attach_evidence(conn: AsyncConnection, rec_id: int, d: Draft, demand_id: int, user_id: int) -> None:
    s = get_settings()
    order = 0
    for c in d.cards:
        hit = c.hits.get("OPEN_ISSUE") if d.linkage == "FOLLOW_UP" else c.hits.get("CORE_TECH")
        rows = await (await conn.execute(
            """SELECT evidence_id FROM ax.card_field_evidence
                WHERE card_id = %s
                ORDER BY (target_table = %s AND target_id IS NOT DISTINCT FROM %s) DESC, id
                LIMIT 3""", (c.card_id, hit.source_table if hit else None, hit.source_id if hit else None))).fetchall()
        for r in rows:
            await conn.execute(
                """INSERT INTO ax.recommendation_evidence
                       (recommendation_id, evidence_id, side, role, criterion, explanation, retrieved_by, sort_order)
                   VALUES (%s, %s, 'SOURCE_CARD', 'SUPPORT', 'TECH', %s, 'CARD_FIELD', %s)
                   ON CONFLICT DO NOTHING""",
                (rec_id, r["evidence_id"], f"성과카드 '{c.title}' 구조화 정보의 원문", order))
            order += 1

        # RAG: 수요 기술수요로 원과제 문서를 검색 (요청자 열람권한 적용)
        chunks = await (await conn.execute(
            """SELECT sc.* FROM ax.demand_embedding de,
                      LATERAL ax.search_chunks(de.embedding, %s, %s, NULL, %s) sc
                WHERE de.demand_id = %s AND de.facet = 'TECH_NEED' AND de.source_table IS NULL""",
            (user_id, s.rag_evidence_k, c.project_id, demand_id))).fetchall()
        for ch in chunks:
            ev = await (await conn.execute(
                """INSERT INTO ax.evidence (document_id, section_id, chunk_id, page_start, page_end, quote, location, created_by)
                   SELECT c.document_id, c.section_id, c.id, c.page_start, c.page_end, left(c.content, 300), c.location, 'AI'
                     FROM ax.document_chunk c WHERE c.id = %s
                   RETURNING id""", (ch["chunk_id"],))).fetchone()
            await conn.execute(
                """INSERT INTO ax.recommendation_evidence
                       (recommendation_id, evidence_id, side, role, criterion, relevance_score, explanation, retrieved_by, sort_order)
                   VALUES (%s, %s, 'SOURCE_CARD', 'SUPPORT', 'TECH', %s, %s, 'RAG', %s)""",
                (rec_id, ev["id"], max(0.0, min(1.0, float(ch["similarity"]))),
                 f"{ch['document_title']} {ch['section_no'] or ''} p.{ch['page_start']}", order))
            order += 1


async def _attach_candidates(conn: AsyncConnection, rec_id: int, d: Draft, demand: DemandContext) -> None:
    owner = d.cards[0].project_dept_id
    if owner:
        await conn.execute(
            "INSERT INTO ax.recommendation_department VALUES (%s, %s, 'OWNER', NULL, '원과제 소관부서')", (rec_id, owner))
    collab = {c.project_dept_id for c in d.cards[1:] if c.project_dept_id} | (
        {demand.requesting_dept_id} if demand.requesting_dept_id else set())
    for dept in collab - {owner}:
        await conn.execute(
            "INSERT INTO ax.recommendation_department VALUES (%s, %s, 'COLLABORATOR', NULL, '수요 요청부서/결합 성과 소관부서') "
            "ON CONFLICT DO NOTHING", (rec_id, dept))

    if d.linkage != "COMMERCIALIZATION":
        return
    card_id = d.cards[0].card_id
    companies = await (await conn.execute(
        """INSERT INTO ax.recommendation_company (recommendation_id, organization_id, role, score, reason, relation_status)
           SELECT %s, cc.organization_id,
                  CASE cc.relation_type WHEN 'SIMILAR_PRODUCER' THEN 'SIMILAR_PRODUCER' ELSE 'TECH_HOLDER' END,
                  cc.confidence, '성과카드 기업 관계(' || cc.relation_type || ')', cc.relation_status
             FROM ax.card_company cc
            WHERE cc.card_id = %s AND cc.relation_status <> 'REJECTED'
           ON CONFLICT DO NOTHING
           RETURNING organization_id, relation_status""", (rec_id, card_id))).fetchall()
    await conn.execute(
        """INSERT INTO ax.recommendation_item (recommendation_id, item_id, role, reason, relation_status)
           SELECT %s, ci.item_id, CASE ci.relation_type WHEN 'LOCALIZATION_TARGET' THEN 'LOCALIZATION' ELSE 'APPLICATION' END,
                  '성과카드 품목 관계(' || ci.relation_type || ')', ci.relation_status
             FROM ax.card_item ci WHERE ci.card_id = %s AND ci.relation_status <> 'REJECTED'
           ON CONFLICT DO NOTHING""", (rec_id, card_id))
    for co in companies:
        if co["relation_status"] == "NEEDS_CONFIRMATION":
            await conn.execute(
                """INSERT INTO ax.confirmation_item (recommendation_id, subject_type, description)
                   SELECT %s, 'COMPANY', '기업 ' || o.name || ' 과(와) 성과의 관계 확인 필요'
                     FROM ax.organization o WHERE o.id = %s""", (rec_id, co["organization_id"]))


async def load_llm_evidence(conn: AsyncConnection, rec_id: int, max_security: str) -> list[EvidenceSnippet]:
    """LLM 입력용 근거. 보안등급 상한을 넘는 문서는 원문을 보내지 않는다. 같은 청크는 한 번만."""
    rows = await (await conn.execute(
        """SELECT e.id AS evidence_id, d.id AS document_id, d.title, s.section_no, e.page_start,
                  re.retrieved_by, re.relevance_score, COALESCE(e.quote, left(c.content, 300)) AS quote,
                  COALESCE(e.chunk_id::text, e.id::text) AS dedup_key
             FROM ax.recommendation_evidence re
             JOIN ax.evidence e ON e.id = re.evidence_id
             JOIN ax.source_document d ON d.id = e.document_id
             JOIN ax.code_security_level dl ON dl.code = d.security_code
             LEFT JOIN ax.document_section s ON s.id = e.section_id
             LEFT JOIN ax.document_chunk c ON c.id = e.chunk_id
            WHERE re.recommendation_id = %s
              AND dl.level_rank <= (SELECT level_rank FROM ax.code_security_level WHERE code = %s)
            ORDER BY re.sort_order""", (rec_id, max_security))).fetchall()
    seen: set[str] = set()
    out: list[EvidenceSnippet] = []
    for r in rows:
        if not r["quote"] or r["dedup_key"] in seen:
            continue
        seen.add(r["dedup_key"])
        label = " ".join(x for x in (r["title"], r["section_no"],
                                     f"p.{r['page_start']}" if r["page_start"] is not None else None) if x)
        out.append(EvidenceSnippet(r["evidence_id"], r["document_id"], label, r["quote"], r["retrieved_by"],
                                   float(r["relevance_score"]) if r["relevance_score"] is not None else None))
    return out


async def write_llm_rationales(conn: AsyncConnection, items: list[tuple[int, Draft]], demand: DemandContext,
                               writer: LLMRationaleWriter) -> dict:
    """저장된 추천에 LLM 연계이유를 붙인다. 실패한 추천은 템플릿 문장(rationale)을 그대로 쓴다."""
    s = get_settings()
    inputs = [(rec_id, d, await load_llm_evidence(conn, rec_id, s.llm_evidence_max_security)) for rec_id, d in items]
    sem = asyncio.Semaphore(max(1, s.llm_concurrency))

    async def one(d: Draft, evidence: list[EvidenceSnippet]):
        async with sem:
            try:
                return await writer.write(d.linkage, d.cards, demand, d.scores, d.reasons[d.linkage], d.needs,
                                          evidence, d.contributions)
            except (LLMError, RationaleRejected) as e:
                return e

    results = await asyncio.gather(*(one(d, ev) for _, d, ev in inputs))
    ok = 0
    for (rec_id, _, _), res in zip(inputs, results):
        if isinstance(res, Exception):
            log.warning("추천 %s LLM 연계이유 실패, 템플릿 사용: %s", rec_id, res)
            meta = {"generator": writer.name, "status": "FALLBACK", "error": f"{type(res).__name__}: {res}"}
            await conn.execute("UPDATE ax.recommendation SET rationale_meta = %s WHERE id = %s",
                               (json.dumps(meta, ensure_ascii=False), rec_id))
            continue
        ok += 1
        meta = {"generator": writer.name, "status": "OK", "document_ids": res.document_ids,
                "evidence_ids": res.evidence_ids}
        await conn.execute("UPDATE ax.recommendation SET rationale_llm = %s, rationale_meta = %s WHERE id = %s",
                           (res.text, json.dumps(meta, ensure_ascii=False), rec_id))
    return {"generator": writer.name, "ok": ok, "fallback": len(items) - ok}


async def run_demand_matching(conn: AsyncConnection, demand_id: int, user_id: int, top_k: int | None = None,
                              rationale: RationaleGenerator | None = None,
                              llm_writer: LLMRationaleWriter | None = None) -> int:
    s = get_settings()
    top_k = top_k or s.match_top_k
    rationale = rationale or TemplateRationale()
    llm_writer = llm_writer or get_llm_writer(s)

    demand = await load_demand(conn, demand_id)
    await emb.sync_demand_embeddings(conn, demand_id)
    rules = await load_rules(conn)
    model_id = await emb.active_model_id(conn)

    run = await (await conn.execute(
        """INSERT INTO ax.match_run (run_type, demand_id, model_id, rule_snapshot, params, requested_by, status, started_at)
           VALUES ('DEMAND_TO_CARD', %s, %s, %s, %s, %s, 'RUNNING', clock_timestamp()) RETURNING id""",
        (demand_id, model_id, json.dumps(rules, ensure_ascii=False),
         json.dumps({"top_k": top_k, "facet_k": s.match_facet_k, "ef_search": s.hnsw_ef_search,
                     "min_score": s.match_min_score, "embedder": s.embedder,
                     "rationale_generator": llm_writer.name if llm_writer else "template"}), user_id))).fetchone()
    run_id = run["id"]

    ids = await candidate_card_ids(conn, demand_id, s.match_facet_k)
    conv_hits, element_names = await convergence_hits(conn, demand_id, s.match_facet_k)
    conv = plan_convergence(conv_hits, CONVERGENCE_THRESHOLD)
    ids.update(cid for _, cid, _ in conv)
    cards = await load_candidates(conn, demand_id, sorted(ids)) if ids else {}
    drafts = build_drafts(demand, cards, rules, conv, element_names, rationale)[:top_k]

    llm_items: list[tuple[int, Draft]] = []
    for rank, d in enumerate(drafts, start=1):
        excluded = d.total < s.match_min_score
        rec = await (await conn.execute(
            """INSERT INTO ax.recommendation (match_run_id, demand_id, linkage_type_code, rank, total_score, confidence,
                                              rationale, development_needs, is_excluded, exclusion_reason)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (run_id, demand_id, d.linkage, rank, round(d.total, 5), round(d.probabilities.get(d.linkage, 0.0), 5),
             d.rationale, d.needs, excluded,
             f"종합점수 {d.total:.2f} < 기준 {s.match_min_score}" if excluded else None))).fetchone()
        rec_id = rec["id"]

        for i, c in enumerate(d.cards):
            await conn.execute(
                """INSERT INTO ax.recommendation_source_card (recommendation_id, card_id, role, contribution, open_issue_id)
                   VALUES (%s, %s, %s, %s, %s)""",
                (rec_id, c.card_id, "PRIMARY" if i == 0 else "COMPLEMENTARY",
                 (d.contributions or {}).get(c.card_id), d.open_issue_id if i == 0 else None))
        weights = rules[d.linkage]["weights"]
        wkey = {"TECH": "tech", "PERFORMANCE": "performance", "TRL": "trl", "ENVIRONMENT": "environment", "PURPOSE": "purpose"}
        for crit, sc in d.scores.items():
            await conn.execute(
                "INSERT INTO ax.recommendation_score VALUES (%s, %s, %s, %s, %s, %s)",
                (rec_id, crit, round(sc.score, 5), weights.get(wkey[crit], 0.0), sc.method,
                 json.dumps(sc.detail, ensure_ascii=False, default=float)))
        for code, p in d.probabilities.items():
            await conn.execute(
                "INSERT INTO ax.recommendation_linkage_score VALUES (%s, %s, %s, %s)",
                (rec_id, code, round(p, 5), d.reasons.get(code)))
        await _attach_evidence(conn, rec_id, d, demand_id, user_id)
        await _attach_candidates(conn, rec_id, d, demand)
        if llm_writer and not excluded:  # 제외 후보는 템플릿 문장으로 충분 (호출 비용 절감)
            llm_items.append((rec_id, d))

    if llm_writer and llm_items:
        summary = await write_llm_rationales(conn, llm_items, demand, llm_writer)
        await conn.execute("UPDATE ax.match_run SET params = params || %s WHERE id = %s",
                           (json.dumps({"rationale_llm": summary}, ensure_ascii=False), run_id))

    await conn.execute("UPDATE ax.match_run SET status = 'SUCCEEDED', finished_at = clock_timestamp() WHERE id = %s",
                       (run_id,))
    await conn.execute("UPDATE ax.planning_demand SET status = 'MATCHING' WHERE id = %s AND status IN ('DRAFT','OPEN')",
                       (demand_id,))
    return run_id
