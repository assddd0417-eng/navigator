"""공고 API. 등록·수정은 PLANNER, 조회는 공개(PUBLISHED 만, 담당자는 전체)."""
from pathlib import PurePath

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Response, UploadFile, status
from psycopg import AsyncConnection

from app.auth import CurrentUser, get_current_user, request_id, require_roles
from app.db import transaction
from app.errors import NotFound
from app.repositories.sql import evidence_from_chunk, insert, update
from app.routers.documents import parse_file, store_document
from app.schemas.announcements import (AnnouncementCreate, AnnouncementCreated, AnnouncementUpdate,
                                       RequirementIn, RequirementUpdate, TechNeedIn, normalize_rule)
from app.schemas.common import Created
from app.schemas.documents import ChunkIn, DocumentCreate
from app.services.navigator_alerts import safe_dispatch
from app.services.navigator_embedding import sync_announcement_embeddings
from app.services.ratelimit import public_rate_limit

router = APIRouter(prefix="/navigator/announcements", tags=["Navigator 공고"])
STAFF = ("PLANNER",)
RECEIPT_LABEL = {"UPCOMING": "접수전", "OPEN": "접수중", "CLOSED": "마감", "DRAFT": "작성중", "CANCELLED": "취소"}


def _unprocessable(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)


async def optional_user(x_user_id: int | None = Header(default=None)) -> CurrentUser | None:
    return None if x_user_id is None else await get_current_user(x_user_id)


def _is_staff(user: CurrentUser | None) -> bool:
    return user is not None and user.has_any(*STAFF)


async def _check_codes(conn: AsyncConnection, req_type: str, rule: dict) -> None:
    if req_type == "REQUIRED_CERT":
        rows = await (await conn.execute(
            "SELECT code FROM ax.code_certification_type WHERE code = ANY(%s) AND is_active",
            (rule["any_of"],))).fetchall()
        unknown = set(rule["any_of"]) - {r["code"] for r in rows}
        if unknown:
            raise _unprocessable(f"알 수 없는 인증 종류: {', '.join(sorted(unknown))}")
    elif req_type == "MIN_CREDIT_GRADE":
        if not await (await conn.execute(
                "SELECT 1 FROM ax.code_credit_grade WHERE grade = %s", (rule["min_grade"],))).fetchone():
            raise _unprocessable(f"알 수 없는 신용등급: {rule['min_grade']} (예: AAA, BBB-, B+)")


async def _insert_requirement(conn: AsyncConnection, ann_id: int, document_id: int | None,
                              r: RequirementIn, sort_order: int) -> int:
    if not await (await conn.execute(
            "SELECT 1 FROM ax.code_requirement_type WHERE code = %s AND is_active", (r.req_type_code,))).fetchone():
        raise _unprocessable(f"알 수 없는 자격요건 종류: {r.req_type_code}")
    try:
        rule = normalize_rule(r.req_type_code, r.rule)
    except ValueError as e:
        raise _unprocessable(str(e)) from None
    await _check_codes(conn, r.req_type_code, rule)
    evidence_id, quote, page = None, r.source_quote, r.source_page
    if r.evidence:
        chunk = await (await conn.execute(
            "SELECT document_id, page_start FROM ax.document_chunk WHERE id = %s", (r.evidence.chunk_id,))).fetchone()
        if chunk is None or chunk["document_id"] != document_id:
            raise _unprocessable(f"청크 {r.evidence.chunk_id} 는 이 공고의 원문이 아닙니다")
        evidence_id = await evidence_from_chunk(conn, r.evidence.chunk_id, r.evidence.quote,
                                                r.evidence.page_start, r.evidence.page_end)
        quote = quote or r.evidence.quote
        page = page or r.evidence.page_start or chunk["page_start"]
    return await insert(conn, "announcement_requirement", {
        "announcement_id": ann_id, "req_type_code": r.req_type_code, "rule": rule,
        "is_mandatory": r.is_mandatory, "description": r.description, "evidence_id": evidence_id,
        "source_quote": quote, "source_page": page, "sort_order": sort_order})


