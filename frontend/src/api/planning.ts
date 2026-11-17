/** 신규 과제 기획 API (backend/app/routers/planning.py): 동향 → 관련 과거 과제 → 새 기획에 넣을 것 → 기획수요 */
import { api } from './client'
import type { GapStatus, GapType } from './gaps'

export type TrendKind = 'ROADMAP' | 'CALL' | 'EXPORT_REQ' | 'DOMESTIC_PLAN' | 'UPGRADE' | 'SUPPLY'
export type Comparator = 'GTE' | 'LTE' | 'EQ' | 'RANGE'

export interface TrendRow {
  id: number
  demand_no: string
  title: string
  demand_kind: TrendKind
  demand_kind_name: string
  region: string
  tech_area: string | null
  target_system: string | null
  target_period: string | null
  confidence: 'HIGH' | 'MEDIUM' | 'LOW'
  source_note: string | null
  planning_demand_no: string | null
}

export interface TrendPerformanceIn {
  metric_name: string
  comparator: Comparator
  required_value: number | null
  required_text: string | null
  unit: string | null
}

export interface TrendIn {
  title: string
  demand_kind: TrendKind
  region: string
  requirement: string
  source_note: string
  target_system?: string | null
  target_period?: string | null
  performances: TrendPerformanceIn[]
}

export type CompareStatus = 'MET' | 'SHORT' | 'NO_DATA' | 'UNIT_DIFF' | 'TEXT'
export type SuggestionKind = 'CAUTION' | 'UPGRADE' | 'RESOLVE' | 'EVAL' | 'LOCALIZE' | 'NEW' | 'REUSE'

export interface BriefProject {
  project_id: number
  project_no: string
  title: string
  status_name: string
  program_name: string | null
  program_type_name: string | null
  department: string | null
  period: string | null
  outcome_code: string | null
  outcome_name: string | null
  outcome_is_failure: boolean
  outcome_note: string | null
  similarity: number
  cards: {
    card_id: number
    title: string
    trl: number | null
    similarity: number
    performances: { metric_name: string; target_value: number | null; achieved_value: number | null; unit: string | null; is_achieved: boolean | null }[]
    limits: { issue_type: string; issue_type_name: string; description: string; priority: string | null }[]
    imported_items: string[]
  }[]
  evaluations: { id: number; eval_kind: 'RESULT' | 'INTERIM' | 'EXPERT' | 'USER'; eval_date: string | null; grade: string | null; opinion: string; suggestion: string | null; evaluator: string | null }[]
}

export interface Brief {
  trend: {
    id: number
    demand_no: string
    title: string
    demand_kind: TrendKind
    demand_kind_name: string
    region: string
    requirement: string
    target_system: string | null
    target_period: string | null
    source_note: string | null
    sources: { source_no: string; issuer: string; title: string; url: string }[]
    requirements: { metric_name: string; text: string }[]
  }
  projects: BriefProject[]
  comparison: {
    metric_name: string
    required: string
    unit: string | null
    status: CompareStatus
    status_name: string
    achieved_value: number | null
    ratio: number | null
    card_title: string | null
    project_title: string | null
    note: string | null
  }[]
  suggestions: { kind: SuggestionKind; kind_name: string; title: string; detail: string; project_ids: number[] }[]
  summary: { project_count: number; outcomes: Record<string, number>; met: number; short: number; no_data: number; unchecked: number; cautions: number }
  gaps: { id: number; status: GapStatus; gap_type_code: GapType; gap_type_name: string; summary: string; score: number }[]
  planning_demand: { id: number; demand_no: string; status: string } | null
}

/** 관련도 기준은 서버가 임베더별로 정한다 (hash 0.45/0.35, bge-m3 0.55/0.50). wide = '덜 비슷한 과제도 보기' */
const sim = (wide: boolean) => ({ wide: wide || undefined })

export const listTrends = () => api<TrendRow[]>('/planning/trends')
export const createTrend = (body: TrendIn) => api<{ id: number }>('/planning/trends', { method: 'POST', body })
export const getBrief = (trendId: number, wide: boolean) => api<Brief>(`/planning/brief/${trendId}`, { query: sim(wide) })
export const briefToDemand = (trendId: number, wide: boolean) =>
  api<{ demand_id: number; demand_no: string; created: boolean }>(`/planning/brief/${trendId}/to-demand`,
    { method: 'POST', query: sim(wide) })
