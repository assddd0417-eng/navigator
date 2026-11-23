"""지원사업 운영규정·지침. 조문 단위 등록, 근거 검색, 공통 참여제한.

  등록     본문을 '제N조(제목)' 단위로 나눠 조문으로 저장한다. 조문 글에서 참여제한 항목(체납·부도·참여제한·
           부정당제재·중복지원)을 찾아 checks 후보로 넣고, 소관부서가 고친다
  확인     소관부서가 내용을 확인하면 confirmed_at (판단기준 확인일) 을 남긴다. 확인 전 규정은 근거 목록에
           "확인 전"으로만 보이고 판정(공통 참여제한, AI 판단 근거)에는 쓰지 않는다
  검색     벡터 관련도 + 낱말 겹침으로 후보를 뽑고, 사업 일치·참여제한 조문을 더해 다시 정렬한다
  공통 참여제한  공통운영규정과 그 사업의 운영규정 조문 checks 를 모든 공고의 필수요건으로 더한다
                (공고에 같은 항목이 있으면 더하지 않는다)
"""
from __future__ import annotations

import re

from psycopg import AsyncConnection

from app.services.eligibility import DISQUALIFY_KO, Requirement
from app.services.embedding import active_model_id, embed_query, embed_texts

KIND_KO = {"COMMON": "공통운영규정", "PROGRAM": "사업별 운영규정·지침"}
CHECK_KO = {**DISQUALIFY_KO, "DUPLICATE": "중복지원 제한"}
CHECK_WORDS = {
    "TAX_DELINQUENT": r"체납",
    "INSOLVENT": r"부도|자본\s*잠식|파산|회생",
    "RND_RESTRICTED": r"참여\s*제한",
    "PROCUREMENT_SANCTIONED": r"부정당",
    "DUPLICATE": r"중복\s*(지원|수혜|신청)|동일\s*(사업|과제|분야)",
}
ARTICLE = re.compile(r"(?m)^\s*(제\s*\d+\s*조(?:의\s*\d+)?)\s*(?:\(([^)\n]{1,60})\))?")
MAX_RESULTS = 5


def split_articles(text: str) -> list[dict]:
    """'제N조(제목)' 으로 나눈다. 조문 표시가 없으면 빈 줄 단위 문단을 1, 2, ... 로 둔다."""
    text = (text or "").strip()
    marks = list(ARTICLE.finditer(text))
    if not marks:
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        return [{"article_no": str(i), "title": None, "body": p} for i, p in enumerate(paras, 1)]
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end].strip()
        if body:
            out.append({"article_no": re.sub(r"\s+", "", m.group(1)), "title": (m.group(2) or "").strip() or None,
                        "body": body})
    return out


NEGATED = re.compile(r"^\s*(에\s*관한\s*|관련\s*)?(내용|사항|규정|조항|대상)?\s*(은|는|이|가)?\s*(해당\s*)?(사항\s*)?(없습니다|없음|없다)")


def _found(pat: str, body: str) -> bool:
    """'참여제한 내용은 없습니다' 처럼 바로 뒤에서 부정하는 문장은 빼고 찾는다."""
    return any(not NEGATED.match(body[m.end():]) for m in re.finditer(pat, body))


def guess_checks(body: str) -> tuple[list[str], int | None]:
    checks = [code for code, pat in CHECK_WORDS.items() if _found(pat, body or "")]
    years = None
    if "DUPLICATE" in checks:
        m = re.search(r"(\d+)\s*년", body)
        years = min(max(int(m.group(1)), 1), 10) if m else 1
    return checks, years


def ref_of(reg_title: str, a: dict) -> str:
    return f"{reg_title} {a['article_no']}" + (f"({a['title']})" if a.get("title") else "")


# ---------- 등록·관리 ----------

async def _embed_articles(conn: AsyncConnection, ids: list[int]) -> None:
    if not ids:
        return
    rows = await (await conn.execute(
        "SELECT id, coalesce(title, '') || ' ' || body AS text FROM ax.regulation_article WHERE id = ANY(%s)",
        (ids,))).fetchall()
    model = await active_model_id(conn)
    for r, vec in zip(rows, await embed_texts([r["text"] for r in rows])):
        await conn.execute("UPDATE ax.regulation_article SET embedding = %s, model_id = %s WHERE id = %s",
                           (vec, model, r["id"]))


