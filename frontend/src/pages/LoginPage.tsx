import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { canAccessPath, homePath, ROLES, SEED_USERS, type RoleCode } from '../auth/roles'
import { useToast } from '../components/Toast'

/** 역할 선택형 로그인 (시연: 시드 사용자 1~4 중 하나를 고른다. 운영 시 기관 통합로그인으로 교체) */
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
        <h1>국방 R&amp;D 성과연계 · 이어달리기</h1>
        <p>끝난 R&amp;D 과제의 성과를 새로 필요한 기술과 이어 주고, 해외 수요와 비교해 부족한 부분을 찾습니다.</p>
        {from && from !== '/login' && <p className="notice small">로그인하면 보려던 화면으로 바로 이동합니다.</p>}
      </div>

      {(['ADMIN', 'WORKER'] as const).map((group) => (
        <div key={group} className="login-group">
          <h2>{group === 'ADMIN' ? '기획·검수 담당' : '실무 담당'}</h2>
          <div className="login-grid">
            {SEED_USERS.filter((u) => ROLES[u.role].group === group).map((u) => {
              const meta = ROLES[u.role]
              return (
                <button key={u.id} className={`role-card role-card-${group.toLowerCase()}`}
                  disabled={pending != null} onClick={() => void choose(u.id)}>
                  <div className="role-card-top">
                    <span className="role-card-label">{meta.label}</span>
                  </div>
                  <div className="role-card-user">{u.name} · {u.department}</div>
                  <p>{meta.description}</p>
                  <ul>{meta.can.map((c) => <li key={c}>{c}</li>)}</ul>
                  <div className="role-card-foot">
                    {pending === u.id ? '확인 중…' : `${meta.label}(으)로 시작하기 →`}
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      ))}
      <p className="login-note">
        시연용 화면입니다. 실제 운영에서는 기관 통합로그인으로 들어오고, 역할은 계정에 따라 정해집니다.
        <br /><Link to="/navigator">기업 사용자 화면(Navigator)으로 가기</Link>
      </p>
    </div>
  )
}
