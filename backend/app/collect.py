"""외부 수집 실행.

    python -m app.collect --due              # 주기가 된 출처만 (cron 에서 매시간 등)
    python -m app.collect --source KIPRIS    # 한 출처 지금
    python -m app.collect --source DART --org 101
"""
import argparse
import asyncio
import json

from app.db import close_pool
from app.services.collector import COLLECTORS, run_due, run_source


async def main() -> int:
    ap = argparse.ArgumentParser(description="Navigator 외부 수집")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--due", action="store_true", help="주기가 된 출처 전부")
    g.add_argument("--source", choices=sorted(COLLECTORS))
    ap.add_argument("--org", type=int, help="기업 id (기업별 출처만)")
    a = ap.parse_args()
    try:
        results = await run_due("cli") if a.due else [await run_source(a.source, organization_id=a.org,
                                                                      request_id="cli")]
    finally:
        await close_pool()
    for r in results:
        print(json.dumps(r, ensure_ascii=False))
    return 1 if any(r["status"] == "FAILED" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
