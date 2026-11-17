import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { RequireRole } from './auth/RequireRole'
import { ADMIN_ROLES, ALL_ROLES, homePath, PLANNING_ROLES, PORTFOLIO_ROLES, WORKER_ROLES } from './auth/roles'
import { Layout } from './components/Layout'
import { ToastProvider } from './components/Toast'
import { DashboardPage } from './pages/admin/DashboardPage'
import { ProjectsPage } from './pages/admin/ProjectsPage'
import { ReviewQueuePage } from './pages/admin/ReviewQueuePage'
import { NavigatorSourcesPage } from './pages/admin/NavigatorSourcesPage'
import { AnnouncementReviewPage } from './pages/admin/AnnouncementReviewPage'
import { NavigatorStaffPage } from './pages/admin/NavigatorStaffPage'
import { LoginPage } from './pages/LoginPage'
import { CompanyManagePage } from './pages/navigator/CompanyManagePage'
import { CompanyRegisterPage } from './pages/navigator/CompanyRegisterPage'
import { CompanySearchPage } from './pages/navigator/CompanySearchPage'
import { SubscriptionLinkPage } from './pages/navigator/SubscriptionLinkPage'
import { GapDetailPage } from './pages/gaps/GapDetailPage'
import { GapListPage } from './pages/gaps/GapListPage'
import { PlanningPage } from './pages/planning/PlanningPage'
import { PortfolioPage } from './pages/portfolio/PortfolioPage'
import { ReviewSheetDetailPage } from './pages/review/ReviewSheetDetailPage'
import { ReviewSheetsPage } from './pages/review/ReviewSheetsPage'
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
            {/* Navigator 기업 화면: 로그인 없음 (사업자번호 · 관리 링크) */}
            <Route path="/navigator" element={<CompanySearchPage />} />
            <Route path="/navigator/register" element={<CompanyRegisterPage />} />
            <Route path="/navigator/manage" element={<CompanyManagePage />} />
            <Route path="/navigator/subscriptions/confirm" element={<SubscriptionLinkPage mode="confirm" />} />
            <Route path="/navigator/unsubscribe" element={<SubscriptionLinkPage mode="unsubscribe" />} />
            <Route path="/navigator/outreach/optout" element={<SubscriptionLinkPage mode="outreach-optout" />} />
            <Route element={<RequireRole roles={ALL_ROLES}><Layout /></RequireRole>}>
              {/* 관리자: PLANNER · DEPT_REVIEWER */}
              <Route path="/dashboard" element={<RequireRole roles={ADMIN_ROLES}><DashboardPage /></RequireRole>} />
              <Route path="/projects" element={<RequireRole roles={ADMIN_ROLES}><ProjectsPage /></RequireRole>} />
              <Route path="/reviews" element={<RequireRole roles={ADMIN_ROLES}><ReviewQueuePage /></RequireRole>} />
              <Route path="/review-sheets" element={<RequireRole roles={ADMIN_ROLES}><ReviewSheetsPage /></RequireRole>} />
              <Route path="/review-sheets/:id" element={<RequireRole roles={ADMIN_ROLES}><ReviewSheetDetailPage /></RequireRole>} />
              <Route path="/staff/announcements" element={<RequireRole roles={ADMIN_ROLES}><AnnouncementReviewPage /></RequireRole>} />
              <Route path="/staff/navigator" element={<RequireRole roles={ADMIN_ROLES}><NavigatorStaffPage /></RequireRole>} />
              <Route path="/staff/sources" element={<RequireRole roles={ADMIN_ROLES}><NavigatorSourcesPage /></RequireRole>} />
              {/* 기관 포트폴리오: 관리자 + 기관 열람자(VIEWER). 넘기기는 PLANNER 만 — 서버가 판단 */}
              <Route path="/planning" element={<RequireRole roles={PLANNING_ROLES}><PlanningPage /></RequireRole>} />
              <Route path="/portfolio" element={<RequireRole roles={PORTFOLIO_ROLES}><PortfolioPage /></RequireRole>} />
              {/* 작업자: CURATOR · EXPERT */}
              <Route path="/my-tasks" element={<RequireRole roles={WORKER_ROLES}><MyTasksPage /></RequireRole>} />
              <Route path="/documents/upload" element={<RequireRole roles={WORKER_ROLES}><DocumentUploadPage /></RequireRole>} />
              {/* 공통: 추천 상세·검수/의견 */}
              <Route path="/recommendations/:id" element={<RecommendationPage />} />
              {/* 공통: 해외 수요 갭 분석 (재실행 PLANNER·CURATOR, 확정·기각 DEPT_REVIEWER — 서버가 판단) */}
              <Route path="/gaps" element={<GapListPage />} />
              <Route path="/gaps/:id" element={<GapDetailPage />} />
            </Route>
            <Route path="*" element={<Home />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ToastProvider>
  )
}
