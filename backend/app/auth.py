"""PoC 인증: X-User-Id 헤더로 사용자를 식별한다.

운영 전환 시 SSO/JWT 검증으로 교체하고, 검증된 사용자 ID 만 이 모듈 밖으로 내보내면 된다.
"""
from dataclasses import dataclass, field

from fastapi import Depends, Header, HTTPException, Request, status

from app.db import open_pool


@dataclass(frozen=True)
class CurrentUser:
    id: int
    name: str
    department_id: int | None
    clearance_code: str
    roles: frozenset[str] = field(default_factory=frozenset)

    def has_any(self, *roles: str) -> bool:
        return "ADMIN" in self.roles or any(r in self.roles for r in roles)


async def get_current_user(x_user_id: int | None = Header(default=None)) -> CurrentUser:
    if x_user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-User-Id 헤더가 필요합니다")
    pool = await open_pool()
    async with pool.connection() as conn:
        row = await (await conn.execute(
            """SELECT u.id, u.name, u.department_id, u.clearance_code,
                      COALESCE(array_agg(r.role_code) FILTER (WHERE r.role_code IS NOT NULL), '{}') AS roles
                 FROM ax.app_user u LEFT JOIN ax.user_role r ON r.user_id = u.id
                WHERE u.id = %s AND u.is_active
                GROUP BY u.id""",
            (x_user_id,),
        )).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "알 수 없거나 비활성화된 사용자입니다")
    return CurrentUser(row["id"], row["name"], row["department_id"], row["clearance_code"], frozenset(row["roles"]))


def require_roles(*roles: str):
    """지정 역할 중 하나(또는 ADMIN)가 있어야 통과."""

    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_any(*roles):
            names = {"STAFF": "기업지원 담당자", "PROGRAM_OWNER": "지원사업 소관부서", "AX_ADMIN": "AX 주관부서"}
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"{'·'.join(names.get(r, r) for r in roles)}만 할 수 있습니다")
        return user

    return checker


def request_id(request: Request) -> str:
    return request.state.request_id
