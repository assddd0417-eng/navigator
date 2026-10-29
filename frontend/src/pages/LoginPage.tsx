import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { homePath, ROLES, SEED_USERS } from '../auth/roles'
import { useToast } from '../components/Toast'

/** 역할 선택형 로그인 (PoC: 시드 사용자 1~4 중 하나를 고르면 X-User-Id 로 로그인) */
export function LoginPage() {
  const { user, role, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const toast = useToast()
  const [pending, setPending] = useState<number | null>(null)

  if (user && role) return <Navigate to={homePath(role)} replace />

  const choose = async (id: number) => {
    setPending(id)
    try {
      const me = await login(id)
      const seed = SEED_USERS.find((u) => u.id === me.id)!
      const from = (location.state as { from?: string } | null)?.from
      navigate(from && from !== '/login' ? from : homePath(seed.role), { replace: true })
    } catch (e) {
      toast.show({
        kind: 'error',
        title: '로그인할 수 없습니다',
        message: e instanceof Error ? e.message : '백엔드에서 사용자를 확인하지 못했습니다.',
      })
    } finally {
      setPending(null)
    }
  }

  return (
    <div className="login">
      <div className="login-head">
        <span className="brand-mark brand-mark-lg">AX</span>
        <h1>국방 R&amp;D 성과연계 · 이어달리기 AX</h1>
        <p>시연할 역할을 선택하세요. 로그인 후에도 상단에서 언제든 역할을 바꿀 수 있습니다.</p>
      </div>

      {(['ADMIN', 'WORKER'] as const).map((group) => (
        <div key={group} className="login-group">
          <h2>{group === 'ADMIN' ? '관리자' : '작업자'}</h2>
          <div className="login-grid">
            {SEED_USERS.filter((u) => ROLES[u.role].group === group).map((u) => {
              const meta = ROLES[u.role]
              return (
                <button key={u.id} className={`role-card role-card-${group.toLowerCase()}`}
                  disabled={pending != null} onClick={() => void choose(u.id)}>
                  <div className="role-card-top">
                    <span className="role-card-label">{meta.label}</span>
                    <code>{u.role}</code>
                  </div>
                  <div className="role-card-user">{u.name} · {u.department}</div>
                  <p>{meta.description}</p>
                  <ul>{meta.can.map((c) => <li key={c}>{c}</li>)}</ul>
                  <div className="role-card-foot">
                    {pending === u.id ? '확인 중…' : `X-User-Id: ${u.id} 로 로그인 →`}
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      ))}
      <p className="login-note">
        PoC 인증: 선택한 사용자 ID 가 모든 API 요청의 <code>X-User-Id</code> 헤더로 전송됩니다. 운영 시 SSO 로 교체됩니다.
      </p>
    </div>
  )
}
