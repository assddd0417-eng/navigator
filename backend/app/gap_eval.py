"""갭 분석 정답 사례 측정 (전차·파워팩 공개자료 기준).

seeds/overseas/전차파워팩_해외수요.xlsx 의 '갭사례' 시트(G01~)를 정답으로 두고,
갭 분석을 한 번 돌려 정답 사례가 상위 N 안에 나오는지(적중)와 갭 종류까지 맞는지(종류 일치)를 잰다.

    cd backend
    python -m app.gap_eval load    # 해외 수요 엑셀 + K2 파워팩 국내 성과 카드 적재 (재실행 안전)
    python -m app.gap_eval eval    # 갭 분석 실행 + 정답 비교
    python -m app.gap_eval all     # load + eval
    python -m app.gap_eval sims    # 유사도 분포: 기준값(관련 성과 0.45, 공백 0.55 등)이 지금 임베더에 맞는지 본다

전제: 마이그레이션 + seeds/init_test_data.sql. 의미 비교이므로 EMBEDDER=bge_m3 로 잰다 (hash 는 의미를 모름).
정답 사례가 4건뿐이라 수치는 참고값이다. 정답에 없는 갭은 '전문가 확인 필요'로 따로 보여 준다.
"""
from __future__ import annotations

import os

os.environ["RATIONALE_GENERATOR"] = "template"
os.environ.setdefault("GAP_AUTO_RUN", "false")  # 적재 중 자동 실행 대신 마지막에 한 번만 잰다

import argparse
import asyncio
import io
import logging
from pathlib import Path

import httpx
from openpyxl import load_workbook

from app.config import get_settings
from app.db import close_pool, transaction
from app.services.gap_analysis import run_gap_analysis
from app.services.gap_rules import AnswerCase, FoundGap, evaluate_cases

log = logging.getLogger("app.gap_eval")

SEEDS = Path(__file__).resolve().parents[2] / "seeds" / "overseas"
WORKBOOK = SEEDS / "전차파워팩_해외수요.xlsx"
K2_CORPUS = SEEDS / "국내성과_K2파워팩.json"
PLANNER = 1
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TYPE_KO = {"NO_COVERAGE": "공백", "PERFORMANCE_SHORT": "성능미달", "LOCALIZATION": "국산화·현지화",
           "MATURITY": "성숙도부족"}


def read_cases(path: Path = WORKBOOK) -> list[AnswerCase]:
    wb = load_workbook(io.BytesIO(path.read_bytes()), read_only=True, data_only=True)
    if "갭사례" not in wb.sheetnames:
        raise SystemExit(f"{path.name} 에 '갭사례' 시트가 없습니다")
    rows = list(wb["갭사례"].iter_rows(values_only=True))
    head = [str(h).strip() if h else "" for h in rows[0]]
    out = []
    for r in rows[1:]:
        rec = dict(zip(head, r))
        if not rec.get("사례 번호"):
            continue
        demands = [d.strip() for d in str(rec.get("해외 수요") or "").split(",") if d.strip()]
        out.append(AnswerCase(str(rec["사례 번호"]).strip(), demands, str(rec.get("갭 유형") or ""),
                              str(rec.get("갭 내용") or "")))
    return out


async def load() -> None:
    from app import synthetic
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gap-eval") as api:
        r = await api.post("/overseas/import", headers={"X-User-Id": str(PLANNER)},
                           files={"file": (WORKBOOK.name, WORKBOOK.read_bytes(), XLSX)})
        if r.status_code >= 400:
            raise RuntimeError(f"해외 수요 엑셀 올리기 실패 {r.status_code}: {r.text[:500]}")
        log.info("해외 수요 적재: %s", r.json())
    await synthetic.load(synthetic.load_corpus(K2_CORPUS))


