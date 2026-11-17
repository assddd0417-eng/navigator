/** PoC 효과 측정 API (backend/app/routers/measurements.py): 업무시간·만족도 */
import { api, downloadFile } from './client'

export type TaskType = 'RESEARCH' | 'DOCUMENT_READING' | 'CANDIDATE_LIST' | 'REVIEW_MATERIAL'
export const TASKS: Record<TaskType, { name: string; help: string }> = {
  RESEARCH: { name: '관련 성과·과제 조사', help: '기획에 쓸 기존 성과·과제를 찾는 시간 (목표 70% 단축)' },
  DOCUMENT_READING: { name: '자료 열람', help: '찾은 보고서·자료를 읽고 확인하는 시간' },
  CANDIDATE_LIST: { name: '후보목록 작성', help: '연계 후보 목록을 만드는 시간' },
  REVIEW_MATERIAL: { name: '통합기획 검토자료 작성', help: '회의용 검토자료를 만드는 시간 (목표 60% 단축)' },
}
export const ASPECTS: Record<string, string> = {
  usefulness: '추천이 쓸모 있음', evidence: '근거가 믿을 만함', ease: '쓰기 쉬움', time_saving: '시간이 줄었음',
}

export interface WorkTimeRow {
  id: number
  task_type: TaskType
  task_name: string
  method: 'MANUAL' | 'AX'
  minutes: number
  candidates_found: number | null
  measured_on: string
  note: string | null
  demand_no: string | null
  user_name: string | null
  user_id: number
}

export interface TaskSummary {
  task_type: TaskType
  task_name: string
  target_pct: number | null
  manual_n: number
  ax_n: number
  manual_avg: number | null
  ax_avg: number | null
  manual_candidates: number | null
  ax_candidates: number | null
  reduction_pct: number | null
  met: boolean | null
}

export interface MeasureSummary {
  tasks: TaskSummary[]
  overall_reduction_pct: number | null
  survey: { n: number; avg_score: number | null; by_role: Record<string, number>;
    aspects: { key: string; name: string; avg: number; n: number }[] }
}

export const addWorkTime = (body: { task_type: TaskType; method: 'MANUAL' | 'AX'; minutes: number;
  candidates_found?: number | null; demand_id?: number | null; note?: string }) =>
  api<{ id: number }>('/measurements/work-time', { method: 'POST', body })
export const listWorkTime = (mine = true) => api<WorkTimeRow[]>('/measurements/work-time', { query: { mine } })
export const deleteWorkTime = (id: number) => api<void>(`/measurements/work-time/${id}`, { method: 'DELETE' })
export const addSurvey = (body: { score: number; aspects: Record<string, number>; comment?: string }) =>
  api<{ id: number }>('/measurements/surveys', { method: 'POST', body })
export const getMeasureSummary = () => api<MeasureSummary>('/measurements/summary', { silent: true })
export const downloadMeasureXlsx = () => downloadFile('/measurements/export.xlsx', '효과측정.xlsx')
