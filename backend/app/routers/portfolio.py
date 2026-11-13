"""기관 포트폴리오: 전국 R&D 성과 ↔ 해외 수요 갭을 모아 정책·예산 기획 후보로 보여 준다.

- 보는 사람: 기획자·조직 검수자·열람자(조회 전용). 넘기기(갭 → 신규 기획수요)는 기획자만.
- 새 표 없이 성과 카드·해외 수요·갭 분석 결과를 조회만 한다.
- 열람 등급보다 높은 카드·해외 수요·갭은 목록뿐 아니라 건수에도 넣지 않는다 (건수로 존재가 드러나지 않게).
- 부서로는 거르지 않는다 (기관 전체 보기). 부서 제한은 기존처럼 최종판정에만 걸린다.
"""
from datetime import date
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.auth import CurrentUser, request_id, require_roles
from app.db import transaction
from app.repositories.sql import CLEARANCE_OK, insert
from app.routers.gaps import _visible_finding
from app.services.embedding import sync_demand_embeddings
from app.services.planning_brief import DEMAND_KIND_KO

router = APIRouter(prefix="/portfolio", tags=["기관 포트폴리오"])
READERS = ("PLANNER", "DEPT_REVIEWER", "VIEWER")

# 갭 종류 → 대응 방향 (정책·예산 기획 후보 묶음)
DIRECTIONS = {
    "NO_COVERAGE": ("NEW_PROJECT", "신규 과제 기획"),
    "PERFORMANCE_SHORT": ("FOLLOW_UP", "후속·고도화 과제"),
    "LOCALIZATION": ("LOCALIZATION", "국산화·현지화 사업"),
    "MATURITY": ("PILOT", "시험·실증"),
}
GAP_TYPES = list(DIRECTIONS)
STATUS_KO = {"CONFIRMED": "확정", "DRAFT": "검수 전", "REJECTED": "기각", "SUPERSEDED": "새 분석으로 대체"}

_OK = CLEARANCE_OK.format


def _statuses(include_draft: bool) -> list[str]:
    return ["CONFIRMED", "DRAFT"] if include_draft else ["CONFIRMED"]


async def _overview(conn, uid: int) -> dict:
    return await (await conn.execute(
        f"""SELECT
              (SELECT count(*) FROM ax.achievement_card ac
                WHERE ac.status = 'PUBLISHED' AND {_OK(col='ac.security_code')}) AS cards_published,
              (SELECT count(*) FROM ax.overseas_demand d
                WHERE d.status <> 'ARCHIVED' AND {_OK(col='d.security_code')}) AS overseas_demands,
              (SELECT count(*) FROM ax.gap_finding f
                WHERE f.status = 'CONFIRMED' AND {_OK(col='f.security_code')}) AS gaps_confirmed,
              (SELECT count(*) FROM ax.gap_finding f
                WHERE f.status = 'DRAFT' AND {_OK(col='f.security_code')}) AS gaps_draft,
              (SELECT count(*) FROM ax.planning_demand pd
                WHERE pd.origin_gap_finding_id IS NOT NULL AND {_OK(col='pd.security_code')}) AS handed_off""",
        {"uid": uid})).fetchone()


async def _areas(conn, uid: int, include_draft: bool) -> list[dict]:
    """해외 수요 기술분류별: 수요 수, 갭 종류별 건수, 근거 국내 성과 수, 가장 큰 갭 점수."""
    rows = await (await conn.execute(
        f"""WITH d AS (
                SELECT d.id, COALESCE(NULLIF(btrim(d.tech_area), ''), '분류 없음') AS area
                  FROM ax.overseas_demand d
                 WHERE d.status <> 'ARCHIVED' AND {_OK(col='d.security_code')}),
            f AS (
                SELECT f.id, f.overseas_demand_id, f.gap_type_code, f.status, f.score
                  FROM ax.gap_finding f
                 WHERE f.status = ANY(%(st)s) AND {_OK(col='f.security_code')})
            SELECT d.area,
                   count(DISTINCT d.id) AS demand_count,
                   count(DISTINCT f.overseas_demand_id) AS demands_with_gap,
                   count(DISTINCT f.id) AS gap_count,
                   count(DISTINCT f.id) FILTER (WHERE f.status = 'CONFIRMED') AS confirmed_count,
                   {", ".join(f"count(DISTINCT f.id) FILTER (WHERE f.gap_type_code = '{g}') AS {g.lower()}"
                              for g in GAP_TYPES)},
                   (SELECT count(DISTINCT fc.card_id) FROM ax.gap_finding_card fc
                     WHERE fc.finding_id = ANY(array_agg(f.id))) AS card_count,
                   round(max(f.score), 4)::float AS max_score
              FROM d LEFT JOIN f ON f.overseas_demand_id = d.id
             GROUP BY d.area
             ORDER BY count(DISTINCT f.id) DESC, max(f.score) DESC NULLS LAST, d.area""",
        {"uid": uid, "st": _statuses(include_draft)})).fetchall()
    for r in rows:
        r["by_type"] = {g: r.pop(g.lower()) for g in GAP_TYPES}
    return rows


