import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { homePath, MENU, ROLES } from '../auth/roles'

/** 기관 담당자 화면 틀: 상단 바 + 메뉴 */
export function Layout() {
  const { user, role, logout } = useAuth()
  const navigate = useNavigate()
  if (!user || !role) return null

  const meta = ROLES[role]
  const menu = MENU.filter((m) => m.roles.includes(role))

  return (
    <div className="app-shell">
      <header className="topbar">
        <NavLink to={homePath(role)} className="brand brand-link">
          <span className="brand-mark">AX</span>
          <span>Navigator</span>
        </NavLink>
        <div className="topbar-right">
          <NavLink to="/navigator" className="topbar-link">기업 화면</NavLink>
          <button className="btn btn-ghost" onClick={() => { logout(); navigate('/login') }}>로그아웃</button>
        </div>
      </header>
      <div className="body">
        <nav className="sidebar">
          <div className="whoami whoami-admin">
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
            <div className="sidebar-can-title">할 수 있는 일</div>
            <ul>{meta.can.map((c) => <li key={c}>{c}</li>)}</ul>
          </div>
        </nav>
        <main className="content">
          <Outlet key={user.id} />
        </main>
      </div>
    </div>
  )
}
