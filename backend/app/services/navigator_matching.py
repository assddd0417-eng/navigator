"""기업-공고 매칭 (양방향). HNSW 로 후보를 뽑고 쌍별 유사도, 자격요건 판정, 점수를 계산해 저장한다."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from psycopg import AsyncConnection

from app.config import get_settings
from app.errors import NotFound
from app.services.eligibility import (
    RESULT_KO,
    VERDICT_KO,
    Cert,
    Check,
    CompanyFacts,
    Credit,
    Patent,
    Requirement,
    Rnd,
    Support,
    judge,
    overall,
)
from app.services.embedding import active_model_id
from app.services.navigator_embedding import ensure_embeddings, rnd_facts

RULE_VERSION = "navigator-v2"
# NAVIGATOR_RANKING=vector (기본, A안): 규칙 판정으로 거른 뒤 벡터 유사도(요구기술 0.7 + 사업 목적 0.3) 순.
#   IPC 일치·우대 충족은 순위에 넣지 않고 같은 점수일 때만 앞에 둔다.
# weighted: 이전 방식 (기술 .45 · IPC .15 · 목적 .20 · 우대 .20 가중합)
WEIGHTS_BY_MODE = {
    "vector": {"TECH": 0.7, "IPC": 0.0, "PURPOSE": 0.3, "PREFERENCE": 0.0},
    "weighted": {"TECH": 0.45, "IPC": 0.15, "PURPOSE": 0.20, "PREFERENCE": 0.20},
}
WEIGHTS = WEIGHTS_BY_MODE["weighted"]   # 이전 결과 해석용
NEUTRAL = 0.5
VERDICT_ORDER = {"ELIGIBLE": 0, "NEEDS_INFO": 1, "INELIGIBLE": 2}
COMPANY_TECH_FACETS = ("TECH", "PATENT", "RND", "BUSINESS")
COMPANY_SUMMARY_FACETS = ("SUMMARY", "BUSINESS")
SOURCE_KO = {"company_patent": "특허", "company_rnd_history": "R&D 이력", "project": "내부 과제",
             "company_technology": "보유기술", "company_product": "제품", None: "주요사업"}
SENSITIVE_TYPES = ("MIN_CREDIT_GRADE", "REVENUE")   # 공개(사업자번호만) 조회에서는 결과를 가린다


@dataclass
class AnnInfo:
    id: int
    title: str
    agency_name: str
    as_of: date
    receipt_state: str
    receipt_end: date | None
    requirements: list[Requirement] = field(default_factory=list)
    req_meta: dict[int, dict] = field(default_factory=dict)      # requirement_id: 근거·종류명
    tech_needs: dict[int, dict] = field(default_factory=dict)    # tech_need_id: row


@dataclass
class Scored:
    org: CompanyFacts
    ann: AnnInfo
    checks: list[tuple[Requirement, Check]]
    verdict: str
    scores: dict[str, tuple[float, str, dict]]    # criterion: (score, method, detail)
    total: float
    evidence: list[dict]
    rationale: str
    counts: dict[str, int]


async def load_announcements(conn: AsyncConnection, ann_ids: list[int]) -> dict[int, AnnInfo]:
    rows = await (await conn.execute(
        "SELECT id, title, agency_name, receipt_end, receipt_state, series_key, program_id, program_name "
        "FROM ax.v_announcement WHERE id = ANY(%s)", (ann_ids,))).fetchall()
    ctx = {r["id"]: r for r in rows}
    anns = {r["id"]: AnnInfo(r["id"], r["title"], r["agency_name"], r["receipt_end"] or date.today(),
                             r["receipt_state"], r["receipt_end"]) for r in rows}
    ranks = {r["grade"]: r["rank"] for r in await (await conn.execute(
        "SELECT grade, rank FROM ax.code_credit_grade")).fetchall()}
    for r in await (await conn.execute(
            """SELECT r.id, r.announcement_id, r.req_type_code, r.rule, r.is_mandatory, r.description,
                      r.evidence_id, r.source_quote, r.source_page, t.name_ko
                 FROM ax.announcement_requirement r JOIN ax.code_requirement_type t ON t.code = r.req_type_code
                WHERE r.announcement_id = ANY(%s) ORDER BY r.sort_order, r.id""", (ann_ids,))).fetchall():
        rule = dict(r["rule"])
        if r["req_type_code"] == "MIN_CREDIT_GRADE":
            rule["min_rank"] = ranks.get(rule.get("min_grade"), 99)
        if r["req_type_code"] == "DUPLICATE_SUPPORT":   # 같은 사업 판단에 쓰는 공고 정보
            x = ctx[r["announcement_id"]]
            rule.update(_announcement_id=x["id"], _title=x["title"], _series_key=x["series_key"], _program_id=x["program_id"],
                        _program_name=x["program_name"])
        a = anns[r["announcement_id"]]
        a.requirements.append(Requirement(r["id"], r["req_type_code"], rule, r["is_mandatory"], r["description"]))
        a.req_meta[r["id"]] = {"type_name": r["name_ko"], "evidence_id": r["evidence_id"],
                               "quote": r["source_quote"], "page": r["source_page"]}
    for t in await (await conn.execute(
            "SELECT id, announcement_id, tech_name, ipc_codes, is_core FROM ax.announcement_tech_need "
            "WHERE announcement_id = ANY(%s)", (ann_ids,))).fetchall():
        anns[t["announcement_id"]].tech_needs[t["id"]] = t
    return anns


async def load_companies(conn: AsyncConnection, org_ids: list[int]) -> dict[int, CompanyFacts]:
    rows = await (await conn.execute(
        """SELECT o.id, o.name, cp.company_size, COALESCE(cp.opened_on, cp.established_on) AS opened_on, cp.region,
                  cp.employee_count, cp.annual_revenue_krw, cp.business_status, cp.is_defense_company,
                  cp.tax_delinquent, cp.insolvent, cp.rnd_restricted, cp.defense_goods, cp.military_supply_krw,
                  cp.export_krw, cp.procurement_sanctioned
             FROM ax.organization o JOIN ax.company_profile cp ON cp.organization_id = o.id
            WHERE o.id = ANY(%s)""", (org_ids,))).fetchall()
    facts = {r["id"]: CompanyFacts(r["id"], r["name"], r["company_size"], r["opened_on"], r["region"],
                                   r["employee_count"], r["annual_revenue_krw"], r["business_status"],
                                   r["is_defense_company"], r["tax_delinquent"], r["insolvent"], r["rnd_restricted"],
                                   r["defense_goods"], r["military_supply_krw"], r["export_krw"],
                                   r["procurement_sanctioned"]) for r in rows}
    # 외부 확인값 우선
    for r in await (await conn.execute(
            """SELECT organization_id, field_name, preferred_value FROM ax.v_company_field_compare
                WHERE organization_id = ANY(%s) AND any_verified
                  AND field_name IN ('employee_count','annual_revenue_krw')""", (org_ids,))).fetchall():
        v = r["preferred_value"]
        if isinstance(v, (int, float)):
            if r["field_name"] == "employee_count":
                facts[r["organization_id"]].employee_count = int(v)
            else:
                facts[r["organization_id"]].revenue_krw = int(v)
    for r in await (await conn.execute(
            "SELECT organization_id, cert_type_code, issued_on, expires_on, verified_at IS NOT NULL AS v "
            "FROM ax.company_certification WHERE organization_id = ANY(%s)", (org_ids,))).fetchall():
        facts[r["organization_id"]].certs.append(Cert(r["cert_type_code"], r["issued_on"], r["expires_on"], r["v"]))
    for r in await (await conn.execute(
            """SELECT c.organization_id, g.rank, c.rated_on, c.valid_until, c.verified_at IS NOT NULL AS v
                 FROM ax.company_credit_rating c LEFT JOIN ax.code_credit_grade g ON g.grade = c.grade
                WHERE c.organization_id = ANY(%s)""", (org_ids,))).fetchall():
        facts[r["organization_id"]].credits.append(Credit(r["rank"], r["rated_on"], r["valid_until"], r["v"]))
    for r in await (await conn.execute(
            "SELECT organization_id, status, ipc_codes, title FROM ax.company_patent WHERE organization_id = ANY(%s)",
            (org_ids,))).fetchall():
        facts[r["organization_id"]].patents.append(Patent(r["status"], list(r["ipc_codes"] or []), r["title"]))
    for r in await (await conn.execute(
            """SELECT s.organization_id, s.program_name, s.year, s.result, a.series_key, a.program_id, s.announcement_id
                 FROM ax.company_support_history s LEFT JOIN ax.announcement a ON a.id = s.announcement_id
                WHERE s.organization_id = ANY(%s)""", (org_ids,))).fetchall():
        facts[r["organization_id"]].support.append(
            Support(r["program_name"], r["year"], r["result"], r["series_key"], r["program_id"],
                    r["announcement_id"]))
    for org_id in facts:
        facts[org_id].rnd = [Rnd(x["role"], x["end_date"], x["title"]) for x in await rnd_facts(conn, org_id)]
    for r in await (await conn.execute(
            "SELECT organization_id, requirement_id, answer FROM ax.eligibility_answer WHERE organization_id = ANY(%s)",
            (org_ids,))).fetchall():
        facts[r["organization_id"]].answers[r["requirement_id"]] = (r["answer"] or {}).get("value")
    return facts


async def candidate_companies(conn: AsyncConnection, ann_id: int, k: int) -> set[int]:
    ids: set[int] = set()
    for afacet, cfacets in (("TECH_NEED", "('TECH','PATENT','RND')"), ("SUMMARY", "('SUMMARY','BUSINESS')"),
                            ("PURPOSE", "('SUMMARY','BUSINESS')")):
        rows = await (await conn.execute(
            f"""SELECT DISTINCT c.organization_id FROM ax.announcement_embedding ae
                CROSS JOIN LATERAL (
                    SELECT ce.organization_id FROM ax.company_embedding ce
                     WHERE ce.facet IN {cfacets} AND ce.model_id = ae.model_id
                     ORDER BY ce.embedding <=> ae.embedding LIMIT %(k)s) c
                WHERE ae.announcement_id = %(ann)s AND ae.facet = %(f)s
                  AND ae.model_id = (SELECT id FROM ax.embedding_model WHERE is_active)""",
            {"ann": ann_id, "f": afacet, "k": k * 4})).fetchall()
        ids.update(r["organization_id"] for r in rows)
    if not ids:
        return ids
    rows = await (await conn.execute(
        "SELECT organization_id FROM ax.company_profile cp JOIN ax.organization o ON o.id = cp.organization_id "
        "WHERE cp.organization_id = ANY(%s) AND o.org_type = 'COMPANY' AND o.is_active",
        (list(ids),))).fetchall()
    return {r["organization_id"] for r in rows}


async def candidate_announcements(conn: AsyncConnection, org_id: int, k: int, states: tuple[str, ...],
                                  closed_since: date | None = None) -> set[int]:
    ids: set[int] = set()
    # 상태 조건을 이웃 검색 안에 넣어야 마감 공고가 많아도 현재 공고 후보가 밀려나지 않는다
    pool = """SELECT id FROM ax.v_announcement WHERE status = 'PUBLISHED' AND receipt_state = ANY(%(states)s)
                 AND (%(since)s::date IS NULL OR receipt_end >= %(since)s::date)"""
    for cfacets, afacets in (("('TECH','PATENT','RND','BUSINESS')", "('TECH_NEED')"),
                             ("('SUMMARY','BUSINESS')", "('SUMMARY','PURPOSE')")):
        rows = await (await conn.execute(
            f"""SELECT DISTINCT a.announcement_id FROM ax.company_embedding ce
                CROSS JOIN LATERAL (
                    SELECT ae.announcement_id FROM ax.announcement_embedding ae
                     WHERE ae.facet IN {afacets} AND ae.model_id = ce.model_id
                       AND ae.announcement_id IN ({pool})
                     ORDER BY ae.embedding <=> ce.embedding LIMIT %(k)s) a
                WHERE ce.organization_id = %(org)s AND ce.facet IN {cfacets}
                  AND ce.model_id = (SELECT id FROM ax.embedding_model WHERE is_active)""",
            {"org": org_id, "k": k * 4, "states": list(states), "since": closed_since})).fetchall()
        ids.update(r["announcement_id"] for r in rows)
    return ids


async def pair_similarities(conn: AsyncConnection, org_ids: list[int], ann_ids: list[int]) -> list[dict]:
    return await (await conn.execute(
        """SELECT ae.announcement_id, ae.facet AS afacet, ae.source_id AS tech_need_id,
                  ce.organization_id, ce.facet AS cfacet, ce.source_table, ce.source_id, ce.source_text,
                  1 - (ce.embedding <=> ae.embedding) AS sim
             FROM ax.announcement_embedding ae
             JOIN ax.company_embedding ce ON ce.model_id = ae.model_id
            WHERE ae.model_id = (SELECT id FROM ax.embedding_model WHERE is_active)
              AND ae.announcement_id = ANY(%s) AND ce.organization_id = ANY(%s)
              AND ((ae.facet = 'TECH_NEED' AND ce.facet IN ('TECH','PATENT','RND','BUSINESS'))
                OR (ae.facet IN ('SUMMARY','PURPOSE') AND ce.facet IN ('SUMMARY','BUSINESS')))""",
        (ann_ids, org_ids))).fetchall()


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _ipc_subclass(code: str) -> str:
    return code.replace(" ", "")[:4].upper()


def score_pair(org: CompanyFacts, ann: AnnInfo, sims: list[dict]) -> Scored:
    checks = [(req, judge(req, org, ann.as_of)) for req in ann.requirements]
    verdict = overall(checks)
    mand = [ch for req, ch in checks if req.is_mandatory]
    pref = [ch for req, ch in checks if not req.is_mandatory]
    counts = {"mandatory_met": sum(c.result == "MET" for c in mand), "mandatory_total": len(mand),
              "preferred_met": sum(c.result == "MET" for c in pref), "preferred_total": len(pref)}

    # TECH: 요구기술별 최대 유사도, 핵심 요구기술 x2
    best: dict[int, dict] = {}
    for s in sims:
        if s["afacet"] == "TECH_NEED" and s["tech_need_id"] in ann.tech_needs:
            cur = best.get(s["tech_need_id"])
            if cur is None or s["sim"] > cur["sim"]:
                best[s["tech_need_id"]] = s
    evidence: list[dict] = []
    if ann.tech_needs:
        num = den = 0.0
        per_need = {}
        for tn_id, tn in ann.tech_needs.items():
            w = 2.0 if tn["is_core"] else 1.0
            hit = best.get(tn_id)
            sim = _clamp(float(hit["sim"])) if hit else 0.0
            num, den = num + w * sim, den + w
            per_need[tn["tech_name"]] = round(sim, 4)
            if hit:
                evidence.append({"kind": "TECH_MATCH", "company_source_table": hit["source_table"],
                                 "company_source_id": hit["source_id"], "company_text": hit["source_text"][:300],
                                 "tech_need_id": tn_id, "similarity": round(sim, 5)})
        tech = (num / den, "cosine max per tech need, core x2", {"per_tech_need": per_need})
    else:
        tech = (NEUTRAL, "neutral:요구기술 없음", {})

    # IPC: 서브클래스(4자리) 일치 비율
    company_ipc = {_ipc_subclass(c) for p in org.patents if p.status != "LAPSED" for c in p.ipc_codes}
    with_ipc = [(tn_id, tn) for tn_id, tn in ann.tech_needs.items() if tn["ipc_codes"]]
    if with_ipc and org.patents:
        matched = []
        for tn_id, tn in with_ipc:
            common = sorted({_ipc_subclass(c) for c in tn["ipc_codes"]} & company_ipc)
            if common:
                matched.append(tn["tech_name"])
                evidence.append({"kind": "IPC_MATCH", "tech_need_id": tn_id, "company_text": ", ".join(common)})
        ipc = (len(matched) / len(with_ipc), "ipc:소분류 일치 비율", {"matched": matched, "considered": len(with_ipc)})
    else:
        ipc = (NEUTRAL, "neutral:" + ("요구기술 IPC 없음" if not with_ipc else "기업 특허 없음"), {})

    purpose_sims = [float(s["sim"]) for s in sims if s["afacet"] in ("SUMMARY", "PURPOSE")]
    purpose = ((_clamp(max(purpose_sims)), "cosine max (summary/purpose vs summary/business)", {})
               if purpose_sims else (NEUTRAL, "neutral:벡터 없음", {}))

    preference = ((counts["preferred_met"] / len(pref), "rule:우대 요건 충족 비율",
                   {"met": counts["preferred_met"], "total": len(pref)})
                  if pref else (NEUTRAL, "neutral:우대 요건 없음", {}))

    scores = {"TECH": tech, "IPC": ipc, "PURPOSE": purpose, "PREFERENCE": preference}
    total = combine(scores)

    for req, ch in checks:
        if ch.result != "MET" or not req.is_mandatory:
            meta = ann.req_meta[req.id]
            evidence.append({"kind": "REQUIREMENT", "requirement_id": req.id, "evidence_id": meta["evidence_id"],
                             "quote": meta["quote"], "page": meta["page"]})
    return Scored(org, ann, checks, verdict, scores, total, evidence,
                  rationale_text(org, ann, checks, verdict, scores, best, counts), counts)


def rationale_text(org: CompanyFacts, ann: AnnInfo, checks: list[tuple[Requirement, Check]], verdict: str,
                   scores: dict, best: dict[int, dict], counts: dict[str, int]) -> str:
    head = f"필수 요건 {counts['mandatory_met']}/{counts['mandatory_total']}개 충족"
    if counts["preferred_total"]:
        head += f", 우대 {counts['preferred_met']}/{counts['preferred_total']}개"
    head += "."
    if best:
        tn_id, hit = max(best.items(), key=lambda kv: kv[1]["sim"])
        head += (f" 요구기술 '{ann.tech_needs[tn_id]['tech_name']}'와 가장 가까운 {SOURCE_KO.get(hit['source_table'], '기업 정보')}: "
                 f"'{hit['source_text'].splitlines()[0][:60]}'.")
    if verdict == "INELIGIBLE":
        head += " 미충족 필수 요건: " + "; ".join(req.description for req, ch in checks
                                              if req.is_mandatory and ch.result == "UNMET") + "."
    elif verdict == "NEEDS_INFO":
        head += " 확인이 필요한 요건: " + "; ".join(req.description for req, ch in checks
                                              if req.is_mandatory and ch.result == "UNKNOWN") + "."
    return head


def ranking_mode() -> str:
    mode = get_settings().navigator_ranking.lower()
    if mode not in WEIGHTS_BY_MODE:
        raise ValueError(f"NAVIGATOR_RANKING={mode} (vector|weighted)")
    return mode


def weights() -> dict[str, float]:
    return WEIGHTS_BY_MODE[ranking_mode()]


def combine(scores: dict[str, tuple]) -> float:
    """기준별 점수 → 관련도. vector 모드는 값이 없는(neutral) 기준을 빼고 나머지 비율로 다시 나눈다."""
    w = weights()
    if ranking_mode() == "weighted":
        return _clamp(sum(w[k] * v[0] for k, v in scores.items()))
    used = {k: w[k] for k, v in scores.items() if w[k] > 0 and not str(v[1]).startswith("neutral")}
    if not used:
        return NEUTRAL
    return _clamp(sum(wk * scores[k][0] for k, wk in used.items()) / sum(used.values()))


def rank(scored: list[Scored]) -> list[Scored]:
    # 판정 → 관련도 → (같으면) 우대 충족 → IPC 일치
    return sorted(scored, key=lambda s: (VERDICT_ORDER[s.verdict], -round(s.total, 4),
                                         -s.scores["PREFERENCE"][0], -s.scores["IPC"][0],
                                         s.org.organization_id, s.ann.id))


def rule_snapshot() -> dict[str, Any]:
    s = get_settings()
    return {"version": RULE_VERSION, "ranking": ranking_mode(), "weights": weights(),
            "candidate_k": s.navigator_match_candidate_k,
            "verdict": "mandatory UNMET=INELIGIBLE, UNKNOWN=NEEDS_INFO", "neutral": NEUTRAL}


async def _save(conn: AsyncConnection, direction: str, ranked: list[Scored], *, ann_id: int | None,
                org_id: int | None, requested_by: int | None, via: str, params: dict) -> int:
    run = await (await conn.execute(
        """INSERT INTO ax.company_match_run (direction, announcement_id, organization_id, model_id, rule_snapshot,
                                             params, requested_by, requested_via, candidate_count)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (direction, ann_id, org_id, await active_model_id(conn), json.dumps(rule_snapshot(), ensure_ascii=False),
         json.dumps(params, ensure_ascii=False), requested_by, via, len(ranked)))).fetchone()
    for i, s in enumerate(ranked, 1):
        rec = await (await conn.execute(
            """INSERT INTO ax.company_recommendation
                      (match_run_id, organization_id, announcement_id, rank, total_score, verdict,
                       mandatory_met, mandatory_total, preferred_met, preferred_total, rationale)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (run["id"], s.org.organization_id, s.ann.id, i, round(s.total, 5), s.verdict,
             s.counts["mandatory_met"], s.counts["mandatory_total"], s.counts["preferred_met"],
             s.counts["preferred_total"], s.rationale))).fetchone()
        rec_id = rec["id"]
        for crit, (score, method, detail) in s.scores.items():
            await conn.execute(
                "INSERT INTO ax.company_recommendation_score (recommendation_id, criterion, score, weight, method, detail) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (rec_id, crit, round(_clamp(score), 5), weights()[crit], method, json.dumps(detail, ensure_ascii=False)))
        for req, ch in s.checks:
            await conn.execute(
                """INSERT INTO ax.eligibility_check (recommendation_id, requirement_id, result, is_mandatory, reason,
                                                     question, detail, self_declared)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (rec_id, req.id, ch.result, req.is_mandatory, ch.reason, ch.question,
                 json.dumps(ch.detail, ensure_ascii=False, default=str), ch.self_declared))
        for j, e in enumerate(s.evidence):
            await conn.execute(
                """INSERT INTO ax.company_recommendation_evidence
                          (recommendation_id, kind, company_source_table, company_source_id, company_text,
                           tech_need_id, requirement_id, evidence_id, quote, page, similarity, sort_order)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (rec_id, e["kind"], e.get("company_source_table"), e.get("company_source_id"), e.get("company_text"),
                 e.get("tech_need_id"), e.get("requirement_id"), e.get("evidence_id"), e.get("quote"),
                 e.get("page"), e.get("similarity"), j))
    return run["id"]


async def match_announcement(conn: AsyncConnection, ann_id: int, *, requested_by: int | None,
                             via: str = "STAFF", org_ids: list[int] | None = None) -> int:
    """org_ids 를 주면 후보 검색 없이 그 기업들만 판정 (알림 구독 기업)."""
    if not await (await conn.execute("SELECT 1 FROM ax.announcement WHERE id = %s", (ann_id,))).fetchone():
        raise NotFound("공고", ann_id)
    await ensure_embeddings(conn)
    k = get_settings().navigator_match_candidate_k
    params: dict[str, Any] = {"candidate_k": k}
    if org_ids is None:
        org_ids = sorted(await candidate_companies(conn, ann_id, k))
    else:
        org_ids, params = sorted(set(org_ids)), {"organization_ids": sorted(set(org_ids))}
    anns = await load_announcements(conn, [ann_id])
    orgs = await load_companies(conn, org_ids)
    sims = await pair_similarities(conn, org_ids, [ann_id]) if org_ids else []
    by_org: dict[int, list[dict]] = {}
    for s in sims:
        by_org.setdefault(s["organization_id"], []).append(s)
    ranked = rank([score_pair(orgs[o], anns[ann_id], by_org.get(o, [])) for o in org_ids if o in orgs])
    return await _save(conn, "ANNOUNCEMENT_TO_COMPANY", ranked, ann_id=ann_id, org_id=None,
                       requested_by=requested_by, via=via, params=params)


def past_since(today: date | None = None) -> date:
    t = today or date.today()
    years = get_settings().navigator_past_years
    try:
        return t.replace(year=t.year - years)
    except ValueError:          # 2월 29일
        return t.replace(year=t.year - years, day=28)


async def match_company(conn: AsyncConnection, org_id: int, *, include_closed: bool = False, past: bool = False,
                        requested_by: int | None = None, via: str = "COMPANY_LINK") -> int:
    """past=True 면 최근 N년 안에 마감된 공고만 (참여할 수 있었던 사업). 판정 기준일은 각 공고 마감일."""
    await ensure_embeddings(conn)
    k = get_settings().navigator_match_candidate_k
    since = None
    if past:
        states, since = ("CLOSED",), past_since()
    else:
        states = ("OPEN", "UPCOMING", "CLOSED") if include_closed else ("OPEN", "UPCOMING")
    ann_ids = sorted(await candidate_announcements(conn, org_id, k, states, since))
    orgs = await load_companies(conn, [org_id])
    if org_id not in orgs:
        raise NotFound("기업 프로필", org_id)
    anns = await load_announcements(conn, ann_ids) if ann_ids else {}
    if past and orgs[org_id].opened_on:     # 회사가 생기기 전에 마감된 공고는 뺀다
        ann_ids = [a for a in ann_ids if anns[a].as_of >= orgs[org_id].opened_on]
    sims = await pair_similarities(conn, [org_id], ann_ids) if ann_ids else []
    by_ann: dict[int, list[dict]] = {}
    for s in sims:
        by_ann.setdefault(s["announcement_id"], []).append(s)
    ranked = rank([score_pair(orgs[org_id], anns[a], by_ann.get(a, [])) for a in ann_ids])
    return await _save(conn, "COMPANY_TO_ANNOUNCEMENT", ranked, ann_id=None, org_id=org_id,
                       requested_by=requested_by, via=via,
                       params={"candidate_k": k, "include_closed": include_closed, "past": past,
                               "closed_since": since.isoformat() if since else None})


async def fresh_company_run(conn: AsyncConnection, org_id: int, include_closed: bool,
                            past: bool = False) -> int | None:
    """오늘 실행했고 이후 변경이 없으면 그 run id 재사용."""
    row = await (await conn.execute(
        """SELECT r.id FROM ax.company_match_run r
            WHERE r.direction = 'COMPANY_TO_ANNOUNCEMENT' AND r.organization_id = %(org)s
              AND (r.params->>'include_closed')::boolean = %(closed)s
              AND coalesce((r.params->>'past')::boolean, false) = %(past)s
              AND r.created_at::date = current_date
              AND r.model_id = (SELECT id FROM ax.embedding_model WHERE is_active)
              AND r.created_at > GREATEST(
                    (SELECT updated_at FROM ax.company_profile WHERE organization_id = %(org)s),
                    (SELECT max(updated_at) FROM ax.announcement),
                    (SELECT max(answered_at) FROM ax.eligibility_answer WHERE organization_id = %(org)s),
                    (SELECT max(recorded_at) FROM ax.company_field_source WHERE organization_id = %(org)s),
                    (SELECT max(updated_at) FROM ax.company_patent WHERE organization_id = %(org)s),
                    (SELECT max(updated_at) FROM ax.company_certification WHERE organization_id = %(org)s),
                    (SELECT max(updated_at) FROM ax.company_credit_rating WHERE organization_id = %(org)s),
                    (SELECT max(updated_at) FROM ax.company_rnd_history WHERE organization_id = %(org)s),
                    (SELECT max(updated_at) FROM ax.company_product WHERE organization_id = %(org)s),
                    (SELECT max(created_at) FROM ax.company_technology WHERE organization_id = %(org)s),
                    (SELECT max(updated_at) FROM ax.company_support_history WHERE organization_id = %(org)s))
              AND r.rule_snapshot->>'version' = %(ver)s
              AND r.rule_snapshot->>'ranking' = %(mode)s
            ORDER BY r.created_at DESC LIMIT 1""",
        {"org": org_id, "closed": include_closed, "past": past, "ver": RULE_VERSION, "mode": ranking_mode()})).fetchone()
    return row["id"] if row else None


async def run_results(conn: AsyncConnection, run_id: int, *, public: bool = False,
                      verdicts: tuple[str, ...] | None = None) -> dict:
    run = await (await conn.execute(
        """SELECT r.id, r.direction, r.announcement_id, r.organization_id, r.rule_snapshot, r.requested_via,
                  r.candidate_count, r.created_at, m.name AS model
             FROM ax.company_match_run r JOIN ax.embedding_model m ON m.id = r.model_id WHERE r.id = %s""",
        (run_id,))).fetchone()
    if run is None:
        raise NotFound("매칭 실행", run_id)
    recs = await (await conn.execute(
        """SELECT cr.id, cr.rank, cr.organization_id, o.name AS company_name, o.business_reg_no,
                  cr.announcement_id, a.announcement_no, a.title AS announcement_title, a.agency_name,
                  a.receipt_end, a.receipt_state, cr.total_score, cr.verdict, cr.mandatory_met, cr.mandatory_total,
                  cr.preferred_met, cr.preferred_total, cr.rationale
             FROM ax.company_recommendation cr
             JOIN ax.organization o ON o.id = cr.organization_id
             JOIN ax.v_announcement a ON a.id = cr.announcement_id
            WHERE cr.match_run_id = %s AND (%s::text[] IS NULL OR cr.verdict = ANY(%s))
            ORDER BY cr.rank""", (run_id, list(verdicts) if verdicts else None,
                                  list(verdicts) if verdicts else None))).fetchall()
    ids = [r["id"] for r in recs]
    scores: dict[int, dict] = {}
    for s in await (await conn.execute(
            "SELECT recommendation_id, criterion, score, weight, method, detail FROM ax.company_recommendation_score "
            "WHERE recommendation_id = ANY(%s)", (ids,))).fetchall():
        scores.setdefault(s["recommendation_id"], {})[s["criterion"]] = {
            "score": float(s["score"]), "weight": float(s["weight"]), "method": s["method"], "detail": s["detail"]}
    checks: dict[int, list] = {}
    for c in await (await conn.execute(
            """SELECT ec.recommendation_id, ec.requirement_id, r.req_type_code, t.name_ko AS req_type_name,
                      r.description, ec.is_mandatory, ec.result, ec.reason, ec.question, ec.detail, ec.self_declared,
                      r.source_quote, r.source_page
                 FROM ax.eligibility_check ec
                 JOIN ax.announcement_requirement r ON r.id = ec.requirement_id
                 JOIN ax.code_requirement_type t ON t.code = r.req_type_code
                WHERE ec.recommendation_id = ANY(%s) ORDER BY ec.is_mandatory DESC, r.sort_order, r.id""",
            (ids,))).fetchall():
        c["result_label"] = RESULT_KO[c["result"]]
        c["mandatory_label"] = "필수" if c["is_mandatory"] else "우대"
        if public and c["req_type_code"] in SENSITIVE_TYPES:
            c.update(result=None, result_label="회사 정보에서 확인", reason="회사 정보 입력·수정에서 확인할 수 있습니다",
                     question=None, detail={})
        checks.setdefault(c.pop("recommendation_id"), []).append(c)
    evidence: dict[int, list] = {}
    for e in await (await conn.execute(
            """SELECT ev.recommendation_id, ev.kind, ev.company_source_table, ev.company_source_id, ev.company_text,
                      ev.tech_need_id, tn.tech_name, ev.requirement_id, ev.evidence_id, e.chunk_id AS evidence_chunk_id,
                      ev.quote, ev.page, ev.similarity
                 FROM ax.company_recommendation_evidence ev
                 LEFT JOIN ax.announcement_tech_need tn ON tn.id = ev.tech_need_id
                 LEFT JOIN ax.evidence e ON e.id = ev.evidence_id
                WHERE ev.recommendation_id = ANY(%s) ORDER BY ev.sort_order""", (ids,))).fetchall():
        evidence.setdefault(e.pop("recommendation_id"), []).append(e)
    for r in recs:
        r["total_score"] = float(r["total_score"])
        r["verdict_label"] = VERDICT_KO[r["verdict"]]
        r["scores"] = scores.get(r["id"], {})
        r["checks"] = checks.get(r["id"], [])
        r["questions"] = [{"requirement_id": c["requirement_id"], "question": c["question"]}
                          for c in r["checks"] if c["result"] == "UNKNOWN" and c["question"]]
        r["evidence"] = evidence.get(r["id"], [])
        if public:
            _redact_public(r)
    if public:
        recs.sort(key=lambda r: (VERDICT_ORDER[r["verdict"]], -r["total_score"], r["announcement_id"]))
        for i, r in enumerate(recs, 1):
            r["rank"] = i
    summary = {v: sum(r["verdict"] == v for r in recs) for v in VERDICT_ORDER}
    return {"run": run, "summary": summary, "recommendations": recs}


async def add_past_context(conn: AsyncConnection, org_id: int, res: dict) -> dict:
    """마감 공고 결과에 덧붙임: 같은 사업의 지금 열린 공고(next_round), 기업이 이미 참여 이력에 적은 공고(participated)."""
    recs = res["recommendations"]
    ids = [r["announcement_id"] for r in recs]
    nxt = {r["past_id"]: r for r in await (await conn.execute(
        """SELECT DISTINCT ON (p.id) p.id AS past_id, n.id, n.title, n.receipt_state, n.receipt_start, n.receipt_end
             FROM ax.announcement p
             JOIN ax.v_announcement n ON n.series_key = p.series_key AND n.id <> p.id
            WHERE p.id = ANY(%s) AND p.series_key IS NOT NULL
              AND n.status = 'PUBLISHED' AND n.receipt_state IN ('OPEN', 'UPCOMING')
            ORDER BY p.id, n.receipt_end NULLS LAST""", (ids,))).fetchall()}
    joined = {r["announcement_id"] for r in await (await conn.execute(
        """SELECT announcement_id FROM ax.company_support_history
            WHERE organization_id = %s AND announcement_id = ANY(%s)""", (org_id, ids))).fetchall()}
    for r in recs:
        n = nxt.get(r["announcement_id"])
        r["next_round"] = {k: n[k] for k in ("id", "title", "receipt_state", "receipt_start", "receipt_end")} if n else None
        r["participated"] = r["announcement_id"] in joined
    res["closed_since"] = past_since().isoformat()
    return res


def _redact_public(r: dict) -> None:
    # 가린 요건(신용·매출)이 판정으로 새지 않게 나머지 요건만으로 판정 재계산
    r.pop("business_reg_no", None)
    shown = [c for c in r["checks"] if c["result"] is not None]
    mand = [c for c in shown if c["is_mandatory"]]
    pref = [c for c in shown if not c["is_mandatory"]]
    if any(c["result"] == "UNMET" for c in mand):
        verdict = "INELIGIBLE"
    elif any(c["result"] == "UNKNOWN" for c in mand):
        verdict = "NEEDS_INFO"
    else:
        verdict = "ELIGIBLE"
    hidden = len(r["checks"]) - len(shown)
    r.update(verdict=verdict, verdict_label=VERDICT_KO[verdict],
             mandatory_met=sum(c["result"] == "MET" for c in mand), mandatory_total=len(mand),
             preferred_met=sum(c["result"] == "MET" for c in pref), preferred_total=len(pref),
             hidden_requirements=hidden, questions=[])
    text = f"공개 정보 기준 필수 요건 {r['mandatory_met']}/{r['mandatory_total']}개 충족."
    if hidden:
        text += f" 신용등급·매출 요건 {hidden}개는 '회사 정보 입력·수정'에서 확인."
    r["rationale"] = text
    r["evidence"] = [e for e in r["evidence"] if e["kind"] != "REQUIREMENT"
                     or any(c["requirement_id"] == e["requirement_id"] for c in shown)]
