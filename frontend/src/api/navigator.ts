// Navigator API. 기업 쪽은 X-User-Id 없이 호출하고, 관리 링크 토큰은 X-Manage-Token 으로 보냄
import { api } from './client'

export type Verdict = 'ELIGIBLE' | 'NEEDS_INFO' | 'INELIGIBLE'
export type CheckResult = 'MET' | 'UNMET' | 'UNKNOWN'

export const VERDICT_LABELS: Record<Verdict, string> = { ELIGIBLE: '적합', NEEDS_INFO: '확인 필요', INELIGIBLE: '부적격' }
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

export interface NextRound { id: number; title: string; receipt_state: string; receipt_start: string | null; receipt_end: string | null }
export interface PastMatchRec extends MatchRec { next_round: NextRound | null; participated: boolean }
export interface PastMatchRun extends Omit<MatchRun, 'recommendations'> { recommendations: PastMatchRec[]; closed_since: string }

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
  company_evidence_id: number | null
  origin: string
  is_verified: boolean
}

export interface CreditRating {
  id: number
  agency: string
  grade: string
  rated_on: string | null
  valid_until: string | null
  company_evidence_id: number | null
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
  tax_delinquent: boolean | null
  insolvent: boolean | null
  rnd_restricted: boolean | null
  procurement_sanctioned: boolean | null
  defense_goods: boolean | null
  military_supply_krw: number | null
  export_krw: number | null
  export_year: number | null
  business_status_label: string
  biz_verify_label: string
  registered_email: string | null
  patents: Patent[]
  certifications: Certification[]
  credit_ratings: CreditRating[]
  rnd_history: RndHistory[]
  products: Product[]
  technologies: Technology[]
  support_history: SupportHistory[]
  evidence: Evidence[]
  field_sources: { field_name: string; preferred_value: unknown; any_verified: boolean; differs: boolean }[]
  radar: Radar
  outreach_consent_at?: string | null
  access_link?: { expires_at: string }
}

export type RadarAxis = { code: string; label: string; note: string; value: number | null; average: number | null; level_label?: string }
export type Radar = { axes: RadarAxis[]; company_count: number }

export type ProductCategory = 'WEAPON_SYSTEM' | 'COMPONENT' | 'MATERIAL' | 'SOFTWARE' | 'EQUIPMENT' | 'SERVICE' | 'OTHER'
export const PRODUCT_CATEGORIES: Record<ProductCategory, string> = {
  WEAPON_SYSTEM: '무기체계', COMPONENT: '부품·구성품', MATERIAL: '소재', SOFTWARE: '소프트웨어', EQUIPMENT: '장비', SERVICE: '서비스', OTHER: '기타',
}
export type SupportResult = 'APPLIED' | 'SELECTED' | 'COMPLETED' | 'SUCCESS' | 'FAILED'
export const SUPPORT_RESULTS: Record<SupportResult, string> = {
  APPLIED: '신청', SELECTED: '선정', COMPLETED: '수행 완료', SUCCESS: '성공 판정', FAILED: '탈락·실패',
}
export interface Product { id: number; name: string; category: ProductCategory; description: string | null; is_defense: boolean; customers: string | null; origin: string }
export interface Technology { id: number; tech_name: string; description: string | null; trl: number | null; origin: string }
export interface SupportHistory { id: number; program_name: string; agency: string | null; year: number | null; result: SupportResult; amount_krw: number | null; summary: string | null; origin: string }
export interface Evidence {
  id: number
  file_name: string
  parse_status: 'PARSED' | 'UNSUPPORTED' | 'FAILED'
  parse_note: string | null
  detected_kind: 'CERTIFICATION' | 'CREDIT_RATING' | 'UNKNOWN' | null
  detected: Record<string, string>
  created_at: string
  text_excerpt?: string | null
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
  tax_delinquent?: boolean | null
  insolvent?: boolean | null
  rnd_restricted?: boolean | null
  procurement_sanctioned?: boolean | null
  defense_goods?: boolean | null
  military_supply_krw?: number | null
  export_krw?: number | null
  export_year?: number | null
  certifications?: { cert_type_code: string; cert_no?: string | null; issued_on?: string | null; expires_on?: string | null; company_evidence_id?: number | null }[]
  credit_ratings?: { agency: string; grade: string; rated_on?: string | null; valid_until?: string | null; company_evidence_id?: number | null }[]
  products?: { name: string; category: ProductCategory; description?: string | null; is_defense: boolean; customers?: string | null }[]
  technologies?: { tech_name: string; description?: string | null; trl?: number | null }[]
  support_history?: { program_name: string; agency?: string | null; year?: number | null; result: SupportResult; amount_krw?: number | null; summary?: string | null }[]
  rnd_history?: { title: string; project_no?: string | null; funding_agency?: string | null; start_date?: string | null;
    end_date?: string | null; role: 'LEAD' | 'PARTICIPANT'; summary?: string | null }[]
}

export interface CompanyRegister extends ProfileUpdate {
  business_reg_no: string
  company_name: string
  representative_name: string
  opened_on: string
  email: string
}

export interface LinkSent {
  sent_to: string
  expires_at: string
  dev_management_link: string | null
}

