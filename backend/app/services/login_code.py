"""회사 정보 화면 본인 확인: 등록 이메일로 6자리 코드를 보내고 확인되면 관리 토큰을 준다."""
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime

from psycopg import AsyncConnection

TTL_MINUTES = 10
MAX_ATTEMPTS = 5
RESEND_SECONDS = 60


def _hash(org_id: int, code: str) -> str:
    return hashlib.sha256(f"{org_id}:{code}".encode()).hexdigest()


@dataclass(frozen=True)
class IssuedCode:
    code: str
    expires_at: datetime


class TooSoon(Exception):
    def __init__(self, wait_s: int):
        self.wait_s = wait_s


async def issue(conn: AsyncConnection, org_id: int, email: str) -> IssuedCode:
    last = await (await conn.execute(
        """SELECT ceil(extract(epoch FROM created_at + make_interval(secs => %s) - now()))::int AS wait
             FROM ax.company_login_code WHERE organization_id = %s ORDER BY created_at DESC LIMIT 1""",
        (RESEND_SECONDS, org_id))).fetchone()
    if last and last["wait"] > 0:
        raise TooSoon(last["wait"])
    await conn.execute("UPDATE ax.company_login_code SET revoked_at = now() "
                       "WHERE organization_id = %s AND used_at IS NULL AND revoked_at IS NULL", (org_id,))
    code = f"{secrets.randbelow(1_000_000):06d}"
    row = await (await conn.execute(
        """INSERT INTO ax.company_login_code (organization_id, email, code_hash, expires_at)
           VALUES (%s, %s, %s, now() + make_interval(mins => %s)) RETURNING expires_at""",
        (org_id, email, _hash(org_id, code), TTL_MINUTES))).fetchone()
    return IssuedCode(code, row["expires_at"])


async def verify(conn: AsyncConnection, org_id: int, code: str) -> str:
    """OK / WRONG / EXPIRED (없음·만료·사용함·횟수 초과)."""
    row = await (await conn.execute(
        """SELECT id, code_hash, attempts FROM ax.company_login_code
            WHERE organization_id = %s AND used_at IS NULL AND revoked_at IS NULL AND expires_at > now()
            ORDER BY created_at DESC LIMIT 1 FOR UPDATE""", (org_id,))).fetchone()
    if row is None or row["attempts"] >= MAX_ATTEMPTS:
        return "EXPIRED"
    if hmac.compare_digest(row["code_hash"], _hash(org_id, code.strip())):
        await conn.execute("UPDATE ax.company_login_code SET used_at = now() WHERE id = %s", (row["id"],))
        return "OK"
    await conn.execute("UPDATE ax.company_login_code SET attempts = attempts + 1 WHERE id = %s", (row["id"],))
    return "EXPIRED" if row["attempts"] + 1 >= MAX_ATTEMPTS else "WRONG"
