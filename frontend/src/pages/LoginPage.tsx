import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { canAccessPath, homePath, ROLES, SEED_USERS, type RoleCode } from '../auth/roles'
import { useToast } from '../components/Toast'

/** 기관 담당자 로그인 (시연용 계정 선택. 운영 시 기관 통합로그인으로 교체) */
export function LoginPage() {
  const { user, role, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const toast = useToast()
  const [pending, setPending] = useState<number | null>(null)
  const from = (location.state as { from?: string } | null)?.from

  /** 원래 가려던 화면이 이 역할로 열 수 있는 화면이면 그리로, 아니면 역할의 첫 화면으로 */
  const target = (r: RoleCode) =>
    from && from !== '/login' && canAccessPath(r, from.split('?')[0]) ? from : homePath(r)

  if (user && role) return <Navigate to={target(role)} replace />

  const choose = async (id: number) => {
    setPending(id)
    try {
      const me = await login(id)
      const seed = SEED_USERS.find((u) => u.id === me.id)!
      navigate(target(seed.role), { replace: true })
    } catch (e) {
      toast.show({
        kind: 'error',
        title: '로그인할 수 없습니다',
        message: e instanceof Error ? e.message : '서버에서 사용자를 확인하지 못했습니다.',
      })
    } finally {
      setPending(null)
    }
  }

  return (
    <div className="login">
      <div className="login-head">
        <span className="brand-mark brand-mark-lg">AX</span>
        <h1>Navigator</h1>
        <p>AI 기반 방산기업 성장경로 서비스의 담당자 화면입니다. 맡은 역할을 고르세요.</p>
        {from && from !== '/login' && <p className="notice small">로그인하면 보려던 화면으로 바로 이동합니다.</p>}
      </div>

      <div className="login-group">
        <h2>기관 담당자</h2>
        <div className="login-grid">
          {SEED_USERS.map((u) => {
            const meta = ROLES[u.role]
            return (
              <button key={u.id} className="role-card role-card-admin"
                disabled={pending != null} onClick={() => void choose(u.id)}>
                <div className="role-card-top">
                  <span className="role-card-label">{meta.label}</span>
                </div>
                <div className="role-card-user">{u.name} · {u.department}</div>
                <p>{meta.description}</p>
                <ul>{meta.can.map((c) => <li key={c}>{c}</li>)}</ul>
                <div className="role-card-foot">{pending === u.id ? '확인 중…' : '이 역할로 시작'}</div>
              </button>
            )
          })}
        </div>
      </div>
      <p className="login-note">
        시연용 화면입니다. 실제 운영에서는 기관 통합로그인으로 들어옵니다.
        <br /><Link to="/navigator">기업 화면으로 가기</Link>
      </p>
    </div>
  )
}
