import { useEffect, useState } from 'react'
import {
  getDiagnosisHistory, getDstateRules, growthRoute, previewDstate, reviewEligibility, runDstate, saveStaffDstateValues, searchConsultCompanies,
  type ConsultCompany, type DstateResult, type EligibilityReview, type DstateVariable, type GrowthRoute,
} from '../../api/navigator'
import { changedValues, DstateInput } from '../../components/DstateInput'
import { RadarChart } from '../../components/RadarChart'
import { useToast } from '../../components/Toast'
import { EligibilityPanel } from './EligibilityPanel'
import { RoutePanel } from './RoutePanel'
import { RouteRulesCard } from './RouteRulesCard'
import { Card, Empty, fmtDate, PageHeader, useAction, useAsync } from '../../components/ui'

type Task = 'A' | 'B' | 'C'
type ResultTab = 'dstate' | 'qualify' | 'route'

const TASKS: { code: Task; label: string; ready: boolean }[] = [
  { code: 'A', label: 'A. D-STATE 진단', ready: true },
  { code: 'B', label: 'B. 자격요건 검토 (A+B)', ready: true },
  { code: 'C', label: 'C. 종합 성장경로 (A+B+C)', ready: true },
]
const RESULT_TABS: { code: ResultTab; label: string; ready: boolean }[] = [
  { code: 'dstate', label: 'D-STATE 진단결과', ready: true },
  { code: 'qualify', label: '자격요건 검토', ready: true },
  { code: 'route', label: 'D-ROUTE 성장경로', ready: true },
]

const fmtDelta = (n: number) => (n > 0 ? `+${n}` : n < 0 ? `${n}` : '변동 없음')

export function ConsultPage() {
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')
  const companies = useAsync(() => searchConsultCompanies(query), [query])
  const [orgId, setOrgId] = useState<number | null>(null)
  const [task, setTask] = useState<Task>('A')
  const [tab, setTab] = useState<ResultTab>('dstate')
  const [result, setResult] = useState<DstateResult | null>(null)
  const [concern, setConcern] = useState('')
  const [includeClosed, setIncludeClosed] = useState(false)
  const [elig, setElig] = useState<EligibilityReview | null>(null)
  const [route, setRoute] = useState<GrowthRoute | null>(null)
  const [histKey, setHistKey] = useState(0)
  const { busy, run } = useAction()
  const toast = useToast()

  useEffect(() => {
    if (orgId == null) return
    setResult(null); setElig(null); setRoute(null)
    void run(async () => setResult(await previewDstate(orgId)))
  }, [orgId, run])

  const company = companies.data?.find((c) => c.organization_id === orgId) ?? null
  const execute = () => run(async () => {
    setResult(await runDstate(orgId!))
    setHistKey((k) => k + 1)
    const c = concern.trim() || undefined
    if (task === 'B' || task === 'C') {
      setElig(await reviewEligibility(orgId!, { concern: c, include_closed: includeClosed }))
      setTab('qualify')
    }
    if (task === 'C') {
      setRoute(await growthRoute(orgId!, { concern: c }))
      setTab('route')
    }
    toast.show({ kind: 'success', title: '진단을 저장했습니다', message: '진단 이력에서 볼 수 있습니다.' })
  })

  return (
    <>
      <PageHeader title="기업 상담" subtitle="기업과 검토 업무를 고르고 실행하면 상담에 쓸 결과가 나옵니다." />
      <div className="grid-side">
        <Card title="기업 및 검토 업무 선택">
          <form className="form-row" style={{ marginBottom: 10 }} onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()) }}>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="상호 또는 사업자번호" aria-label="기업 검색" />
          </form>
          {companies.loading ? <div className="page-loading">불러오는 중…</div> : !companies.data?.length ? <Empty>기업이 없습니다.</Empty> : (
            <ul className="select-list">
              {companies.data.map((c) => <CompanyButton key={c.organization_id} c={c} on={c.organization_id === orgId}
                onClick={() => setOrgId(c.organization_id)} />)}
            </ul>
          )}
          <div className="small muted" style={{ margin: '14px 0 6px' }}>검토 업무</div>
          <ul className="select-list">
            {TASKS.map((t) => (
              <li key={t.code}>
                <button className={task === t.code ? 'on' : ''} disabled={!t.ready} onClick={() => setTask(t.code)}>
                  <span>{t.label}</span>
                </button>
              </li>
            ))}
          </ul>
          {(task === 'B' || task === 'C') && (
            <label className="small muted" style={{ display: 'block', margin: '14px 0 6px' }}>상담 내용 (애로사항·관심분야)
              <textarea rows={3} value={concern} onChange={(e) => setConcern(e.target.value)}
                placeholder="사업 목적 부합 평가에 씁니다. 비워도 됩니다." />
            </label>
          )}
          {(task === 'B' || task === 'C') && (
            <label className="check small" style={{ marginTop: 8 }}>
              <input type="checkbox" checked={includeClosed} onChange={(e) => setIncludeClosed(e.target.checked)} /> 마감 공고 포함
            </label>
          )}
          <button className="btn btn-primary" style={{ marginTop: 12, width: '100%' }}
            disabled={busy || orgId == null} onClick={() => void execute()}>
            {busy ? '진단 중…' : '실행'}
          </button>
        </Card>

        <div className="stack">
          {orgId == null ? <Card><Empty>왼쪽에서 상담할 기업을 고르세요.</Empty></Card> : (
            <>
              <div className="seg tabs" role="tablist">
                {RESULT_TABS.map((t) => (
                  <button key={t.code} role="tab" className={tab === t.code ? 'on' : ''} disabled={!t.ready}
                    title={t.ready ? undefined : '다음 단계에서 연결'} onClick={() => setTab(t.code)}>{t.label}</button>
                ))}
              </div>
              {tab === 'dstate' && (!result ? <div className="page-loading">불러오는 중…</div> : (
                <DstatePanel result={result} company={company} onChange={setResult} orgId={orgId} />
              ))}
              {tab === 'qualify' && (elig ? <EligibilityPanel data={elig} />
                : <Card><Empty>검토 업무 B를 고르고 실행하면 결과가 나옵니다.</Empty></Card>)}
              {tab === 'route' && (route ? <RoutePanel data={route} />
                : <Card><Empty>검토 업무 C를 고르고 실행하면 결과가 나옵니다.</Empty></Card>)}
              {tab === 'dstate' && <HistoryCard key={`${orgId}-${histKey}`} orgId={orgId} />}
            </>
          )}
          <RulesCard />
          <RouteRulesCard />
          <p className="small muted">진단 결과는 상담 참고자료입니다. 확정과 기업 안내는 담당자가 판단합니다.</p>
        </div>
      </div>
    </>
  )
}