export interface RegisterResult extends LinkSent {
  organization_id: number
  manage_token: string
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

export const getFitLevels = () =>
  api<{ embedder: string; high: number; mid: number }>('/navigator/fit-levels', { ...anon, silent: true })
export const getPublicCompany = (brn: string) =>
  api<PublicProfile>(`/navigator/companies/${bizno(brn)}`, { ...anon, silent: true })
export const getPublicMatches = (brn: string) =>
  api<MatchRun>(`/navigator/companies/${bizno(brn)}/matches`, anon)
export const requestAccessLink = (brn: string) =>
  api<LinkSent>(`/navigator/companies/${bizno(brn)}/access-link`, { ...anon, method: 'POST' })
export const sendLoginCode = (brn: string) =>
  api<{ sent_to: string; expires_at: string; dev_code?: string }>(`/navigator/companies/${bizno(brn)}/login-code`,
    { ...anon, method: 'POST', silent: true })
export const loginWithCode = (brn: string, code: string) =>
  api<{ token: string; expires_at: string }>(`/navigator/companies/${bizno(brn)}/login`,
    { ...anon, method: 'POST', body: { code }, silent: true })
export interface AutofillResult { source: string; label: string; ok: boolean; error: string | null; counts: Record<string, number> }
export const uploadEvidence = (token: string, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api<Evidence>('/navigator/manage/evidence', { ...manage(token), method: 'POST', body: form })
}
export const deleteEvidence = (token: string, id: number) =>
  api<void>(`/navigator/manage/evidence/${id}`, { ...manage(token), method: 'DELETE' })
export const autofillProfile = (token: string) =>
  api<{ results: AutofillResult[]; profile: FullProfile }>('/navigator/manage/autofill', { ...manage(token), method: 'POST' })
export const registerCompany = (body: CompanyRegister) =>
  api<RegisterResult>('/navigator/companies', { ...anon, method: 'POST', body })

export const getMyProfile = (token: string) =>
  api<FullProfile>('/navigator/manage/profile', { ...manage(token), silent: true })
export const updateMyProfile = (token: string, body: ProfileUpdate) =>
  api<FullProfile>('/navigator/manage/profile', { ...manage(token), method: 'PATCH', body })
export const getMyMatches = (token: string, query: { include_closed?: boolean; refresh?: boolean } = {}) =>
  api<MatchRun>('/navigator/manage/matches', { ...manage(token), method: 'POST', query })
export const getMyPastMatches = (token: string, query: { refresh?: boolean } = {}) =>
  api<PastMatchRun>('/navigator/manage/past-matches', { ...manage(token), method: 'POST', query })
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
  source_kind?: string
  posted_on?: string | null
  attachment_count?: number
  requirements_confirmed_at?: string | null
}

export const listAnnouncements = (query: { receipt_state?: string; q?: string; review?: 'PENDING' | 'DONE' } = {}) =>
  api<AnnouncementRow[]>('/navigator/announcements', { query: { limit: 200, ...query } })
export const latestAnnouncementRun = (annId: number) =>
  api<MatchRun>(`/navigator/matching/announcements/${annId}`)
export const runAnnouncementMatching = (annId: number) =>
  api<MatchRun>(`/navigator/matching/announcements/${annId}`, { method: 'POST' })
export const staffCompanyProfile = (orgId: number) =>
  api<FullProfile>(`/navigator/matching/companies/${orgId}/profile`)

// 알림
export type AlertChannel = 'SCREEN' | 'EMAIL'

export interface Subscription {
  id: number
  email: string
  keywords: string[]
  min_score: number
  include_needs_info: boolean
  channels: AlertChannel[]
  is_active: boolean
  email_confirmed_at: string | null
  unsubscribed_at: string | null
  confirm_expires_at: string | null
  created_at: string
  confirm_sent?: boolean
  dev_confirm_link?: string | null
}

export interface SubscriptionInput {
  email?: string
  keywords?: string[]
  min_score?: number
  include_needs_info?: boolean
  channels?: AlertChannel[]
  is_active?: boolean
}

export interface AlertItem {
  announcement_id: number
  announcement_title: string
  agency_name: string
  receipt_end: string | null
  receipt_state: string
  verdict: Verdict
  verdict_label: string
  total_score: number
  rationale: string
  created_at: string
  is_read: boolean
}

export interface AnnouncementAlerts {
  subscribed_companies: number
  notifications: { id: number; company_name: string; email: string; verdict: Verdict; verdict_label: string; total_score: number;
    status: 'PENDING' | 'SENT' | 'FAILED' | 'READ'; created_at: string; sent_at: string | null;
    read_at: string | null; channels: AlertChannel[] }[]
}

export const getMySubscriptions = (token: string) =>
  api<{ registered_email: string; max: number; subscriptions: Subscription[] }>(
    '/navigator/manage/subscriptions', manage(token))
export const addSubscription = (token: string, body: SubscriptionInput) =>
  api<Subscription>('/navigator/manage/subscriptions', { ...manage(token), method: 'POST', body })
export const updateSubscription = (token: string, id: number, body: SubscriptionInput) =>
  api<Subscription>(`/navigator/manage/subscriptions/${id}`, { ...manage(token), method: 'PATCH', body })
export const deleteSubscription = (token: string, id: number) =>
  api<void>(`/navigator/manage/subscriptions/${id}`, { ...manage(token), method: 'DELETE' })
