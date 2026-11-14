import { useEffect, useState } from 'react'
import {
  dispatchAnnouncementAlerts, getAnnouncementAlerts, latestAnnouncementRun, listAnnouncements, PRODUCT_CATEGORIES, runAnnouncementMatching, SIZE_LABELS, staffCompanyProfile, SUPPORT_RESULTS,
  type AnnouncementAlerts, type AnnouncementRow, type FullProfile, type MatchRun, type Verdict,
} from '../../api/navigator'
import { useAuth } from '../../auth/AuthContext'
import { Card, Empty, fmtDate, PageHeader, useAction, useAsync } from '../../components/ui'
import { AGENCY_LABELS, bizStatus, fmtBrn, fmtDay, fmtKrw, GroupedMatches, MatchCard, VerdictBadge, VerdictSummary } from '../navigator/components'
import { RadarChart } from '../../components/RadarChart'

const STATES: [string, string][] = [['', '전체'], ['OPEN', '접수중'], ['UPCOMING', '접수전'], ['CLOSED', '마감']]
const STATE_TONES: Record<string, string> = { OPEN: 'ok', UPCOMING: 'info', CLOSED: 'muted' }
// 판정별로 나눠 각각 관련도 순. 확인 필요를 적합 뒤에 이어 붙이면 분야가 맞는 기업이 분야가 다른 적합 기업 뒤로 밀린다
const HINTS: Partial<Record<Verdict, string>> = {
  ELIGIBLE: '필수 조건을 모두 충족',
  NEEDS_INFO: '비어 있는 정보만 확인되면 적합이 될 수 있음',
  INELIGIBLE: '필수 조건 미충족',
}

export function NavigatorStaffPage() {
  const { role } = useAuth()
  const canRun = role === 'PLANNER'
  const [state, setState] = useState('')
  const anns = useAsync(() => listAnnouncements({ receipt_state: state || undefined }), [state])
  const [selected, setSelected] = useState<number | null>(null)
  const [result, setResult] = useState<MatchRun | null>(null)
  const [company, setCompany] = useState<FullProfile | null>(null)
  const { busy, run } = useAction()

  useEffect(() => {
    if (selected == null && anns.data?.length) setSelected(anns.data[0].id)
  }, [anns.data, selected])

  useEffect(() => {
    if (selected == null) return
    setResult(null); setCompany(null)
    void run(async () => setResult(await latestAnnouncementRun(selected)))
  }, [selected, run])

  const ann = anns.data?.find((a) => a.id === selected) ?? null
  const rerun = () => run(async () => setResult(await runAnnouncementMatching(selected!)))
  const openProfile = (orgId: number) => void run(async () => setCompany(await staffCompanyProfile(orgId)))

  return (
    <>
      <PageHeader title="공고별 적합 기업" subtitle="공고를 고르면 지원 조건을 충족하는 기업을 관련도 순으로 보여 줍니다." />
      <div className="grid-side">
        <Card title="공고">
          <div className="chips" style={{ marginTop: 0, marginBottom: 10 }}>
            {STATES.map(([v, l]) => (
              <button key={v} className={`chip ${state === v ? 'chip-on' : ''}`} onClick={() => { setState(v); setSelected(null) }}>{l}</button>
            ))}
          </div>
          {anns.loading ? <div className="page-loading">불러오는 중…</div> : !anns.data?.length ? <Empty>공고가 없습니다.</Empty> : (
            <ul className="select-list">
              {anns.data.map((a) => <AnnButton key={a.id} a={a} on={a.id === selected} onClick={() => setSelected(a.id)} />)}
            </ul>
          )}
        </Card>

        <div className="stack">
          {ann && (
            <Card title={ann.title} actions={
              <button className="btn btn-primary" disabled={busy || !canRun}
                title={canRun ? '등록 기업 전체를 이 공고 조건으로 다시 판정합니다' : '기획 담당자만 실행할 수 있습니다'}
                onClick={() => void rerun()}>
                {busy ? '판정 중…' : result?.run ? '다시 판정' : '기업 판정 실행'}
              </button>
            }>
              <div className="profile-line small">
                <span>{ann.announcement_no}</span>
                <span>{ann.agency_name}</span>
                {ann.program_name && <span>{ann.program_name}</span>}
                <span>접수 {fmtDay(ann.receipt_start)} ~ {fmtDay(ann.receipt_end)}</span>
                <span>지원 조건 {ann.requirement_count}개 (필수 {ann.mandatory_count}) · 요구 기술 {ann.tech_need_count}개</span>
                {ann.status !== 'PUBLISHED' && <span className="badge badge-warn">{ann.status === 'DRAFT' ? '작성 중' : '취소'}</span>}
              </div>
              {result?.run && (
                <p className="small muted">{fmtDate(result.run.created_at)} 기준 · 등록 기업 {result.run.candidate_count}곳 검토</p>
              )}
            </Card>
          )}

          {result && (
            <Card title="판정 결과" actions={result.run && <VerdictSummary run={result} />}>
              {!result.run ? (
                <div className="empty">
                  아직 이 공고로 판정한 적이 없습니다.
                  {canRun && <div style={{ marginTop: 8 }}><button className="btn btn-primary" disabled={busy} onClick={() => void rerun()}>기업 판정 실행</button></div>}
                </div>
              ) : (
                <GroupedMatches run={result} audience="staff" hints={HINTS}
                  renderCard={(r, i) => (
                    <MatchCard rec={r} audience="staff" rank={i + 1}
                      title={<strong>{r.company_name}</strong>}
                      meta={fmtBrn(r.business_reg_no)}
                      onTitle={() => openProfile(r.organization_id)} />
                  )} />
              )}
            </Card>
          )}

          {ann && <AlertsCard ann={ann} />}
        </div>
      </div>
      {company && <CompanyDrawer p={company} onClose={() => setCompany(null)} />}
    </>
  )
}

