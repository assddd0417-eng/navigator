import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useAuth } from '../auth/AuthContext'
import { ROLES, type RoleCode } from '../auth/roles'
import type { Num } from '../api/endpoints'

/** 비동기 조회 상태. reload 로 다시 불러온다. 오류 토스트는 API 클라이언트가 띄운다. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  const run = useCallback(fn, deps)
  const reload = useCallback(() => {
    setLoading(true)
    return run()
      .then((d) => {
        setData(d)
        setFailed(false)
      })
      .catch(() => setFailed(true))
      .finally(() => setLoading(false))
  }, [run])

  useEffect(() => {
    void reload()
  }, [reload])

  return { data, loading, failed, reload }
}

/** 버튼 클릭 → API 호출 중 상태 관리 */
export function useAction() {
  const [busy, setBusy] = useState(false)
  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true)
    try {
      return await fn()
    } catch {
      return undefined // 오류 알림은 전역 토스트가 처리
    } finally {
      setBusy(false)
    }
  }, [])
  return { busy, run }
}

export const num = (v: Num | null | undefined): number | null => (v == null ? null : Number(v))
export const pct = (v: Num | null | undefined) => (v == null ? '–' : `${Number(v).toFixed(1)}%`)
export const score = (v: Num | null | undefined) => (v == null ? '–' : Number(v).toFixed(2))
/** 0~1 점수를 사람이 읽는 백분율로 (0.823 → 82%) */
export const pct100 = (v: Num | null | undefined) => (v == null ? '–' : `${Math.round(Number(v) * 100)}%`)

/**
 * 적합도 등급 (화면 표시용 눈금, 판정 규칙 아님).
 * 0.70 이상 높음 · 0.50 이상 보통 · 그 아래 낮음
 */
export function fitLevel(v: Num | null | undefined): { label: string; tone: 'ok' | 'warn' | 'muted' } {
  const n = v == null ? 0 : Number(v)
  if (n >= 0.7) return { label: '높음', tone: 'ok' }
  if (n >= 0.5) return { label: '보통', tone: 'warn' }
  return { label: '낮음', tone: 'muted' }
}

/** 적합도: 82% + 높음/보통/낮음 배지 */
export function Fit({ value, big = false }: { value: Num | null | undefined; big?: boolean }) {
  const lv = fitLevel(value)
  return (
    <span className={`fit ${big ? 'fit-big' : ''}`} title="AI가 계산한 적합도 (100%에 가까울수록 잘 맞음)">
      <strong>{pct100(value)}</strong> <span className={`badge badge-${lv.tone}`}>{lv.label}</span>
    </span>
  )
}

/** 0~1 점수 막대 한 줄 */
export function ScoreBar({ label, value, help }: { label: string; value: Num | null | undefined; help?: string }) {
  const n = value == null ? 0 : Number(value)
  return (
    <div className="bar-row" title={help}>
      <span>{label}</span>
      <div className="bar"><div style={{ width: `${Math.round(n * 100)}%` }} /></div>
      <span className="num">{pct100(value)}</span>
    </div>
  )
}

/** 화면 맨 위 '이 화면에서 할 일' 안내 (단계 번호 + 짧은 문장) */
export function Steps({ items }: { items: ReactNode[] }) {
  return (
    <ol className="steps">
      {items.map((t, i) => <li key={i}><span className="steps-num">{i + 1}</span><span>{t}</span></li>)}
    </ol>
  )
}

/** 접었다 펼치는 '자세히' 영역 (자주 쓰지 않는 입력·기술 정보) */
export function More({ label, children }: { label: string; children: ReactNode }) {
  return (
    <details className="more">
      <summary>{label}</summary>
      <div className="more-body">{children}</div>
    </details>
  )
}
export const fmtDate = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'short' }) : '–'

const STATUS_LABELS: Record<string, string> = {
  // 추천
  GENERATED: '검토자 배정 전', ASSIGNED: '검토 요청됨', IN_REVIEW: '검토 중', NEEDS_INFO: '추가 정보 필요', DECIDED: '판정 완료',
  WITHDRAWN: '철회',
  // 카드
  DRAFT: '초안', PUBLISHED: '발행됨', ARCHIVED: '보관',
  // 갭
  CONFIRMED: '확정', REJECTED: '기각', SUPERSEDED: '새 분석으로 대체',
  // 문서
  PENDING: '처리 대기', PARSED: '글자 읽음', CHUNKED: '검색 준비 중', EMBEDDED: '검색 가능', FAILED: '처리 실패',
  // 배정·매칭
  IN_PROGRESS: '진행 중', SUBMITTED: '제출', SUCCEEDED: '완료', RUNNING: '실행 중', QUEUED: '대기',
  // 수요
  OPEN: '접수', MATCHING: 'AI 추천 받음', PLANNED: '기획 반영', CLOSED: '종료',
  // 판정
  ADOPT: '채택', HOLD: '보류', EXCLUDE: '제외',
}

