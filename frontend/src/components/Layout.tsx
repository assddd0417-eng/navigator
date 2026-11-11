import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { canAccessPath, homePath, MENU, ROLES, SEED_USERS } from '../auth/roles'
import { useToast } from './Toast'

/** 상단 바(시연용 사용자 바꾸기) + 역할별 사이드 메뉴 */
export function Layout() {
  const { user, role, login, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const toast = useToast()
  if (!user || !role) return null

  const meta = ROLES[role]
  const menu = MENU.filter((m) => m.roles.includes(role))

  const switchUser = async (id: number) => {
    try {
      const me = await login(id)
      const next = SEED_USERS.find((u) => u.id === me.id)!
      toast.show({ kind: 'info', title: `${ROLES[next.role].label}(으)로 바꿨습니다`, message: `${me.name} 계정으로 보고 있습니다` })
      // 추천 상세처럼 새 역할도 볼 수 있는 화면이면 그대로 머물고, 아니면 새 역할의 첫 화면으로
      if (!canAccessPath(next.role, location.pathname)) navigate(homePath(next.role))
    } catch {
      toast.show({ kind: 'error', title: '사용자를 바꾸지 못했습니다', message: '서버에서 사용자를 확인하지 못했습니다.' })
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <NavLink to={homePath(role)} className="brand brand-link">
          <span className="brand-mark">AX</span>
          <span>국방 R&amp;D 성과연계 · 이어달리기</span>
        </NavLink>
        <div className="topbar-right">
          <label className="role-switcher" title="시연용: 다른 역할의 화면을 바로 확인할 수 있습니다">
            <span>사용자 바꾸기(시연)</span>
            <select value={user.id} onChange={(e) => void switchUser(Number(e.target.value))}>
              {SEED_USERS.map((u) => (
                <option key={u.id} value={u.id}>{ROLES[u.role].label} · {u.name}</option>
              ))}
            </select>
          </label>
          <button className="btn btn-ghost" onClick={() => { logout(); navigate('/login') }}>로그아웃</button>
        </div>
      </header>
      <div className="body">
        <nav className="sidebar">
          <div className={`whoami whoami-${meta.group.toLowerCase()}`}>
            <div className="whoami-name">{user.name}</div>
            <div className="whoami-role">{meta.label}</div>
          </div>
          {menu.map((m) => (
            <NavLink key={m.path} to={m.path} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <span className="nav-icon">{m.icon}</span>
              {m.label}
            </NavLink>
          ))}
          <div className="sidebar-can">
            <div className="sidebar-can-title">내가 할 수 있는 일</div>
            <ul>{meta.can.map((c) => <li key={c}>{c}</li>)}</ul>
          </div>
        </nav>
        <main className="content">
          {/* 사용자별로 다시 마운트: 같은 화면에서 역할을 바꿔도 새 사용자 권한으로 다시 조회한다 */}
          <Outlet key={user.id} />
        </main>
      </div>
    </div>
  )
}
