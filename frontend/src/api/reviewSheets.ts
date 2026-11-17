/** 통합기획 검토 API (backend/app/routers/review_sheets.py): 후보 검토표 · 통합기획 자료 초안 · 회의 결정 */
import { api, downloadFile } from './client'

export type SheetScope = 'COMPLETED_PROJECT_UTILIZATION' | 'CROSS_PROGRAM' | 'DEMAND' | 'CUSTOM'

export const SCOPES: { code: SheetScope; name: string; help: string }[] = [
  { code: 'CUSTOM', name: '전체 후보', help: '최근 AI 추천 가운데 상위 후보를 모두 모읍니다' },
  { code: 'COMPLETED_PROJECT_UTILIZATION', name: '종료과제 활용 후보', help: '끝난 과제의 성과를 이어 쓸 후보만' },
  { code: 'CROSS_PROGRAM', name: '사업트랙·부서 간 연계 후보', help: '다른 사업이나 다른 부서의 성과를 잇는 후보만' },
  { code: 'DEMAND', name: '신규 기획수요 대상 후보', help: '기획수요 하나에 대한 후보만' },
]

export interface SheetRow {
  id: number
  title: string
  sheet_scope: SheetScope
  status: 'DRAFT' | 'FINALIZED' | 'ARCHIVED'
  security_code: string
  created_at: string
  finalized_at: string | null
  department_name: string | null
  meeting_id: number | null
  meeting_title: string | null
  item_count: number
  decided_count: number
  draft_count: number
}

export interface EvidenceSnap {
  evidence_id: number
  document_title: string
  section_no: string | null
  page_start: number | null
  page_end: number | null
  quote: string
}

export interface ItemSnapshot {
  recommendation_id: number
  rank: number
  total_score: number
  linkage_type_code: string
  linkage_type_name: string
  demand_id: number | null
  demand_no: string | null
  demand_title: string | null
  target_program_name: string | null
  rationale: string
  development_needs: string | null
  source_cards: { card_id: number; title: string; project_no: string; project_title: string; project_status: string;
    end_date: string | null; trl: number | null; department: string | null; program: string | null }[]
  owner_departments: string[]
  collab_departments: string[]
  companies: string[]
  evidence: EvidenceSnap[]
  evidence_count: number
  open_confirmations: number
}

export interface SheetItem {
  recommendation_id: number
  sort_order: number
  snapshot: ItemSnapshot
  live: {
    status: string
    status_name: string
    final_decision_code: string | null
    final_decision_name: string | null
    final_linkage_type_name: string | null
    final_decision: { decision_code: string; opinion: string | null; reviewer: string } | null
  }
}

export interface SheetDetail extends SheetRow {
  scope_name: string
  demand_id: number | null
  demand_no: string | null
  demand_title: string | null
  created_by_name: string | null
  finalized_by_name: string | null
  items: SheetItem[]
  summary: { candidates: number; decided: number; adopted: number; final_review_rate_pct: number;
    evidence_linked: number; by_linkage_type: Record<string, number> }
  drafts: { id: number; title: string; version: number; status: string; created_at: string }[]
}

export interface Draft {
  id: number
  sheet_id: number
  title: string
  version: number
  status: 'DRAFT' | 'REVIEWED' | 'FINAL'
  content_md: string
  created_at: string
  created_by_name: string | null
  evidence_count: number
}

export interface MeetingRow {
  id: number
  title: string
  held_at: string | null
  status: 'SCHEDULED' | 'HELD' | 'CANCELLED'
  host_dept_name: string | null
  sheet_count: number
  decision_count: number
  open_count: number
}

export interface MeetingDecision {
  id: number
  decision: string
  recommendation_id: number | null
  follow_up_action: string | null
  owner_dept_id: number | null
  owner_dept_name: string | null
  due_date: string | null
  status: 'OPEN' | 'DONE' | 'DROPPED'
  decided_by_name: string | null
}

export interface MeetingDetail extends MeetingRow {
  departments: { id: number; name: string }[]
  sheets: { id: number; title: string; status: string }[]
  decisions: MeetingDecision[]
}

export const listSheets = () => api<SheetRow[]>('/review-sheets')
export const getSheet = (id: number) => api<SheetDetail>(`/review-sheets/${id}`)
export const createSheet = (body: { sheet_scope: SheetScope; department_id?: number | null; demand_id?: number | null;
  meeting_id?: number | null; title?: string; per_target?: number }) =>
  api<{ id: number }>('/review-sheets', { method: 'POST', body })
export const attachSheet = (id: number, meetingId: number | null) =>
  api<void>(`/review-sheets/${id}`, { method: 'PATCH', body: { meeting_id: meetingId } })
export const finalizeSheet = (id: number) => api<void>(`/review-sheets/${id}/finalize`, { method: 'POST' })
export const removeSheetItem = (id: number, recId: number) =>
  api<void>(`/review-sheets/${id}/items/${recId}`, { method: 'DELETE' })
export const downloadSheetXlsx = (id: number) => downloadFile(`/review-sheets/${id}/export.xlsx`, `후보검토표_${id}.xlsx`)

