"""기업 관리 링크. 토큰은 해시만 저장, 링크는 .../navigator/manage#t=<토큰> (fragment 라 서버 로그에 안 남음)."""
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
    # 기존 링크는 폐기
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
    if not token or len(token) > 200:
        return None
    return await (await conn.execute(
        """UPDATE ax.company_access_link
              SET last_used_at = now(), email_verified_at = COALESCE(email_verified_at, now())
            WHERE token_hash = %s AND revoked_at IS NULL AND expires_at > now()
        RETURNING id AS link_id, organization_id, email, expires_at""",
        (hash_token(token),))).fetchone()
