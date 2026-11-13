/** 기관 포트폴리오 API (backend/app/routers/portfolio.py): 전국 R&D 성과 ↔ 해외 수요 갭 → 정책·예산 기획 후보 */
import { api, downloadFile } from './client'
import type { GapStatus, GapType } from './gaps'

export interface PortfolioOverview {
  cards_published: number
  overseas_demands: number
  gaps_confirmed: number
  gaps_draft: number
  handed_off: number
}

export interface PortfolioArea {
  area: string
  demand_count: number
  demands_with_gap: number
  gap_count: number
  confirmed_count: number
  by_type: Record<GapType, number>
  card_count: number
  max_score: number | null
}

export interface DomesticRow {
  weapon_system: string
  weapon_system_id: number | null
  card_count: number
  avg_trl: number | null
  mature_count: number
  open_issue_count: number
  linked_gap_count: number
  linked_demand_count: number
}

export type Direction = 'NEW_PROJECT' | 'FOLLOW_UP' | 'LOCALIZATION' | 'PILOT'

export interface PolicyAction {
  finding_id: number
  gap_type_code: GapType
  gap_type_name: string
  status: GapStatus
  score: number
  summary: string
  maybe_resolved_at: string | null
  overseas_demand_id: number
  demand_no: string
  demand_title: string
  demand_kind: 'ROADMAP' | 'CALL' | 'EXPORT_REQ' | 'DOMESTIC_PLAN' | 'UPGRADE' | 'SUPPLY'
  region: string
  area: string
  target_period: string | null
  cards: { card_id: number; title: string; trl: number | null; role: 'NEAREST' | 'EVIDENCE' }[]
  departments: string[]
  pathways: { linkage_name: string; description: string }[]
  planning_demand_id: number | null
  planning_demand_no: string | null
  direction: Direction
  direction_name: string
}

const q = (includeDraft: boolean) => ({ include_draft: includeDraft || undefined })

export const getPortfolioOverview = () => api<PortfolioOverview>('/portfolio/overview')
export const getPortfolioAreas = (includeDraft: boolean) => api<PortfolioArea[]>('/portfolio/areas', { query: q(includeDraft) })
export const getPortfolioDomestic = () => api<DomesticRow[]>('/portfolio/domestic')
export const getPolicyActions = (includeDraft: boolean, area?: string | null) =>
  api<PolicyAction[]>('/portfolio/actions', { query: { ...q(includeDraft), area } })
export const handOffToDemand = (findingId: number) =>
  api<{ demand_id: number; demand_no: string; created: boolean }>(`/portfolio/actions/${findingId}/to-demand`, { method: 'POST' })
export const downloadPortfolioXlsx = (includeDraft: boolean) =>
  downloadFile('/portfolio/export.xlsx', '기관포트폴리오.xlsx', { query: q(includeDraft) })
