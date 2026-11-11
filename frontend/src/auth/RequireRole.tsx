import type { ReactNode } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'
import { canAccess, homePath, ROLES, type RoleCode } from './roles'

/** 로그인과 역할을 확인하는 라우트 가드. 역할이 맞지 않으면 접근 거부 화면을 보여 준다. */
export function RequireRole({ roles, children }: { roles: RoleCode[]; children: ReactNode }) {
  const { user, role, restoring } = useAuth()
  const location = useLocation()

  if (restoring) return <div className="page-loading">로그인 정보를 확인하는 중…</div>
  // 로그인 뒤 원래 화면(주소 뒤 ?조건 포함)으로 돌아올 수 있게 기억해 둔다
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  if (!canAccess(role, roles)) {
    return (
      <div className="forbidden">
        <div className="forbidden-icon">🔒</div>
        <h2>이 화면은 {roles.map((r) => ROLES[r].label).join('·')}만 볼 수 있습니다</h2>
        <p>
          지금 역할은 <strong>{role ? ROLES[role].label : '역할 없음'}</strong>입니다.
          <br />
          다른 역할로 보려면 위쪽의 ‘사용자 바꾸기’에서 바꿔 주세요.
        </p>
        {role && <Link className="btn btn-primary" to={homePath(role)}>내 첫 화면으로</Link>}
      </div>
    )
  }
  return <>{children}</>
}