function CompanyButton({ c, on, onClick }: { c: ConsultCompany; on: boolean; onClick: () => void }) {
  return (
    <li>
      <button className={on ? 'on' : ''} onClick={onClick}>
        <span>{c.name}</span>
        <span className="small muted">
          {[c.business_reg_no, c.region, c.last_diagnosed_at ? `진단 ${fmtDate(c.last_diagnosed_at)}` : '진단 전'].filter(Boolean).join(' · ')}
        </span>
      </button>
    </li>
  )
}

function DstatePanel({ result, company, orgId, onChange }:
  { result: DstateResult; company: ConsultCompany | null; orgId: number; onChange: (r: DstateResult) => void }) {
  const prev = result.previous
  const radar = {
    company_count: 0,
    axes: result.areas.map((a) => ({
      code: a.code, label: a.label, value: a.score, average: null,
      note: `${a.formula}${a.missing.length ? ' (미확보 변수 있음)' : ''}`,
    })),
  }
  return (
    <>
      <Card title={`${result.company_name} D-STATE 진단결과`} actions={
        <span className="small muted">
          {result.diagnosis_id ? `저장 ${fmtDate(result.created_at)}` : '저장 전 미리보기'}
          {company?.business_reg_no ? ` · ${company.business_reg_no}` : ''}
        </span>
      }>
        <div className="grid-3" style={{ marginBottom: 14 }}>
          <Tile label="종합 준비도" value={`${result.total_score}점`} />
          <Tile label="우선 보완영역" value={result.weakest_label} />
          <Tile label="상태유형" value={result.state_label} />
        </div>
        <RadarChart radar={radar} who={result.company_name} />
        <h4>진단결과 요약</h4>
        <p>{result.summary}</p>
        {result.missing.length > 0 && (
          <div className="notice">미확보 변수 {result.missing.length}개는 추정하지 않고 비워 두었습니다. 값을 확인하면 점수가 달라질 수 있습니다.</div>
        )}
        <div className="grid-2" style={{ marginTop: 14 }}>
          <div>
            <h4>강점</h4>
            {result.strengths.length ? <ul>{result.strengths.map((s) => <li key={s.area}>{s.label} : {s.text}</li>)}</ul> : <p className="muted">없음</p>}
          </div>
          <div>
            <h4>우선 보완과제</h4>
            {result.tasks.length ? <ul>{result.tasks.map((t) => <li key={t.area}>{t.label} : {t.text}</li>)}</ul> : <p className="muted">없음</p>}
          </div>
        </div>
      </Card>

      {prev && (
        <Card title="직전 진단 대비" actions={<span className="small muted">{fmtDate(prev.created_at)} 진단</span>}>
          <p>
            종합 {prev.total_score}점에서 {result.total_score}점, <strong>{fmtDelta(result.total_score - prev.total_score)}</strong>
            {prev.state_type !== result.state_type && <> · 상태유형 {prev.state_label}에서 {result.state_label}</>}
          </p>
          <div className="chips" style={{ marginTop: 0 }}>
            {result.areas.map((a) => {
              const d = a.score - (prev.scores[a.code] ?? 0)
              return <span key={a.code} className={`badge badge-${d > 0 ? 'ok' : d < 0 ? 'bad' : 'muted'}`}>{a.label} {fmtDelta(d)}</span>
            })}
          </div>
        </Card>
      )}

      <Card title="영역별 점수">
        <table className="table">
          <thead><tr><th>영역</th><th className="num">점수</th><th>산정식</th><th>반영 항목</th></tr></thead>
          <tbody>
            {result.areas.map((a) => (
              <tr key={a.code}>
                <td>{a.label}</td>
                <td className="num">{a.score}</td>
                <td className="small">{a.formula}</td>
                <td className="small">
                  {a.items.map((it) => {
                    const name = result.variables.find((v) => v.code === it.variable)?.name ?? it.variable
                    const miss = a.missing.includes(it.variable)
                    return <div key={it.variable}>{name} {it.points}점 {miss && <span className="badge badge-warn">미확보</span>}</div>
                  })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <VariablesCard key={`${orgId}-${result.diagnosis_id}-${result.variables.map((v) => v.display).join('|')}`}
        vars={result.variables} orgId={orgId} onSaved={onChange} />
    </>
  )
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="card" style={{ textAlign: 'center' }}>
      <div className="small muted">{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700 }}>{value}</div>
    </div>
  )
}

function VariablesCard({ vars, orgId, onSaved }: { vars: DstateVariable[]; orgId: number; onSaved: (r: DstateResult) => void }) {
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const { busy, run } = useAction()
  const toast = useToast()
  const values = changedValues(vars, drafts)
  const count = Object.keys(values).length
  const save = () => run(async () => {
    onSaved(await saveStaffDstateValues(orgId, values))
    setDrafts({})
    toast.show({ kind: 'success', title: '값을 저장했습니다', message: '진단 결과를 다시 계산했습니다.' })
  })
  return (
    <Card title="진단 변수" actions={
      <button className="btn btn-primary" disabled={busy || count === 0} onClick={() => void save()}>
        {busy ? '저장 중…' : count ? `${count}개 저장` : '저장'}
      </button>
    }>
      <p className="small muted">확인되지 않은 값은 추정하지 않고 미확보로 둡니다. 담당자가 입력한 값이 기업 답변보다 먼저 쓰입니다.</p>
      <table className="table">
        <thead><tr><th>변수</th><th>값</th><th>출처</th><th>확인일</th><th>영역</th></tr></thead>
        <tbody>
          {vars.map((v) => {
            const editable = v.value_type !== 'PROFILE'
            return (
              <tr key={v.code} title={v.definition}>
                <td>{v.name}</td>
                <td>
                  {editable ? (
                    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                      <DstateInput v={v} draft={drafts[v.code]} onChange={(d) => setDrafts({ ...drafts, [v.code]: d })} />
                      {(drafts[v.code] ?? (v.value == null ? '' : String(v.value))) !== '' && (
                        <button className="btn btn-sm" onClick={() => setDrafts({ ...drafts, [v.code]: '' })}>지우기</button>
                      )}
                    </span>
                  ) : v.missing ? <span className="badge badge-warn">미확보</span> : v.display}
                  {editable && v.missing && drafts[v.code] === undefined && <> <span className="badge badge-warn">미확보</span></>}
                  {!editable && <div className="small muted">회사 정보에서 고칩니다</div>}
                </td>
                <td className="small">{v.source_label ?? '–'}</td>
                <td className="small">{v.checked_on ?? '–'}</td>
                <td className="small">{v.areas_label.join(', ')}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </Card>
  )
}

function HistoryCard({ orgId }: { orgId: number }) {
  const hist = useAsync(() => getDiagnosisHistory(orgId), [orgId])
  return (
    <Card title="진단 이력">
      {hist.loading ? <div className="page-loading">불러오는 중…</div> : !hist.data?.length ? <Empty>저장된 진단이 없습니다.</Empty> : (
        <table className="table">
          <thead><tr><th>일시</th><th className="num">종합</th><th>상태유형</th><th>우선 보완영역</th><th>담당자</th></tr></thead>
          <tbody>
            {hist.data.map((h) => (
              <tr key={h.id}>
                <td>{fmtDate(h.created_at)}</td>
                <td className="num">{h.total_score}</td>
                <td>{h.state_label}</td>
                <td>{h.weakest_label ?? '–'}</td>
                <td>{h.created_by_name ?? '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}

function RulesCard() {
  const [open, setOpen] = useState(false)
  const rules = useAsync(() => (open ? getDstateRules() : Promise.resolve(null)), [open])
  return (
    <Card title="진단 기준" actions={<button className="btn btn-sm" onClick={() => setOpen(!open)}>{open ? '접기' : '펼치기'}</button>}>
      {!open ? <p className="small muted">영역별 산정식과 상태유형 조건을 볼 수 있습니다.</p>
        : !rules.data ? <div className="page-loading">불러오는 중…</div> : (
          <>
            <h4>영역별 산정식</h4>
            <table className="table">
              <tbody>{rules.data.areas.map((a) => <tr key={a.code}><td>{a.label}</td><td className="small">{a.formula}</td></tr>)}</tbody>
            </table>
            <h4>상태유형 조건</h4>
            <table className="table">
              <tbody>{rules.data.state_types.map((s) => <tr key={s.code}><td>{s.label}</td><td className="small">{s.condition}</td></tr>)}</tbody>
            </table>
            <p className="small muted">기준 버전 {rules.data.rule_version}</p>
          </>
        )}
    </Card>
  )
}
