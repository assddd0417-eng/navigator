import { useEffect, useRef, useState } from 'react'
import {
  latestAnnouncementRun, listAnnouncements, runAnnouncementMatching, SIZE_LABELS, staffCompanyProfile,
  VERDICT_LABELS, type AnnouncementRow, type FullProfile, type MatchRun, type Verdict,
} from '../../api/navigator'
import { Card, Empty, fmtDate, PageHeader, RoleHint, useAction, useAsync } from '../../components/ui'
import { fmtDay, fmtKrw, MatchItem, VerdictSummary } from '../navigator/components'

const fmtBrn = (v?: string) => (v && v.length === 10 ? `${v.slice(0, 3)}-${v.slice(3, 5)}-${v.slice(5)}` : v ?? '')
const STATES: [string, string][] = [['', '전체'], ['OPEN', '접수중'], ['UPCOMING', '접수전'], ['CLOSED', '마감']]
const STATE_TONES: Record<string, string> = { OPEN: 'ok', UPCOMING: 'info', CLOSED: 'muted' }

export function NavigatorStaffPage() {
  const [state, setState] = useState('')
  const anns = useAsync(() => listAnnouncements({ receipt_state: state || undefined }), [state])
  const [selected, setSelected] = useState<number | null>(null)
  const [result, setResult] = useState<MatchRun | null>(null)
  const [filter, setFilter] = useState<Verdict | null>(null)
  const [company, setCompany] = useState<FullProfile | null>(null)
  const { busy, run } = useAction()

  useEffect(() => {
    if (selected == null && anns.data?.length) setSelected(anns.data[0].id)
  }, [anns.data, selected])

  useEffect(() => {
    if (selected == null) return
    setResult(null); setCompany(null); setFilter(null)
    void run(async () => setResult(await latestAnnouncementRun(selected)))
  }, [selected, run])

  const ann = anns.data?.find((a) => a.id === selected) ?? null
  const rerun = () => run(async () => setResult(await runAnnouncementMatching(selected!)))
  const recs = (result?.recommendations ?? []).filter((r) => !filter || r.verdict === filter)

  return (
    <>
      <PageHeader title="공고별 적합 기업" subtitle="Navigator 매칭 결과" />
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
              <>
                <RoleHint roles={['PLANNER']} />
                <button className="btn btn-primary" disabled={busy} onClick={() => void rerun()}>
                  {busy ? '매칭 중…' : result?.run ? '다시 매칭' : '매칭 실행'}
                </button>
              </>
            }>
              <div className="profile-line small">
                <span>{ann.announcement_no}</span>
                <span>{ann.agency_name}</span>
                {ann.program_name && <span>{ann.program_name}</span>}
                <span>접수 {fmtDay(ann.receipt_start)} ~ {fmtDay(ann.receipt_end)}</span>
                <span>자격요건 {ann.requirement_count}개 (필수 {ann.mandatory_count}) · 요구기술 {ann.tech_need_count}개</span>
                {ann.status !== 'PUBLISHED' && <span className="badge badge-warn">{ann.status === 'DRAFT' ? '작성중' : ann.status}</span>}
              </div>
              {result?.run && (
                <p className="small muted">
                  마지막 매칭 {fmtDate(result.run.created_at)} · 후보 {result.run.candidate_count}곳 · 모델 {result.run.model}
                </p>
              )}
            </Card>
          )}

          {result && (
            <Card title="판정 결과" actions={<VerdictSummary run={result} />}>
              {!result.run ? <Empty>매칭 이력이 없습니다.</Empty> : (
                <>
                  <div className="chips" style={{ marginTop: 0, marginBottom: 10 }}>
                    <button className={`chip ${!filter ? 'chip-on' : ''}`} onClick={() => setFilter(null)}>전체</button>
                    {(['ELIGIBLE', 'NEEDS_INFO', 'INELIGIBLE'] as Verdict[]).map((v) => (
                      <button key={v} className={`chip ${filter === v ? 'chip-on' : ''}`} onClick={() => setFilter(v)}>
                        {VERDICT_LABELS[v]} {result.summary[v]}
                      </button>
                    ))}
                  </div>
                  {recs.length === 0 ? <Empty>해당하는 기업이 없습니다.</Empty> : (
                    <ul className="match-list">
                      {recs.map((r) => (
                        <MatchItem key={r.id} rec={r}
                          title={<span><strong>{r.company_name}</strong> <span className="small muted">{fmtBrn(r.business_reg_no)}</span></span>}
                          onTitle={() => void run(async () => setCompany(await staffCompanyProfile(r.organization_id)))} />
                      ))}
                    </ul>
                  )}
                </>
              )}
            </Card>
          )}

          {company && <CompanyCard p={company} onClose={() => setCompany(null)} />}
        </div>
      </div>
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

function CompanyCard({ p, onClose }: { p: FullProfile; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }, [p.organization_id])
  return (
    <div ref={ref}>
    <Card title={`${p.company_name} 프로필`} actions={<button className="btn btn-sm" onClick={onClose}>닫기</button>}>
      <div className="profile-line small">
        <span>{p.business_reg_no}</span>
        <span>국세청 {p.biz_verify_label}</span>
        <span>{p.business_status_label}</span>
        {p.company_size && <span>{SIZE_LABELS[p.company_size] ?? p.company_size}</span>}
        {p.region && <span>{p.region}</span>}
        {p.employee_count != null && <span>근로자 {p.employee_count}명</span>}
        <span>매출 {fmtKrw(p.annual_revenue_krw)}</span>
        {p.registered_email && <span>연락 {p.registered_email}</span>}
      </div>
      {p.main_business && <p>{p.main_business}</p>}
      <div className="grid-2">
        <div>
          <h4>인증 {p.certifications.length}</h4>
          <ul className="plain-list small">
            {p.certifications.map((c) => <li key={c.id}>{c.cert_type_name}{c.is_expired ? ' (만료)' : ''}{c.is_verified ? ' (확인)' : ''}</li>)}
          </ul>
          <h4>신용등급 <span className="pill">담당자 전용</span></h4>
          <ul className="plain-list small">
            {p.credit_ratings.map((c) => <li key={c.id}>{c.agency} {c.grade} ({c.rated_on ?? '–'}){c.is_verified ? ' (확인)' : ' (자가입력)'}</li>)}
          </ul>
        </div>
        <div>
          <h4>특허 {p.patents.length}</h4>
          <ul className="plain-list small">{p.patents.map((x) => <li key={x.application_no}>{x.title}</li>)}</ul>
          <h4>R&amp;D 이력 {p.rnd_history.length}</h4>
          <ul className="plain-list small">
            {p.rnd_history.map((r) => <li key={r.id}>{r.title} ({r.role === 'LEAD' ? '주관' : '참여'})</li>)}
          </ul>
        </div>
      </div>
    </Card>
    </div>
  )
}