async def _domestic(conn, uid: int) -> list[dict]:
    """무기체계별 국내 성과 분포 (발행 카드만). 해외 수요와 이어진 갭이 없으면 '해외 수요 확인 안 됨'."""
    return await (await conn.execute(
        f"""WITH c AS (
                SELECT ac.id, ac.trl,
                       COALESCE(ws.name, '무기체계 미지정') AS weapon_system, ws.id AS weapon_system_id
                  FROM ax.achievement_card ac
                  LEFT JOIN ax.card_weapon_system cws ON cws.card_id = ac.id AND cws.relation_status <> 'REJECTED'
                  LEFT JOIN ax.weapon_system ws ON ws.id = cws.weapon_system_id
                 WHERE ac.status = 'PUBLISHED' AND {_OK(col='ac.security_code')})
            SELECT c.weapon_system, c.weapon_system_id,
                   count(DISTINCT c.id) AS card_count,
                   round(avg(c.trl), 1)::float AS avg_trl,
                   count(DISTINCT c.id) FILTER (WHERE c.trl >= 7) AS mature_count,
                   (SELECT count(*) FROM ax.card_open_issue oi
                     WHERE oi.card_id = ANY(array_agg(c.id)) AND NOT oi.is_resolved) AS open_issue_count,
                   (SELECT count(DISTINCT f.id) FROM ax.gap_finding_card fc
                      JOIN ax.gap_finding f ON f.id = fc.finding_id
                     WHERE fc.card_id = ANY(array_agg(c.id)) AND f.status IN ('DRAFT','CONFIRMED')
                       AND {_OK(col='f.security_code')}) AS linked_gap_count,
                   (SELECT count(DISTINCT f.overseas_demand_id) FROM ax.gap_finding_card fc
                      JOIN ax.gap_finding f ON f.id = fc.finding_id
                     WHERE fc.card_id = ANY(array_agg(c.id)) AND f.status IN ('DRAFT','CONFIRMED')
                       AND {_OK(col='f.security_code')}) AS linked_demand_count
              FROM c
             GROUP BY c.weapon_system, c.weapon_system_id
             ORDER BY (c.weapon_system_id IS NULL), count(DISTINCT c.id) DESC, c.weapon_system""",
        {"uid": uid})).fetchall()


async def _actions(conn, uid: int, include_draft: bool, area: str | None) -> list[dict]:
    rows = await (await conn.execute(
        f"""SELECT f.id AS finding_id, f.gap_type_code, g.name_ko AS gap_type_name, f.status,
                   round(f.score, 4)::float AS score, f.summary, f.maybe_resolved_at,
                   d.id AS overseas_demand_id, d.demand_no, d.title AS demand_title, d.demand_kind, d.region,
                   COALESCE(NULLIF(btrim(d.tech_area), ''), '분류 없음') AS area, d.target_period,
                   (SELECT COALESCE(jsonb_agg(jsonb_build_object('card_id', ac.id, 'title', ac.title, 'trl', ac.trl,
                                                                 'role', fc.role) ORDER BY fc.role DESC, fc.similarity DESC NULLS LAST), '[]')
                      FROM ax.gap_finding_card fc JOIN ax.achievement_card ac ON ac.id = fc.card_id
                     WHERE fc.finding_id = f.id AND {_OK(col='ac.security_code')}) AS cards,
                   (SELECT COALESCE(array_agg(DISTINCT dep.name ORDER BY dep.name), '{{}}')
                      FROM ax.gap_finding_card fc
                      JOIN ax.achievement_card ac ON ac.id = fc.card_id
                      JOIN ax.project pr ON pr.id = ac.project_id
                      JOIN ax.department dep ON dep.id = pr.department_id
                     WHERE fc.finding_id = f.id) AS departments,
                   (SELECT COALESCE(jsonb_agg(jsonb_build_object(
                               'linkage_name', COALESCE(lt.name_ko, '신규 기획수요'), 'description', p.description)
                             ORDER BY p.sort_order, p.id), '[]')
                      FROM ax.gap_pathway p LEFT JOIN ax.code_linkage_type lt ON lt.code = p.linkage_type_code
                     WHERE p.finding_id = f.id) AS pathways,
                   pd.id AS planning_demand_id, pd.demand_no AS planning_demand_no
              FROM ax.gap_finding f
              JOIN ax.overseas_demand d ON d.id = f.overseas_demand_id
              JOIN ax.code_gap_type g ON g.code = f.gap_type_code
              LEFT JOIN ax.planning_demand pd ON pd.origin_gap_finding_id = f.id AND {_OK(col='pd.security_code')}
             WHERE f.status = ANY(%(st)s) AND {_OK(col='f.security_code')}
               AND (%(area)s::text IS NULL OR COALESCE(NULLIF(btrim(d.tech_area), ''), '분류 없음') = %(area)s)
             ORDER BY f.score DESC, f.id""",
        {"uid": uid, "st": _statuses(include_draft), "area": area})).fetchall()
    for r in rows:
        r["direction"], r["direction_name"] = DIRECTIONS[r["gap_type_code"]]
    return rows


