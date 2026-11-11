import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  addSubscription, deleteSubscription, getMyAlerts, getMySubscriptions, markAlertsRead, resendConfirm,
  updateSubscription, type AlertChannel, type AlertItem, type Subscription, type SubscriptionInput,
} from '../../api/navigator'
import { useToast } from '../../components/Toast'
import { Card, Empty, useAction } from '../../components/ui'
import { Deadline, FitBadge, FIT_LEVELS, fmtDay, VerdictBadge } from './components'

const CHANNEL_LABELS: Record<AlertChannel, string> = { SCREEN: '화면', EMAIL: '이메일' }
// 관련도 조건. 값은 components 의 FIT_LEVELS 경계와 같다
const MIN_FIT: [number, string][] = [[0, '전체'], [FIT_LEVELS[1].min, '보통 이상'], [FIT_LEVELS[0].min, '높음만']]
const minFitLabel = (v: number) => [...MIN_FIT].reverse().find(([m]) => v >= m)?.[1] ?? '전체'

function subState(s: Subscription): { label: string; tone: string } {
  if (s.unsubscribed_at) return { label: '수신 거부', tone: 'bad' }
  if (!s.email_confirmed_at) return { label: '확인 대기', tone: 'warn' }
  if (!s.is_active) return { label: '꺼짐', tone: 'muted' }
  return { label: '받는 중', tone: 'ok' }
}

