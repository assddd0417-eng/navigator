"""외부 출처 수집. 출처별로 원본을 external_raw_record 에 남기고 우리 테이블에 반영한다.

한 번 실행 = external_fetch_job 1행. 실패하면 FAILED 와 오류를 남긴다 (반영한 것은 롤백).
주기 실행은 `python -m app.collect --due` 를 cron 등에서 돌린다.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from psycopg import AsyncConnection

from app.config import get_settings
from app.db import transaction
from app.errors import NotFound
from app.services.company_profile import record_field
from app.services.external import bizinfo, dart, kipris, nts
from app.services.external.base import ConnectorUnavailable, content_hash
from app.services.navigator_embedding import sync_announcement_embeddings, sync_company_embeddings

log = logging.getLogger("app.collector")


@dataclass
class Run:
    job_id: int
    source_id: int
    source_code: str
    mode: str
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n


async def _raw(conn: AsyncConnection, run: Run, org_id: int | None, key: str, payload) -> int:
    row = await (await conn.execute(
        """INSERT INTO ax.external_raw_record (fetch_job_id, source_id, organization_id, external_key, payload, content_hash)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (run.job_id, run.source_id, org_id, key, json.dumps(payload, ensure_ascii=False, default=str),
         content_hash(json.loads(json.dumps(payload, default=str)))))).fetchone()
    run.add("records")
    return row["id"]


async def _companies(conn: AsyncConnection, org_id: int | None) -> list[dict]:
    rows = await (await conn.execute(
        """SELECT o.id, o.name, o.business_reg_no, cp.business_status, cp.biz_verify_status
             FROM ax.organization o JOIN ax.company_profile cp ON cp.organization_id = o.id
            WHERE o.org_type = 'COMPANY' AND o.is_active AND o.business_reg_no IS NOT NULL
              AND (%(org)s::bigint IS NULL OR o.id = %(org)s)
            ORDER BY o.id""", {"org": org_id})).fetchall()
    if org_id is not None and not rows:
        raise NotFound("기업 프로필", org_id)
    return rows


async def _external_id(conn: AsyncConnection, org_id: int, source_id: int) -> str | None:
    row = await (await conn.execute(
        "SELECT external_id FROM ax.company_external_id WHERE organization_id = %s AND source_id = %s",
        (org_id, source_id))).fetchone()
    return row["external_id"] if row else None


async def _set_external_id(conn: AsyncConnection, org_id: int, source_id: int, value: str) -> None:
    await conn.execute(
        """INSERT INTO ax.company_external_id (organization_id, source_id, external_id)
           VALUES (%s, %s, %s) ON CONFLICT (organization_id, source_id) DO NOTHING""",
        (org_id, source_id, value))


async def _touch_company(conn: AsyncConnection, org_id: int) -> None:
    # 매칭 캐시 무효화
    await conn.execute("UPDATE ax.company_profile SET updated_at = now() WHERE organization_id = %s", (org_id,))


# 국세청: 휴·폐업 재확인
async def collect_nts(conn: AsyncConnection, run: Run, org_id: int | None) -> None:
    connector = nts.get_nts_connector()
    companies = {c["business_reg_no"]: c for c in await _companies(conn, org_id)}
    if not companies:
        return
    items = await asyncio.to_thread(connector.status, list(companies))
    for it in items:
        c = companies.get(it.get("b_no"))
        if c is None:
            continue
        raw_id = await _raw(conn, run, c["id"], c["business_reg_no"], it)
        status = nts.status_of(it.get("b_stt_cd"))
        if status == "UNKNOWN":
            run.add("not_found")
            continue
        await record_field(conn, c["id"], "business_status", status, "EXTERNAL", source_code=nts.SOURCE_CODE,
                           raw_record_id=raw_id, verified=True)
        await conn.execute(
            "UPDATE ax.company_profile SET business_status = %s, business_status_checked_at = now() "
            "WHERE organization_id = %s", (status, c["id"]))
        if status != c["business_status"]:
            run.add("changed")
            await _touch_company(conn, c["id"])


