// 점수를 화면에서는 높음/보통/낮음으로만 보여 준다. 정확한 값은 마우스를 올리면 보인다.
import { getFitLevels } from '../api/navigator'

export type Level = { min: number; label: string; tone: string }

// 유사도(내용이 얼마나 가까운지). 경계는 임베더마다 달라 서버(/navigator/fit-levels)에서 받는다. 받기 전에는 hash 기준
export const SIM_LEVELS: Level[] = [
  { min: 0.45, label: '높음', tone: 'ok' },
  { min: 0.25, label: '보통', tone: 'info' },
  { min: 0, label: '낮음', tone: 'muted' },
]
export async function loadSimLevels() {
  try {
    const r = await getFitLevels()
    SIM_LEVELS[0].min = r.high
    SIM_LEVELS[1].min = r.mid
  } catch { /* 기본값 유지 */ }
}
export const simLevel = (v: number) => SIM_LEVELS.find((l) => v >= l.min) ?? SIM_LEVELS[2]

// 비율형 점수(적합도·성능 충족·성숙도 등 0~1). 판정 규칙이 아니라 화면 표시용 눈금
export const SCORE_LEVELS: Level[] = [
  { min: 0.7, label: '높음', tone: 'ok' },
  { min: 0.5, label: '보통', tone: 'warn' },
  { min: 0, label: '낮음', tone: 'muted' },
]
export const scoreLevel = (v: number) => SCORE_LEVELS.find((l) => v >= l.min) ?? SCORE_LEVELS[2]