async def evaluate(top_n: int = 10) -> dict:
    async with transaction(PLANNER) as conn:
        run_id = await run_gap_analysis(conn, PLANNER, None, "MANUAL", note="정답 사례 측정 (app.gap_eval)")
        rows = await (await conn.execute(
            """SELECT f.id, d.demand_no, f.gap_type_code, f.score, f.summary
                 FROM ax.gap_finding f JOIN ax.overseas_demand d ON d.id = f.overseas_demand_id
                WHERE f.gap_run_id = %s ORDER BY f.score DESC""", (run_id,))).fetchall()
        model = (await (await conn.execute("SELECT name FROM ax.embedding_model WHERE is_active")).fetchone())["name"]
    if not rows:
        raise SystemExit("갭이 하나도 나오지 않았습니다. 먼저 `python -m app.gap_eval load` 를 실행했는지 확인하세요.")
    found = [FoundGap(r["demand_no"], r["gap_type_code"], float(r["score"]), r["id"]) for r in rows]
    res = evaluate_cases(read_cases(), found, top_n)
    return {**res, "gap_run_id": run_id, "model": model, "all": rows}


def print_report(res: dict) -> None:
    print(f"\n갭 분석 정답 사례 측정 (gap_run {res['gap_run_id']}, 모델 {res['model']}, 상위 {res['top_n']}건 기준)")
    print("-" * 78)
    for r in res["rows"]:
        mark = "O" if r["type_match"] else ("△" if r["hit"] else "X")
        got = ", ".join(f.split(":")[0] + ":" + TYPE_KO.get(f.split(":")[1], f) for f in r["found"]) or "없음"
        print(f" {mark} {r['case_no']} {'/'.join(r['demands']):<8} 정답 {r['expected']:<14} 찾은 갭 {got}")
    print("-" * 78)
    print(f" 정답 {res['cases']}건 · 적중 {res['hit_pct']}% · 종류 일치 {res['type_match_pct']}% · 전체 갭 {res['found_total']}건")
    if res["unmatched"]:
        print(" 정답에 없는 갭 (전문가 확인 필요):")
        for u in res["unmatched"]:
            print(f"   - {u['demand_no']} {TYPE_KO.get(u['gap_type'], u['gap_type'])} (점수 {u['score']:.2f})")
    if get_settings().embedder != "bge_m3":
        print(" ※ EMBEDDER 가 bge_m3 가 아닙니다. hash 임베더 결과는 품질 평가에 쓰지 마세요.")


K2_PREFIX = "SYN-K2-"
CUTS = (0.35, 0.45, 0.55, 0.60, 0.65, 0.70)


def _pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))] if xs else float("nan")


async def similarities() -> dict:
    """해외 수요(D01~) × 검수 확정 카드 전체의 유사도. K2 파워팩 카드(관련)와 나머지 카드(대부분 무관)를 나눠 본다."""
    from app.services.embedding import active_model_id
    from app.services.gap_analysis import _PAIRS_SQL

    async with transaction(PLANNER) as conn:
        model_id = await active_model_id(conn)
        model = (await (await conn.execute("SELECT name FROM ax.embedding_model WHERE id = %s", (model_id,))).fetchone())["name"]
        cards = await (await conn.execute(
            f"""WITH pairs(dfacet, cfacet) AS (VALUES {_PAIRS_SQL})
                SELECT d.demand_no, ac.id AS card_id, ac.title, p.project_no,
                       max(1 - (ce.embedding <=> oe.embedding)) AS sim
                  FROM ax.overseas_demand d
                  JOIN ax.overseas_demand_embedding oe ON oe.overseas_demand_id = d.id AND oe.model_id = %(m)s
                  JOIN pairs ON pairs.dfacet = oe.facet
                  JOIN ax.card_embedding ce ON ce.facet = pairs.cfacet AND ce.model_id = %(m)s
                  JOIN ax.achievement_card ac ON ac.id = ce.card_id AND ac.status = 'PUBLISHED'
                  JOIN ax.project p ON p.id = ac.project_id
                 WHERE d.demand_no ~ '^D[0-9]+$'
                 GROUP BY d.demand_no, ac.id, ac.title, p.project_no""", {"m": model_id})).fetchall()
        issues = await (await conn.execute(
            """SELECT d.demand_no, oi.description, p.project_no,
                      max(1 - (ce.embedding <=> oe.embedding)) AS sim
                 FROM ax.overseas_demand d
                 JOIN ax.overseas_demand_embedding oe
                   ON oe.overseas_demand_id = d.id AND oe.model_id = %(m)s AND oe.facet IN ('TECH_NEED', 'SUMMARY')
                 JOIN ax.card_embedding ce ON ce.facet = 'OPEN_ISSUE' AND ce.model_id = %(m)s
                  AND ce.source_table = 'card_open_issue'
                 JOIN ax.card_open_issue oi ON oi.id = ce.source_id
                 JOIN ax.achievement_card ac ON ac.id = oi.card_id AND ac.status = 'PUBLISHED'
                 JOIN ax.project p ON p.id = ac.project_id
                WHERE d.demand_no ~ '^D[0-9]+$'
                GROUP BY d.demand_no, oi.id, oi.description, p.project_no""", {"m": model_id})).fetchall()
    if not cards:
        raise SystemExit("해외 수요 D01~ 와 카드 임베딩이 없습니다. 먼저 `python -m app.gap_eval load` 를 실행하세요.")
    return {"model": model, "cards": cards, "issues": issues}