async def _insert_tech_need(conn: AsyncConnection, ann_id: int, t: TechNeedIn, sort_order: int) -> int:
    return await insert(conn, "announcement_tech_need", {**t.model_dump(), "announcement_id": ann_id,
                                                         "sort_order": sort_order})


async def _changed(conn: AsyncConnection, ann_id: int) -> None:
    # updated_at 은 매칭 캐시 무효화에 씀
    await conn.execute("UPDATE ax.announcement SET updated_at = now() WHERE id = %s", (ann_id,))
    await sync_announcement_embeddings(conn, ann_id)


async def _next_sort(conn: AsyncConnection, table: str, ann_id: int) -> int:
    row = await (await conn.execute(
        f"SELECT COALESCE(max(sort_order) + 1, 0) AS n FROM ax.{table} WHERE announcement_id = %s",
        (ann_id,))).fetchone()
    return row["n"]


async def _announcement(conn: AsyncConnection, ann_id: int, user: CurrentUser | None) -> dict:
    a = await (await conn.execute("SELECT * FROM ax.v_announcement WHERE id = %s", (ann_id,))).fetchone()
    if a is None or (a["status"] != "PUBLISHED" and not _is_staff(user)):
        raise NotFound("공고", ann_id)
    return a


async def _create(conn: AsyncConnection, body: AnnouncementCreate, user: CurrentUser,
                  extra: dict | None = None) -> AnnouncementCreated:
    data = {**body.model_dump(exclude={"requirements", "tech_needs"}), "created_by": user.id, **(extra or {})}
    ann_id = await insert(conn, "announcement", data)
    req_ids = [await _insert_requirement(conn, ann_id, data.get("document_id"), r, i)
               for i, r in enumerate(body.requirements)]
    tech_ids = [await _insert_tech_need(conn, ann_id, t, i) for i, t in enumerate(body.tech_needs)]
    await sync_announcement_embeddings(conn, ann_id)
    return AnnouncementCreated(id=ann_id, requirement_ids=req_ids, tech_need_ids=tech_ids,
                               document_id=data.get("document_id"))


