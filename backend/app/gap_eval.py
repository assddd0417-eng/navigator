"""갭 분석 정답 사례 측정 (전차·파워팩 공개자료 기준).

seeds/overseas/전차파워팩_해외수요.xlsx 의 '갭사례' 시트(G01~)를 정답으로 두고,
갭 분석을 한 번 돌려 정답 사례가 상위 N 안에 나오는지(적중)와 갭 종류까지 맞는지(종류 일치)를 잰다.

    cd backend
    python -m app.gap_eval load    # 해외 수요 엑셀 + K2 파워팩 국내 성과 카드 적재 (재실행 안전)
    python -m app.gap_eval eval    # 갭 분석 실행 + 정답 비교
    python -m app.gap_eval all     # load + eval

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


def main() -> None:
    ap = argparse.ArgumentParser(description="갭 분석 정답 사례 측정")
    ap.add_argument("command", choices=["load", "eval", "all"])
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    async def run() -> None:
        try:
            if args.command in ("load", "all"):
                await load()
            if args.command in ("eval", "all"):
                print_report(await evaluate(args.top))
        finally:
            await close_pool()

    asyncio.run(run())


if __name__ == "__main__":
    main()
