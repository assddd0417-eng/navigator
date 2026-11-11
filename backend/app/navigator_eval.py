"""Navigator 판정·추천 검증.

seeds/navigator_eval/corpus.json 의 가상 기업 20곳(시드 101~103 + 111~127)과 공고 101~105 를 짝지어
1) 판정(적합/정보부족/부적격)과 걸린 필수 요건이 정답과 같은지,
2) 공고별 추천 순위에서 정답 기업이 상위 K 안에 드는지 잰다.

    cd backend
    python -m app.navigator_eval load    # 기업 111~127 넣기 (재실행 안전)
    python -m app.navigator_eval eval    # 측정 (eval_run 에 기록)
    python -m app.navigator_eval all     # load + eval
    python -m app.navigator_eval clean   # 기업 111~127 비활성화 (화면·매칭에서 빠짐)

전제: 마이그레이션, seeds/init_test_data.sql, navigator_companies.sql, navigator_announcements.sql.
보완질문 답(TRL, 보안측정)은 DB 에 넣지 않고 측정할 때만 corpus 의 answers 를 쓴다.
판정은 규칙이라 임베더와 무관하다. 순위는 EMBEDDER=bge_m3 로 잰 값만 의미가 있다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import date
from pathlib import Path

from app.config import get_settings
from app.db import close_pool, transaction
from app.services.navigator_embedding import ensure_embeddings
from app.services.navigator_matching import (
    candidate_companies,
    load_announcements,
    load_companies,
    pair_similarities,
    rank,
    score_pair,
)

log = logging.getLogger("app.navigator_eval")

CORPUS = Path(__file__).resolve().parents[2] / "seeds" / "navigator_eval" / "corpus.json"
PLANNER = 1
TOP_KS = (3, 5)
VERDICT_KO = {"ELIGIBLE": "적합", "NEEDS_INFO": "정보부족", "INELIGIBLE": "부적격"}


def load_corpus(path: Path = CORPUS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_expected(v: str) -> tuple[str, frozenset[str]]:
    verdict, _, why = v.partition(":")
    return verdict, frozenset(x for x in why.split(",") if x)


def _d(v: str | None) -> date | None:
    return date.fromisoformat(v) if v else None


async def load(c: dict) -> int:
    new = [x for x in c["companies"] if not x.get("seed")]
    ids = [x["id"] for x in new]
    async with transaction(PLANNER) as conn:
        have = await (await conn.execute(
            "SELECT count(*) AS n FROM ax.company_profile WHERE organization_id = ANY(%s)",
            ([x["id"] for x in c["companies"] if x.get("seed")],))).fetchone()
        anns = await (await conn.execute(
            "SELECT count(*) AS n FROM ax.announcement WHERE id = ANY(%s)", (c["announcements"],))).fetchone()
        if have["n"] < 3 or anns["n"] < len(c["announcements"]):
            raise SystemExit("시드 기업·공고가 없습니다. seeds/navigator_companies.sql, navigator_announcements.sql 을 먼저 넣으세요.")

        for x in new:
            await conn.execute(
                """INSERT INTO ax.organization (id, name, org_type, business_reg_no) OVERRIDING SYSTEM VALUE
                   VALUES (%s, %s, 'COMPANY', %s)
                   ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, org_type = 'COMPANY',
                       business_reg_no = EXCLUDED.business_reg_no, is_active = true""",
                (x["id"], x["name"], x["brn"]))
            verified = x["status"] != "UNKNOWN"
            await conn.execute(
                """INSERT INTO ax.company_profile (organization_id, is_defense_company, company_size, main_business,
                       representative_name, opened_on, established_on, employee_count, annual_revenue_krw, revenue_year,
                       region, business_status, business_status_checked_at, biz_verify_status, biz_verified_at,
                       registered_email, registration_channel)
                   VALUES (%(id)s, %(defense)s, %(size)s, %(business)s, '(가상)대표', %(opened)s, %(opened)s,
                       %(employees)s, %(revenue)s, 2025, %(region)s, %(status)s, CASE WHEN %(v)s THEN now() END,
                       CASE WHEN %(v)s THEN 'VERIFIED' ELSE 'UNVERIFIED' END, CASE WHEN %(v)s THEN now() END,
                       %(email)s, 'SELF')
                   ON CONFLICT (organization_id) DO UPDATE SET
                       is_defense_company = EXCLUDED.is_defense_company, company_size = EXCLUDED.company_size,
                       main_business = EXCLUDED.main_business, opened_on = EXCLUDED.opened_on,
                       established_on = EXCLUDED.established_on, employee_count = EXCLUDED.employee_count,
                       annual_revenue_krw = EXCLUDED.annual_revenue_krw, region = EXCLUDED.region,
                       business_status = EXCLUDED.business_status,
                       business_status_checked_at = EXCLUDED.business_status_checked_at,
                       biz_verify_status = EXCLUDED.biz_verify_status, biz_verified_at = EXCLUDED.biz_verified_at""",
                {**x, "opened": _d(x["opened"]), "v": verified, "email": f"eval{x['id']}@example.com"})

        for t in ("company_patent", "company_certification", "company_credit_rating", "company_rnd_history",
                  "company_field_source", "company_access_link", "company_embedding", "eligibility_answer"):
            await conn.execute(f"DELETE FROM ax.{t} WHERE organization_id = ANY(%s)", (ids,))

        for x in new:
            for code, issued, expires in x["certs"]:
                await conn.execute(
                    "INSERT INTO ax.company_certification (organization_id, cert_type_code, issued_on, expires_on, origin) "
                    "VALUES (%s, %s, %s, %s, 'SELF')", (x["id"], code, _d(issued), _d(expires)))
            if x["credit"]:
                agency, grade, rated, until, ver = x["credit"]
                await conn.execute(
                    "INSERT INTO ax.company_credit_rating (organization_id, agency, grade, rated_on, valid_until, origin, verified_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, CASE WHEN %s THEN now() END)",
                    (x["id"], agency, grade, _d(rated), _d(until), "EXTERNAL" if ver else "SELF", ver))
            for title, role, start, end, summary in x["rnd"]:
                await conn.execute(
                    "INSERT INTO ax.company_rnd_history (organization_id, title, funding_agency, start_date, end_date, role, summary, origin) "
                    "VALUES (%s, %s, '(가상)전담기관', %s, %s, %s, %s, 'SELF')",
                    (x["id"], title, _d(start), _d(end), role, summary))
            for app_no, title, ipc, status, abstract in x["patents"]:
                await conn.execute(
                    "INSERT INTO ax.company_patent (organization_id, application_no, registration_no, title, abstract, "
                    "ipc_codes, status, origin) VALUES (%s, %s, %s, %s, %s, %s, %s, 'SELF')",
                    (x["id"], app_no, "10-" + app_no[-7:] if status == "REGISTERED" else None, title, abstract, ipc, status))
        n = await ensure_embeddings(conn)
    log.info("검증 기업 %d곳 적재, 임베딩 %s", len(new), n)
    return len(new)


async def clean(c: dict) -> int:
    ids = [x["id"] for x in c["companies"] if not x.get("seed")]
    async with transaction(PLANNER) as conn:
        cur = await conn.execute("UPDATE ax.organization SET is_active = false WHERE id = ANY(%s)", (ids,))
    return cur.rowcount


async def evaluate(c: dict) -> dict:
    s = get_settings()
    companies = {x["id"]: x for x in c["companies"]}
    org_ids = sorted(companies)
    async with transaction(PLANNER) as conn:
        await ensure_embeddings(conn)
        model = (await (await conn.execute("SELECT name FROM ax.embedding_model WHERE is_active")).fetchone())["name"]
        missing = await (await conn.execute(
            "SELECT array_agg(x) AS ids FROM unnest(%s::bigint[]) x WHERE NOT EXISTS "
            "(SELECT 1 FROM ax.organization o WHERE o.id = x AND o.is_active)", (org_ids,))).fetchone()
        if missing["ids"]:
            raise SystemExit(f"검증 기업이 없거나 비활성입니다: {missing['ids']}. `python -m app.navigator_eval load` 를 먼저 실행하세요.")

        pairs, rankings = [], {}
        for ann_id in c["announcements"]:
            ann = (await load_announcements(conn, [ann_id]))[ann_id]
            req_by_type = {r.req_type: r.id for r in ann.requirements}
            facts = await load_companies(conn, org_ids)
            for org_id, f in facts.items():
                f.answers = {req_by_type[k.split(":")[1]]: v
                             for k, v in companies[org_id].get("answers", {}).items()
                             if int(k.split(":")[0]) == ann_id}
            sims = await pair_similarities(conn, org_ids, [ann_id])
            ranked = rank([score_pair(facts[o], ann, [x for x in sims if x["organization_id"] == o]) for o in org_ids])
            candidates = await candidate_companies(conn, ann_id, s.navigator_match_candidate_k)
            major = c["major"][str(ann_id)]
            rankings[ann_id] = {"title": ann.title, "major": major, "candidates": candidates,
                                "ranked": [(sc.org.organization_id, sc.org.name, sc.verdict, round(sc.total, 3)) for sc in ranked]}
            for sc in ranked:
                exp_v, exp_why = parse_expected(companies[sc.org.organization_id]["expected"][str(ann_id)])
                bad = "UNMET" if sc.verdict == "INELIGIBLE" else "UNKNOWN"
                got_why = frozenset(req.req_type for req, ch in sc.checks
                                    if req.is_mandatory and ch.result == bad and sc.verdict != "ELIGIBLE")
                pairs.append({"ann": ann_id, "org": sc.org.organization_id, "name": sc.org.name,
                              "expected": exp_v, "got": sc.verdict, "expected_why": sorted(exp_why),
                              "got_why": sorted(got_why), "verdict_ok": exp_v == sc.verdict,
                              "why_ok": exp_v == sc.verdict and exp_why == got_why})

        metrics = _metrics(pairs, rankings)
        run_id = (await (await conn.execute(
            "INSERT INTO ax.eval_run (name, top_k, config, metrics, created_by) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (f"Navigator 판정·추천 ({model})", max(TOP_KS),
             json.dumps({"kind": "NAVIGATOR", "embedder": s.embedder, "model": model,
                         "dataset": "seeds/navigator_eval/corpus.json",
                         "companies": len(org_ids), "announcements": c["announcements"]}, ensure_ascii=False),
             json.dumps(metrics, ensure_ascii=False), PLANNER))).fetchone())["id"]
    return {"eval_run_id": run_id, "model": model, "embedder": s.embedder, "metrics": metrics,
            "pairs": pairs, "rankings": rankings}


def _metrics(pairs: list[dict], rankings: dict) -> dict:
    n = len(pairs)
    confusion: dict[str, dict[str, int]] = {}
    for p in pairs:
        row = confusion.setdefault(p["expected"], {})
        row[p["got"]] = row.get(p["got"], 0) + 1
    m: dict = {"pairs": n,
               "verdict_accuracy_pct": round(100.0 * sum(p["verdict_ok"] for p in pairs) / n, 1),
               "reason_accuracy_pct": round(100.0 * sum(p["why_ok"] for p in pairs) / n, 1),
               "confusion": confusion}
    # 담당자 화면은 판정별 목록(적합 / 정보부족 / 부적격)을 따로 총점 순으로 보여 준다.
    # group: 정답 기업이 자기 판정 목록 안에서 몇 위인지, overall: 판정 → 총점 한 줄 순위
    hits, overall, eligible_hits, rr, cand = [], [], [], [], []
    for r in rankings.values():
        order = [o for o, *_ in r["ranked"]]
        verdict = {o: v for o, _, v, _ in r["ranked"]}
        for o in r["major"]:
            pos = [x for x in order if verdict[x] == verdict[o]].index(o) + 1
            hits.append(pos)
            overall.append(order.index(o) + 1)
            rr.append(1.0 / pos)
            cand.append(o in r["candidates"])
            if verdict[o] == "ELIGIBLE":
                eligible_hits.append(pos)
    m["major_total"] = len(hits)
    for k in TOP_KS:
        m[f"top{k}_recall_major_pct"] = round(100.0 * sum(h <= k for h in hits) / len(hits), 1)
        m[f"top{k}_recall_major_overall_pct"] = round(100.0 * sum(h <= k for h in overall) / len(overall), 1)
        m[f"top{k}_recall_eligible_major_pct"] = (round(100.0 * sum(h <= k for h in eligible_hits) / len(eligible_hits), 1)
                                                 if eligible_hits else None)
    m["mrr_major"] = round(sum(rr) / len(rr), 3)
    m["candidate_recall_major_pct"] = round(100.0 * sum(cand) / len(cand), 1)
    return m


def print_report(res: dict) -> None:
    m = res["metrics"]
    print(f"\nNavigator 판정·추천 검증 (eval_run {res['eval_run_id']}, 모델 {res['model']})")
    print("=" * 78)
    print(f" 판정 일치 {m['verdict_accuracy_pct']}% · 걸린 요건까지 일치 {m['reason_accuracy_pct']}% ({m['pairs']}쌍)")
    print(" 정답\\결과   " + "".join(f"{ko:>8}" for ko in VERDICT_KO.values()))
    for exp, exp_ko in VERDICT_KO.items():
        row = m["confusion"].get(exp, {})
        print(f" {exp_ko:<10}" + "".join(f"{row.get(v, 0):>9}" for v in VERDICT_KO))
    wrong = [p for p in res["pairs"] if not p["why_ok"]]
    for p in wrong:
        print(f"  ✗ 공고 {p['ann']} × {p['name']}: 정답 {VERDICT_KO[p['expected']]} {p['expected_why']} "
              f"/ 결과 {VERDICT_KO[p['got']]} {p['got_why']}")
    print("-" * 78)
    for ann_id, r in res["rankings"].items():
        print(f" 공고 {ann_id} {r['title'][:40]}")
        for v_code in ("ELIGIBLE", "NEEDS_INFO"):
            group = [x for x in r["ranked"] if x[2] == v_code]
            print(f"   [{VERDICT_KO[v_code]} {len(group)}곳]")
            for i, (o, name, _, total) in enumerate(group, 1):
                if i <= 4 or o in r["major"]:
                    print(f"   {i:>2}. {'★' if o in r['major'] else ' '} {name:<16} {total:.3f}")
    print("-" * 78)
    print(f" 정답 기업 {m['major_total']}건 (판정별 목록 안 순위) · 상위 3 포함률 {m['top3_recall_major_pct']}% "
          f"· 상위 5 {m['top5_recall_major_pct']}% · MRR {m['mrr_major']} · 후보 검색 포함 {m['candidate_recall_major_pct']}%")
    print(f" 한 줄 순위(판정 → 총점)였다면: 상위 3 {m['top3_recall_major_overall_pct']}% · 상위 5 {m['top5_recall_major_overall_pct']}%")
    print(f" 그중 적합 판정 정답만: 상위 3 {m['top3_recall_eligible_major_pct']}% · 상위 5 {m['top5_recall_eligible_major_pct']}%")
    if res["embedder"] != "bge_m3":
        print(" ※ EMBEDDER 가 bge_m3 가 아닙니다. 판정 수치는 그대로 쓰되, 순위 수치는 참고만 하세요.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Navigator 판정·추천 검증")
    ap.add_argument("command", choices=["load", "eval", "all", "clean"])
    ap.add_argument("--corpus", type=Path, default=CORPUS)
    ap.add_argument("--json", type=Path, help="결과를 JSON 으로도 저장")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    async def run() -> None:
        c = load_corpus(args.corpus)
        try:
            if args.command in ("load", "all"):
                await load(c)
            if args.command in ("eval", "all"):
                res = await evaluate(c)
                print_report(res)
                if args.json:
                    out = {**res, "rankings": {k: {**v, "candidates": sorted(v["candidates"])}
                                               for k, v in res["rankings"].items()}}
                    args.json.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            if args.command == "clean":
                print(f"검증 기업 {await clean(c)}곳 비활성화")
        finally:
            await close_pool()

    asyncio.run(run())


if __name__ == "__main__":
    main()
