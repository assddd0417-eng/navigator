/** 백엔드 라우터(backend/app/routers)와 1:1 로 맞춘 호출 함수와 응답 타입. */
import { api } from './client'

// ---- 공통 ------------------------------------------------------------------
export interface Created {
  id: number
}

/** psycopg 는 numeric 을 문자열로 직렬화하므로 숫자 필드는 number | string 으로 받는다. */
export type Num = number | string

// ---- 사용자 (GET /me) -------------------------------------------------------
export interface Me {
  id: number
  name: string
  department_id: number | null
  clearance_code: string
  roles: string[]
}

export const getMe = (userId?: number) => api<Me>('/me', { userId, silent: userId !== undefined })

// ---- 문서 (/documents) ------------------------------------------------------
export interface DocumentRow {
  id: number
  doc_type_code: string
  doc_type_name: string
  title: string
  project_id: number | null
  owner_dept_id: number | null
  parse_status: 'PENDING' | 'PARSED' | 'CHUNKED' | 'EMBEDDED' | 'FAILED'
  security_code: string
  created_at: string
  chunk_count: number
}

export interface DocumentCreate {
  doc_type_code: string
  title: string
  project_id?: number | null
  owner_dept_id?: number | null
  version_label?: string | null
  authored_at?: string | null
  page_count?: number | null
  security_code?: string
  sections?: { key: string; section_no?: string; heading?: string; page_start?: number; page_end?: number }[]
  chunks: { content: string; section_key?: string; page_start?: number | null; page_end?: number | null }[]
}

export interface DocumentCreated {
  id: number
  chunk_ids: number[]
  embedded: number
}

export const listDocuments = (query: { project_id?: number; parse_status?: string } = {}) =>
  api<DocumentRow[]>('/documents', { query: { limit: 200, ...query } })
export const createDocument = (body: DocumentCreate) =>
  api<DocumentCreated>('/documents', { method: 'POST', body })

// ---- 성과 활용카드 (/cards) --------------------------------------------------
export type CardStatus = 'DRAFT' | 'IN_REVIEW' | 'PUBLISHED' | 'ARCHIVED'

export interface CardRow {
  id: number
  card_no: string
  title: string
  trl: number | null
  status: CardStatus
  revision: number
  project_id: number
  project_no: string
  project_title: string
  updated_at: string
}

export interface CardCreate {
  card_no: string
  project_id: number
  title: string
  core_achievement: string
  trl?: number | null
  application_env?: string | null
  technologies?: { tech_name: string; is_primary?: boolean; evidence?: { chunk_id: number }[] }[]
  evidence?: { chunk_id: number; quote?: string }[]
}

export const listCards = (query: { status?: CardStatus; project_id?: number } = {}) =>
  api<CardRow[]>('/cards', { query: { limit: 200, ...query } })
export const createCard = (body: CardCreate) => api<Created>('/cards', { method: 'POST', body })
export const publishCard = (cardId: number) => api<void>(`/cards/${cardId}/publish`, { method: 'POST' })

// ---- 신규 기획수요 (/demands) -------------------------------------------------
export interface DemandRow {
  id: number
  demand_no: string
  title: string
  status: string
  required_trl_min: number | null
  required_trl_max: number | null
  target_program_id: number | null
  requesting_dept_id: number | null
  updated_at: string
}

export interface DemandDetail extends DemandRow {
  tech_need: string
  match_runs: { id: number; status: string; created_at: string; finished_at: string | null }[]
}

export interface DemandCreate {
  demand_no: string
  title: string
  tech_need: string
  business_purpose?: string | null
  required_trl_min?: number | null
  required_trl_max?: number | null
  target_program_id?: number | null
  technologies?: { tech_name: string }[]
}

export const listDemands = () => api<DemandRow[]>('/demands', { query: { limit: 200 } })
export const getDemand = (id: number) => api<DemandDetail>(`/demands/${id}`)
export const createDemand = (body: DemandCreate) => api<Created>('/demands', { method: 'POST', body })
export const runMatch = (demandId: number, topK?: number) =>
  api<Created>(`/demands/${demandId}/match`, { method: 'POST', body: topK ? { top_k: topK } : {} })

// ---- 추천·HITL 검토 ----------------------------------------------------------
export interface SourceCard {
  card_id: number
  card_no: string
  title: string
  project_no: string
  role: string
}

export interface RecommendationOverview {
  recommendation_id: number
  match_run_id: number
  rank: number
  total_score: Num
  linkage_type_code: string
  linkage_type_name: string
  final_linkage_type_code: string | null
  status: RecommendationStatus
  final_decision_code: string | null
  is_excluded: boolean
  demand_id: number | null
  demand_title: string | null
  target_program_name: string | null
  rationale: string | null
  development_needs: string | null
  source_cards: SourceCard[] | null
  scores: Record<string, Num> | null
  owner_department: string | null
  evidence_count: number
  open_confirmations: number
  created_at: string
}

