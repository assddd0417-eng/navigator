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
