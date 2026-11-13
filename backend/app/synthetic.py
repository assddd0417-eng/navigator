"""검증용 합성 데이터 적재와 추천 적중률 측정.

seeds/synthetic/corpus.json (공개 사례 기반 합성 과제·결과보고서·성과카드·기획수요·정답 연계) 를 넣고,
기획수요마다 매칭을 돌려 정답 성과카드가 상위 K 안에 드는지 잰다 (제안서 목표: 주요 후보 포함률 80%).

    cd backend
    python -m app.synthetic load        # 합성 데이터 적재 (이미 있는 항목은 건너뜀, 재실행 안전)
    python -m app.synthetic eval        # 매칭 실행 + 적중률 (eval_run 에 기록, KPI 화면 '평가' 에 표시)
    python -m app.synthetic all         # load + eval

전제: 마이그레이션 + seeds/init_test_data.sql. 서버를 띄울 필요는 없다 (API 를 프로세스 안에서 호출).
임베딩은 .env 의 EMBEDDER 를 따른다. 적중률은 반드시 EMBEDDER=bge_m3 로 잰다 (hash 는 의미를 모름).
측정 중에는 LLM 연계이유를 만들지 않는다 (적중률과 무관, 호출 비용 절감).
"""
from __future__ import annotations

import os

os.environ["RATIONALE_GENERATOR"] = "template"  # get_settings() 캐시 전에 설정

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path

import httpx

from app.config import get_settings
from app.db import close_pool, transaction
from app.services.matching import run_demand_matching

log = logging.getLogger("app.synthetic")

CORPUS = Path(__file__).resolve().parents[2] / "seeds" / "synthetic" / "corpus.json"
PLANNER, CURATOR = 1, 4
EVAL_TAG = "SYNTHETIC"


