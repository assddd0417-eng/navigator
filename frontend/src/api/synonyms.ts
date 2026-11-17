/** 국방기술 동의어 사전 API (backend/app/routers/synonyms.py) */
import { api } from './client'

export type Relation = 'SYNONYM' | 'ABBREVIATION' | 'EN_KO' | 'BROADER' | 'NARROWER' | 'RELATED'
export const RELATIONS: Record<Relation, { name: string; help: string }> = {
  SYNONYM: { name: '동의어', help: '같은 뜻의 다른 말' },
  ABBREVIATION: { name: '약어', help: '줄임말 (예: AESA)' },
  EN_KO: { name: '영문·한글', help: '영문 표기와 한글 표기 (예: UAV ↔ 무인항공기)' },
  BROADER: { name: '넓은 말', help: '더 넓은 뜻의 말. 참고용이고 매칭에는 쓰지 않습니다' },
  NARROWER: { name: '좁은 말', help: '더 좁은 뜻의 말. 참고용이고 매칭에는 쓰지 않습니다' },
  RELATED: { name: '관련어', help: '관련 있지만 뜻이 다른 말. 참고용이고 매칭에는 쓰지 않습니다' },
}

export interface SynonymRow {
  id: number
  canonical_term: string
  synonym: string
  relation: Relation
  relation_name: string
  domain: string | null
  source_note: string | null
  is_active: boolean
  used_in_matching: boolean
  created_at: string
}

export interface ExpandPreview {
  text: string
  expanded: string
  matched: { canonical_term: string; found: string; terms: string[] }[]
}

export interface ImportResult {
  rows: number
  added?: number
  would_add?: number
  skipped: number
  errors: { row: number; reason: string }[]
  dry_run?: boolean
}

export const listSynonyms = (q?: string, includeInactive = false) =>
  api<SynonymRow[]>('/synonyms', { query: { q: q || undefined, include_inactive: includeInactive } })
export const addSynonym = (body: { canonical_term: string; synonym: string; relation: Relation; domain?: string | null;
  source_note?: string | null }) => api<{ id: number }>('/synonyms', { method: 'POST', body })
export const patchSynonym = (id: number, body: { is_active?: boolean; relation?: Relation }) =>
  api<void>(`/synonyms/${id}`, { method: 'PATCH', body })
export const previewExpand = (text: string) => api<ExpandPreview>('/synonyms/expand', { query: { text } })
export const importSynonyms = (file: File, dryRun: boolean) => {
  const fd = new FormData()
  fd.append('file', file)
  return api<ImportResult>('/synonyms/import', { method: 'POST', body: fd, query: { dry_run: dryRun } })
}
export const applySynonyms = () =>
  api<{ re_embedded: { cards: number; demands: number; overseas_demands: number } }>('/synonyms/apply', { method: 'POST' })