@router.get("/overview")
async def overview(user: CurrentUser = Depends(require_roles(*READERS))):
    """숫자 4개: 발행 성과 카드 · 해외 수요 · 열린 갭(확정/검수 전) · 기획수요로 넘긴 갭."""
    async with transaction(user.id) as conn:
        return await _overview(conn, user.id)


@router.get("/areas")
async def areas(include_draft: bool = False, user: CurrentUser = Depends(require_roles(*READERS))):
    """해외 수요 기술분류별 대조표 (기본은 확정된 갭만 셈)."""
    async with transaction(user.id) as conn:
        return await _areas(conn, user.id, include_draft)


@router.get("/domestic")
async def domestic(user: CurrentUser = Depends(require_roles(*READERS))):
    """무기체계별 국내 성과 분포."""
    async with transaction(user.id) as conn:
        return await _domestic(conn, user.id)


@router.get("/actions")
async def actions(include_draft: bool = False, area: str | None = Query(None, description="기술분류로 거르기"),
                  user: CurrentUser = Depends(require_roles(*READERS))):
    """정책·예산 기획 후보: 갭을 대응 방향(신규 과제·후속 과제·국산화·실증)과 함께, 점수 높은 순."""
    async with transaction(user.id) as conn:
        return await _actions(conn, user.id, include_draft, area)


@router.post("/actions/{finding_id}/to-demand")
async def to_demand(finding_id: int, response: Response, user: CurrentUser = Depends(require_roles("PLANNER")),
                    rid: str = Depends(request_id)):
    """확정된 갭으로 신규 기획수요를 만든다. 이미 만든 갭이면 새로 만들지 않고 그 기획수요를 돌려준다."""
    async with transaction(user.id, rid) as conn:
        f = await _visible_finding(conn, finding_id, user.id)
        existing = await (await conn.execute(
            "SELECT id, demand_no FROM ax.planning_demand WHERE origin_gap_finding_id = %s", (finding_id,))).fetchone()
        if existing:
            response.status_code = status.HTTP_200_OK
            return {"demand_id": existing["id"], "demand_no": existing["demand_no"], "created": False}
        if f["status"] != "CONFIRMED":
            now = STATUS_KO.get(f["status"], f["status"])
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"검수자가 확정한 갭만 기획수요로 넘길 수 있습니다 (지금 상태: {now})")
        d = await (await conn.execute(
            "SELECT * FROM ax.overseas_demand WHERE id = %s", (f["overseas_demand_id"],))).fetchone()
        # 보안등급: 기획수요 기본(내부)과 갭 등급 중 높은 쪽
        sec = (await (await conn.execute(
            """SELECT l.code FROM ax.code_security_level l
                WHERE l.level_rank = GREATEST((SELECT level_rank FROM ax.code_security_level WHERE code = 'INTERNAL'),
                                              (SELECT level_rank FROM ax.code_security_level WHERE code = %s))""",
            (f["security_code"],))).fetchone())["code"]
        _, direction_name = DIRECTIONS[f["gap_type_code"]]
        purpose = (f"{d['region']} {DEMAND_KIND_KO.get(d['demand_kind'], '해외 수요')} 대응 ({direction_name})"
                   + (f", 목표 시기 {d['target_period']}" if d["target_period"] else ""))
        demand_no = f"PD-GAP-{finding_id:04d}"
        demand_id = await insert(conn, "planning_demand", {
            "demand_no": demand_no,
            "title": f"[{f['gap_type_name']}] {d['title']}",
            "tech_need": f"{d['requirement']}\n\n갭 분석: {f['summary']}",
            "business_purpose": purpose,
            "application_env": d["target_system"],
            "status": "OPEN",
            "security_code": sec,
            "owner_user_id": user.id,
            "requesting_dept_id": user.department_id,
            "origin_overseas_demand_id": d["id"],
            "origin_gap_finding_id": finding_id})
        for i, p in enumerate(await (await conn.execute(
                "SELECT metric_name, comparator, required_value, required_max, required_text, unit "
                "FROM ax.overseas_demand_performance WHERE overseas_demand_id = %s ORDER BY sort_order, id",
                (d["id"],))).fetchall()):
            await insert(conn, "demand_performance_req", {**p, "demand_id": demand_id, "sort_order": i})
        if d["weapon_system_id"]:
            await insert(conn, "demand_weapon_system",
                         {"demand_id": demand_id, "weapon_system_id": d["weapon_system_id"]}, "demand_id")
        await sync_demand_embeddings(conn, demand_id)
    response.status_code = status.HTTP_201_CREATED
    return {"demand_id": demand_id, "demand_no": demand_no, "created": True}