# KIPRIS: 특허
async def collect_kipris(conn: AsyncConnection, run: Run, org_id: int | None) -> None:
    connector = kipris.get_kipris_connector()
    for c in await _companies(conn, org_id):
        code = await _external_id(conn, c["id"], run.source_id)
        patents = await asyncio.to_thread(connector.patents, c["name"], c["business_reg_no"], code)
        if not patents:
            run.add("not_found")
            continue
        changed = False
        for p in patents:
            await _raw(conn, run, c["id"], p.application_no, p.raw())
            if p.applicant_code and not code:
                await _set_external_id(conn, c["id"], run.source_id, p.applicant_code)
                code = p.applicant_code
            cur = await (await conn.execute(
                """INSERT INTO ax.company_patent (organization_id, application_no, registration_no, title, abstract,
                                                  ipc_codes, status, applied_on, registered_on, origin, verified_at)
                   VALUES (%(org)s, %(app)s, %(reg)s, %(title)s, %(abs)s, %(ipc)s, %(status)s, %(applied)s,
                           %(registered)s, 'EXTERNAL', now())
                   ON CONFLICT (organization_id, application_no) DO UPDATE SET
                     registration_no = EXCLUDED.registration_no, title = EXCLUDED.title,
                     abstract = COALESCE(EXCLUDED.abstract, company_patent.abstract), ipc_codes = EXCLUDED.ipc_codes,
                     status = EXCLUDED.status, applied_on = EXCLUDED.applied_on,
                     registered_on = EXCLUDED.registered_on, origin = 'EXTERNAL', verified_at = now()
                   WHERE (company_patent.registration_no, company_patent.title, company_patent.ipc_codes,
                          company_patent.status, company_patent.origin)
                         IS DISTINCT FROM (EXCLUDED.registration_no, EXCLUDED.title, EXCLUDED.ipc_codes,
                                           EXCLUDED.status, 'EXTERNAL')
                   RETURNING (xmax = 0) AS inserted""",
                {"org": c["id"], "app": p.application_no, "reg": p.registration_no, "title": p.title,
                 "abs": p.abstract, "ipc": p.ipc_codes, "status": p.status, "applied": p.applied_on,
                 "registered": p.registered_on})).fetchone()
            if cur is not None:
                run.add("inserted" if cur["inserted"] else "updated")
                changed = True
        if changed:
            await sync_company_embeddings(conn, c["id"])
            await _touch_company(conn, c["id"])


# DART: 매출·직원 수
async def collect_dart(conn: AsyncConnection, run: Run, org_id: int | None) -> None:
    connector = dart.get_dart_connector()
    for c in await _companies(conn, org_id):
        corp = await _external_id(conn, c["id"], run.source_id)
        if corp is None:
            corp = await asyncio.to_thread(connector.find_corp_code, c["name"], c["business_reg_no"])
            if corp is None:
                run.add("not_found")
                continue
            await _set_external_id(conn, c["id"], run.source_id, corp)
        fin = await asyncio.to_thread(connector.financials, corp)
        if fin is None:
            run.add("not_found")
            continue
        raw_id = await _raw(conn, run, c["id"], f"{corp}:{fin.year}", fin.raw)
        for f, v in (("annual_revenue_krw", fin.revenue_krw), ("employee_count", fin.employee_count),
                     ("revenue_year", fin.year)):
            if v is not None:
                await record_field(conn, c["id"], f, v, "EXTERNAL", source_code=dart.SOURCE_CODE,
                                   raw_record_id=raw_id, verified=True)
        run.add("updated")
        await _touch_company(conn, c["id"])