async def _insert_articles(conn: AsyncConnection, reg_id: int, articles: list[dict], start: int = 0) -> list[int]:
    ids = []
    for i, a in enumerate(articles):
        checks, years = (a["checks"], a.get("within_years")) if a.get("checks") is not None else guess_checks(a["body"])
        if "DUPLICATE" in checks and not years:
            years = 1
        row = await (await conn.execute(
            """INSERT INTO ax.regulation_article (regulation_id, sort_order, article_no, title, body, checks,
                                                  within_years)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (reg_id, start + i, a["article_no"], a.get("title"), a["body"], checks,
             years if "DUPLICATE" in checks else None))).fetchone()
        ids.append(row["id"])
    await _embed_articles(conn, ids)
    return ids


async def create(conn: AsyncConnection, data: dict, user_id: int, dept_id: int | None) -> dict:
    if data["kind"] == "PROGRAM":
        if not data.get("program_id") or not await (await conn.execute(
                "SELECT 1 FROM ax.program WHERE id = %s", (data["program_id"],))).fetchone():
            raise ValueError("사업별 운영규정은 지원사업을 골라야 합니다")
    else:
        data["program_id"] = None
    articles = data.get("articles") or split_articles(data.get("text") or "")
    if not articles:
        raise ValueError("조문이 없습니다")
    row = await (await conn.execute(
        """INSERT INTO ax.regulation (title, kind, program_id, owner_dept_id, version_label, effective_on, source_url,
                                      created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (data["title"], data["kind"], data["program_id"], dept_id, data.get("version_label"),
         data.get("effective_on"), data.get("source_url"), user_id))).fetchone()
    await _insert_articles(conn, row["id"], articles)
    return await get(conn, row["id"])


async def get(conn: AsyncConnection, reg_id: int) -> dict:
    r = await (await conn.execute(
        """SELECT g.*, p.name AS program_name, d.name AS owner_dept_name, u.name AS confirmed_by_name
             FROM ax.regulation g LEFT JOIN ax.program p ON p.id = g.program_id
             LEFT JOIN ax.department d ON d.id = g.owner_dept_id LEFT JOIN ax.app_user u ON u.id = g.confirmed_by
            WHERE g.id = %s""", (reg_id,))).fetchone()
    if r is None:
        raise LookupError(reg_id)
    r["kind_label"] = KIND_KO[r["kind"]]
    arts = await (await conn.execute(
        """SELECT id, sort_order, article_no, title, body, checks, within_years
             FROM ax.regulation_article WHERE regulation_id = %s ORDER BY sort_order, id""", (reg_id,))).fetchall()
    for a in arts:
        a["check_labels"] = [CHECK_KO[c] for c in a["checks"]]
        a["ref"] = ref_of(r["title"], a)
    r["articles"] = arts
    return r


async def list_all(conn: AsyncConnection) -> list[dict]:
    rows = await (await conn.execute(
        """SELECT g.id, g.title, g.kind, g.program_id, p.name AS program_name, g.version_label, g.effective_on,
                  g.is_active, g.confirmed_at, g.updated_at, d.name AS owner_dept_name,
                  (SELECT count(*) FROM ax.regulation_article a WHERE a.regulation_id = g.id) AS article_count,
                  (SELECT count(*) FROM ax.regulation_article a WHERE a.regulation_id = g.id AND a.checks <> '{}')
                      AS limit_count
             FROM ax.regulation g LEFT JOIN ax.program p ON p.id = g.program_id
             LEFT JOIN ax.department d ON d.id = g.owner_dept_id
            ORDER BY g.is_active DESC, g.kind, g.title""")).fetchall()
    for r in rows:
        r["kind_label"] = KIND_KO[r["kind"]]
    return rows


async def update(conn: AsyncConnection, reg_id: int, data: dict) -> dict:
    await get(conn, reg_id)
    fields = {k: data[k] for k in ("title", "version_label", "effective_on", "source_url", "is_active") if k in data}
    if fields:
        sets = ", ".join(f"{k} = %({k})s" for k in fields)
        await conn.execute(f"UPDATE ax.regulation SET {sets}, updated_at = now() WHERE id = %(id)s",
                           {**fields, "id": reg_id})
    if data.get("articles") is not None:
        await conn.execute("DELETE FROM ax.regulation_article WHERE regulation_id = %s", (reg_id,))
        await _insert_articles(conn, reg_id, data["articles"])
        # 내용이 바뀌면 다시 확인받는다
        await conn.execute("UPDATE ax.regulation SET confirmed_at = NULL, confirmed_by = NULL, updated_at = now() "
                           "WHERE id = %s", (reg_id,))
    return await get(conn, reg_id)


async def confirm(conn: AsyncConnection, reg_id: int, user_id: int) -> dict:
    await get(conn, reg_id)
    await conn.execute("UPDATE ax.regulation SET confirmed_at = now(), confirmed_by = %s, updated_at = now() "
                       "WHERE id = %s", (user_id, reg_id))
    return await get(conn, reg_id)


async def delete(conn: AsyncConnection, reg_id: int) -> None:
    if (await conn.execute("DELETE FROM ax.regulation WHERE id = %s", (reg_id,))).rowcount == 0:
        raise LookupError(reg_id)


# ---------- 검색 ----------

def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", text or "")}


async def search(conn: AsyncConnection, query: str, *, program_id: int | None = None,
                 limit: int = MAX_RESULTS) -> list[dict]:
    """조문 검색. 그 사업의 운영규정과 공통운영규정만 본다 (program_id 가 없으면 전체)."""
    query = (query or "").strip()
    if not query:
        return []
    model = await active_model_id(conn)
    missing = await (await conn.execute(   # SQL 로 넣은 조문이나 모델이 바뀐 조문
        "SELECT id FROM ax.regulation_article WHERE model_id IS DISTINCT FROM %s LIMIT 500", (model,))).fetchall()
    await _embed_articles(conn, [r["id"] for r in missing])
    q = await embed_query(query)
    rows = await (await conn.execute(
        """SELECT a.id, a.article_no, a.title, a.body, a.checks, a.within_years, g.id AS regulation_id,
                  g.title AS regulation_title, g.kind, g.program_id, g.confirmed_at, g.effective_on,
                  CASE WHEN a.model_id = %(m)s THEN 1 - (a.embedding <=> %(q)s) ELSE 0 END AS sim
             FROM ax.regulation_article a JOIN ax.regulation g ON g.id = a.regulation_id
            WHERE g.is_active AND (%(p)s::bigint IS NULL OR g.kind = 'COMMON' OR g.program_id = %(p)s)
            ORDER BY sim DESC LIMIT 40""", {"m": model, "q": q, "p": program_id})).fetchall()
    words = _words(query)
    for r in rows:
        text = f"{r['title'] or ''} {r['body']}"
        overlap = sum(w in text for w in words) / len(words) if words else 0.0
        r["keyword"] = round(overlap, 3)
        r["score"] = round(0.6 * float(r["sim"]) + 0.4 * overlap
                           + (0.05 if program_id and r["program_id"] == program_id else 0), 4)
        r["ref"] = ref_of(r["regulation_title"], r)
        r["check_labels"] = [CHECK_KO[c] for c in r["checks"]]
    rows = [r for r in rows if r["keyword"] > 0 or float(r["sim"]) >= 0.3]
    rows.sort(key=lambda r: -r["score"])
    return rows[:limit]


async def basis_for(conn: AsyncConnection, *, program_id: int | None, query: str) -> list[dict]:
    """자격 판단 근거로 쓸 조문: 검색 상위 + 참여제한 조문 (중복 없이)."""
    found = await search(conn, query, program_id=program_id)
    seen = {r["id"] for r in found}
    for r in await limit_articles(conn, program_id, confirmed_only=False):
        if r["id"] not in seen:
            found.append(r)
            seen.add(r["id"])
    return [{"source": "운영규정", "ref": r["ref"], "text": r["body"][:800], "article_id": r["id"],
             "regulation_id": r["regulation_id"], "regulation_title": r["regulation_title"],
             "confirmed_at": r["confirmed_at"]} for r in found]


async def limit_articles(conn: AsyncConnection, program_id: int | None, *, confirmed_only: bool = True) -> list[dict]:
    """참여제한 항목이 있는 조문. 판정에 쓸 때는 소관부서가 확인한 규정만."""
    rows = await (await conn.execute(
        """SELECT a.id, a.article_no, a.title, a.body, a.checks, a.within_years, g.id AS regulation_id,
                  g.title AS regulation_title, g.kind, g.program_id, g.confirmed_at
             FROM ax.regulation_article a JOIN ax.regulation g ON g.id = a.regulation_id
            WHERE g.is_active AND a.checks <> '{}' AND (g.kind = 'COMMON' OR g.program_id = %s)
              AND (NOT %s OR g.confirmed_at IS NOT NULL)
            ORDER BY g.kind, g.id, a.sort_order""", (program_id, confirmed_only))).fetchall()
    for r in rows:
        r["ref"] = ref_of(r["regulation_title"], r)
    return rows


def common_requirements(articles: list[dict], existing: list[Requirement], ann: dict) -> list[tuple[Requirement, dict]]:
    """공고에 없는 공통 참여제한을 필수요건으로 만든다. id 는 음수 (-조문 id)."""
    covered: set[str] = set()
    has_dup = False
    for r in existing:
        if r.req_type == "NO_DISQUALIFICATION":
            covered |= set(r.rule.get("checks") or [])
        if r.req_type == "DUPLICATE_SUPPORT":
            has_dup = True
    out = []
    for a in articles:
        new = [c for c in a["checks"] if c != "DUPLICATE" and c not in covered]
        if new:
            covered |= set(new)
            desc = "공통 참여제한: " + ", ".join(DISQUALIFY_KO[c] + " 없음" for c in new)
            out.append((Requirement(-a["id"], "NO_DISQUALIFICATION", {"checks": new}, True, desc), a))
        if "DUPLICATE" in a["checks"] and not has_dup:
            has_dup = True
            years = a["within_years"] or 1
            rule = {"within_years": years, "_announcement_id": ann["id"], "_title": ann["title"],
                    "_series_key": ann.get("series_key"), "_program_id": ann.get("program_id"),
                    "_program_name": ann.get("program_name")}
            out.append((Requirement(-a["id"] - 10**9, "DUPLICATE_SUPPORT", rule, True,
                                    f"공통 참여제한: 최근 {years}년 같은 사업 중복지원 없음"), a))
    return out
