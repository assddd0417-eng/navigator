import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  addConsultEvidence, createConsultation, createConsultRequest, deleteConsultEvidence, listConsultEvidence, getConsultation, getConsultationHistory, listConsultRequests, setConsultRequestStatus,
  getDiagnosisHistory, getDstateRules, growthRoute, previewDstate, reviewEligibility, runDstate, saveStaffDstateValues, searchConsultCompanies, getCompanyAccess,
  type ConsultCompany, type ConsultEvidence, type Consultation, type ConsultRequest, type DstateResult, type EligibilityReview, type DstateVariable, type GrowthRoute,
} from '../../api/navigator'
import { changedValues, DstateInput } from '../../components/DstateInput'
import { RadarChart } from '../../components/RadarChart'
import { useToast } from '../../components/Toast'
import { ConsultReportPanel } from './ConsultReportPanel'
import { EligibilityPanel } from './EligibilityPanel'
import { RoutePanel } from './RoutePanel'
import { GateLine } from '../../components/GateLine'
import { Card, Empty, fmtDate, PageHeader, useAction, useAsync } from '../../components/ui'

type Task = 'A' | 'B' | 'C'
type ResultTab = 'dstate' | 'qualify' | 'route' | 'report'

const TASKS: { code: Task; label: string; ready: boolean }[] = [
  { code: 'A', label: 'A. D-STATE 진단', ready: true },
  { code: 'B', label: 'B. 자격요건 검토 (A+B)', ready: true },
  { code: 'C', label: 'C. 종합 성장경로 (A+B+C)', ready: true },
]
const RESULT_TABS: { code: ResultTab; label: string; ready: boolean }[] = [
  { code: 'dstate', label: 'D-STATE 진단결과', ready: true },
  { code: 'qualify', label: '자격요건 검토', ready: true },
  { code: 'route', label: 'D-ROUTE 성장경로', ready: true },
  { code: 'report', label: '상담결과서', ready: true },
]

const fmtDelta = (n: number) => (n > 0 ? `+${n}` : n < 0 ? `${n}` : '변동 없음')