# 기업마당: 공고 → 작성중 공고
async def collect_bizinfo(conn: AsyncConnection, run: Run, org_id: int | None) -> None:
    connector = bizinfo.get_bizinfo_connector()
    keywords = [k.strip() for k in get_settings().navigator_announcement_keywords.split(",") if k.strip()]
    for r in await asyncio.to_thread(connector.announcements):
        if not bizinfo.matches_keywords(r, keywords):
            run.add("skipped")
            continue
        await _raw(conn, run, None, r.external_id, r.raw)
        end = r.receipt_end if not (r.receipt_start and r.receipt_end and r.receipt_end < r.receipt_start) else None
        row = await (await conn.execute(
            """INSERT INTO ax.announcement (announcement_no, title, agency_name, summary, receipt_start, receipt_end,
                                            source_kind, external_source_id, source_url, status)
               VALUES (%(no)s, %(title)s, %(agency)s, %(summary)s, %(start)s, %(end)s, 'EXTERNAL', %(src)s,
                       %(url)s, 'DRAFT')
               ON CONFLICT (announcement_no) DO UPDATE SET
                 title = EXCLUDED.title, agency_name = EXCLUDED.agency_name, summary = EXCLUDED.summary,
                 receipt_start = EXCLUDED.receipt_start, receipt_end = EXCLUDED.receipt_end,
                 source_url = EXCLUDED.source_url
               WHERE announcement.status = 'DRAFT'
                 AND (announcement.title, announcement.summary, announcement.receipt_start, announcement.receipt_end)
                     IS DISTINCT FROM (EXCLUDED.title, EXCLUDED.summary, EXCLUDED.receipt_start, EXCLUDED.receipt_end)
               RETURNING id, (xmax = 0) AS inserted""",
            {"no": f"{bizinfo.SOURCE_CODE}-{r.external_id}", "title": r.title[:500], "agency": r.agency_name[:200],
             "summary": r.summary, "start": r.receipt_start, "end": end, "src": run.source_id,
             "url": r.url})).fetchone()
        if row is not None:
            run.add("inserted" if row["inserted"] else "updated")
            await sync_announcement_embeddings(conn, row["id"])


Collector = Callable[[AsyncConnection, Run, "int | None"], Awaitable[None]]
COLLECTORS: dict[str, tuple[Collector, str, bool]] = {
    # code: (함수, 설정 이름, 기업별 실행 가능)
    nts.SOURCE_CODE: (collect_nts, "source_nts_biz", True),
    kipris.SOURCE_CODE: (collect_kipris, "source_kipris", True),
    dart.SOURCE_CODE: (collect_dart, "source_dart", True),
    bizinfo.SOURCE_CODE: (collect_bizinfo, "source_bizinfo", False),
}


def source_mode(code: str) -> str | None:
    entry = COLLECTORS.get(code)
    return getattr(get_settings(), entry[1]).lower() if entry else None


async def run_source(code: str, *, organization_id: int | None = None, trigger: str = "ON_DEMAND",
                     request_id: str | None = None) -> dict:
    if code not in COLLECTORS:
        raise NotFound("수집 연결 부품", code)
    fn, _, per_company = COLLECTORS[code]
    if organization_id is not None and not per_company:
        raise ValueError(f"{code} 는 기업별로 수집하지 않습니다")
    mode = source_mode(code)
    params = {"organization_id": organization_id} if organization_id else {}
    async with transaction(None, request_id) as conn:
        job = await (await conn.execute(
            """INSERT INTO ax.external_fetch_job (source_id, organization_id, mode, trigger_kind, request_params)
               SELECT id, %s, %s, %s, %s FROM ax.external_source WHERE code = %s AND is_active
               RETURNING id, source_id""",
            (organization_id, mode.upper(), trigger, json.dumps(params), code))).fetchone()
    if job is None:
        raise NotFound("외부 출처", code)
    run = Run(job["id"], job["source_id"], code, mode)
    error: str | None = None
    try:
        async with transaction(None, request_id) as conn:
            await fn(conn, run, organization_id)
    except (ConnectorUnavailable, NotFound) as e:
        error = str(getattr(e, "detail", e))
    except Exception as e:  # noqa: BLE001  실행 기록은 남긴다
        log.exception("수집 실패 %s", code)
        error = f"{type(e).__name__}: {e}"[:1000]
    if error:
        run.counts = {}
    async with transaction(None, request_id) as conn:
        await conn.execute(
            """UPDATE ax.external_fetch_job
                  SET status = %s, records_count = %s, error_message = %s, finished_at = clock_timestamp(),
                      request_params = request_params || %s
                WHERE id = %s""",
            ("FAILED" if error else "SUCCEEDED", run.counts.get("records", 0), error,
             json.dumps({"result": run.counts}), run.job_id))
    return {"job_id": run.job_id, "source": code, "mode": mode, "status": "FAILED" if error else "SUCCEEDED",
            "error": error, "counts": run.counts}