export const resendConfirm = (token: string, id: number) =>
  api<Subscription>(`/navigator/manage/subscriptions/${id}/confirm-mail`, { ...manage(token), method: 'POST' })
export const getMyAlerts = (token: string) =>
  api<{ unread: number; alerts: AlertItem[] }>('/navigator/manage/alerts', manage(token))
export const markAlertsRead = (token: string, announcement_ids?: number[]) =>
  api<void>('/navigator/manage/alerts/read', { ...manage(token), method: 'POST', body: { announcement_ids } })
export const confirmSubscription = (token: string) =>
  api<{ company_name: string; email: string }>('/navigator/subscriptions/confirm',
    { ...anon, method: 'POST', body: { token }, silent: true })
export const unsubscribeAlerts = (token: string) =>
  api<{ company_name: string; email: string }>('/navigator/subscriptions/unsubscribe',
    { ...anon, method: 'POST', body: { token }, silent: true })
export const setOutreachConsent = (token: string, consent: boolean) =>
  api<{ outreach_consent: boolean; outreach_consent_at: string | null }>('/navigator/manage/outreach-consent',
    { ...manage(token), method: 'PUT', body: { consent } })
export const outreachOptout = (token: string) =>
  api<{ company_name: string; email: string }>('/navigator/outreach/optout', { ...anon, method: 'POST', body: { token }, silent: true })

// 참여 권유 (담당자)
export interface OutreachCompany {
  recommendation_id: number
  organization_id: number
  company_name: string
  verdict: Verdict
  verdict_label: string
  total_score: number
  rank: number
  consent: boolean
  has_email: boolean
  sendable: boolean
  sent_status: 'PENDING' | 'SENT' | 'FAILED' | null
  sent_at: string | null
  sent_error: string | null
}
export interface OutreachCandidates { announcement_id: number; match_run_id: number | null; open: boolean; companies: OutreachCompany[] }
export interface OutreachResult {
  sent: number
  failed: number
  skipped: { organization_id: number; company_name: string | null; reason: string; reason_label: string }[]
  candidates: OutreachCandidates
}
export const getOutreach = (annId: number) =>
  api<OutreachCandidates>(`/navigator/matching/announcements/${annId}/outreach`)
export const sendOutreach = (annId: number, organization_ids: number[], note: string) =>
  api<OutreachResult>(`/navigator/matching/announcements/${annId}/outreach`, { method: 'POST', body: { organization_ids, note } })

export const getAnnouncementAlerts = (annId: number) =>
  api<AnnouncementAlerts>(`/navigator/alerts/announcements/${annId}`)
export const dispatchAnnouncementAlerts = (annId: number) =>
  api<{ notifications: number; emails_sent: number; emails_failed: number }>(
    `/navigator/alerts/announcements/${annId}`, { method: 'POST' })

// 외부 수집 (담당자)
export interface SourceRow {
  id: number
  code: string
  name: string
  provider: string | null
  data_kind: string
  fetch_interval: string | null
  requires_key: boolean
  is_paid: boolean
  is_active: boolean
  notes: string | null
  implemented: boolean
  mode: 'mock' | 'live' | null
  per_company: boolean
  auto_minutes: number
  last_job_id: number | null
  last_status: 'RUNNING' | 'SUCCEEDED' | 'FAILED' | null
  last_started_at: string | null
  last_finished_at: string | null
  last_records: number | null
  last_error: string | null
  last_result: Record<string, number> | null
  last_mode: string | null
  next_due_at: string | null
}

export interface FetchJob {
  id: number
  source: string
  organization_id: number | null
  company_name: string | null
  mode: string
  trigger_kind: 'ON_DEMAND' | 'SCHEDULED' | 'REGISTRATION'
  status: 'RUNNING' | 'SUCCEEDED' | 'FAILED'
  records_count: number
  error_message: string | null
  result: Record<string, number> | null
  started_at: string
  finished_at: string | null
}

export interface RunResult {
  job_id: number
  source: string
  mode: string
  status: 'SUCCEEDED' | 'FAILED'
  error: string | null
  counts: Record<string, number>
}

export const listSources = () => api<SourceRow[]>('/navigator/sources')
export const listFetchJobs = (source?: string) =>
  api<FetchJob[]>('/navigator/sources/jobs', { query: { source, limit: 50 } })
export const runSource = (code: string, organizationId?: number) =>
  api<RunResult>(`/navigator/sources/${code}/run`, { method: 'POST', query: { organization_id: organizationId } })