export function ConsultPage() {
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')
  const companies = useAsync(() => searchConsultCompanies(query), [query])
  useEffect(() => { // 입력하면 잠시 뒤 바로 찾는다 (Enter 를 몰라도 되게)
    const t = setTimeout(() => setQuery(q.trim()), 300)
    return () => clearTimeout(t)
  }, [q])
  // 고른 기업·열어 본 결과서는 주소에 남겨 새로고침·뒤로가기 후에도 이어서 본다
  const [params, setParams] = useSearchParams()
  const [orgId, setOrgId] = useState<number | null>(() => Number(params.get('org')) || null)
  const [openId] = useState<number | null>(() => Number(params.get('c')) || null)
  const [task, setTask] = useState<Task>('A')
  const [tab, setTab] = useState<ResultTab>('dstate')
  const [result, setResult] = useState<DstateResult | null>(null)
  const [concern, setConcern] = useState('')
  const [includeClosed, setIncludeClosed] = useState(false)
  const [elig, setElig] = useState<EligibilityReview | null>(null)
  const [route, setRoute] = useState<GrowthRoute | null>(null)
  const [histKey, setHistKey] = useState(0)
  const [consultation, setConsultation] = useState<Consultation | null>(null)
  const [requestId, setRequestId] = useState<number | null>(null)
  const [consultKey, setConsultKey] = useState(0)
  const [evidenceIds, setEvidenceIds] = useState<number[]>([])
  const requests = useAsync(() => listConsultRequests(), [])
  const { busy, run } = useAction()
  const toast = useToast()

  useEffect(() => {
    if (orgId == null) return
    setResult(null); setElig(null); setRoute(null); setConsultation(null); setEvidenceIds([])
    void run(async () => {
      setResult(await previewDstate(orgId))
      if (openId != null && Number(params.get('c')) === openId) { // 주소에 있던 결과서 다시 열기 (처음 한 번)
        const c = await getConsultation(openId)
        if (c.organization_id === orgId) { setConsultation(c); setTab('report') }
      }
    })
  }, [orgId, run]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const next = new URLSearchParams()
    if (orgId != null) next.set('org', String(orgId))
    if (consultation && consultation.organization_id === orgId) next.set('c', String(consultation.id))
    if (next.toString() !== params.toString()) setParams(next, { replace: true })
  }, [orgId, consultation]) // eslint-disable-line react-hooks/exhaustive-deps

  const company = companies.data?.find((c) => c.organization_id === orgId) ?? null
  const execute = () => run(async () => {
    setResult(await runDstate(orgId!))
    setHistKey((k) => k + 1)
    void companies.reload()
    if (task === 'A') setElig(null)
    if (task !== 'C') setRoute(null)
    const c = concern.trim() || undefined
    if (task === 'B' || task === 'C') {
      setElig(await reviewEligibility(orgId!, { concern: c, include_closed: includeClosed }))
      setTab('qualify')
    }
    if (task === 'C') {
      setRoute(await growthRoute(orgId!, { concern: c, include_closed: includeClosed }))
      setTab('route')
    }
    toast.show({ kind: 'success', title: '진단을 저장했습니다', message: '진단 이력에서 볼 수 있습니다.' })
  })

  const saveDraft = () => run(async () => {
    const c = await createConsultation(orgId!, { task, concern: concern.trim() || undefined, request_id: requestId ?? undefined,
      include_closed: includeClosed,
      evidence_ids: evidenceIds.length ? evidenceIds : undefined })
    setConsultation(c)
    setTab('report')
    setConsultKey((k) => k + 1)
    void requests.reload()
    toast.show({ kind: 'success', title: '상담결과서 초안을 저장했습니다', message: '내용을 고친 뒤 확정합니다.' })
  })
  const openConsultation = (id: number) => run(async () => {
    setConsultation(await getConsultation(id))
    setTab('report')
  })
  const pickRequest = (r: ConsultRequest) => {
    setOrgId(r.organization_id)
    setConcern(r.concern)
    setRequestId(r.id)
  }

  return (
    <>
      <PageHeader eyebrow="AI 서비스 포털 › 방산기업 성장경로" title="방산기업 성장경로 상담"
        subtitle="기업과 검토 업무를 고르면 성장준비도 진단, 자격요건 검토, 단계별 성장경로를 근거와 함께 보여 줍니다." />
      <div className="grid-side">
        <Card title={<><span className="step-label" style={{ display: 'block' }}>1단계</span>기업 및 수행 업무 선택</>}>
          <RequestList items={requests.data} loading={requests.loading} orgId={orgId} company={company}
            requestId={requestId} onPick={pickRequest} onChanged={() => void requests.reload()} />
          <form className="form-row" style={{ marginBottom: 10 }} onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()) }}>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="상호 또는 사업자번호" aria-label="기업 검색" />
          </form>
          {companies.loading ? <div className="page-loading">불러오는 중…</div> : !companies.data?.length ? <Empty>{query ? `‘${query}’에 맞는 기업이 없습니다.` : '기업이 없습니다.'}</Empty> : (
            <ul className="select-list">
              {companies.data.map((c) => <CompanyButton key={c.organization_id} c={c} on={c.organization_id === orgId}
                onClick={() => {
                  if (requestId != null) setConcern('')
                  setOrgId(c.organization_id); setRequestId(null)
                }} />)}
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
          {orgId != null && <EvidenceBlock key={orgId} orgId={orgId} checked={evidenceIds} onChecked={setEvidenceIds} />}
          {requestId != null && <div className="small muted" style={{ marginTop: 10 }}>상담 요청 {requestId}번에 연결됩니다.</div>}
          {(
            <label className="small muted" style={{ display: 'block', margin: '14px 0 6px' }}>상담 내용 (애로사항·관심분야)
              <textarea rows={3} value={concern} onChange={(e) => setConcern(e.target.value)} maxLength={2000}
                placeholder="사업 목적 부합 평가에 씁니다. 비워도 됩니다." />
              {concern.length > 1800 && <span className="small muted">{concern.length}/2000자</span>}
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
          <div className="step-label" style={{ marginBottom: -8 }}>2단계 결과 화면</div>
          {orgId == null ? <Card><Empty>왼쪽에서 상담할 기업을 고르세요.</Empty></Card> : (
            <>
              <AccessLine orgId={orgId} name={company?.name ?? result?.company_name ?? ''} />
              {result && (
                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <button className="btn btn-primary" disabled={busy} onClick={() => void saveDraft()}>결과 저장 · 상담결과서 초안</button>
                </div>
              )}
              <div className="seg tabs" role="tablist">
                {RESULT_TABS.map((t) => (
                  <button key={t.code} role="tab" className={tab === t.code ? 'on' : ''} disabled={!t.ready}
                    title={t.ready ? undefined : '다음 단계에서 연결'} onClick={() => setTab(t.code)}>{t.label}</button>
                ))}
              </div>
              {tab !== 'dstate' && tab !== 'qualify' && <GateLine gate="route" />}
              {tab === 'dstate' && <GateLine gate="dstate" />}
              {tab === 'qualify' && <GateLine gate="eligibility" />}
              {tab === 'dstate' && (!result ? <div className="page-loading">불러오는 중…</div> : (
                <DstatePanel result={result} company={company} onChange={setResult} orgId={orgId} />
              ))}
              {tab === 'qualify' && (elig ? <EligibilityPanel data={elig} />
                : <Card><Empty>검토 업무 B를 고르고 실행하면 결과가 나옵니다.</Empty></Card>)}
              {tab === 'route' && (route ? <RoutePanel data={route} />
                : <Card><Empty>검토 업무 C를 고르고 실행하면 결과가 나옵니다.</Empty></Card>)}
              {tab === 'report' && (consultation && consultation.organization_id === orgId
                ? <ConsultReportPanel key={`${consultation.id}-${consultKey}`} data={consultation}
                  onChange={(c) => { setConsultation(c); setConsultKey((k) => k + 1); void requests.reload() }} />
                : <Card><Empty>결과를 저장하거나 아래 상담 이력에서 고르면 상담결과서가 열립니다.</Empty></Card>)}
              <ConsultHistoryCard key={`c-${orgId}-${consultKey}`} orgId={orgId} onOpen={(id) => void openConsultation(id)} />
              {tab === 'dstate' && <HistoryCard key={`${orgId}-${histKey}`} orgId={orgId} />}
            </>
          )}
          <RulesCard />
          <p className="small muted">진단 결과는 상담 참고자료입니다. 확정과 기업 안내는 담당자가 판단합니다.</p>
        </div>
      </div>
    </>
  )
}

function EvidenceBlock({ orgId, checked, onChecked }: { orgId: number; checked: number[]; onChecked: (ids: number[]) => void }) {
  const list = useAsync(() => listConsultEvidence(orgId), [orgId])
  const [file, setFile] = useState<File | null>(null)
  const [note, setNote] = useState('')
  const [inputKey, setInputKey] = useState(0)
  const { busy, run } = useAction()
  const toast = useToast()
  const upload = () => run(async () => {
    const e = await addConsultEvidence(orgId, file!, note.trim() || undefined)
    setFile(null); setNote(''); setInputKey((k) => k + 1)
    onChecked([...checked, e.id])
    await list.reload()
    toast.show({ kind: 'success', title: '보완자료를 올렸습니다' })
  })
  const remove = (e: ConsultEvidence) => run(async () => {
    await deleteConsultEvidence(orgId, e.id)
    onChecked(checked.filter((id) => id !== e.id))
    await list.reload()
  })
  const toggle = (id: number) => onChecked(checked.includes(id) ? checked.filter((x) => x !== id) : [...checked, id])
  return (
    <div style={{ marginTop: 14 }}>
      <div className="small muted" style={{ marginBottom: 6 }}>보완자료 (선택)</div>
      {list.loading ? <div className="small muted">불러오는 중…</div> : !list.data?.length ? <div className="small muted">올라온 보완자료가 없습니다.</div> : (
        <ul className="select-list" style={{ maxHeight: 240 }}>
          {list.data.map((e) => (
            <li key={e.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 6, padding: '4px 0' }}>
              <input type="checkbox" checked={checked.includes(e.id)} onChange={() => toggle(e.id)} aria-label={`${e.file_name} 상담에 쓰기`} style={{ marginTop: 4, width: 'auto', flex: 'none' }} />
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ wordBreak: 'break-all' }}>{e.file_name}</span>
                <span className="small muted" style={{ display: 'block' }}>
                  {[e.origin_label, e.kind_label, e.note, fmtDate(e.created_at)].filter(Boolean).join(' · ')}
                </span>
              </span>
              {e.origin_label === '담당자 첨부' && (
                <button className="link-btn small" style={{ width: 'auto', flex: 'none', display: 'inline', padding: '0 4px', whiteSpace: 'nowrap' }} disabled={busy} onClick={() => void remove(e)}>삭제</button>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="stack" style={{ marginTop: 8 }}>
        <input key={inputKey} type="file" accept=".pdf,.hwp,.hwpx" aria-label="보완자료 파일" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="메모 (선택)" aria-label="보완자료 메모" maxLength={500} />
        <button className="btn btn-sm" disabled={busy || !file} onClick={() => void upload()}>{busy ? '올리는 중…' : '올리기'}</button>
      </div>
      <p className="small muted" style={{ marginTop: 6 }}>인증서·수출실적·보유기술 자료를 올리면 글자와 찾은 값만 남깁니다. 값은 진단 변수에서 확인해 넣습니다.</p>
    </div>
  )
}

function AccessLine({ orgId, name }: { orgId: number; name: string }) {
  const acc = useAsync(() => getCompanyAccess(orgId), [orgId])
  return (
    <div className="access-line">
      <strong>{name}</strong>
      {' · 열람 범위: '}{acc.data ? acc.data.text : acc.loading ? '확인 중…' : '확인하지 못했습니다.'}
    </div>
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

const STATUS_TONE: Record<string, string> = { REQUESTED: 'warn', IN_PROGRESS: 'info', DONE: 'ok', CANCELED: 'muted' }

function RequestList({ items, loading, orgId, company, requestId, onPick, onChanged }: {
  items: ConsultRequest[] | null; loading: boolean; orgId: number | null; company: ConsultCompany | null; requestId: number | null
  onPick: (r: ConsultRequest) => void; onChanged: () => void
}) {
  const [adding, setAdding] = useState(false)
  const [concern, setConcern] = useState('')
  const [interest, setInterest] = useState('')
  const { busy, run } = useAction()
  const toast = useToast()
  const open = (items ?? []).filter((r) => r.status === 'REQUESTED' || r.status === 'IN_PROGRESS')
  const add = () => run(async () => {
    await createConsultRequest(orgId!, { concern: concern.trim(), interest: interest.trim() || undefined })
    setConcern(''); setInterest(''); setAdding(false)
    onChanged()
    toast.show({ kind: 'success', title: '상담 요청을 등록했습니다' })
  })
  const cancel = (id: number) => run(async () => {
    await setConsultRequestStatus(id, 'CANCELED')
    onChanged()
  })
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="small muted">상담 요청</span>
        <button className="link-btn small" disabled={orgId == null} onClick={() => setAdding(!adding)}
          title={orgId == null ? '기업을 먼저 고르세요' : undefined}>{adding ? '닫기' : '요청 등록'}</button>
      </div>
      {adding && (
        <div className="stack" style={{ margin: '6px 0' }}>
          <div className="small muted">{company?.name ?? '선택한 기업'}의 요청으로 등록합니다.</div>
          <textarea rows={2} value={concern} onChange={(e) => setConcern(e.target.value)} placeholder="애로사항 (필수)" aria-label="애로사항" />
          <input value={interest} onChange={(e) => setInterest(e.target.value)} placeholder="관심 지원사업" aria-label="관심 지원사업" />
          <button className="btn btn-sm" disabled={busy || !concern.trim()} onClick={() => void add()}>등록</button>
        </div>
      )}
      {loading ? <div className="small muted">불러오는 중…</div> : !open.length ? <div className="small muted">대기 중인 요청이 없습니다.</div> : (
        <ul className="select-list" style={{ maxHeight: 220, marginTop: 6 }}>
          {open.map((r) => (
            <li key={r.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 4 }}>
              <button className={r.id === requestId ? 'on' : ''} style={{ flex: 1, minWidth: 0 }} onClick={() => onPick(r)}>
                <span>{r.company_name} <span className={`badge badge-${STATUS_TONE[r.status]}`}>{r.status_label}</span></span>
                <span className="small muted">{r.concern.split('\n')[0]}</span>
              </button>
              <button className="link-btn small" style={{ width: 'auto', padding: '8px 6px', flexShrink: 0 }} disabled={busy}
                title="요청 취소" onClick={() => void cancel(r.id)}>취소</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ConsultHistoryCard({ orgId, onOpen }: { orgId: number; onOpen: (id: number) => void }) {
  const hist = useAsync(() => getConsultationHistory(orgId), [orgId])
  return (
    <Card title="상담 이력">
      {hist.loading ? <div className="page-loading">불러오는 중…</div> : !hist.data?.length ? <Empty>저장된 상담이 없습니다.</Empty> : (
        <table className="table">
          <thead><tr><th>일시</th><th>업무</th><th>상태</th><th className="num">종합</th><th>상태유형</th><th className="num">신청 가능</th><th>수정</th><th>담당자</th></tr></thead>
          <tbody>
            {hist.data.map((h) => (
              <tr key={h.id} style={{ cursor: 'pointer' }} onClick={() => onOpen(h.id)}>
                <td>{fmtDate(h.created_at)}</td>
                <td>{h.task_label}</td>
                <td><span className={`badge badge-${h.status === 'CONFIRMED' ? 'ok' : 'warn'}`}>{h.status_label}</span></td>
                <td className="num">{h.total_score ?? '–'}</td>
                <td>{h.state_label ?? '–'}</td>
                <td className="num">{h.eligible_count ?? '–'}</td>
                <td className="small">판정 {h.override_count}건, 결과서 항목 {h.edited_sections.length}개</td>
                <td>{h.created_by_name ?? '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}
