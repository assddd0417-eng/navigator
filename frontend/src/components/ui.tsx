import { useCallback, useEffect, useState, type ReactNode } from 'react'

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