def load_corpus(path: Path = CORPUS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


async def _id(conn, sql: str, params) -> int:
    return (await (await conn.execute(sql, params)).fetchone())["id"]


async def upsert_masters(c: dict) -> dict[str, dict[str, int]]:
    """사업트랙·부서·무기체계·품목·기관·과제를 코드 기준으로 넣고 키→ID 사전을 돌려준다."""
    ids: dict[str, dict[str, int]] = {"program": {}, "dept": {}, "ws": {}, "item": {}, "org": {}, "project": {}}
    async with transaction() as conn:
        for d in c["departments"]:
            await conn.execute(
                "INSERT INTO ax.department (dept_code, name, description) VALUES (%s, %s, %s) "
                "ON CONFLICT (dept_code) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description",
                (d["code"], d["name"], d["description"]))
        rows = await (await conn.execute("SELECT id, dept_code FROM ax.department")).fetchall()
        by_code = {r["dept_code"]: r["id"] for r in rows}
        ids["dept"] = {k: by_code[v] for k, v in c["dept_keys"].items()}
        # 기획팀(PLANNER·CURATOR 소속)이 합성 과제 소관부서 자료를 열람할 수 있게 (원문 근거 표시용)
        plan = ids["dept"]["PLAN"]
        for k, dept_id in ids["dept"].items():
            if dept_id != plan:
                await conn.execute(
                    "INSERT INTO ax.department_access_grant (grantee_dept_id, target_dept_id, max_security_code) "
                    "SELECT %s, %s, 'RESTRICTED' WHERE NOT EXISTS (SELECT 1 FROM ax.department_access_grant "
                    "WHERE grantee_dept_id = %s AND target_dept_id = %s AND grantee_user_id IS NULL)",
                    (plan, dept_id, plan, dept_id))

        for p in c["programs"]:
            await conn.execute(
                "INSERT INTO ax.program (program_code, name, program_type_code, purpose, owner_dept_id) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (program_code) DO UPDATE SET name = EXCLUDED.name, "
                "program_type_code = EXCLUDED.program_type_code, purpose = EXCLUDED.purpose",
                (p["code"], p["name"], p["type"], p["purpose"], plan))
        rows = await (await conn.execute("SELECT id, program_code FROM ax.program")).fetchall()
        by_code = {r["program_code"]: r["id"] for r in rows}
        ids["program"] = {k: by_code[v] for k, v in c["program_keys"].items()}

        for w in c["weapon_systems"]:
            ids["ws"][w["key"]] = await _id(conn,
                "INSERT INTO ax.weapon_system (system_code, name) VALUES (%s, %s) "
                "ON CONFLICT (system_code) DO UPDATE SET name = EXCLUDED.name RETURNING id", (w["code"], w["name"]))
        for i in c["items"]:
            ids["item"][i["key"]] = await _id(conn,
                "INSERT INTO ax.item (item_no, name, is_part, is_imported) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (item_no) DO UPDATE SET name = EXCLUDED.name RETURNING id",
                (i["code"], i["name"], i["is_part"], i["is_imported"]))
        for o in c["organizations"]:
            ids["org"][o["key"]] = await _id(conn,
                "INSERT INTO ax.organization (org_code, name, org_type) VALUES (%s, %s, %s) "
                "ON CONFLICT (org_code) DO UPDATE SET name = EXCLUDED.name RETURNING id",
                (f"SYN-ORG-{o['key']}", o["name"], o["org_type"]))
        for p in c["projects"]:
            ids["project"][p["key"]] = await _id(conn,
                """INSERT INTO ax.project (project_no, title, program_id, lead_org_id, department_id, status_code,
                                           start_date, end_date, objective)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (project_no) DO UPDATE SET title = EXCLUDED.title, program_id = EXCLUDED.program_id,
                       lead_org_id = EXCLUDED.lead_org_id, department_id = EXCLUDED.department_id,
                       status_code = EXCLUDED.status_code, start_date = EXCLUDED.start_date,
                       end_date = EXCLUDED.end_date, objective = EXCLUDED.objective
                   RETURNING id""",
                (p["project_no"], p["title"], ids["program"][p["program"]], ids["org"][p["lead_org"]],
                 ids["dept"][p["dept"]], p["status"], p["start"], p["end"], p["report"][0]["paragraphs"][0]))
            await _upsert_outcome_and_evaluations(conn, ids["project"][p["key"]], p)
    return ids


async def _upsert_outcome_and_evaluations(conn, project_id: int, p: dict) -> None:
    """과제 결과 구분·평가 의견 (있는 과제만). 같은 종류·의견이 이미 있으면 다시 넣지 않는다."""
    if p.get("outcome"):
        await conn.execute("UPDATE ax.project SET outcome_code = %s, outcome_note = %s WHERE id = %s",
                           (p["outcome"]["code"], p["outcome"].get("note"), project_id))
    for e in p.get("evaluations", []):
        await conn.execute(
            """INSERT INTO ax.project_evaluation (project_id, eval_kind, eval_date, grade, opinion, suggestion, evaluator)
               SELECT %(pid)s, %(eval_kind)s, %(eval_date)s, %(grade)s, %(opinion)s, %(suggestion)s, %(evaluator)s
                WHERE NOT EXISTS (SELECT 1 FROM ax.project_evaluation
                                   WHERE project_id = %(pid)s AND eval_kind = %(eval_kind)s AND opinion = %(opinion)s)""",
            {"pid": project_id, "eval_date": None, "grade": None, "suggestion": None, "evaluator": None, **e})


def document_body(p: dict, ids: dict) -> dict:
    """결과보고서 → POST /documents 본문. 장마다 2쪽씩 배정한다."""
    sections, chunks, page = [], [], 3
    for s in p["report"]:
        key = f"s{s['no']}"
        span = max(2, len(s["paragraphs"]))
        sections.append({"key": key, "section_no": s["no"], "heading": s["heading"], "level": 1,
                         "page_start": page, "page_end": page + span - 1})
        for i, para in enumerate(s["paragraphs"]):
            chunks.append({"content": para, "section_key": key, "page_start": page + i, "location": {"paragraph": i + 1}})
        page += span
    return {"doc_type_code": "FINAL_REPORT", "title": f"{p['title']} 최종보고서(합성)", "project_id": ids["project"][p["key"]],
            "owner_dept_id": ids["dept"][p["dept"]], "external_ref": f"SYN:{p['key']}", "version_label": "합성 v1",
            "authored_at": p["end"], "page_count": page - 1, "security_code": "INTERNAL", "is_deidentified": True,
            "metadata": {"synthetic": True, "sources": p["sources"], "public_facts": p["public_facts"]},
            "sections": sections, "chunks": chunks}


def card_body(p: dict, ids: dict, chunk_ids: list[list[int]]) -> dict:
    card = dict(p["card"])

    def ev(ref: list[int] | None) -> list[dict]:
        return [{"chunk_id": chunk_ids[ref[0]][ref[1]]}] if ref else []

    card["performances"] = [{**{k: v for k, v in f.items() if k != "chunk"}, "evidence": ev(f.get("chunk"))}
                            for f in card["performances"]]
    card["open_issues"] = [{**{k: v for k, v in f.items() if k != "chunk"}, "source": "REPORT", "evidence": ev(f.get("chunk"))}
                           for f in card["open_issues"]]
    card["evidence"] = [{"chunk_id": chunk_ids[2][0]}]  # 핵심성과 근거 = 시험평가 결과 첫 문단
    card.update(card_no=f"SYN-AC-{p['key']}", project_id=ids["project"][p["key"]], extracted_by="IMPORT",
                weapon_systems=[{"id": ids["ws"][w]} for w in p["ws"]], items=[{"id": ids["item"][i]} for i in p["items"]],
                companies=[{"id": ids["org"][o]} for o in p["companies"]],
                programs=[{"id": ids["program"][p["program"]]}])
    return card


def demand_body(d: dict, ids: dict) -> dict:
    return {"demand_no": f"SYN-DM-{d['key']}", "title": d["title"], "tech_need": d["tech_need"],
            "business_purpose": d["business_purpose"], "application_env": d["application_env"],
            "required_trl_min": d["trl"][0], "required_trl_max": d["trl"][1],
            "target_program_id": ids["program"][d["program"]], "requesting_dept_id": ids["dept"][d["dept"]],
            "status": "OPEN", "performance_reqs": d["reqs"], "technologies": d.get("techs", []),
            "weapon_system_ids": [ids["ws"][w] for w in d["ws"]], "item_ids": [ids["item"][i] for i in d["items"]]}


async def _existing(sql: str, keys: list[str]) -> dict[str, int]:
    async with transaction() as conn:
        rows = await (await conn.execute(sql, (keys,))).fetchall()
    return {r["k"]: r["id"] for r in rows}


async def load(c: dict) -> dict[str, dict[str, int]]:
    from app.main import app  # 라우터 검증·임베딩·감사 로그를 그대로 쓰기 위해 API 를 프로세스 안에서 호출

    ids = await upsert_masters(c)
    t0 = time.monotonic()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic") as api:
        async def call(method: str, path: str, user: int, body: dict | None = None) -> dict:
            r = await api.request(method, path, json=body, headers={"X-User-Id": str(user)})
            if r.status_code >= 400:
                raise RuntimeError(f"{method} {path} → {r.status_code}: {r.text[:500]}")
            return r.json() if r.content else {}

        docs = await _existing("SELECT external_ref AS k, id FROM ax.source_document WHERE external_ref = ANY(%s)",
                               [f"SYN:{p['key']}" for p in c["projects"]])
        cards = await _existing("SELECT card_no AS k, id FROM ax.achievement_card WHERE card_no = ANY(%s)",
                                [f"SYN-AC-{p['key']}" for p in c["projects"]])
        ids["card"] = {}
        for n, p in enumerate(c["projects"], 1):
            ref, card_no = f"SYN:{p['key']}", f"SYN-AC-{p['key']}"
            if card_no in cards:
                ids["card"][p["key"]] = cards[card_no]
                continue
            if ref in docs:  # 문서만 있고 카드가 없으면 (중간에 멈춤) 청크 ID 를 다시 읽는다
                async with transaction() as conn:
                    flat = [r["id"] for r in await (await conn.execute(
                        "SELECT id FROM ax.document_chunk WHERE document_id = %s ORDER BY chunk_index", (docs[ref],))).fetchall()]
            else:
                flat = (await call("POST", "/documents", CURATOR, document_body(p, ids)))["chunk_ids"]
            it = iter(flat)
            chunk_ids = [[next(it) for _ in s["paragraphs"]] for s in p["report"]]
            card_id = (await call("POST", "/cards", CURATOR, card_body(p, ids, chunk_ids)))["id"]
            await call("POST", f"/cards/{card_id}/publish", CURATOR)
            ids["card"][p["key"]] = card_id
            log.info("과제 %d/%d %s 적재 (%.0f초)", n, len(c["projects"]), p["title"], time.monotonic() - t0)

        demands = await _existing("SELECT demand_no AS k, id FROM ax.planning_demand WHERE demand_no = ANY(%s)",
                                  [f"SYN-DM-{d['key']}" for d in c["demands"]])
        ids["demand"] = {}
        for d in c["demands"]:
            no = f"SYN-DM-{d['key']}"
            ids["demand"][d["key"]] = demands.get(no) or (await call("POST", "/demands", PLANNER, demand_body(d, ids)))["id"]
    await upsert_eval_cases(c, ids)
    log.info("적재 완료: 과제 %d · 성과카드 %d · 기획수요 %d (%.0f초)",
             len(ids["project"]), len(ids["card"]), len(ids["demand"]), time.monotonic() - t0)
    return ids


async def upsert_eval_cases(c: dict, ids: dict) -> None:
    """기획수요마다 평가 케이스와 정답(성과카드)을 다시 만든다."""
    async with transaction(PLANNER) as conn:
        for d in c["demands"]:
            demand_id = ids["demand"][d["key"]]
            await conn.execute("DELETE FROM ax.eval_case WHERE demand_id = %s AND note LIKE %s", (demand_id, f"{EVAL_TAG}%"))
            case_id = await _id(conn,
                "INSERT INTO ax.eval_case (name, case_type, query_type, demand_id, note, created_by) "
                "VALUES (%s, 'EXPERT_PANEL', 'DEMAND', %s, %s, %s) RETURNING id",
                (d["title"], demand_id, f"{EVAL_TAG} 합성 정답 (seeds/synthetic/corpus.json {d['key']})", PLANNER))
            for card_key, linkage, importance in d["expected"]:
                await conn.execute(
                    "INSERT INTO ax.eval_ground_truth (case_id, expected_card_id, linkage_type_code, importance, opinion) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (case_id, ids["card"][card_key], linkage, importance, f"합성 정답 {card_key}"))


async def evaluate(top_ks: tuple[int, ...] = (5, 10)) -> dict:
    """합성 평가 케이스마다 매칭을 새로 돌리고 상위 K 포함률을 계산한다."""
    s = get_settings()
    async with transaction(PLANNER) as conn:
        cases = await (await conn.execute(
            "SELECT id, name, demand_id FROM ax.eval_case WHERE note LIKE %s ORDER BY id", (f"{EVAL_TAG}%",))).fetchall()
    if not cases:
        raise SystemExit("합성 평가 케이스가 없습니다. 먼저 `python -m app.synthetic load` 를 실행하세요.")

    async with transaction(PLANNER) as conn:
        model = (await (await conn.execute("SELECT name FROM ax.embedding_model WHERE is_active")).fetchone())["name"]
        run_id = await _id(conn,
            "INSERT INTO ax.eval_run (name, top_k, config, created_by) VALUES (%s, %s, %s, %s) RETURNING id",
            (f"합성 데이터 적중률 ({model})", max(top_ks),
             json.dumps({"embedder": s.embedder, "model": model, "match_top_k": s.match_top_k,
                         "dataset": "seeds/synthetic/corpus.json"}, ensure_ascii=False), PLANNER))
    t0 = time.monotonic()
    for n, case in enumerate(cases, 1):
        async with transaction(PLANNER) as conn:
            match_run_id = await run_demand_matching(conn, case["demand_id"], PLANNER, max(s.match_top_k, max(top_ks)))
            await conn.execute("INSERT INTO ax.eval_run_case VALUES (%s, %s, %s)", (run_id, case["id"], match_run_id))
        log.info("매칭 %d/%d %s (%.0f초)", n, len(cases), case["name"], time.monotonic() - t0)

    async with transaction(PLANNER) as conn:
        hits = await (await conn.execute(
            """SELECT h.case_id, c.name, h.importance, h.hit_rank, h.expected_linkage_type, h.predicted_linkage_type,
                      ac.title AS expected_card
                 FROM ax.v_eval_topk_hits h
                 JOIN ax.eval_case c ON c.id = h.case_id
                 JOIN ax.eval_ground_truth g ON g.id = h.ground_truth_id
                 JOIN ax.achievement_card ac ON ac.id = g.expected_card_id
                WHERE h.eval_run_id = %s ORDER BY h.case_id, h.ground_truth_id""", (run_id,))).fetchall()
        major = [h for h in hits if h["importance"] == "MAJOR"]
        metrics: dict = {"cases": len(cases), "major_candidates": len(major)}
        for k in top_ks:
            got = sum(1 for h in major if h["hit_rank"] is not None and h["hit_rank"] <= k)
            metrics[f"top{k}_recall_major_pct"] = round(100.0 * got / len(major), 1) if major else None
        ranked = [h for h in major if h["hit_rank"]]
        metrics["mrr_major"] = round(sum(1.0 / h["hit_rank"] for h in ranked) / len(major), 3) if major else None
        typed = [h for h in major if h["hit_rank"] and h["hit_rank"] <= max(top_ks)]
        metrics["linkage_type_accuracy_pct"] = (round(100.0 * sum(h["predicted_linkage_type"] == h["expected_linkage_type"]
                                                                  for h in typed) / len(typed), 1) if typed else None)
        await conn.execute("UPDATE ax.eval_run SET metrics = %s WHERE id = %s", (json.dumps(metrics), run_id))
    return {"eval_run_id": run_id, "model": model, "metrics": metrics, "hits": hits}


def print_report(res: dict) -> None:
    m = res["metrics"]
    print(f"\n합성 데이터 추천 적중률 (eval_run {res['eval_run_id']}, 모델 {res['model']})")
    print("-" * 78)
    for h in res["hits"]:
        rank = f"{h['hit_rank']}위" if h["hit_rank"] else "순위 밖"
        mark = "O" if h["hit_rank"] and h["hit_rank"] <= 5 else ("△" if h["hit_rank"] and h["hit_rank"] <= 10 else "X")
        typ = "" if not h["hit_rank"] else (" 유형일치" if h["predicted_linkage_type"] == h["expected_linkage_type"]
                                            else f" 유형:{h['predicted_linkage_type']}≠{h['expected_linkage_type']}")
        print(f" {mark} {h['name'][:30]:<30} ← {h['expected_card'][:22]:<22} [{h['importance']}] {rank}{typ}")
    print("-" * 78)
    print(f" 주요 정답 {m['major_candidates']}건 · 상위 5 포함률 {m.get('top5_recall_major_pct')}% · "
          f"상위 10 포함률 {m.get('top10_recall_major_pct')}% (목표 80%) · MRR {m['mrr_major']} · "
          f"연계유형 일치 {m['linkage_type_accuracy_pct']}%")
    if get_settings().embedder != "bge_m3":
        print(" ※ EMBEDDER 가 bge_m3 가 아닙니다. hash 임베더 결과는 추천 품질 평가에 쓰지 마세요.")


def main() -> None:
    ap = argparse.ArgumentParser(description="검증용 합성 데이터 적재·적중률 측정")
    ap.add_argument("command", choices=["load", "eval", "all"])
    ap.add_argument("--corpus", type=Path, default=CORPUS)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    async def run() -> None:
        try:
            if args.command in ("load", "all"):
                await load(load_corpus(args.corpus))
            if args.command in ("eval", "all"):
                print_report(await evaluate())
        finally:
            await close_pool()

    asyncio.run(run())


if __name__ == "__main__":
    main()
