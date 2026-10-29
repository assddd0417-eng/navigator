import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { homePath, MENU, ROLES, SEED_USERS } from '../auth/roles'
import { useToast } from './Toast'

/** 상단 바(역할 즉시 전환) + 역할별 사이드 메뉴 */
export function Layout() {
  const { user, role, login, logout } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()
  if (!user || !role) return null

  const meta = ROLES[role]
  const menu = MENU.filter((m) => m.roles.includes(role))

  const switchUser = async (id: number) => {
    try {
      const me = await login(id)
      const next = SEED_USERS.find((u) => u.id === me.id)!
      toast.show({ kind: 'info', title: `${ROLES[next.role].label}(으)로 전환했습니다`, message: `${me.name} · X-User-Id: ${me.id}` })
      navigate(homePath(next.role))
    } catch {
      toast.show({ kind: 'error', title: '역할 전환 실패', message: '백엔드에서 사용자를 확인하지 못했습니다.' })
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">AX</span>
          <span>국방 R&amp;D 성과연계 · 이어달리기</span>
        </div>
        <div className="topbar-right">
          <span className={`group-chip group-${meta.group.toLowerCase()}`}>
            {meta.group === 'ADMIN' ? '관리자 화면' : '작업자 화면'}
          </span>
          <label className="role-switcher">
            <span>역할 전환</span>
            <select value={user.id} onChange={(e) => void switchUser(Number(e.target.value))}>
              {SEED_USERS.map((u) => (
                <option key={u.id} value={u.id}>
                  {ROLES[u.role].label} · {u.name} (ID {u.id})
                </option>
              ))}
            </select>
          </label>
          <button className="btn btn-ghost" onClick={() => { logout(); navigate('/login') }}>로그아웃</button>
        </div>
      </header>
      <div className="body">
        <nav className="sidebar">
          <div className="whoami">
            <div className="whoami-name">{user.name}</div>
            <div className="whoami-role">{meta.label}</div>
            <div className="whoami-header">X-User-Id: {user.id}</div>
          </div>
          {menu.map((m) => (
            <NavLink key={m.path} to={m.path} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <span className="nav-icon">{m.icon}</span>
              {m.label}
            </NavLink>
          ))}
          <div className="sidebar-can">
            <div className="sidebar-can-title">이 역할이 할 수 있는 일</div>
            <ul>{meta.can.map((c) => <li key={c}>{c}</li>)}</ul>
          </div>
        </nav>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
