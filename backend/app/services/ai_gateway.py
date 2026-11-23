"""AI 게이트웨이. 상담 AI 판단의 LLM 호출을 한곳에서 처리한다.

  프롬프트   prompt_template 의 사용 중 버전 (system_text + guide_text)
  호출       설정(AI_JUDGE_MODE)과 자격증명을 보고 LLM 을 쓸지 정한다. 못 쓰면 None 을 돌려 규칙·템플릿으로 대체
  캐시       같은 입력·같은 프롬프트 버전이면 AI_CACHE_HOURS 안의 결과를 다시 쓴다
  감사로그   호출마다 ai_call_log 에 목적·프롬프트·모델·입력 근거·출력·차단 사유를 남긴다
기업 이름과 사업자번호는 보내지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.services.llm import LLMClient, LLMError, build_llm_client, llm_credentials_configured

log = logging.getLogger("app.ai")

_override: LLMClient | None = None      # 테스트용 가짜 LLM
_client: LLMClient | None = None


def set_client(client: LLMClient | None) -> None:
    global _override
    _override = client


def mode() -> str:
    if _override is not None:
        return "llm"
    m = get_settings().ai_judge_mode.lower()
    if m == "auto":
        return "llm" if llm_credentials_configured(get_settings()) else "rules"
    return m if m in ("llm", "rules") else "rules"


def client() -> LLMClient | None:
    global _client
    if _override is not None:
        return _override
    if mode() != "llm":
        return None
    if _client is None:
        _client = build_llm_client(get_settings())
    return _client


async def active_prompt(conn: AsyncConnection, code: str) -> dict:
    row = await (await conn.execute(
        "SELECT * FROM ax.prompt_template WHERE code = %s AND is_active", (code,))).fetchone()
    if row is None:
        raise RuntimeError(f"사용 중인 프롬프트 없음: {code}")
    return row


def parse_json(text: str) -> dict:
    """응답에서 JSON 객체 하나를 꺼낸다 (코드 블록 감싸기 허용)."""
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("JSON 객체가 없음")
    return json.loads(t[a:b + 1])


@dataclass
class Result:
    output: dict | None
    status: str                 # OK / CACHED / FALLBACK
    log_id: int | None
    model: str | None = None
    prompt_version: int | None = None
    error: str | None = None
    blocked: list = field(default_factory=list)


async def call(conn: AsyncConnection, *, purpose: str, payload: dict, refs: dict, org_id: int | None = None,
               ann_id: int | None = None, user_id: int | None = None) -> Result:
    """LLM 을 한 번 부른다. 쓸 수 없거나 실패하면 output=None (호출 측이 규칙·템플릿으로 대체)."""
    llm = client()
    if llm is None:
        return Result(None, "FALLBACK", None, error="AI 판단 꺼짐 (규칙 사용)")
    prompt = await active_prompt(conn, purpose)
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    key = hashlib.sha256(f"{purpose}|{prompt['id']}|{llm.name}|{body}".encode()).hexdigest()
    hours = get_settings().ai_cache_hours
    if hours > 0:
        hit = await (await conn.execute(
            """SELECT output, model FROM ax.ai_call_log WHERE cache_key = %s AND status IN ('OK', 'PARTIAL')
                 AND created_at > now() - make_interval(hours => %s) ORDER BY id DESC LIMIT 1""",
            (key, hours))).fetchone()
        if hit:
            lid = await _log(conn, purpose, org_id, ann_id, prompt["id"], hit["model"], key, refs, hit["output"],
                             "CACHED", None, None, user_id)
            return Result(hit["output"], "CACHED", lid, hit["model"], prompt["version"])
    system = prompt["system_text"] + ("\n\n지침:\n" + prompt["guide_text"] if prompt["guide_text"] else "")
    t0 = time.monotonic()
    try:
        out = parse_json(await llm.complete(system, body))
    except (LLMError, ValueError) as e:
        ms = int((time.monotonic() - t0) * 1000)
        log.warning("AI 호출 실패 (%s): %s", purpose, e)
        lid = await _log(conn, purpose, org_id, ann_id, prompt["id"], llm.name, key, refs, None,
                         "FALLBACK", str(e)[:500], ms, user_id)
        return Result(None, "FALLBACK", lid, llm.name, prompt["version"], error=str(e)[:200])
    ms = int((time.monotonic() - t0) * 1000)
    lid = await _log(conn, purpose, org_id, ann_id, prompt["id"], llm.name, key, refs, out, "OK", None, ms, user_id)
    return Result(out, "OK", lid, llm.name, prompt["version"])


async def _log(conn, purpose, org_id, ann_id, prompt_id, model, key, refs, output, status, error, ms, user_id) -> int:
    row = await (await conn.execute(
        """INSERT INTO ax.ai_call_log (purpose, organization_id, announcement_id, prompt_id, model, cache_key,
                                       input_refs, output, status, error, latency_ms, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (purpose, org_id, ann_id, prompt_id, model, key, Jsonb(refs), Jsonb(output) if output is not None else None,
         status, error, ms, user_id))).fetchone()
    return row["id"]


