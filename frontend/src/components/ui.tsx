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
export const fmtDate = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'short' }) : '–'

const STATUS_LABELS: Record<string, string> = {
  // 추천
  GENERATED: '생성됨', ASSIGNED: '배정됨', IN_REVIEW: '검토 중', NEEDS_INFO: '추가 정보 필요', DECIDED: '판정 완료',
  WITHDRAWN: '철회',
  // 카드
  DRAFT: '초안', PUBLISHED: '발행', ARCHIVED: '보관',
  // 문서
  PENDING: '대기', PARSED: '파싱 완료', CHUNKED: '청킹 완료', EMBEDDED: '임베딩 완료', FAILED: '실패',
  // 배정·매칭
  IN_PROGRESS: '진행 중', SUBMITTED: '제출', SUCCEEDED: '완료', RUNNING: '실행 중', QUEUED: '대기',
  // 수요
  OPEN: '접수', CLOSED: '종료',
  // 판정
  ADOPT: '채택', HOLD: '보류', EXCLUDE: '제외',
}

const STATUS_TONES: Record<string, string> = {
  DECIDED: 'ok', PUBLISHED: 'ok', SUCCEEDED: 'ok', ADOPT: 'ok', EMBEDDED: 'ok', CHUNKED: 'ok', SUBMITTED: 'ok',
  IN_REVIEW: 'warn', ASSIGNED: 'warn', NEEDS_INFO: 'warn', PENDING: 'warn', IN_PROGRESS: 'warn', HOLD: 'warn',
  DRAFT: 'muted', GENERATED: 'muted', OPEN: 'info',
  FAILED: 'bad', WITHDRAWN: 'bad', EXCLUDE: 'bad',
}

export const statusLabel = (s: string) => STATUS_LABELS[s] ?? s

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge badge-${STATUS_TONES[status] ?? 'muted'}`}>{statusLabel(status)}</span>
}

export const REVIEW_ROLE_LABELS: Record<string, string> = {
  DEPT_OWNER: '소관부서', COLLAB_DEPT: '협업부서', EXPERT: '전문가',
}

/** 시드 부서 (seeds/init_test_data.sql) */
export const DEPT_NAMES: Record<number, string> = { 1: '과제기획팀', 2: '지휘정찰기술팀', 3: '무인미래통신기술팀' }

export const LINKAGE_TYPES: Record<string, string> = {
  FOLLOW_UP: '후속형', ADVANCEMENT: '고도화형', TRANSITION: '전환형',
  CONVERGENCE: '융합형', UTILIZATION: '활용형', COMMERCIALIZATION: '사업화형',
}

export const CRITERIA_LABELS: Record<string, string> = {
  TECH: '기술 유사도', PERFORMANCE: '성능 충족', TRL: 'TRL 적합', ENVIRONMENT: '적용환경', PURPOSE: '사업목적',
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
      title={allowed ? '현재 역할로 실행할 수 있습니다' : '현재 역할로는 서버가 거부합니다 (403)'}>
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
