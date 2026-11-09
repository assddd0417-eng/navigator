// Navigator API. 기업 쪽은 X-User-Id 없이 호출하고, 관리 링크 토큰은 X-Manage-Token 으로 보냄
import { api } from './client'

export type Verdict = 'ELIGIBLE' | 'NEEDS_INFO' | 'INELIGIBLE'
export type CheckResult = 'MET' | 'UNMET' | 'UNKNOWN'

export const VERDICT_LABELS: Record<Verdict, string> = { ELIGIBLE: '적합', NEEDS_INFO: '정보부족', INELIGIBLE: '부적격' }
export const VERDICT_TONES: Record<Verdict, string> = { ELIGIBLE: 'ok', NEEDS_INFO: 'warn', INELIGIBLE: 'bad' }
export const CRITERION_LABELS: Record<string, string> = {
  TECH: '기술 적합도', IPC: '특허 분류 일치', PURPOSE: '사업목적', PREFERENCE: '우대 요건',
}
export const SIZE_LABELS: Record<string, string> = {
  LARGE: '대기업', MIDSIZE: '중견기업', SME: '중소기업', STARTUP: '창업기업', VENTURE: '벤처기업',
}
export const REGIONS = ['서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종', '경기',
  '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주'] as const
export const CERT_TYPES: Record<string, string> = {
  VENTURE: '벤처기업 확인', INNOBIZ: '이노비즈', MAINBIZ: '메인비즈', RND_LAB: '기업부설연구소',
  RND_DEPT: '연구개발전담부서', ISO9001: 'ISO 9001', AS9100: 'AS9100', DEFENSE_COMPANY: '방산업체 지정',
  DEFENSE_QMS: '국방품질경영체제 인증', SME_CONFIRM: '중소기업 확인', OTHER: '기타',
}

export interface ScoreItem {
  score: number
  weight: number
  method: string
  detail: Record<string, unknown>
}

export interface EligibilityCheck {
  requirement_id: number
  req_type_code: string
  req_type_name: string
  description: string
  is_mandatory: boolean
  mandatory_label: string
  result: CheckResult | null      // 공개 조회에서 가린 요건은 null
  result_label: string
  reason: string
  question: string | null
  self_declared: boolean
  source_quote: string | null
  source_page: number | null
}

export interface MatchEvidence {
  kind: 'TECH_MATCH' | 'IPC_MATCH' | 'REQUIREMENT'
  company_source_table: string | null
  company_text: string | null
  tech_name: string | null
  requirement_id: number | null
  quote: string | null
  page: number | null
  similarity: number | string | null
}

export interface MatchRec {
  id: number
  rank: number
  organization_id: number
  company_name: string
  business_reg_no?: string
  announcement_id: number
  announcement_no: string
  announcement_title: string
  agency_name: string
  receipt_end: string | null
  receipt_state: string
  total_score: number
  verdict: Verdict
  verdict_label: string
  mandatory_met: number
  mandatory_total: number
  preferred_met: number
  preferred_total: number
  rationale: string
  scores: Record<string, ScoreItem>
  checks: EligibilityCheck[]
  questions: { requirement_id: number; question: string }[]
  evidence: MatchEvidence[]
  hidden_requirements?: number
}

export interface MatchRun {
  run: { id: number; direction: string; announcement_id: number | null; organization_id: number | null;
    created_at: string; model: string; candidate_count: number; requested_via: string } | null
  summary: Record<Verdict, number>
  recommendations: MatchRec[]
}

export interface Patent {
  id?: number
  application_no: string
  registration_no: string | null
  title: string
  ipc_codes: string[]
  status: string
  applied_on: string | null
  registered_on: string | null
  origin?: string
  is_verified?: boolean
}

export interface PublicProfile {
  visibility: 'PUBLIC'
  business_reg_no: string
  company_name: string
  biz_verify_status: string
  biz_verify_label: string
  business_status_label: string
  patents: Patent[]
  note: string
}

export interface Certification {
  id: number
  cert_type_code: string
  cert_type_name: string
  cert_no: string | null
  issuer: string | null
  issued_on: string | null
  expires_on: string | null
  is_expired: boolean
  origin: string
  is_verified: boolean
}

export interface CreditRating {
  id: number
  agency: string
  grade: string
  rated_on: string | null
  valid_until: string | null
  origin: string
  is_verified: boolean
}

export interface RndHistory {
  id: number
  project_no: string | null
  title: string
  funding_agency: string | null
  start_date: string | null
  end_date: string | null
  amount_krw: number | null
  role: 'LEAD' | 'PARTICIPANT'
  summary: string | null
  internal_project_title: string | null
  origin: string
  is_verified: boolean
}