// 공고 등록·조건 확인
export interface ReqDraft {
  req_type_code: string
  rule: Record<string, unknown>
  is_mandatory: boolean
  description: string
  source_quote: string | null
  quote_found?: boolean
  origin?: 'MANUAL' | 'AI_EXTRACTED'
  bonus_points?: number | null
}
export interface TechDraft { tech_name: string; description?: string | null; is_core: boolean }
export interface AnnFields {
  receipt_start?: string | null
  receipt_end?: string | null
  support_amount_krw?: number | null
  support_period_months?: number | null
  target_desc?: string | null
  summary?: string | null
  company_burden?: string | null
  submit_documents?: SubmitDoc[] | null
}
export interface SubmitDoc { name: string; required: boolean }
export type EvalKind = 'CAPABILITY' | 'PURPOSE' | 'APPLICATION'
export interface EvalItem {
  name: string
  points: number
  kind: EvalKind
  areas: string[]
  source_quote?: string | null
  source_page?: number | null
}
export interface Extraction {
  extractor: string
  fields: AnnFields
  requirements: ReqDraft[]
  tech_needs: TechDraft[]
  warnings: string[]
}
export interface AnnSource {
  announcement_id: number
  body_text: string | null
  attachments: { id: number | null; file_name: string; file_ext: string | null; parse_status: string; parse_note: string | null; text_content: string | null; source_url: string | null }[]
}
export interface AnnDetail extends AnnouncementRow {
  support_amount_krw: number | null
  support_period_months: number | null
  target_desc: string | null
  summary: string | null
  source_url: string | null
  requirements: (ReqDraft & { id: number; req_type_name: string })[]
  tech_needs: (TechDraft & { id: number })[]
  eval_items: EvalItem[]
  company_burden: string | null
  submit_documents: SubmitDoc[] | null
}
export interface RequirementTypes {
  types: { code: string; name_ko: string; rule_example: Record<string, unknown>; description: string | null }[]
  certifications: { code: string; name_ko: string }[]
}

export const getAnnouncement = (id: number) => api<AnnDetail>(`/navigator/announcements/${id}`)
export const getAnnouncementSource = (id: number) => api<AnnSource>(`/navigator/announcements/${id}/source`)
export const extractRequirements = (id: number) =>
  api<Extraction>(`/navigator/announcements/${id}/extract`, { method: 'POST' })
export const getRequirementTypes = () => api<RequirementTypes>('/navigator/announcements/requirement-types')
export const saveReview = (id: number, body: { fields: AnnFields; requirements: ReqDraft[]; tech_needs: TechDraft[]; eval_items?: EvalItem[]; confirm: boolean; publish: boolean }) =>
  api<void>(`/navigator/announcements/${id}/review`, { method: 'PUT', body })
/** 공고문 파일(PDF·TXT)을 올려 작성 중 공고를 만든다. 조건 뽑기는 올린 글자로 한다 */
export const uploadAnnouncement = (file: File, f: { title?: string; agency_name: string; announcement_no: string }) => {
  const form = new FormData()
  form.append('file', file)
  form.append('agency_name', f.agency_name)
  form.append('announcement_no', f.announcement_no)
  if (f.title) form.append('title', f.title)
  return api<{ id: number; chunk_count?: number; warnings?: string[] }>('/navigator/announcements/upload', { method: 'POST', body: form })
}
export const createAnnouncementFromText = (body: { title: string; agency_name?: string; announcement_no?: string; body_text: string; source_url?: string; posted_on?: string }) =>
  api<{ id: number }>('/navigator/announcements/text', { method: 'POST', body })

// D-STATE 성장준비도 진단
export type DstateValueType = 'LEVEL' | 'INTEGER' | 'PROFILE'
export interface DstateVariable {
  code: string
  name: string
  definition: string
  value_type: DstateValueType
  options: { code: string; label: string }[]
  areas: string[]
  areas_label: string[]
  source_desc: string
  question: string
  value: string | number | null
  display: string | null
  source: 'PROFILE' | 'CERT' | 'SELF' | 'STAFF' | null
  source_label: string | null
  checked_on: string | null
  missing: boolean
}
export interface DstateArea {
  code: string
  label: string
  score: number
  base: number
  items: { variable: string; points: number }[]
  missing: string[]
  formula: string
}
export interface DstateNote { area: string; label: string; score: number; text: string }
export interface DstatePrevious {
  diagnosis_id: number
  total_score: number
  state_type: string
  state_label: string
  scores: Record<string, number>
  created_at: string
}
export interface DstateResult {
  rule_version: string
  as_of: string
  organization_id: number
  company_name: string
  total_score: number
  state_type: string
  state_label: string
  weakest_area: string
  weakest_label: string
  areas: DstateArea[]
  strengths: DstateNote[]
  tasks: DstateNote[]
  missing: string[]
  summary: string
  variables: DstateVariable[]
  diagnosis_id: number | null
  created_at?: string
  previous: DstatePrevious | null
}
export interface ConsultCompany {
  organization_id: number
  name: string
  business_reg_no: string | null
  company_size: string | null
  main_business: string | null
  region: string | null
  business_status: string | null
  last_diagnosed_at: string | null
}
export interface DstateRules {
  rule_version: string
  areas: { code: string; label: string; formula: string }[]
  state_types: { code: string; label: string; condition: string }[]
}
export interface DiagnosisHistoryRow {
  id: number
  total_score: number
  state_type: string
  state_label: string
  weakest_area: string
  weakest_label: string | null
  scores: Record<string, number>
  missing: string[]
  created_at: string
  created_by_name: string | null
}
export type DstateValues = Record<string, string | number | null>

export const searchConsultCompanies = (q: string) =>
  api<ConsultCompany[]>('/navigator/consult/companies', { query: { q } })
export const getDstateRules = () => api<DstateRules>('/navigator/consult/dstate/rules')
export const previewDstate = (orgId: number) => api<DstateResult>(`/navigator/consult/companies/${orgId}/dstate`)
export const runDstate = (orgId: number) =>
  api<DstateResult>(`/navigator/consult/companies/${orgId}/dstate`, { method: 'POST' })