export type RecommendationStatus = 'GENERATED' | 'ASSIGNED' | 'IN_REVIEW' | 'NEEDS_INFO' | 'DECIDED' | 'WITHDRAWN'

export interface MatchRun {
  id: number
  status: string
  demand_id: number
  created_at: string
  recommendations: RecommendationOverview[]
}

export interface EvidenceRow {
  evidence_id: number
  side: string
  criterion: string | null
  quote: string | null
  page_start: number | null
  page_end: number | null
  document_id: number
  document_title: string
  section_no: string | null
  section_heading: string | null
}

export interface DecisionRow {
  id: number
  reviewer_id: number
  reviewer_name: string
  decision_code: string
  is_final: boolean
  opinion: string | null
  linkage_type_override: string | null
  created_at: string
}

export interface CommentRow {
  id: number
  author_id: number
  body: string
  parent_id: number | null
  created_at: string
}

export interface AssignmentRow {
  id: number
  review_role: string
  assignee_user_id: number | null
  assignee_dept_id: number | null
  status: string
  due_at: string | null
}

export interface RecommendationDetail extends RecommendationOverview {
  score_details: { criterion: string; score: Num; weight: Num; method: string }[]
  linkage_scores: { linkage_type_code: string; probability: Num; reason: string | null }[]
  evidence: EvidenceRow[]
  departments: { department_id: number; name: string; role: string }[]
  companies: { organization_id: number; name: string; relation_status: string }[]
  confirmations: { id: number; subject_type: string; description: string; status: string }[]
  assignments: AssignmentRow[]
  decisions: DecisionRow[]
  comments: CommentRow[]
}

export interface StatusHistoryRow {
  id: number
  from_status: string | null
  to_status: string
  changed_by: number | null
  changed_by_name: string | null
  changed_at: string
  reason: string | null
}

export interface ReviewQueueRow {
  assignment_id: number
  review_role: 'DEPT_OWNER' | 'COLLAB_DEPT' | 'EXPERT'
  assignee_user_id: number | null
  assignee_dept_id: number | null
  assignment_status: string
  assigned_at: string
  due_at: string | null
  is_overdue: boolean
  recommendation_id: number
  linkage_type_name: string
  total_score: Num
  demand_title: string | null
  source_cards: SourceCard[] | null
  evidence_count: number
  open_confirmations: number
  recommendation_status: RecommendationStatus
}

export interface AssignmentCreate {
  review_role: 'DEPT_OWNER' | 'COLLAB_DEPT' | 'EXPERT'
  assignee_user_id?: number | null
  assignee_dept_id?: number | null
  note?: string | null
}

export type DecisionCode = 'ADOPT' | 'HOLD' | 'EXCLUDE' | 'NEEDS_INFO'

export interface DecisionCreate {
  decision_code: DecisionCode
  is_final: boolean
  assignment_id?: number | null
  linkage_type_override?: string | null
  opinion?: string | null
  relevance_rating?: number | null
  evidence_adequacy?: number | null
}

export const getMatchRun = (id: number) => api<MatchRun>(`/match-runs/${id}`)
export const getRecommendation = (id: number) => api<RecommendationDetail>(`/recommendations/${id}`)
export const getRecommendationHistory = (id: number) =>
  api<{ status_history: StatusHistoryRow[] }>(`/recommendations/${id}/history`)
export const assignReview = (recId: number, body: AssignmentCreate) =>
  api<Created>(`/recommendations/${recId}/assignments`, { method: 'POST', body })
export const submitDecision = (recId: number, body: DecisionCreate) =>
  api<Created>(`/recommendations/${recId}/decisions`, { method: 'POST', body })
export const addComment = (recId: number, body: string) =>
  api<Created>(`/recommendations/${recId}/comments`, { method: 'POST', body: { body } })
export const getReviewQueue = (mine: boolean) => api<ReviewQueueRow[]>('/reviews/queue', { query: { mine } })

// ---- KPI (/kpi) ------------------------------------------------------------
export interface RecommendationKpi {
  match_run_id: number
  recommendations: number
  with_evidence: number
  evidence_coverage_pct: Num | null
  finally_reviewed: number
  final_review_pct: Num | null
  adopted: number
}

export interface WorkTimeKpi {
  task_type: string
  avg_manual_min: Num | null
  avg_ax_min: Num | null
  reduction_pct: Num | null
}

export interface EvalKpi {
  eval_run_id: number
  top_k: number
  major_topk_recall_pct: Num | null
  linkage_type_accuracy_pct: Num | null
}

export const getRecommendationKpi = () => api<RecommendationKpi[]>('/kpi/recommendations')
export const getWorkTimeKpi = () => api<WorkTimeKpi[]>('/kpi/work-time')
export const getEvalKpi = () => api<EvalKpi[]>('/kpi/eval')