async def mark(conn: AsyncConnection, log_id: int | None, blocked: list[dict]) -> None:
    """검증에서 뺀 판단을 감사로그에 남긴다."""
    if log_id is None or not blocked:
        return
    await conn.execute(
        """UPDATE ax.ai_call_log SET blocked = %s,
                  status = CASE WHEN status = 'OK' THEN 'PARTIAL' ELSE status END WHERE id = %s""",
        (Jsonb(blocked), log_id))


# ---------- 관리 ----------

async def prompts(conn: AsyncConnection) -> list[dict]:
    rows = await (await conn.execute(
        """SELECT p.*, u.name AS created_by_name FROM ax.prompt_template p
             LEFT JOIN ax.app_user u ON u.id = p.created_by ORDER BY p.code, p.version DESC""")).fetchall()
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
    return rows


async def save_prompt(conn: AsyncConnection, code: str, data: dict, user_id: int) -> dict:
    """새 버전을 만들고 사용 중으로 바꾼다."""
    cur = await active_prompt(conn, code)
    nv = (await (await conn.execute(
        "SELECT max(version) AS v FROM ax.prompt_template WHERE code = %s", (code,))).fetchone())["v"] + 1
    await conn.execute("UPDATE ax.prompt_template SET is_active = false WHERE code = %s AND is_active", (code,))
    row = await (await conn.execute(
        """INSERT INTO ax.prompt_template (code, version, title, system_text, guide_text, is_active, note, created_by)
           VALUES (%s, %s, %s, %s, %s, true, %s, %s) RETURNING id""",
        (code, nv, data.get("title") or cur["title"], data.get("system_text") or cur["system_text"],
         data["guide_text"] if data.get("guide_text") is not None else cur["guide_text"], data.get("note"),
         user_id))).fetchone()
    return {"id": row["id"], "code": code, "version": nv}


async def activate_prompt(conn: AsyncConnection, prompt_id: int, code: str | None = None) -> dict:
    row = await (await conn.execute("SELECT code, version FROM ax.prompt_template WHERE id = %s",
                                    (prompt_id,))).fetchone()
    if row is None or (code is not None and row["code"] != code):
        raise LookupError(prompt_id)
    await conn.execute("UPDATE ax.prompt_template SET is_active = false WHERE code = %s AND is_active", (row["code"],))
    await conn.execute("UPDATE ax.prompt_template SET is_active = true WHERE id = %s", (prompt_id,))
    return {"id": prompt_id, **row}


async def call_logs(conn: AsyncConnection, limit: int = 100, purpose: str | None = None) -> dict:
    rows = await (await conn.execute(
        """SELECT l.id, l.purpose, l.organization_id, o.name AS company_name, l.announcement_id,
                  a.title AS announcement_title, p.version AS prompt_version, l.model, l.status, l.blocked,
                  l.error, l.latency_ms, l.created_at, u.name AS created_by_name, l.input_refs, l.output
             FROM ax.ai_call_log l LEFT JOIN ax.organization o ON o.id = l.organization_id
             LEFT JOIN ax.announcement a ON a.id = l.announcement_id
             LEFT JOIN ax.prompt_template p ON p.id = l.prompt_id
             LEFT JOIN ax.app_user u ON u.id = l.created_by
            WHERE %(p)s::text IS NULL OR l.purpose = %(p)s
            ORDER BY l.id DESC LIMIT %(n)s""", {"p": purpose, "n": limit})).fetchall()
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
    stats = await (await conn.execute(
        """SELECT count(*) AS total, count(*) FILTER (WHERE status = 'OK') AS ok,
                  count(*) FILTER (WHERE status = 'PARTIAL') AS partial,
                  count(*) FILTER (WHERE status = 'FALLBACK') AS fallback,
                  count(*) FILTER (WHERE status = 'CACHED') AS cached,
                  coalesce(sum(jsonb_array_length(blocked)), 0) AS blocked
             FROM ax.ai_call_log""")).fetchone()
    return {"mode": mode(), "stats": stats, "items": rows}