export const saveStaffDstateValues = (orgId: number, values: DstateValues) =>
  api<DstateResult>(`/navigator/consult/companies/${orgId}/dstate/values`, { method: 'PUT', body: { values } })
export const getDiagnosisHistory = (orgId: number) =>
  api<DiagnosisHistoryRow[]>(`/navigator/consult/companies/${orgId}/diagnoses`)

export interface MyDstate { variables: DstateVariable[]; missing: string[] }
export const getMyDstate = (token: string) => api<MyDstate>('/navigator/manage/dstate', manage(token))
export const saveMyDstate = (token: string, values: DstateValues) =>
  api<MyDstate>('/navigator/manage/dstate', { ...manage(token), method: 'PUT', body: { values } })

// 자격요건 검토 (상담 업무 B)
export type Tone = 'ok' | 'warn' | 'bad'
export interface ReviewCheck {
  requirement_id: number
  req_type_code: string
  req_type_name: string
  description: string
  is_mandatory: boolean
  mandatory_label: string
  result: string
  result_label: string
  reason: string
  question: string | null
  self_declared: boolean
  source_quote: string | null
  source_page: number | null
  has_basis: boolean
  bonus_points: number | null
  judged_by?: 'RULE' | 'LLM' | 'CALC'
  judged_label?: string
  ai_reason?: string | null
  ai_quote?: string | null
  regulation_ref?: string | null
}
export interface FitItem {
  id: number
  name: string
  points: number
  kind: EvalKind
  kind_label: string
  areas: string[]
  level: 'FULL' | 'PARTIAL' | 'LOW' | null
  level_label: string
  basis: string
}
export interface AiBlocked {
  requirement_id: number
  reason: string
  llm_result?: string | null
  rule_result?: string | null
  quote?: string | null
}
export interface AiJudgeInfo {
  status: 'OK' | 'PARTIAL' | 'CACHED' | 'FALLBACK'
  model: string | null
  log_id: number | null
  blocked: AiBlocked[]
  error: string | null
  prompt_version: number | null
}
export interface EligibilityResult {
  ai?: AiJudgeInfo | null
  regulations?: { ref: string; text: string; confirmed_at: string | null }[]
  criteria?: {
    requirements_confirmed_at: string | null
    announcement_updated_at: string | null
    regulations_confirmed_at: string | null
    unconfirmed_regulations: string[]
  }
  announcement_id: number
  announcement_no: string
  title: string
  agency_name: string
  program_name: string | null
  receipt_state: string
  receipt_start: string | null
  receipt_end: string | null
  verdict: 'ELIGIBLE' | 'NEEDS_INFO' | 'INELIGIBLE'
  q1_label: string
  q1_text: string
  checks: ReviewCheck[]
  fit: {
    items: FitItem[]
    score: number | null
    grade: string | null
    grade_label: string
    bonus_points: number
    hints: { item: string; after_score: number; text: string }[]
  }
  todo: { kind: string; text: string; question: string | null }[]
  guide: {
    support_amount_krw: number | null
    support_period_months: number | null
    company_burden: string | null
    submit_documents: SubmitDoc[]
    text: string
  }
}
export interface EligibilityReview {
  organization_id: number
  company_name?: string
  as_of?: string
  concern: string | null
  diagnosis?: { total_score: number; state_label: string }
  summary: Record<'ELIGIBLE' | 'NEEDS_INFO' | 'INELIGIBLE', number>
  results: EligibilityResult[]
  ai_mode?: 'llm' | 'rules'
  notice?: string
  fit_rule?: FitRule
}
export const reviewEligibility = (orgId: number, body: { concern?: string; include_closed?: boolean }) =>
  api<EligibilityReview>(`/navigator/consult/companies/${orgId}/eligibility`, { method: 'POST', body })

// ---- D-ROUTE 성장경로 (직원) ----
export type RouteReadiness = 'IMMEDIATE' | 'AFTER_FIX' | 'PREPARE'
export interface RouteProgram {
  program_id: number
  program_code: string
  name: string
  stage: string
  readiness: RouteReadiness
  readiness_label: string
  announcement_id: number | null
  announcement_title: string | null
  announcement_state: string | null
  q1_label: string | null
  fit_grade: string | null
  fit_score: number | null
  entry_condition: string | null
  entry_unmet: { area: string; label: string; min: number; score: number }[]
  prep_tasks: string[]
  expected_output: string | null
  todo: string[]
  submit_documents: SubmitDoc[]
  basis_quotes: string[]
  reason: string
  similar: { count: number; total: number; avg_gap_years: number | null }
}
export interface RouteStep {
  order: number
  horizon: string
  stage: string
  stage_label: string
  goal: string
  is_current: boolean
  programs: RouteProgram[]
  other_programs: RouteProgram[]
  tasks: string[]
  basis: string
}
export interface RouteNotRecommended {
  program_id: number
  program_code?: string
  name: string
  stage?: string | null
  reason: string
  fix: string | string[] | null
  announcement_id?: number | null
}
export interface GrowthRoute {
  organization_id: number
  company_name: string
  state_label: string
  total_score: number
  weakest_area: string | null
  weakest_label: string | null
  strength: { area: string; label: string; score: number; text: string } | null
  current_stage: string | null
  steps: RouteStep[]
  not_recommended: RouteNotRecommended[]
  similar_count?: number
  summary: string
  notice: string
}
export const growthRoute = (orgId: number, body: { concern?: string }) =>
  api<GrowthRoute>(`/navigator/consult/companies/${orgId}/route`, { method: 'POST', body })