@router.post("", response_model=AnnouncementCreated, status_code=201)
async def create_announcement(body: AnnouncementCreate, user: CurrentUser = Depends(require_roles(*STAFF)),
                              rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        created = await _create(conn, body, user)
    if body.status == "PUBLISHED":
        await safe_dispatch(created.id, rid)
    return created


@router.post("/upload", response_model=AnnouncementCreated, status_code=201)
async def upload_announcement(
    file: UploadFile = File(..., description="공고문 PDF · TXT · MD (스캔본 OCR 미지원)"),
    announcement_no: str = Form(...),
    agency_name: str = Form(...),
    title: str | None = Form(None, description="비우면 파일 이름"),
    program_id: int | None = Form(None),
    domain: str = Form("DEFENSE_RND"),
    receipt_start: str | None = Form(None),
    receipt_end: str | None = Form(None),
    source_url: str | None = Form(None),
    user: CurrentUser = Depends(require_roles(*STAFF)),
    rid: str = Depends(request_id),
):
    """공고문 업로드 → 원문 청크 저장 + DRAFT 공고 생성. 자격요건은 chunks 보고 따로 입력."""
    p = await parse_file(file)
    title = (title or "").strip() or PurePath(p.filename).stem or "제목 없음"
    try:
        body = AnnouncementCreate(announcement_no=announcement_no, title=title, agency_name=agency_name,
                                  program_id=program_id, domain=domain, receipt_start=receipt_start,
                                  receipt_end=receipt_end, source_url=source_url, status="DRAFT")
    except ValueError as e:
        raise _unprocessable(str(e)) from None
    doc = DocumentCreate(
        doc_type_code="PROGRAM_NOTICE", title=title, program_id=program_id, source_system_code="MANUAL",
        external_ref=f"announcement:{announcement_no}", security_code="PUBLIC", page_count=p.page_count,
        metadata={"source_filename": p.filename, "file_type": p.file_type, "parser": p.parser,
                  "file_sha256": p.file_sha256, "pages_without_text": p.pages_without_text},
        chunks=[ChunkIn(content=c.content, page_start=c.page_start, page_end=c.page_end, location=c.location)
                for c in p.chunks])
    async with transaction(user.id, rid) as conn:
        created_doc = await store_document(conn, doc)
        created = await _create(conn, body, user, {"source_kind": "PDF", "document_id": created_doc.id})
    created.chunk_count = len(created_doc.chunk_ids)
    created.warnings = p.warnings
    return created


@router.get("", dependencies=[Depends(public_rate_limit)])
async def list_announcements(receipt_state: str | None = Query(None, description="UPCOMING | OPEN | CLOSED"),
                             domain: str | None = None, q: str | None = Query(None, description="제목 검색"),
                             limit: int = Query(50, le=200), offset: int = 0,
                             user: CurrentUser | None = Depends(optional_user)):
    async with transaction() as conn:
        rows = await (await conn.execute(
            """SELECT id, announcement_no, title, agency_name, domain, program_id, program_code, program_name,
                      support_amount_krw, receipt_start, receipt_end, status, receipt_state, source_kind,
                      requirement_count, mandatory_count, tech_need_count, updated_at
                 FROM ax.v_announcement
                WHERE (%(staff)s OR status = 'PUBLISHED')
                  AND (%(state)s::text IS NULL OR receipt_state = %(state)s)
                  AND (%(domain)s::text IS NULL OR domain = %(domain)s)
                  AND (%(q)s::text IS NULL OR title ILIKE '%%' || %(q)s || '%%')
                ORDER BY (receipt_state = 'OPEN') DESC, receipt_end NULLS LAST, id
                LIMIT %(limit)s OFFSET %(offset)s""",
            {"staff": _is_staff(user), "state": receipt_state, "domain": domain, "q": q,
             "limit": limit, "offset": offset})).fetchall()
    for r in rows:
        r["receipt_state_label"] = RECEIPT_LABEL[r["receipt_state"]]
    return rows


@router.get("/{ann_id}", dependencies=[Depends(public_rate_limit)])
async def get_announcement(ann_id: int, user: CurrentUser | None = Depends(optional_user)):
    async with transaction() as conn:
        a = await _announcement(conn, ann_id, user)
        a["receipt_state_label"] = RECEIPT_LABEL[a["receipt_state"]]
        a["requirements"] = await (await conn.execute(
            """SELECT r.id, r.req_type_code, t.name_ko AS req_type_name, r.rule, r.is_mandatory,
                      CASE WHEN r.is_mandatory THEN '필수' ELSE '우대' END AS mandatory_label,
                      r.description, r.source_quote, r.source_page, r.evidence_id, e.chunk_id AS evidence_chunk_id,
                      r.origin, r.sort_order
                 FROM ax.announcement_requirement r
                 JOIN ax.code_requirement_type t ON t.code = r.req_type_code
                 LEFT JOIN ax.evidence e ON e.id = r.evidence_id
                WHERE r.announcement_id = %s ORDER BY r.sort_order, r.id""", (ann_id,))).fetchall()
        a["tech_needs"] = await (await conn.execute(
            """SELECT id, tech_name, description, tech_taxonomy_id, ipc_codes, is_core, sort_order
                 FROM ax.announcement_tech_need WHERE announcement_id = %s ORDER BY sort_order, id""",
            (ann_id,))).fetchall()
        a["document"] = None
        if a["document_id"]:
            a["document"] = await (await conn.execute(
                """SELECT id, title, page_count, metadata->>'source_filename' AS filename,
                          (SELECT count(*) FROM ax.document_chunk c WHERE c.document_id = d.id) AS chunk_count
                     FROM ax.source_document d WHERE id = %s""", (a["document_id"],))).fetchone()
    return a


@router.get("/{ann_id}/chunks", dependencies=[Depends(public_rate_limit)])
async def get_announcement_chunks(ann_id: int, q: str | None = Query(None, description="본문 검색 (예: 신용등급)"),
                                  user: CurrentUser | None = Depends(optional_user)):
    async with transaction() as conn:
        a = await _announcement(conn, ann_id, user)
        if not a["document_id"]:
            return []
        return await (await conn.execute(
            """SELECT id AS chunk_id, chunk_index, page_start, page_end, content
                 FROM ax.document_chunk WHERE document_id = %(doc)s
                  AND (%(q)s::text IS NULL OR content ILIKE '%%' || %(q)s || '%%')
                ORDER BY chunk_index""", {"doc": a["document_id"], "q": q})).fetchall()


@router.patch("/{ann_id}", status_code=204)
async def update_announcement(ann_id: int, body: AnnouncementUpdate,
                              user: CurrentUser = Depends(require_roles(*STAFF)), rid: str = Depends(request_id)):
    data = body.model_dump(exclude_unset=True)
    async with transaction(user.id, rid) as conn:
        cur = await (await conn.execute(
            "SELECT receipt_start, receipt_end, status FROM ax.announcement WHERE id = %s", (ann_id,))).fetchone()
        if cur is None:
            raise NotFound("공고", ann_id)
        start, end = data.get("receipt_start", cur["receipt_start"]), data.get("receipt_end", cur["receipt_end"])
        if start and end and end < start:
            raise _unprocessable("접수 마감일이 접수 시작일보다 빠릅니다")
        await update(conn, "announcement", ann_id, data)
        await _changed(conn, ann_id)
    # 공개로 바뀔 때 구독 기업에 알림
    if data.get("status") == "PUBLISHED" and cur["status"] != "PUBLISHED":
        await safe_dispatch(ann_id, rid)


@router.post("/{ann_id}/requirements", response_model=Created, status_code=201)
async def add_requirement(ann_id: int, body: RequirementIn, user: CurrentUser = Depends(require_roles(*STAFF)),
                          rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        a = await _announcement(conn, ann_id, user)
        req_id = await _insert_requirement(conn, ann_id, a["document_id"], body,
                                           await _next_sort(conn, "announcement_requirement", ann_id))
        await _changed(conn, ann_id)
        return Created(id=req_id)


@router.patch("/{ann_id}/requirements/{req_id}", status_code=204)
async def update_requirement(ann_id: int, req_id: int, body: RequirementUpdate,
                             user: CurrentUser = Depends(require_roles(*STAFF)), rid: str = Depends(request_id)):
    data = body.model_dump(exclude_unset=True)
    async with transaction(user.id, rid) as conn:
        cur = await (await conn.execute(
            "SELECT req_type_code FROM ax.announcement_requirement WHERE id = %s AND announcement_id = %s",
            (req_id, ann_id))).fetchone()
        if cur is None:
            raise NotFound("자격요건", req_id)
        if "rule" in data:
            try:
                data["rule"] = normalize_rule(cur["req_type_code"], data["rule"] or {})
            except ValueError as e:
                raise _unprocessable(str(e)) from None
            await _check_codes(conn, cur["req_type_code"], data["rule"])
        await update(conn, "announcement_requirement", req_id, data)
        await _changed(conn, ann_id)


@router.delete("/{ann_id}/requirements/{req_id}", status_code=204)
async def delete_requirement(ann_id: int, req_id: int, user: CurrentUser = Depends(require_roles(*STAFF)),
                             rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        cur = await conn.execute("DELETE FROM ax.announcement_requirement WHERE id = %s AND announcement_id = %s",
                                 (req_id, ann_id))
        if cur.rowcount == 0:
            raise NotFound("자격요건", req_id)
        await _changed(conn, ann_id)
    return Response(status_code=204)


@router.post("/{ann_id}/tech-needs", response_model=Created, status_code=201)
async def add_tech_need(ann_id: int, body: TechNeedIn, user: CurrentUser = Depends(require_roles(*STAFF)),
                        rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        await _announcement(conn, ann_id, user)
        tech_id = await _insert_tech_need(conn, ann_id, body, await _next_sort(conn, "announcement_tech_need", ann_id))
        await _changed(conn, ann_id)
        return Created(id=tech_id)


@router.delete("/{ann_id}/tech-needs/{tech_id}", status_code=204)
async def delete_tech_need(ann_id: int, tech_id: int, user: CurrentUser = Depends(require_roles(*STAFF)),
                           rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        cur = await conn.execute("DELETE FROM ax.announcement_tech_need WHERE id = %s AND announcement_id = %s",
                                 (tech_id, ann_id))
        if cur.rowcount == 0:
            raise NotFound("요구 기술", tech_id)
        await _changed(conn, ann_id)
    return Response(status_code=204)