async def due_sources(conn: AsyncConnection) -> list[str]:
    rows = await (await conn.execute(
        """SELECT s.code FROM ax.external_source s
            WHERE s.is_active AND s.fetch_interval IS NOT NULL AND s.code = ANY(%s)
              AND NOT EXISTS (SELECT 1 FROM ax.external_fetch_job j
                               WHERE j.source_id = s.id AND j.organization_id IS NULL
                                 AND j.trigger_kind = 'SCHEDULED' AND j.status <> 'RUNNING'
                                 AND j.started_at > now() - s.fetch_interval)
            ORDER BY s.id""", (list(COLLECTORS),))).fetchall()
    return [r["code"] for r in rows]


async def run_due(request_id: str | None = None) -> list[dict]:
    async with transaction() as conn:
        codes = await due_sources(conn)
    return [await run_source(c, trigger="SCHEDULED", request_id=request_id) for c in codes]


async def source_overview(conn: AsyncConnection) -> list[dict]:
    rows = await (await conn.execute(
        """SELECT s.id, s.code, s.name, s.provider, s.data_kind, s.fetch_interval::text AS fetch_interval,
                  s.requires_key, s.is_paid, s.is_active, s.notes,
                  j.id AS last_job_id, j.status AS last_status, j.started_at AS last_started_at,
                  j.finished_at AS last_finished_at, j.records_count AS last_records, j.error_message AS last_error,
                  j.request_params->'result' AS last_result, j.mode AS last_mode,
                  (SELECT max(started_at) FROM ax.external_fetch_job x
                    WHERE x.source_id = s.id AND x.trigger_kind = 'SCHEDULED' AND x.organization_id IS NULL
                      AND x.status <> 'RUNNING') + s.fetch_interval AS next_due_at
             FROM ax.external_source s
             LEFT JOIN LATERAL (SELECT * FROM ax.external_fetch_job j WHERE j.source_id = s.id
                                 ORDER BY j.started_at DESC, j.id DESC LIMIT 1) j ON true
            ORDER BY s.id""")).fetchall()
    for r in rows:
        r["implemented"] = r["code"] in COLLECTORS
        r["mode"] = source_mode(r["code"])
        r["per_company"] = COLLECTORS[r["code"]][2] if r["implemented"] else False
    return rows


async def recent_jobs(conn: AsyncConnection, code: str | None, limit: int) -> list[dict]:
    return await (await conn.execute(
        """SELECT j.id, s.code AS source, j.organization_id, o.name AS company_name, j.mode, j.trigger_kind,
                  j.status, j.records_count, j.error_message, j.request_params->'result' AS result,
                  j.started_at, j.finished_at
             FROM ax.external_fetch_job j JOIN ax.external_source s ON s.id = j.source_id
             LEFT JOIN ax.organization o ON o.id = j.organization_id
            WHERE (%(code)s::text IS NULL OR s.code = %(code)s)
            ORDER BY j.started_at DESC, j.id DESC LIMIT %(limit)s""", {"code": code, "limit": limit})).fetchall()