export interface RouteRuleStage { code: string; name_ko: string; goal: string; areas: string[] }
export interface RouteRuleProgram {
  program_id: number
  program_code: string
  name: string
  purpose: string | null
  stage_code: string | null
  next_program_ids: number[]
  entry_condition: string | null
  entry_min_scores: Record<string, number>
  prep_tasks: string[]
  expected_output: string | null
  repeatable: boolean
  sort_order: number
  updated_at: string | null
  announcement_count: number
  next_programs: { program_id: number; name: string }[]
}
export interface RouteRules {
  stages: RouteRuleStage[]
  programs: RouteRuleProgram[]
  areas: { code: string; label: string }[]
}
export interface ProgramRouteBody {
  stage_code: string
  next_program_ids: number[]
  entry_condition: string
  entry_min_scores: Record<string, number>
  prep_tasks: string[]
  expected_output: string
  repeatable: boolean
  sort_order: number
}
export const routeRules = () => api<RouteRules>('/navigator/consult/route/rules')
export const saveProgramRoute = (id: number, body: ProgramRouteBody) =>
  api<RouteRules>(`/navigator/consult/route/programs/${id}`, { method: 'PUT', body })
export const deleteProgramRoute = (id: number) =>
  api<void>(`/navigator/consult/route/programs/${id}`, { method: 'DELETE' })

// ---- 상담 요청 · 상담결과서 ----
export type RequestStatus = 'REQUESTED' | 'IN_PROGRESS' | 'DONE' | 'CANCELED'
export interface ConsultRequest {
  id: number
  organization_id: number
  company_name: string
  concern: string
  interest: string | null
  contact_name: string | null
  contact_phone?: string | null
  status: RequestStatus
  status_label: string
  origin: string
  created_at: string
  consultation_id: number | null
}
export interface ConsultRequestBody { concern: string; interest?: string; contact_name?: string; contact_phone?: string }
export const listConsultRequests = (status?: string) =>
  api<ConsultRequest[]>('/navigator/consult/requests', { query: status ? { status } : undefined })
export const createConsultRequest = (orgId: number, body: ConsultRequestBody) =>
  api<ConsultRequest>(`/navigator/consult/companies/${orgId}/requests`, { method: 'POST', body })
export const setConsultRequestStatus = (id: number, status: RequestStatus) =>
  api<ConsultRequest>(`/navigator/consult/requests/${id}`, { method: 'PATCH', body: { status } })

export interface ReportSection { key: string; title: string; text: string; drafted_by?: 'LLM' | 'TEMPLATE' }
export interface VerdictOverride { announcement_id: number; title: string; from: string; verdict: string; reason: string }
export interface ConsultCompare {
  total_before: number
  total_after: number
  state_before: string
  state_after: string
  areas: { label: string; before: number; after: number; delta: number }[]
  verdict_changes: { title: string; before: string; after: string }[]
}
export interface Consultation {
  id: number
  organization_id: number
  company_name: string
  request_id: number | null
  task: 'A' | 'B' | 'C'
  task_label: string
  concern: string | null
  eligibility: EligibilityReview | null
  route: GrowthRoute | null
  evidence?: ConsultEvidence[]
  draft: ReportSection[]
  report: ReportSection[]
  overrides: VerdictOverride[]
  edited_sections: string[]
  compare: ConsultCompare | null
  status: 'DRAFT' | 'CONFIRMED'
  status_label: string
  feedback: string | null
  created_at: string
  created_by_name: string | null
  confirmed_at: string | null
  confirmed_by_name: string | null
  notified_at: string | null
}
export interface ConsultationSummary {
  id: number
  task: string
  task_label: string
  status: 'DRAFT' | 'CONFIRMED'
  status_label: string
  concern: string | null
  total_score: number | null
  state_label: string | null
  eligible_count: number | null
  override_count: number
  edited_sections: string[]
  feedback: string | null
  created_at: string
  created_by_name: string | null
  confirmed_at: string | null
  confirmed_by_name: string | null
}
export interface ConsultationUpdate {
  report?: Record<string, string>
  overrides?: { announcement_id: number; verdict: string; reason: string }[]
  feedback?: string
}
export type ConfirmedConsultation = Consultation & { notify: { sent: boolean; to?: string; reason?: string } }

export const createConsultation = (orgId: number, body: { task: 'A' | 'B' | 'C'; concern?: string; request_id?: number; evidence_ids?: number[] }) =>
  api<Consultation>(`/navigator/consult/companies/${orgId}/consultations`, { method: 'POST', body })
export const getConsultationHistory = (orgId: number) =>
  api<ConsultationSummary[]>(`/navigator/consult/companies/${orgId}/consultations`)
export const getConsultation = (id: number) => api<Consultation>(`/navigator/consult/consultations/${id}`)
export const updateConsultation = (id: number, body: ConsultationUpdate) =>
  api<Consultation>(`/navigator/consult/consultations/${id}`, { method: 'PUT', body })
export const confirmConsultation = (id: number, notify: boolean) =>
  api<ConfirmedConsultation>(`/navigator/consult/consultations/${id}/confirm`, { method: 'POST', body: { notify } })