const STATUS_TONES: Record<string, string> = {
  DECIDED: 'ok', PUBLISHED: 'ok', SUCCEEDED: 'ok', ADOPT: 'ok', EMBEDDED: 'ok', CHUNKED: 'ok', SUBMITTED: 'ok',
  IN_REVIEW: 'warn', ASSIGNED: 'warn', NEEDS_INFO: 'warn', PENDING: 'warn', IN_PROGRESS: 'warn', HOLD: 'warn',
  DRAFT: 'muted', GENERATED: 'muted', OPEN: 'info', MATCHING: 'info', PLANNED: 'ok',
  FAILED: 'bad', WITHDRAWN: 'bad', EXCLUDE: 'bad', CONFIRMED: 'ok', REJECTED: 'bad', SUPERSEDED: 'muted',
}

export const statusLabel = (s: string) => STATUS_LABELS[s] ?? s

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge badge-${STATUS_TONES[status] ?? 'muted'}`}>{statusLabel(status)}</span>
}

export const REVIEW_ROLE_LABELS: Record<string, string> = {
  DEPT_OWNER: '담당 부서', COLLAB_DEPT: '협업 부서', EXPERT: '전문가',
}

/** 시드 부서 (seeds/init_test_data.sql) */
export const DEPT_NAMES: Record<number, string> = { 1: '과제기획팀', 2: '지휘정찰기술팀', 3: '무인미래통신기술팀' }

export const LINKAGE_TYPES: Record<string, string> = {
  FOLLOW_UP: '후속형', ADVANCEMENT: '고도화형', TRANSITION: '전환형',
  CONVERGENCE: '융합형', UTILIZATION: '활용형', COMMERCIALIZATION: '사업화형',
}

export const CRITERIA_LABELS: Record<string, string> = {
  TECH: '기술이 비슷한 정도', PERFORMANCE: '요구 성능 충족', TRL: '기술 성숙도 맞음', ENVIRONMENT: '쓰는 환경 맞음', PURPOSE: '사업 목적 맞음',
}

/** 연계유형 한 줄 설명 (처음 보는 사람용) */
export const LINKAGE_HELP: Record<string, string> = {
  FOLLOW_UP: '이전 과제에서 남은 숙제를 이어서 개발',
  ADVANCEMENT: '이전 성과의 성능을 한 단계 끌어올림',
  TRANSITION: '다른 무기체계·분야로 옮겨 적용',
  CONVERGENCE: '여러 과제 성과를 합쳐 새 기술로',
  UTILIZATION: '이미 만든 성과를 그대로 활용',
  COMMERCIALIZATION: '성과를 제품·수출로 사업화',
}

/** TRL 을 쉬운 말로 */
export const trlText = (min: number | null | undefined, max?: number | null) => {
  if (min == null && max == null) return '–'
  if (max === undefined || min === max) return `${min ?? max}단계`
  return `${min ?? '?'}~${max ?? '?'}단계`
}

/**
 * 이 작업에 필요한 역할 표시. 현재 역할에 권한이 없으면 자물쇠를 붙인다.
 * 버튼은 숨기지 않는다 — 눌렀을 때 서버가 403 으로 거부하는 모습을 시연에서 보여 주기 위함.
 */
export function RoleHint({ roles }: { roles: RoleCode[] }) {
  const { role } = useAuth()
  const allowed = role != null && roles.includes(role)
  return (
    <span className={`role-hint ${allowed ? 'role-hint-ok' : 'role-hint-locked'}`}
      title={allowed ? '지금 역할로 할 수 있습니다' : '지금 역할로는 할 수 없습니다. 눌러 보면 거부 사유가 표시됩니다.'}>
      {allowed ? '' : '🔒 '}
      {roles.map((r) => ROLES[r].label).join('·')} 전용
    </span>
  )
}

export function Card({ title, actions, children, className = '' }:
  { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-header">
          {title && <h3>{title}</h3>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}