@router.get("/export.xlsx")
async def export_xlsx(include_draft: bool = False, user: CurrentUser = Depends(require_roles(*READERS))):
    """회의자료용 엑셀: 분야별 대조 · 국내 성과 분포 · 기획 후보 · 작성기준."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    async with transaction(user.id) as conn:
        area_rows = await _areas(conn, user.id, include_draft)
        dom_rows = await _domestic(conn, user.id)
        act_rows = await _actions(conn, user.id, include_draft, None)

    type_ko = {"NO_COVERAGE": "공백", "PERFORMANCE_SHORT": "성능미달", "LOCALIZATION": "국산화·현지화",
               "MATURITY": "성숙도부족"}
    wb = Workbook()
    sheets = [
        ("분야별 대조", ["기술분류", "해외 수요", "갭 있는 수요", "갭 합계", "확정 갭",
                      *type_ko.values(), "근거 국내 성과", "가장 큰 갭 점수"],
         [[r["area"], r["demand_count"], r["demands_with_gap"], r["gap_count"], r["confirmed_count"],
           *(r["by_type"][g] for g in GAP_TYPES), r["card_count"], r["max_score"]] for r in area_rows]),
        ("국내 성과 분포", ["무기체계", "성과 카드", "평균 기술성숙도", "성숙도 7 이상", "미해결 과제",
                       "이어진 해외 수요", "이어진 갭"],
         [[r["weapon_system"], r["card_count"], r["avg_trl"], r["mature_count"], r["open_issue_count"],
           r["linked_demand_count"] or "확인 안 됨", r["linked_gap_count"]] for r in dom_rows]),
        ("기획 후보", ["대응 방향", "갭 종류", "상태", "점수", "해외 수요", "국가/기관", "기술분류", "목표 시기",
                    "갭 설명", "이어 갈 국내 성과", "제안 경로", "소관부서", "넘긴 기획수요"],
         [[r["direction_name"], type_ko[r["gap_type_code"]], STATUS_KO.get(r["status"], r["status"]), r["score"],
           r["demand_title"], r["region"], r["area"], r["target_period"] or "", r["summary"],
           ", ".join(c["title"] for c in r["cards"]), ", ".join(p["linkage_name"] for p in r["pathways"]),
           ", ".join(r["departments"]), r["planning_demand_no"] or ""] for r in act_rows]),
    ]
    head_font, head_fill = Font(bold=True), PatternFill("solid", fgColor="E7F1FB")
    for n, (title, header, rows) in enumerate(sheets):
        ws = wb.active if n == 0 else wb.create_sheet()
        ws.title = title
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill = head_font, head_fill
        for r in rows:
            ws.append(r)
        ws.freeze_panes = "A2"
        for i, h in enumerate(header, start=1):
            longest = max([len(str(h))] + [len(str(r[i - 1])) for r in rows[:200]])
            ws.column_dimensions[ws.cell(1, i).column_letter].width = min(max(10, longest * 1.6), 60)
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(vertical="top", wrap_text=True)
    note = wb.create_sheet("작성기준")
    for line in [
        ["기준일", date.today().isoformat()],
        ["갭 범위", "확정 + 검수 전" if include_draft else "확정된 갭만"],
        ["집계 범위", "내려받은 사람의 열람 등급 안에서 집계"],
        ["대응 방향", "공백 → 신규 과제 기획, 성능미달 → 후속·고도화 과제, 국산화·현지화 → 국산화·현지화 사업, 성숙도부족 → 시험·실증"],
    ]:
        note.append(line)
    note.column_dimensions["A"].width, note.column_dimensions["B"].width = 12, 90
    buf = BytesIO()
    wb.save(buf)
    name = f"기관포트폴리오_{date.today():%Y%m%d}.xlsx"
    return Response(buf.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