export interface ReviewLog {
  total: number
  confirmed: number
  counts: { overrides: number; edits: number; feedback: number }
  items: {
    consultation_id: number
    company_name: string
    task_label: string
    status_label: string
    created_at: string
    created_by_name: string | null
    overrides: VerdictOverride[]
    edited_sections: string[]
    feedback: string | null
  }[]
}
export const getReviewLog = () => api<ReviewLog>('/navigator/consult/review-log')

// 기업 화면
export interface MyConsultation {
  id: number
  task_label: string
  confirmed_at: string | null
  concern: string | null
  state_label: string | null
  report: ReportSection[]
  announcements: { announcement_id: number; title: string; agency_name: string; receipt_end: string | null;
    q1_label: string; fit_grade: '상' | '중' | '하' | null; todo: string[] }[]
  steps: { horizon: string; stage_label: string; goal: string;
    programs: { name: string; readiness_label: string }[]; tasks: string[] }[]
}
export interface MyConsultRequest { id: number; concern: string; interest: string | null; status: RequestStatus; status_label: string; created_at: string }
export const getMyConsultations = (token: string) =>
  api<{ consultations: MyConsultation[]; requests: MyConsultRequest[] }>('/navigator/manage/consultations', manage(token))
export const createMyConsultRequest = (token: string, body: ConsultRequestBody) =>
  api<MyConsultRequest>('/navigator/manage/consult-requests', { ...manage(token), method: 'POST', body })

// ---- 서비스 안내 · 기업정보 열람 권한 ----
export interface ServiceGate { level: string; gate: string; owner: string; text: string }
export interface ServiceInfo {
  service: {
    name: string
    summary: string
    targets: string[]
    functions: { code: string; name: string; items: string[] }[]
    goals: string[]
    flow: string[]
    integrations: { name: string; status: string }[]
  }
  roles: unknown
  levels: { code: string; label: string; desc: string }[]
  gates: Record<'dstate' | 'eligibility' | 'route' | 'criteria' | 'history', ServiceGate>
  raci: { area: string; task: string; company: string; staff: string; owner: string; ax: string; agent: string; level: string }[]
}
export const getServiceInfo = () => api<ServiceInfo>('/navigator/service/info')

export interface CompanyAccess {
  organization_id: number
  restricted: boolean
  departments: { id: number; name: string; allowed: boolean }[]
  text: string
}
export const getCompanyAccess = (orgId: number) => api<CompanyAccess>(`/navigator/consult/companies/${orgId}/access`)
export const saveCompanyAccess = (orgId: number, department_ids: number[]) =>
  api<CompanyAccess>(`/navigator/consult/companies/${orgId}/access`, { method: 'PUT', body: { department_ids } })

// ---- AI 판단 관리 (프롬프트 · 호출 기록) ----
export type PromptCode = 'ELIGIBILITY_JUDGE' | 'REPORT_DRAFT'
export interface AiPrompt {
  id: number
  code: PromptCode
  version: number
  title: string
  system_text: string
  guide_text: string
  is_active: boolean
  note: string | null
  created_by_name: string | null
  created_at: string
}
export interface AiPromptList { mode: string; items: AiPrompt[] }
export const listAiPrompts = () => api<AiPromptList>('/navigator/ai/prompts')
export const saveAiPrompt = (code: PromptCode, body: { title?: string; system_text?: string; guide_text?: string; note?: string }) =>
  api<unknown>(`/navigator/ai/prompts/${code}`, { method: 'POST', body })
export const activateAiPrompt = (code: PromptCode, id: number) =>
  api<unknown>(`/navigator/ai/prompts/${code}/versions/${id}/activate`, { method: 'POST' })

export interface AiCall {
  id: number
  purpose: string
  organization_id: number | null
  company_name: string | null
  announcement_id: number | null
  announcement_title: string | null
  prompt_version: number | null
  model: string | null
  status: string
  blocked: AiBlocked[] | null
  error: string | null
  latency_ms: number | null
  created_at: string
  created_by_name: string | null
  input_refs: { basis?: { source?: string; ref?: string | number | null; chars?: number }[]; sections?: string[] } | null
  output: unknown
}
export interface AiCallList {
  mode: string
  stats: { total: number; ok: number; partial: number; fallback: number; cached: number; blocked: number }
  items: AiCall[]
}
export const listAiCalls = (purpose = '', limit = 100) =>
  api<AiCallList>(`/navigator/ai/calls?limit=${limit}${purpose ? `&purpose=${encodeURIComponent(purpose)}` : ''}`)

