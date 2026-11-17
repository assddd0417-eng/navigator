"""국방기술 동의어 사전 관리: 보기·추가·끄기·엑셀 올리기·적용(다시 임베딩)·넓혀 보기.

- 보기는 로그인한 모든 역할, 고치기는 기획자·큐레이터(자료 담당).
- 사전을 바꾼 뒤 '적용'을 눌러야 성과카드·기획수요·동향의 벡터가 새 사전으로 바뀐다 (바뀐 항목만 다시 계산).
"""
from io import BytesIO
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from app.auth import CurrentUser, get_current_user, request_id, require_roles
from app.db import transaction
from app.errors import NotFound
from app.repositories.sql import insert
from app.schemas.common import Created
from app.services import embedding as emb
from app.services.synonyms import EQUIVALENT, expand, load_groups, matches

router = APIRouter(prefix="/synonyms", tags=["국방기술 동의어 사전"])
EDITORS = ("PLANNER", "CURATOR")
Relation = Literal["SYNONYM", "ABBREVIATION", "BROADER", "NARROWER", "RELATED", "EN_KO"]
RELATION_KO = {"SYNONYM": "동의어", "ABBREVIATION": "약어", "EN_KO": "영문·한글", "BROADER": "넓은 말",
               "NARROWER": "좁은 말", "RELATED": "관련어"}
KO_RELATION = {v: k for k, v in RELATION_KO.items()}


class SynonymIn(BaseModel):
    canonical_term: str = Field(min_length=1, max_length=200)
    synonym: str = Field(min_length=1, max_length=200)
    relation: Relation = "SYNONYM"
    domain: str | None = None
    source_note: str | None = None


class SynonymPatch(BaseModel):
    is_active: bool | None = None
    relation: Relation | None = None
    domain: str | None = None
    source_note: str | None = None


@router.get("")
async def list_synonyms(q: str | None = None, include_inactive: bool = False,
                        user: CurrentUser = Depends(get_current_user)):
    async with transaction(user.id) as conn:
        rows = await (await conn.execute(
            """SELECT id, canonical_term, synonym, relation, domain, source_note, is_active, created_at
                 FROM ax.term_synonym
                WHERE (%(all)s OR is_active)
                  AND (%(q)s::text IS NULL OR canonical_term ILIKE '%%' || %(q)s || '%%'
                       OR synonym ILIKE '%%' || %(q)s || '%%')
                ORDER BY canonical_term, relation, synonym""", {"all": include_inactive, "q": q})).fetchall()
    for r in rows:
        r["relation_name"] = RELATION_KO[r["relation"]]
        r["used_in_matching"] = r["relation"] in EQUIVALENT
    return rows


@router.post("", response_model=Created, status_code=201)
async def add_synonym(body: SynonymIn, user: CurrentUser = Depends(require_roles(*EDITORS)),
                      rid: str = Depends(request_id)):
    if body.canonical_term.strip().lower() == body.synonym.strip().lower():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "표준 용어와 같은 말입니다")
    async with transaction(user.id, rid) as conn:
        data = body.model_dump()
        data["canonical_term"], data["synonym"] = data["canonical_term"].strip(), data["synonym"].strip()
        return Created(id=await insert(conn, "term_synonym", data))


@router.patch("/{sid}", status_code=204)
async def patch_synonym(sid: int, body: SynonymPatch, user: CurrentUser = Depends(require_roles(*EDITORS)),
                        rid: str = Depends(request_id)):
    data = body.model_dump(exclude_unset=True)
    async with transaction(user.id, rid) as conn:
        if data:
            sets = ", ".join(f"{k} = %({k})s" for k in data)
            cur = await conn.execute(f"UPDATE ax.term_synonym SET {sets} WHERE id = %(id)s", {**data, "id": sid})
            if cur.rowcount == 0:
                raise NotFound("용어", sid)


