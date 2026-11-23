import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { RequireRole } from './auth/RequireRole'
import { homePath, STAFF_ROLES, type RoleCode } from './auth/roles'
import { Layout } from './components/Layout'
import { ToastProvider } from './components/Toast'
import { AccessPage } from './pages/admin/AccessPage'
import { CriteriaPage } from './pages/admin/CriteriaPage'
import { VariablesPage } from './pages/admin/VariablesPage'
import { PromptsPage } from './pages/admin/PromptsPage'
import { AiCallsPage } from './pages/admin/AiCallsPage'
import { RegulationsPage } from './pages/admin/RegulationsPage'
import { RouteRulesPage } from './pages/admin/RouteRulesPage'
import { ServicePage } from './pages/admin/ServicePage'
import { AnnouncementReviewPage } from './pages/admin/AnnouncementReviewPage'
import { ConsultPage } from './pages/admin/ConsultPage'
import { ConsultReviewPage } from './pages/admin/ConsultReviewPage'
import { NavigatorSourcesPage } from './pages/admin/NavigatorSourcesPage'
import { NavigatorStaffPage } from './pages/admin/NavigatorStaffPage'
import { LoginPage } from './pages/LoginPage'
import { CompanyManagePage } from './pages/navigator/CompanyManagePage'
import { CompanyRegisterPage } from './pages/navigator/CompanyRegisterPage'
import { CompanySearchPage } from './pages/navigator/CompanySearchPage'
import { SubscriptionLinkPage } from './pages/navigator/SubscriptionLinkPage'

/** 화면별 허용 역할 */
function Only({ roles, children }: { roles: RoleCode[]; children: ReactNode }) {
  return <RequireRole roles={roles}>{children}</RequireRole>
}

/** 첫 화면: 로그인한 담당자는 담당자 화면, 그 밖에는 기업 화면 */
function Home() {
  const { role, restoring } = useAuth()
  if (restoring) return <div className="page-loading">로그인 정보를 확인하는 중…</div>
  return <Navigate to={role ? homePath(role) : '/navigator'} replace />
}

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            {/* 기업 화면: 로그인 없음 (사업자번호 · 이메일 확인 코드) */}
            <Route path="/navigator" element={<CompanySearchPage />} />
            <Route path="/navigator/register" element={<CompanyRegisterPage />} />
            <Route path="/navigator/manage" element={<CompanyManagePage />} />
            <Route path="/navigator/subscriptions/confirm" element={<SubscriptionLinkPage mode="confirm" />} />
            <Route path="/navigator/unsubscribe" element={<SubscriptionLinkPage mode="unsubscribe" />} />
            <Route path="/navigator/outreach/optout" element={<SubscriptionLinkPage mode="outreach-optout" />} />
            {/* 기관 담당자 화면: 로그인 */}
            <Route element={<RequireRole roles={STAFF_ROLES}><Layout /></RequireRole>}>
              <Route path="/staff/consult" element={<Only roles={['STAFF']}><ConsultPage /></Only>} />
              <Route path="/staff/consult/review" element={<Only roles={['STAFF', 'AX_ADMIN']}><ConsultReviewPage /></Only>} />
              <Route path="/staff/service" element={<ServicePage />} />
              <Route path="/staff/announcements" element={<Only roles={['STAFF', 'PROGRAM_OWNER']}><AnnouncementReviewPage /></Only>} />
              <Route path="/staff/route-rules" element={<RouteRulesPage />} />
              <Route path="/staff/criteria" element={<CriteriaPage />} />
              <Route path="/staff/variables" element={<VariablesPage />} />
              <Route path="/staff/regulations" element={<RegulationsPage />} />
              <Route path="/staff/access" element={<Only roles={['AX_ADMIN']}><AccessPage /></Only>} />
              <Route path="/staff/prompts" element={<PromptsPage />} />
              <Route path="/staff/ai-calls" element={<Only roles={['AX_ADMIN']}><AiCallsPage /></Only>} />
              <Route path="/staff/sources" element={<Only roles={['STAFF', 'PROGRAM_OWNER']}><NavigatorSourcesPage /></Only>} />
              <Route path="/staff/navigator" element={<Only roles={['STAFF']}><NavigatorStaffPage /></Only>} />
            </Route>
            <Route path="*" element={<Home />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ToastProvider>
  )
}