export const createDraft = (sheetId: number) => api<{ id: number }>(`/review-sheets/${sheetId}/drafts`, { method: 'POST' })
export const getDraft = (id: number) => api<Draft>(`/planning-drafts/${id}`)
export const setDraftStatus = (id: number, status: Draft['status']) =>
  api<void>(`/planning-drafts/${id}`, { method: 'PATCH', body: { status } })
export const downloadDraftMd = (id: number) => downloadFile(`/planning-drafts/${id}/export.md`, `통합기획_검토자료_${id}.md`)

export const listMeetings = () => api<MeetingRow[]>('/meetings')
export const getMeeting = (id: number) => api<MeetingDetail>(`/meetings/${id}`)
export const createMeeting = (body: { title: string; held_at?: string | null; department_ids?: number[] }) =>
  api<{ id: number }>('/meetings', { method: 'POST', body })
export const setMeetingStatus = (id: number, status: MeetingRow['status']) =>
  api<void>(`/meetings/${id}`, { method: 'PATCH', body: { status } })
export const addMeetingDecision = (id: number, body: { decision: string; recommendation_id?: number | null;
  follow_up_action?: string; owner_dept_id?: number | null; due_date?: string | null }) =>
  api<{ id: number }>(`/meetings/${id}/decisions`, { method: 'POST', body })
export const setDecisionStatus = (id: number, status: MeetingDecision['status']) =>
  api<void>(`/meeting-decisions/${id}`, { method: 'PATCH', body: { status } })

// ---------------------------------------------------------------------------
// 연계 실행 결과·순환 (backend/app/routers/executions.py)
// ---------------------------------------------------------------------------
export type ExecType = 'NEW_PROJECT' | 'PROGRAM_APPLICATION' | 'TECH_TRANSFER' | 'COMMERCIALIZATION' | 'EXPORT'
  | 'LOCALIZATION' | 'PILOT_TEST' | 'OTHER'
export type ExecStatus = 'PLANNED' | 'IN_PROGRESS' | 'COMPLETED' | 'DROPPED'

export const EXEC_TYPES: Record<ExecType, string> = {
  NEW_PROJECT: '신규 과제', PROGRAM_APPLICATION: '타 사업 신청', TECH_TRANSFER: '기술이전', COMMERCIALIZATION: '사업화',
  EXPORT: '수출', LOCALIZATION: '부품 국산화', PILOT_TEST: '시험·실증', OTHER: '기타',
}
export const EXEC_STATUS: Record<ExecStatus, string> = { PLANNED: '계획', IN_PROGRESS: '진행 중', COMPLETED: '완료', DROPPED: '중단' }

export interface AdoptedCandidate {
  recommendation_id: number
  demand_title: string | null
  target_program_name: string | null
  linkage_type_name: string
  source_cards: { card_id: number; title: string; project_no: string }[]
  owner_department: string | null
  final_decided_at: string | null
  execution_count: number
}

export interface Execution {
  id: number
  recommendation_id: number | null
  source_card_id: number
  card_title: string
  source_project_no: string
  source_project_title: string
  linkage_type_name: string
  execution_type: ExecType
  execution_type_name: string
  status: ExecStatus
  status_name: string
  resulting_project_id: number | null
  resulting_project_no: string | null
  resulting_project_title: string | null
  organization_name: string | null
  executed_on: string | null
  discovered_by_ax: boolean
  note: string | null
  result_note: string | null
  demand_title: string | null
  eval_case_id: number | null
  resulting_cards: number
  created_by_name: string | null
  updated_at: string
}

export interface ExecutionKpi {
  adopted: number
  adopted_executed: number
  conversion_pct: number
  executions: number
  completed: number
  ongoing: number
  dropped: number
  discovered_by_ax: number
  resulting_projects: number
  resulting_cards: number
  eval_cases: number
  by_type: Record<string, number>
}

export interface Lineage {
  card: { id: number; title: string; project_no: string; project_title: string }
  ancestors: { lvl: number; project_no: string; project_title: string; linkage_type_name: string | null;
    cards: { card_id: number; title: string }[] }[]
  descendants: (Execution & { level: number; next_cards: { card_id: number; title: string }[] })[]
}

export interface ExecutionBody {
  recommendation_id?: number | null
  source_card_id?: number | null
  linkage_type_code?: string | null
  execution_type: ExecType
  status: ExecStatus
  resulting_project_id?: number | null
  new_project?: { project_no: string; title: string } | null
  executed_on?: string | null
  note?: string
  result_note?: string
}

export const listAdoptedCandidates = () => api<AdoptedCandidate[]>('/executions/candidates')
export const listExecutions = () => api<Execution[]>('/executions')
export const getExecutionKpi = () => api<ExecutionKpi>('/executions/kpi')
export const getLineage = (cardId: number) => api<Lineage>(`/executions/lineage/cards/${cardId}`)
export const createExecution = (body: ExecutionBody) =>
  api<{ id: number; project_relation_id: number | null; eval_case_id: number | null }>('/executions', { method: 'POST', body })
export const patchExecution = (id: number, body: Partial<Pick<ExecutionBody, 'status' | 'result_note' | 'executed_on'>>) =>
  api<{ id: number; eval_case_id: number | null }>(`/executions/${id}`, { method: 'PATCH', body })
