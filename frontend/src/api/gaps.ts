/** 갭 분석 API (backend/app/routers/gaps.py): 해외 수요 ↔ 국내 성과 비교 결과 조회·재실행·검수 */
import { api } from './client'

export type GapType = 'NO_COVERAGE' | 'PERFORMANCE_SHORT' | 'LOCALIZATION' | 'MATURITY'
export type GapStatus = 'DRAFT' | 'CONFIRMED' | 'REJECTED' | 'SUPERSEDED'

export interface GapSummaryRow {
  overseas_demand_id: number
  demand_no: string
  title: string
  region: string
  tech_area: string | null
  gaps: Partial<Record<GapType, { finding_id: number; status: GapStatus; score: number | string }>>
}

export interface GapFinding {
  id: number
  gap_run_id: number
  overseas_demand_id: number
  demand_no: string
  demand_title: string
  demand_kind: 'ROADMAP' | 'CALL' | 'EXPORT_REQ' | 'DOMESTIC_PLAN' | 'UPGRADE' | 'SUPPLY'
  region: string
  gap_type_code: GapType
  gap_type_name: string
  severity: number
  score: number
  best_similarity: number | null
  summary: string
  security_code: string
  status: GapStatus
  decided_by: number | null
  decided_at: string | null
  decision_reason: string | null
  maybe_resolved_at: string | null
  created_at: string
  card_count?: number
}

export interface GapFindingDetail extends GapFinding {
  detail: { items?: string[]; nearest?: { card_id: number; title: string; similarity: number }[]; unchecked?: string[] }
  cards: { card_id: number; card_no: string; title: string; trl: number | null; project_title: string | null;
    similarity: number | null; role: 'NEAREST' | 'EVIDENCE'; note: string | null }[]
  pathways: { id: number; linkage_type_code: string | null; linkage_name: string; description: string; card_ids: number[] }[]
  sources: { source_no: string; issuer: string; title: string; url: string | null; license_note: string | null; is_primary: boolean }[]
}

export const getGapSummary = () => api<GapSummaryRow[]>('/gaps/summary')
export const listGapFindings = (status: 'open' | 'all' | GapStatus = 'open') =>
  api<GapFinding[]>('/gaps/findings', { query: { status } })
export const getGapFinding = (id: number) => api<GapFindingDetail>(`/gaps/findings/${id}`)
export const runGapAnalysis = (demandIds?: number[]) =>
  api<{ id: number; demand_count: number; finding_count: number }>('/gaps/runs', {
    method: 'POST', body: demandIds?.length ? { demand_ids: demandIds } : {},
  })
export const decideGap = (id: number, decision: 'CONFIRM' | 'REJECT', reason: string | null) =>
  api<void>(`/gaps/findings/${id}/decision`, { method: 'POST', body: { decision, reason } })