// 운영규정·지침
export type RegulationCheck = 'TAX_DELINQUENT' | 'INSOLVENT' | 'RND_RESTRICTED' | 'PROCUREMENT_SANCTIONED' | 'DUPLICATE'
export const REGULATION_CHECKS: { code: RegulationCheck; label: string }[] = [
  { code: 'TAX_DELINQUENT', label: '국세·지방세 체납' },
  { code: 'INSOLVENT', label: '부도·자본잠식' },
  { code: 'RND_RESTRICTED', label: '국가 R&D 참여제한' },
  { code: 'PROCUREMENT_SANCTIONED', label: '부정당제재' },
  { code: 'DUPLICATE', label: '중복지원 제한' },
]
export interface RegulationArticleIn {
  article_no: string
  title: string | null
  body: string
  checks: RegulationCheck[]
  within_years: number | null
}
export interface RegulationArticle extends RegulationArticleIn {
  id: number
  check_labels: string[]
  ref: string
}
export interface RegulationSummary {
  id: number
  title: string
  kind: 'COMMON' | 'PROGRAM'
  kind_label: string
  program_id: number | null
  program_name: string | null
  version_label: string | null
  effective_on: string | null
  is_active: boolean
  confirmed_at: string | null
  owner_dept_name: string | null
  article_count: number
  limit_count: number
}
export interface Regulation extends Omit<RegulationSummary, 'article_count' | 'limit_count'> {
  source_url: string | null
  confirmed_by_name: string | null
  articles: RegulationArticle[]
}
export interface RegulationHit {
  id: number
  ref: string
  regulation_id: number
  kind: string
  body: string
  check_labels: string[]
  score: number
  confirmed_at: string | null
}
export interface RegulationBody {
  title: string
  kind: 'COMMON' | 'PROGRAM'
  program_id?: number | null
  version_label?: string
  effective_on?: string
  source_url?: string
  text?: string
  articles?: RegulationArticleIn[]
}
export const listRegulations = () => api<RegulationSummary[]>('/navigator/regulations')
export const getRegulation = (id: number) => api<Regulation>(`/navigator/regulations/${id}`)
export const searchRegulations = (q: string, programId?: number) =>
  api<RegulationHit[]>('/navigator/regulations/search', { query: { q, program_id: programId } })
export const previewRegulation = (text: string) =>
  api<RegulationArticle[]>('/navigator/regulations/preview', { method: 'POST', body: { text } })
export const createRegulation = (body: RegulationBody) =>
  api<Regulation>('/navigator/regulations', { method: 'POST', body })
export const updateRegulation = (id: number, body: Partial<Pick<RegulationBody, 'title' | 'version_label' | 'effective_on' | 'source_url' | 'articles'>> & { is_active?: boolean }) =>
  api<Regulation>(`/navigator/regulations/${id}`, { method: 'PUT', body })
export const confirmRegulation = (id: number) =>
  api<Regulation>(`/navigator/regulations/${id}/confirm`, { method: 'POST' })
export const deleteRegulation = (id: number) =>
  api<void>(`/navigator/regulations/${id}`, { method: 'DELETE' })


// ---- 판정기준·진단 변수사전·상담 보완자료 ----
export interface FitRule {
  capability_full: number
  capability_partial: number
  grade_high: number
  grade_mid: number
  partial_ratio: number
  version?: number | null
}
export type CheckKind = 'MANDATORY' | 'FIT' | 'GUIDE'
export interface CheckItem { item: string; content: string; kind: CheckKind; kind_label?: string }
export interface CriteriaVersion {
  id: number
  version: number
  is_active: boolean
  note: string | null
  created_at: string
  created_by_name: string | null
  settings: Record<string, unknown>
}
export interface CriteriaView {
  active: FitRule & { version: number | null; check_items: CheckItem[] }
  history: CriteriaVersion[]
  kinds: Record<string, string>
}
export interface CriteriaSave extends FitRule { check_items: CheckItem[]; note?: string }
export const getCriteria = () => api<CriteriaView>('/navigator/consult/criteria')
export const saveCriteria = (body: CriteriaSave) => api<CriteriaView>('/navigator/consult/criteria', { method: 'PUT', body })
export const activateCriteria = (version: number) =>
  api<CriteriaView>(`/navigator/consult/criteria/versions/${version}/activate`, { method: 'POST' })

export interface DstateVariableDef {
  code: string
  name_ko: string
  definition: string
  value_type: 'LEVEL' | 'INTEGER' | 'PROFILE'
  options: { code: string; label: string }[]
  areas: string[]
  source_desc: string
  question: string | null
  sort_order: number
  updated_at: string | null
  updated_by_name: string | null
}
export interface DstateVariableEdit {
  name_ko?: string
  definition?: string
  source_desc?: string
  question?: string
  option_labels?: Record<string, string>
}
export const listDstateVariables = () => api<DstateVariableDef[]>('/navigator/consult/dstate/variables')
export const updateDstateVariable = (code: string, body: DstateVariableEdit) =>
  api<DstateVariableDef>(`/navigator/consult/dstate/variables/${code}`, { method: 'PUT', body })

export interface ConsultEvidence {
  id: number
  file_name: string
  parse_status: string
  parse_note: string | null
  detected_kind: string | null
  kind_label: string | null
  detected: Record<string, unknown> | null
  note: string | null
  consultation_id: number | null
  created_at: string
  uploaded_by: number | null
  uploaded_by_name: string | null
  origin_label: string
  text_excerpt: string | null
}
export const listConsultEvidence = (orgId: number) =>
  api<ConsultEvidence[]>(`/navigator/consult/companies/${orgId}/evidence`)
export const addConsultEvidence = (orgId: number, file: File, note?: string) => {
  const form = new FormData()
  form.append('file', file)
  if (note) form.append('note', note)
  return api<ConsultEvidence>(`/navigator/consult/companies/${orgId}/evidence`, { method: 'POST', body: form })
}
export const deleteConsultEvidence = (orgId: number, id: number) =>
  api<void>(`/navigator/consult/companies/${orgId}/evidence/${id}`, { method: 'DELETE' })