def print_similarities(res: dict) -> None:
    def split(rows):
        k2 = [float(r["sim"]) for r in rows if r["project_no"].startswith(K2_PREFIX)]
        other = [float(r["sim"]) for r in rows if not r["project_no"].startswith(K2_PREFIX)]
        return k2, other

    def line(name, xs):
        if not xs:
            return f" {name:<14} 없음"
        cut = " ".join(f"{c:.2f}↑{sum(x >= c for x in xs) * 100 // len(xs):>3}%" for c in CUTS)
        return (f" {name:<14} {len(xs):>4}쌍  중앙 {_pct(xs, .5):.2f}  상위10% {_pct(xs, .9):.2f}  최고 {max(xs):.2f} | {cut}")

    print(f"\n해외 수요 ↔ 국내 성과 유사도 (모델 {res['model']})")
    print("-" * 78)
    k2, other = split(res["cards"])
    print(" [카드] 동향 D01~D09 × 검수 확정 카드")
    print(line("K2 파워팩 카드", k2))
    print(line("그 밖의 카드", other))
    k2, other = split(res["issues"])
    print(" [미해결 과제] 동향 × 카드의 남은 숙제")
    print(line("K2 파워팩 과제", k2))
    print(line("그 밖의 과제", other))
    print("-" * 78)
    print(" 동향별 K2 카드 최고 / 그 밖의 카드 상위 3")
    by: dict[str, list] = {}
    for r in res["cards"]:
        by.setdefault(r["demand_no"], []).append(r)
    for no in sorted(by):
        rows = sorted(by[no], key=lambda r: -float(r["sim"]))
        k2b = max((float(r["sim"]) for r in rows if r["project_no"].startswith(K2_PREFIX)), default=float("nan"))
        top = [r for r in rows if not r["project_no"].startswith(K2_PREFIX)][:3]
        print(f" {no}  K2 {k2b:.2f} | " + " · ".join(f"{float(r['sim']):.2f} {r['title'][:16]}" for r in top))


def main() -> None:
    ap = argparse.ArgumentParser(description="갭 분석 정답 사례 측정")
    ap.add_argument("command", choices=["load", "eval", "all", "sims"])
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    async def run() -> None:
        try:
            if args.command in ("load", "all"):
                await load()
            if args.command in ("eval", "all"):
                print_report(await evaluate(args.top))
            if args.command == "sims":
                print_similarities(await similarities())
        finally:
            await close_pool()

    asyncio.run(run())


if __name__ == "__main__":
    main()
