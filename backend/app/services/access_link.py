"""기업 관리 링크 (로그인 대신 쓰는 비밀 주소).

- 비밀값은 secrets.token_urlsafe(32) (256비트). DB 에는 SHA-256 해시만 저장한다.
- 링크 형식: {NAVIGATOR_PUBLIC_BASE_URL}/navigator/manage#t=<비밀값>
  (# 뒤는 브라우저가 서버로 보내지 않아 접속 로그에 남지 않는다. 화면이 읽어 X-Manage-Token 헤더로 보낸다)
- 만료(NAVIGATOR_LINK_TTL_DAYS)되면 사업자번호로 다시 요청한다. 다시 요청하면 이전 링크는 폐기된다.
"""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime

from psycopg import AsyncConnection

from app.config import get_settings


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def build_link(token: str) -> str:
    return f"{get_settings().navigator_public_base_url.rstrip('/')}/navigator/manage#t={token}"


@dataclass(frozen=True)
class IssuedLink:
    id: int
    token: str
    url: str
    expires_at: datetime


async def issue(conn: AsyncConnection, organization_id: int, email: str) -> IssuedLink:
    """새 관리 링크를 만들고 같은 기업의 이전 링크는 폐기한다."""
    await conn.execute(
        "UPDATE ax.company_access_link SET revoked_at = now() "
        "WHERE organization_id = %s AND revoked_at IS NULL", (organization_id,))
    token = secrets.token_urlsafe(32)
    row = await (await conn.execute(
        """INSERT INTO ax.company_access_link (organization_id, email, token_hash, expires_at)
           VALUES (%s, %s, %s, now() + make_interval(days => %s))
           RETURNING id, expires_at""",
        (organization_id, email, hash_token(token), get_settings().navigator_link_ttl_days))).fetchone()
    return IssuedLink(row["id"], token, build_link(token), row["expires_at"])


async def resolve(conn: AsyncConnection, token: str) -> dict | None:
    """유효한 링크면 {link_id, organization_id, email, expires_at}. 처음 쓰면 이메일 확인 시각을 남긴다."""
    if not token or len(token) > 200:
        return None
    return await (await conn.execute(
        """UPDATE ax.company_access_link
              SET last_used_at = now(), email_verified_at = COALESCE(email_verified_at, now())
            WHERE token_hash = %s AND revoked_at IS NULL AND expires_at > now()
        RETURNING id AS link_id, organization_id, email, expires_at""",
        (hash_token(token),))).fetchone()
