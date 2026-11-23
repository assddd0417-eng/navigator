import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

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
  const running = useRef(false) // 두 번 눌러도 한 번만 보낸다 (busy 는 다음 렌더부터 반영됨)
  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    if (running.current) return undefined
    running.current = true
    setBusy(true)
    try {
      return await fn()
    } catch {
      return undefined // 오류 알림은 전역 토스트가 처리
    } finally {
      running.current = false
      setBusy(false)
    }
  }, [])
  return { busy, run }
}

export const fmtDate = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'short' }) : '–'

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

export function PageHeader({ title, subtitle, actions, eyebrow }: { title: string; subtitle?: string; actions?: ReactNode; eyebrow?: string }) {
  return (
    <div className="page-header">
      <div>
        {eyebrow && <div className="page-eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}

/** 제출서류 이름. 해당 시 제출하는 서류는 뒤에 '(해당 시)'를 붙인다 (이름에 이미 있으면 그대로) */
export const docName = (d: { name: string; required?: boolean }) =>
  d.required === false && !d.name.includes('해당 시') ? `${d.name} (해당 시)` : d.name
