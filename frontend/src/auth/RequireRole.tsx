import type { ReactNode } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'
import { canAccess, homePath, ROLES, type RoleCode } from './roles'

/** 로그인과 역할을 확인하는 라우트 가드. 역할이 맞지 않으면 접근 거부 화면을 보여 준다. */
export function RequireRole({ roles, children }: { roles: RoleCode[]; children: ReactNode }) {
  const { user, role, restoring } = useAuth()
  const location = useLocation()

  if (restoring) return <div className="page-loading">로그인 정보를 확인하는 중…</div>
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (!canAccess(role, roles)) {
    return (
      <div className="forbidden">
        <div className="forbidden-icon">🔒</div>
        <h2>이 화면에 접근할 권한이 없습니다</h2>
        <p>
          현재 역할: <strong>{role ? ROLES[role].label : '역할 없음'}</strong>
          <br />
          필요 역할: {roles.map((r) => ROLES[r].label).join(', ')}
        </p>
        {role && <Link className="btn" to={homePath(role)}>내 화면으로 이동</Link>}
      </div>
    )
  }
  return <>{children}</>
}