function AnnButton({ a, on, onClick }: { a: AnnouncementRow; on: boolean; onClick: () => void }) {
  return (
    <li>
      <button className={on ? 'on' : ''} onClick={onClick}>
        <span><span className={`badge badge-${STATE_TONES[a.receipt_state] ?? 'muted'}`}>{a.receipt_state_label}</span> {a.title}</span>
        <span className="small muted">{a.agency_name} · 마감 {fmtDay(a.receipt_end)}</span>
      </button>
    </li>
  )
}

function CompanyDrawer({ p, onClose }: { p: FullProfile; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-label={`${p.company_name} 기업 정보`} onClick={(e) => e.stopPropagation()}>
        <header className="drawer-head">
          <div>
            <h3>{p.company_name}</h3>
            <div className="small muted">{p.business_reg_no} · 국세청 {p.biz_verify_label} · {bizStatus(p.business_status_label)}</div>
          </div>
          <button className="btn btn-sm" onClick={onClose}>닫기</button>
        </header>
        <dl className="kv">
          <dt>규모</dt><dd>{p.company_size ? SIZE_LABELS[p.company_size] ?? p.company_size : '–'}</dd>
          <dt>소재지</dt><dd>{p.region ?? '–'}</dd>
          <dt>근로자</dt><dd>{p.employee_count != null ? `${p.employee_count}명` : '–'}</dd>
          <dt>매출</dt><dd>{fmtKrw(p.annual_revenue_krw)}{p.revenue_year ? ` (${p.revenue_year}년)` : ''}</dd>
          <dt>연락처</dt><dd>{p.registered_email ?? '–'}</dd>
        </dl>
        {p.main_business && <p>{p.main_business}</p>}
        <h4>역량</h4>
        <RadarChart radar={p.radar} compact who="이 회사" />
        <h4>제품 {p.products.length}</h4>
        <ul className="plain-list small">
          {p.products.map((x) => <li key={x.id}>{x.name} <span className="muted">{PRODUCT_CATEGORIES[x.category]}{x.is_defense ? ' · 국방' : ''}{x.customers ? ` · ${x.customers}` : ''}</span></li>)}
        </ul>
        <h4>보유 기술 {p.technologies.length}</h4>
        <ul className="plain-list small">
          {p.technologies.map((t) => <li key={t.id}>{t.tech_name}{t.trl ? ` (TRL ${t.trl})` : ''}</li>)}
        </ul>
        <h4>인증 {p.certifications.length}</h4>
        <ul className="plain-list small">
          {p.certifications.map((c) => <li key={c.id}>{c.cert_type_name}{c.is_expired ? ' (만료)' : ''} <Origin v={c.is_verified} />
            {c.company_evidence_id != null && <span className="badge badge-info">증빙 있음</span>}</li>)}
        </ul>
        <h4>신용등급</h4>
        {p.credit_ratings.length === 0 ? <p className="small muted">없음</p> : (
          <ul className="plain-list small">
            {p.credit_ratings.map((c) => <li key={c.id}>{AGENCY_LABELS[c.agency] ?? c.agency} {c.grade}{c.rated_on ? ` (${c.rated_on})` : ''} <Origin v={c.is_verified} /></li>)}
          </ul>
        )}
        <h4>R&amp;D 이력 {p.rnd_history.length}</h4>
        <ul className="plain-list small">
          {p.rnd_history.map((r) => <li key={r.id}>{r.title} ({r.role === 'LEAD' ? '주관' : '참여'}) <Origin v={r.is_verified} /></li>)}
        </ul>
        <h4>지원사업 참여 {p.support_history.length}</h4>
        <ul className="plain-list small">
          {p.support_history.map((h) => <li key={h.id}>{h.program_name}{h.year ? ` (${h.year})` : ''} · {SUPPORT_RESULTS[h.result]}</li>)}
        </ul>
        <h4>특허 {p.patents.length}</h4>
        <ul className="plain-list small">{p.patents.map((x) => <li key={x.application_no}>{x.title}</li>)}</ul>
      </aside>
    </div>
  )
}

