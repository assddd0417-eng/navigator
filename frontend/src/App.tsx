import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { RequireRole } from './auth/RequireRole'
import { ADMIN_ROLES, ALL_ROLES, homePath, WORKER_ROLES } from './auth/roles'
import { Layout } from './components/Layout'
import { ToastProvider } from './components/Toast'
import { DashboardPage } from './pages/admin/DashboardPage'
import { ProjectsPage } from './pages/admin/ProjectsPage'
import { ReviewQueuePage } from './pages/admin/ReviewQueuePage'
import { LoginPage } from './pages/LoginPage'
import { RecommendationPage } from './pages/shared/RecommendationPage'
import { DocumentUploadPage } from './pages/worker/DocumentUploadPage'
import { MyTasksPage } from './pages/worker/MyTasksPage'

function Home() {
  const { role, restoring } = useAuth()
  if (restoring) return <div className="page-loading">로그인 정보를 확인하는 중…</div>
  return <Navigate to={role ? homePath(role) : '/login'} replace />
}

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<RequireRole roles={ALL_ROLES}><Layout /></RequireRole>}>
              {/* 관리자: PLANNER · DEPT_REVIEWER */}
              <Route path="/dashboard" element={<RequireRole roles={ADMIN_ROLES}><DashboardPage /></RequireRole>} />
              <Route path="/projects" element={<RequireRole roles={ADMIN_ROLES}><ProjectsPage /></RequireRole>} />
              <Route path="/reviews" element={<RequireRole roles={ADMIN_ROLES}><ReviewQueuePage /></RequireRole>} />
              {/* 작업자: CURATOR · EXPERT */}
              <Route path="/my-tasks" element={<RequireRole roles={WORKER_ROLES}><MyTasksPage /></RequireRole>} />
              <Route path="/documents/upload" element={<RequireRole roles={WORKER_ROLES}><DocumentUploadPage /></RequireRole>} />
              {/* 공통: 추천 상세·검수/의견 */}
              <Route path="/recommendations/:id" element={<RecommendationPage />} />
            </Route>
            <Route path="*" element={<Home />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ToastProvider>
  )
}