export interface FullProfile {
  visibility: 'OWNER' | 'STAFF'
  organization_id: number
  business_reg_no: string
  company_name: string
  representative_name: string | null
  opened_on: string | null
  main_business: string | null
  homepage: string | null
  company_size: string | null
  established_on: string | null
  employee_count: number | null
  annual_revenue_krw: number | null
  revenue_year: number | null
  region: string | null
  address: string | null
  is_defense_company: boolean
  business_status_label: string
  biz_verify_label: string
  registered_email: string | null
  patents: Patent[]
  certifications: Certification[]
  credit_ratings: CreditRating[]
  rnd_history: RndHistory[]
  field_sources: { field_name: string; preferred_value: unknown; any_verified: boolean; differs: boolean }[]
  access_link?: { expires_at: string }
}

export interface ProfileUpdate {
  company_name?: string
  main_business?: string | null
  homepage?: string | null
  company_size?: string | null
  established_on?: string | null
  employee_count?: number | null
  annual_revenue_krw?: number | null
  revenue_year?: number | null
  region?: string | null
  address?: string | null
  certifications?: { cert_type_code: string; cert_no?: string | null; issued_on?: string | null; expires_on?: string | null }[]
  credit_ratings?: { agency: string; grade: string; rated_on?: string | null; valid_until?: string | null }[]
  rnd_history?: { title: string; project_no?: string | null; funding_agency?: string | null; start_date?: string | null;
    end_date?: string | null; role: 'LEAD' | 'PARTICIPANT'; summary?: string | null }[]
}

export interface CompanyRegister {
  business_reg_no: string
  company_name: string
  representative_name: string
  opened_on: string
  email: string
  main_business?: string | null
  company_size?: string | null
  employee_count?: number | null
  region?: string | null
}

export interface LinkSent {
  sent_to: string
  expires_at: string
  dev_management_link: string | null
}

export interface RegisterResult extends LinkSent {
  organization_id: number
  business_reg_no: string
  biz_verify_label: string
  business_status: string
  message: string
}

export interface Question {
  requirement_id: number
  announcement_id: number
  announcement_title: string
  requirement: string
  mandatory_label: string
  question: string
  answer_type: 'integer' | 'boolean'
}

// 기업
const anon = { anonymous: true } as const
const manage = (token: string) => ({ anonymous: true, headers: { 'X-Manage-Token': token } })
const bizno = (v: string) => encodeURIComponent(v.replace(/[^0-9]/g, ''))

export const getPublicCompany = (brn: string) =>
  api<PublicProfile>(`/navigator/companies/${bizno(brn)}`, { ...anon, silent: true })
export const getPublicMatches = (brn: string) =>
  api<MatchRun>(`/navigator/companies/${bizno(brn)}/matches`, anon)
export const requestAccessLink = (brn: string) =>
  api<LinkSent>(`/navigator/companies/${bizno(brn)}/access-link`, { ...anon, method: 'POST' })
export const registerCompany = (body: CompanyRegister) =>
  api<RegisterResult>('/navigator/companies', { ...anon, method: 'POST', body })

export const getMyProfile = (token: string) =>
  api<FullProfile>('/navigator/manage/profile', { ...manage(token), silent: true })
export const updateMyProfile = (token: string, body: ProfileUpdate) =>
  api<FullProfile>('/navigator/manage/profile', { ...manage(token), method: 'PATCH', body })
export const getMyMatches = (token: string, query: { include_closed?: boolean; refresh?: boolean } = {}) =>
  api<MatchRun>('/navigator/manage/matches', { ...manage(token), method: 'POST', query })
export const getMyQuestions = (token: string) =>
  api<{ run_id: number; questions: Question[] }>('/navigator/manage/questions', manage(token))
export const answerQuestions = (token: string, answers: { requirement_id: number; value: number | boolean }[]) =>
  api<MatchRun>('/navigator/manage/answers', { ...manage(token), method: 'POST', body: { answers } })

// 담당자
export interface AnnouncementRow {
  id: number
  announcement_no: string
  title: string
  agency_name: string
  program_name: string | null
  receipt_start: string | null
  receipt_end: string | null
  status: string
  receipt_state: string
  receipt_state_label: string
  requirement_count: number
  mandatory_count: number
  tech_need_count: number
}

export const listAnnouncements = (query: { receipt_state?: string; q?: string } = {}) =>
  api<AnnouncementRow[]>('/navigator/announcements', { query: { limit: 200, ...query } })
export const latestAnnouncementRun = (annId: number) =>
  api<MatchRun>(`/navigator/matching/announcements/${annId}`)
export const runAnnouncementMatching = (annId: number) =>
  api<MatchRun>(`/navigator/matching/announcements/${annId}`, { method: 'POST' })
export const staffCompanyProfile = (orgId: number) =>
  api<FullProfile>(`/navigator/matching/companies/${orgId}/profile`)
