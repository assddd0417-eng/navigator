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