const Origin = ({ v }: { v: boolean }) =>
  <span className={`badge badge-${v ? 'ok' : 'muted'}`}>{v ? '확인됨' : '직접 입력'}</span>

const ALERT_STATUS: Record<string, [string, string]> = {
  PENDING: ['대기', 'warn'], SENT: ['보냄', 'ok'], FAILED: ['실패', 'bad'], READ: ['읽음', 'muted'],
}

function AlertsCard({ ann }: { ann: AnnouncementRow }) {
  const [data, setData] = useState<AnnouncementAlerts | null>(null)
  const [last, setLast] = useState<string | null>(null)
  const { busy, run } = useAction()

  useEffect(() => {
    setData(null); setLast(null)
    void run(async () => setData(await getAnnouncementAlerts(ann.id)))
  }, [ann.id, run])

  const send = () => run(async () => {
    const r = await dispatchAnnouncementAlerts(ann.id)
    setLast(`새 알림 ${r.notifications}건, 메일 ${r.emails_sent}건 발송${r.emails_failed ? `, 실패 ${r.emails_failed}건` : ''}`)
    setData(await getAnnouncementAlerts(ann.id))
  })

  const canSend = ann.status === 'PUBLISHED' && ann.receipt_state !== 'CLOSED'
  return (
    <Card title="기업 알림" actions={canSend &&
      <button className="btn btn-sm" disabled={busy} onClick={() => void send()}>아직 못 받은 기업에 보내기</button>}>
      <p className="small muted">
        공고가 공개되면 알림을 신청한 기업을 판정해서 적합·확인 필요인 곳에 화면과 이메일로 알립니다.
        {data && ` 알림 신청 기업 ${data.subscribed_companies}곳.`}
      </p>
      {last && <div className="notice notice-ok small">{last}</div>}
      {!data ? <div className="page-loading">불러오는 중…</div> : data.notifications.length === 0 ? (
        <Empty>보낸 알림이 없습니다.</Empty>
      ) : (
        <table className="table">
          <thead><tr><th>기업</th><th>판정</th><th>관련도</th><th>상태</th><th>보낸 시각</th></tr></thead>
          <tbody>
            {data.notifications.map((n) => (
              <tr key={n.id}>
                <td>{n.company_name}</td>
                <td><VerdictBadge verdict={n.verdict} /></td>
                <td className="num">{Math.round(n.total_score * 100)}</td>
                <td><span className={`badge badge-${ALERT_STATUS[n.status][1]}`}>{ALERT_STATUS[n.status][0]}</span></td>
                <td className="nowrap">{fmtDate(n.sent_at ?? n.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}