export function AlertsPanel({ token, onUnread }: { token: string; onUnread: (n: number) => void }) {
  const [alerts, setAlerts] = useState<AlertItem[] | null>(null)
  const [subs, setSubs] = useState<Subscription[] | null>(null)
  const [registered, setRegistered] = useState('')
  const [max, setMax] = useState(5)
  const [editing, setEditing] = useState<number | 'new' | null>(null)
  const [devLink, setDevLink] = useState<string | null>(null)
  const { busy, run } = useAction()
  const toast = useToast()

  const load = useCallback(() => run(async () => {
    const [a, s] = await Promise.all([getMyAlerts(token), getMySubscriptions(token)])
    setAlerts(a.alerts); onUnread(a.unread)
    setSubs(s.subscriptions); setRegistered(s.registered_email); setMax(s.max)
  }), [run, token, onUnread])

  useEffect(() => { void load() }, [load])

  const readAll = () => run(async () => {
    await markAlertsRead(token)
    await load()
  })

  const confirmNotice = (s: Subscription) => {
    if (s.confirm_sent) toast.show({ kind: 'success', title: `${s.email} 로 확인 메일 발송`, message: '확인하면 알림이 시작됩니다' })
    setDevLink(s.dev_confirm_link ?? null)
  }

  const save = (id: number | 'new', body: SubscriptionInput) => run(async () => {
    const s = id === 'new' ? await addSubscription(token, body) : await updateSubscription(token, id, body)
    if (id === 'new') confirmNotice(s)
    else toast.show({ kind: 'success', title: '저장됨', message: '' })
    setEditing(null)
    await load()
  })

  const toggle = (s: Subscription) => run(async () => {
    await updateSubscription(token, s.id, { is_active: !s.is_active })
    await load()
  })

  const resend = (s: Subscription) => run(async () => {
    confirmNotice(await resendConfirm(token, s.id))
    await load()
  })

  const remove = (s: Subscription) => {
    if (!window.confirm(`${s.email} 수신자를 삭제할까요?`)) return
    void run(async () => {
      await deleteSubscription(token, s.id)
      await load()
    })
  }

  const unread = alerts?.filter((a) => !a.is_read).length ?? 0
  const hasRegistered = subs?.some((s) => s.email === registered.toLowerCase()) ?? false

  return (
    <>
      <Card title="새 공고 알림" actions={unread > 0 &&
        <button className="btn btn-sm" disabled={busy} onClick={() => void readAll()}>모두 읽음</button>}>
        {!alerts ? <div className="page-loading">불러오는 중…</div> : alerts.length === 0 ? (
          <Empty>아직 알림이 없습니다. 새 공고가 공개되면 조건에 맞는 공고만 여기와 이메일로 알려 드립니다.</Empty>
        ) : (
          <ul className="alert-list">
            {alerts.map((a) => (
              <li key={a.announcement_id} className={a.is_read ? '' : 'unread'}>
                <VerdictBadge verdict={a.verdict} audience="company" />
                <div className="grow">
                  <strong>{a.announcement_title}</strong> <FitBadge score={a.total_score} />
                  <div className="small muted">
                    {a.agency_name} · <Deadline end={a.receipt_end} state={a.receipt_state} /> · {fmtDay(a.created_at)} 알림
                  </div>
                  <div className="small">{a.rationale}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="알림 받는 사람" actions={
        editing === null && (subs?.length ?? 0) < max &&
        <button className="btn btn-sm" onClick={() => setEditing('new')}>추가</button>
      }>
        <p className="small muted">
          등록 이메일({registered})은 바로 받기 시작합니다. 다른 주소는 그 주소로 간 확인 메일을 열어야 시작됩니다. 최대 {max}명.
        </p>
        {devLink && (
          <div className="notice small">개발 환경: <a href={devLink.replace(/^https?:\/\/[^/]+/, '')}>확인 링크 바로 열기</a></div>
        )}
        {editing === 'new' && (
          <SubForm initial={{ email: hasRegistered ? '' : registered }} withEmail busy={busy}
            onCancel={() => setEditing(null)} onSave={(b) => void save('new', b)} />
        )}
        {subs && subs.length === 0 && editing !== 'new' && (
          <div className="empty">
            <p>아직 알림을 받는 사람이 없습니다.</p>
            <button className="btn btn-primary" disabled={busy}
              onClick={() => void save('new', { email: registered, keywords: [], min_score: 0, include_needs_info: true, channels: ['SCREEN', 'EMAIL'] })}>
              {registered}로 알림 받기
            </button>
          </div>
        )}
        <ul className="sub-list">
          {subs?.map((s) => {
            const st = subState(s)
            return (
              <li key={s.id}>
                {editing === s.id ? (
                  <SubForm initial={s} busy={busy} onCancel={() => setEditing(null)} onSave={(b) => void save(s.id, b)} />
                ) : (
                  <div className="sub-row">
                    <div className="grow">
                      <strong>{s.email}</strong> <span className={`badge badge-${st.tone}`}>{st.label}</span>
                      <div className="small muted">
                        {s.channels.map((c) => CHANNEL_LABELS[c]).join('·')}
                        {' · '}{s.keywords.length ? `관심 분야 ${s.keywords.join(', ')}` : '전체 분야'}
                        {s.min_score > 0 && ` · 관련도 ${minFitLabel(s.min_score)}`}
                        {!s.include_needs_info && ' · 지원 가능 공고만'}
                      </div>
                    </div>
                    <div className="row-actions">
                      {(!s.email_confirmed_at || s.unsubscribed_at) && (
                        <button className="btn btn-sm" disabled={busy} onClick={() => void resend(s)}>확인 메일 다시 보내기</button>
                      )}
                      {s.email_confirmed_at && !s.unsubscribed_at && (
                        <button className="btn btn-sm" disabled={busy} onClick={() => void toggle(s)}>{s.is_active ? '끄기' : '켜기'}</button>
                      )}
                      <button className="btn btn-sm" onClick={() => setEditing(s.id)}>설정</button>
                      <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => remove(s)}>삭제</button>
                    </div>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      </Card>
    </>
  )
}

function SubForm({ initial, withEmail = false, busy, onSave, onCancel }: {
  initial: Partial<Subscription>
  withEmail?: boolean
  busy: boolean
  onSave: (b: SubscriptionInput) => void
  onCancel: () => void
}) {
  const [email, setEmail] = useState(initial.email ?? '')
  const [keywords, setKeywords] = useState((initial.keywords ?? []).join(', '))
  const [minScore, setMinScore] = useState(initial.min_score ?? 0)
  const [needsInfo, setNeedsInfo] = useState(initial.include_needs_info ?? true)
  const [channels, setChannels] = useState<AlertChannel[]>(initial.channels ?? ['SCREEN', 'EMAIL'])

  const flip = (c: AlertChannel) =>
    setChannels(channels.includes(c) ? channels.filter((x) => x !== c) : [...channels, c])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSave({
      ...(withEmail ? { email } : {}),
      keywords: keywords.split(',').map((k) => k.trim()).filter(Boolean),
      min_score: minScore, include_needs_info: needsInfo, channels,
    })
  }

  return (
    <form className="form sub-form" onSubmit={submit}>
      <div className="form-row">
        {withEmail && (
          <label className="grow">이메일 *<input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        )}
        <label className="grow">관심 분야 (쉼표로 구분, 비우면 전체)
          <input value={keywords} onChange={(e) => setKeywords(e.target.value)} placeholder="예: 데이터링크, 영상" />
        </label>
        <label>관련도
          <select value={MIN_FIT.find(([m]) => m === minScore) ? minScore : MIN_FIT[0][0]} onChange={(e) => setMinScore(Number(e.target.value))}>
            {MIN_FIT.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
      </div>
      <div className="form-row">
        {(['SCREEN', 'EMAIL'] as AlertChannel[]).map((c) => (
          <label key={c} className="check">
            <input type="checkbox" checked={channels.includes(c)} onChange={() => flip(c)} /> {CHANNEL_LABELS[c]}
          </label>
        ))}
        <label className="check">
          <input type="checkbox" checked={needsInfo} onChange={(e) => setNeedsInfo(e.target.checked)} /> 확인 필요 공고도 받기
        </label>
      </div>
      <div className="form-foot">
        <button type="button" className="btn btn-ghost" onClick={onCancel}>취소</button>
        <button className="btn btn-primary" disabled={busy || channels.length === 0}>저장</button>
      </div>
    </form>
  )
}