@router.post("/import")
async def import_xlsx(file: UploadFile = File(...), dry_run: bool = Query(False),
                      user: CurrentUser = Depends(require_roles(*EDITORS)), rid: str = Depends(request_id)):
    """엑셀 올리기: 첫 시트, 머리글 '표준 용어 | 동의어 | 관계 | 분야 | 출처'. 이미 있는 짝은 건너뛴다."""
    from openpyxl import load_workbook

    try:
        wb = load_workbook(BytesIO(await file.read()), read_only=True, data_only=True)
    except Exception as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"엑셀 파일을 읽을 수 없습니다: {e}") from e
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    if not rows:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "빈 시트입니다")
    head = [str(c or "").strip() for c in rows[0]]
    try:
        ci, si = head.index("표준 용어"), head.index("동의어")
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "머리글에 '표준 용어'와 '동의어'가 있어야 합니다") from e
    col = {k: head.index(k) if k in head else None for k in ("관계", "분야", "출처")}
    items, errors = [], []
    for n, r in enumerate(rows[1:], start=2):
        canon, syn = (str(r[ci] or "").strip(), str(r[si] or "").strip())
        if not canon and not syn:
            continue
        rel_raw = str(r[col["관계"]] or "").strip() if col["관계"] is not None else ""
        rel = KO_RELATION.get(rel_raw, rel_raw.upper() or "SYNONYM")
        if not canon or not syn or canon.lower() == syn.lower() or rel not in RELATION_KO:
            errors.append({"row": n, "reason": "표준 용어·동의어가 비었거나 같음" if rel in RELATION_KO else f"모르는 관계 '{rel_raw}'"})
            continue
        items.append({"canonical_term": canon, "synonym": syn, "relation": rel,
                      "domain": (str(r[col["분야"]]).strip() if col["분야"] is not None and r[col["분야"]] else None),
                      "source_note": (str(r[col["출처"]]).strip() if col["출처"] is not None and r[col["출처"]] else None)})
    added = 0
    async with transaction(user.id, rid) as conn:
        if dry_run:  # 넣지 않고 몇 건이 새로 들어갈지만 센다
            have = {(r["canonical_term"], r["synonym"]) for r in await (await conn.execute(
                "SELECT canonical_term, synonym FROM ax.term_synonym")).fetchall()}
            seen: set[tuple[str, str]] = set()
            for it in items:
                key = (it["canonical_term"], it["synonym"])
                if key not in have and key not in seen:
                    added += 1
                seen.add(key)
            return {"rows": len(items), "would_add": added, "skipped": len(items) - added, "errors": errors,
                    "dry_run": True}
        for it in items:
            cur = await conn.execute(
                """INSERT INTO ax.term_synonym (canonical_term, synonym, relation, domain, source_note)
                   VALUES (%(canonical_term)s, %(synonym)s, %(relation)s, %(domain)s, %(source_note)s)
                   ON CONFLICT (canonical_term, synonym) DO NOTHING""", it)
            added += cur.rowcount
    return {"rows": len(items), "added": added, "skipped": len(items) - added, "errors": errors}


@router.get("/expand")
async def preview(text: str = Query(min_length=1), user: CurrentUser = Depends(get_current_user)):
    """이 글이 사전으로 어떻게 넓혀지는지 (검색·매칭에 실제로 쓰는 글)."""
    async with transaction(user.id) as conn:
        groups = await load_groups(conn)
    return {"text": text, "expanded": expand(text, groups),
            "matched": [{"canonical_term": g.canonical, "found": t, "terms": list(g.terms)} for g, t in matches(text, groups)]}


@router.post("/apply")
async def apply(user: CurrentUser = Depends(require_roles(*EDITORS)), rid: str = Depends(request_id)):
    """사전을 성과카드·기획수요·동향 벡터에 반영한다 (글이 바뀐 패싯만 다시 임베딩)."""
    done = {}
    async with transaction(user.id, rid) as conn:
        for name, sql, sync in (
                ("cards", "SELECT id FROM ax.achievement_card ORDER BY id", emb.sync_card_embeddings),
                ("demands", "SELECT id FROM ax.planning_demand ORDER BY id", emb.sync_demand_embeddings),
                ("overseas_demands", "SELECT id FROM ax.overseas_demand ORDER BY id",
                 emb.sync_overseas_demand_embeddings)):
            ids = [r["id"] for r in await (await conn.execute(sql)).fetchall()]
            done[name] = sum([await sync(conn, i) for i in ids])
    return {"re_embedded": done}


@router.delete("/{sid}", status_code=204)
async def delete_synonym(sid: int, user: CurrentUser = Depends(require_roles(*EDITORS)),
                         rid: str = Depends(request_id)):
    """잘못 넣은 짝을 지운다. 기록을 남기려면 지우지 말고 끈다."""
    async with transaction(user.id, rid) as conn:
        cur = await conn.execute("DELETE FROM ax.term_synonym WHERE id = %s", (sid,))
        if cur.rowcount == 0:
            raise NotFound("용어", sid)
