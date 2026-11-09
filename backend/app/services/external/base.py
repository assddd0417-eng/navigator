import hashlib
import json
from typing import Any

from psycopg import AsyncConnection


class ConnectorUnavailable(RuntimeError):
    """키 없음·미구현·네트워크 오류. 호출부는 미확인으로 처리."""


def content_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def record_fetch(conn: AsyncConnection, *, source_code: str, mode: str, organization_id: int | None,
                       external_key: str, payload: Any | None, error: str | None = None,
                       trigger_kind: str = "ON_DEMAND", request_params: dict | None = None) -> int | None:
    """fetch_job + raw_record 기록. raw_record id 반환 (실패 시 None)."""
    job = await (await conn.execute(
        """INSERT INTO ax.external_fetch_job
                  (source_id, organization_id, mode, trigger_kind, request_params, status,
                   records_count, error_message, finished_at)
           SELECT id, %s, %s, %s, %s, %s, %s, %s, clock_timestamp() FROM ax.external_source WHERE code = %s
           RETURNING id, source_id""",
        (organization_id, mode.upper(), trigger_kind, json.dumps(request_params or {}, ensure_ascii=False),
         "FAILED" if error else "SUCCEEDED", 0 if error or payload is None else 1, error, source_code))).fetchone()
    if job is None:
        raise LookupError(f"external_source {source_code} 이(가) 없습니다")
    if error or payload is None:
        return None
    raw = await (await conn.execute(
        """INSERT INTO ax.external_raw_record (fetch_job_id, source_id, organization_id, external_key, payload, content_hash)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (job["id"], job["source_id"], organization_id, external_key,
         json.dumps(payload, ensure_ascii=False), content_hash(payload)))).fetchone()
    return raw["id"]


HTTP_TIMEOUT_S = 20.0


def _client():
    import httpx
    return httpx.Client(timeout=HTTP_TIMEOUT_S, headers={"User-Agent": "kd-ax-navigator/1.0"})


def _call(method: str, url: str, **kw) -> Any:
    import httpx
    try:
        with _client() as c:
            r = c.request(method, url, **kw)
            r.raise_for_status()
            return r
    except httpx.HTTPStatusError as e:
        raise ConnectorUnavailable(f"{url.split('?')[0]} HTTP {e.response.status_code}") from None
    except httpx.HTTPError as e:
        raise ConnectorUnavailable(f"{url.split('?')[0]} 연결 실패: {type(e).__name__}") from None


def http_get_json(url: str, params: dict | None = None) -> Any:
    return _call("GET", url, params=params).json()


def http_post_json(url: str, body: Any, params: dict | None = None) -> Any:
    return _call("POST", url, json=body, params=params).json()


def http_get_text(url: str, params: dict | None = None) -> str:
    return _call("GET", url, params=params).text


def http_get_bytes(url: str, params: dict | None = None) -> bytes:
    return _call("GET", url, params=params).content


_CORP_MARKS = ("주식회사", "(주)", "㈜", "유한회사", "(유)", "(가상)")


def normalize_company_name(name: str) -> str:
    """출원인·공시 회사명 비교용: 법인 표기와 공백 제거."""
    n = name or ""
    for m in _CORP_MARKS:
        n = n.replace(m, "")
    return "".join(n.split()).lower()


def load_fixture(name: str) -> Any:
    from pathlib import Path
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8"))
