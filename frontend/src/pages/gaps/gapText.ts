import type { GapType } from '../../api/gaps'

/** 갭 종류 (db/migrations/0026 code_gap_type 와 같은 순서·이름) */
export const GAP_TYPES: { code: GapType; name: string; help: string }[] = [
  { code: 'NO_COVERAGE', name: '공백', help: '해외는 원하는데 국내에 비슷한 성과가 없음' },
  { code: 'PERFORMANCE_SHORT', name: '성능미달', help: '비슷한 성과는 있지만 요구 성능에 못 미침' },
  { code: 'LOCALIZATION', name: '국산화·현지화', help: '해외 부품에 기대거나, 수출국이 현지 생산·정비를 요구함' },
  { code: 'MATURITY', name: '성숙도부족', help: '비슷한 성과의 기술 성숙도가 낮거나 남은 숙제가 있음' },
]

export const DEMAND_KIND: Record<string, string> = {
  ROADMAP: '해외 기술로드맵', CALL: '해외 공모', EXPORT_REQ: '수출 요구',
  DOMESTIC_PLAN: '국내 계획(국방부·방사청)', UPGRADE: '성능개량 요구', SUPPLY: '국산화·단종 대응',
}

/** 갭 점수 → 급한 정도 (화면 표시용 눈금) */
export function urgency(score: number | string | null | undefined): { label: string; tone: 'bad' | 'warn' | 'muted' } {
  const n = score == null ? 0 : Number(score)
  if (n >= 0.6) return { label: '먼저 볼 것', tone: 'bad' }
  if (n >= 0.35) return { label: '살펴볼 것', tone: 'warn' }
  return { label: '참고', tone: 'muted' }
}

/** 갭 상태: 초안은 '검수 전'으로 보여 준다 */
export const GAP_STATUS: Record<string, { label: string; tone: string }> = {
  DRAFT: { label: '검수 전', tone: 'muted' }, CONFIRMED: { label: '확정', tone: 'ok' },
  REJECTED: { label: '기각', tone: 'bad' }, SUPERSEDED: { label: '새 분석으로 대체', tone: 'muted' },
}
