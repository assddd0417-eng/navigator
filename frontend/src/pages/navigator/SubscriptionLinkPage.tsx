// 메일 링크: /navigator/subscriptions/confirm#t=… (수신 확인), /navigator/unsubscribe#t=… (수신 거부)
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { confirmSubscription, unsubscribeAlerts } from '../../api/navigator'
import { Card } from '../../components/ui'
import { CompanyShell } from './components'

export function SubscriptionLinkPage({ mode }: { mode: 'confirm' | 'unsubscribe' }) {
  const [token] = useState(() => {
    const m = window.location.hash.match(/[#&]t=([^&]+)/)
    return m ? decodeURIComponent(m[1]) : null
  })
  const [done, setDone] = useState<{ company_name: string; email: string } | null>(null)
  const [error, setError] = useState<string | null>(token ? null : '링크에 확인 값이 없습니다.')

  const sent = useRef(false)   // 1회용 링크라 StrictMode 이중 호출을 막는다

  useEffect(() => {
    if (!token || sent.current) return
    sent.current = true
    window.history.replaceState(null, '', window.location.pathname)
    const call = mode === 'confirm' ? confirmSubscription : unsubscribeAlerts
    call(token).then(setDone).catch((e) => setError(e instanceof ApiError ? e.detail : '처리하지 못했습니다'))
  }, [token, mode])

  const title = mode === 'confirm' ? '공고 알림 수신 확인' : '공고 알림 수신 거부'
  return (
    <CompanyShell>
      <Card title={title}>
        {error ? <p>{error}</p> : !done ? <p className="muted">처리 중…</p> : mode === 'confirm' ? (
          <p>{done.company_name}의 새 공고 알림을 {done.email} 로 보내 드립니다.</p>
        ) : (
          <p>{done.email} 로 가던 {done.company_name}의 공고 알림을 더 이상 보내지 않습니다.</p>
        )}
        <Link className="btn" to="/navigator">Navigator 로 이동</Link>
      </Card>
    </CompanyShell>
  )
}
