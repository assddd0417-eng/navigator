/**
 * 관리 링크로 여는 기업 화면 (로그인 없음): 내 맞는 공고(전부) · 보완질문 답하기 · 내 정보 고치기.
 * 링크 형식: /navigator/manage#t=<비밀값>. 비밀값은 세션 저장소에만 두고 주소창에서는 지운다.
 */
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../../api/client'
import {
  answerQuestions, CERT_TYPES, getMyMatches, getMyProfile, getMyQuestions, REGIONS, SIZE_LABELS, updateMyProfile,
  VERDICT_LABELS, type FullProfile, type MatchRun, type ProfileUpdate, type Question, type Verdict,
} from '../../api/navigator'
import { useToast } from '../../components/Toast'
import { Card, Empty, useAction } from '../../components/ui'
import { CompanyShell, fmtDay, MatchItem, VerdictSummary } from './components'

const TOKEN_KEY = 'navigator.manageToken'

function readToken(): string | null {
  const m = window.location.hash.match(/[#&]t=([^&]+)/)
  if (m) {
    const t = decodeURIComponent(m[1])
    try { sessionStorage.setItem(TOKEN_KEY, t) } catch { /* 저장소를 못 쓰면 이번 화면에서만 */ }
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
    return t
  }
  try { return sessionStorage.getItem(TOKEN_KEY) } catch { return null }
}

type Tab = 'matches' | 'questions' | 'profile'

export function CompanyManagePage() {
  const [token] = useState(readToken)
  const [tab, setTab] = useState<Tab>('matches')
  const [profile, setProfile] = useState<FullProfile | null>(null)
  const [invalid, setInvalid] = useState<string | null>(token ? null : '관리 링크가 없습니다.')
  const [matches, setMatches] = useState<MatchRun | null>(null)
  const [questions, setQuestions] = useState<Question[] | null>(null)
  const [includeClosed, setIncludeClosed] = useState(false)
  const { busy, run } = useAction()

  const loadMatches = useCallback((closed: boolean, refresh = false) => run(async () => {
    setMatches(await getMyMatches(token!, { include_closed: closed, refresh }))
  }), [run, token])
  const loadQuestions = useCallback(() => run(async () => setQuestions((await getMyQuestions(token!)).questions)),
    [run, token])

  useEffect(() => {
    if (!token) return
    getMyProfile(token)
      .then((p) => { setProfile(p); void loadMatches(false); void loadQuestions() })
      .catch((e) => setInvalid(e instanceof ApiError ? e.detail : '관리 링크를 확인하지 못했습니다.'))
  }, [token, loadMatches, loadQuestions])

  const logout = () => {
    try { sessionStorage.removeItem(TOKEN_KEY) } catch { /* 무시 */ }
    window.location.assign('/navigator')
  }

  if (invalid) {
    return (
      <CompanyShell>
        <Card title="관리 링크로 열 수 없습니다">
          <p>{invalid}</p>
          <p className="muted">사업자등록번호로 찾은 뒤 "관리 링크 이메일로 받기"를 누르면 등록 이메일로 새 링크가 갑니다.</p>
          <Link className="btn btn-primary" to="/navigator">사업자번호로 찾기</Link>
        </Card>
      </CompanyShell>
    )
  }
  if (!profile) return <CompanyShell><div className="page-loading">관리 링크를 확인하는 중…</div></CompanyShell>

  const qCount = questions?.length ?? 0
  return (
    <CompanyShell right={<button className="btn btn-ghost" onClick={logout}>이 기기에서 나가기</button>}>
      <div className="page-header">
        <div>
          <h1>{profile.company_name}</h1>
          <p>
            {profile.business_reg_no} · 국세청 {profile.biz_verify_label} · {profile.business_status_label}
            {profile.access_link && <> · 관리 링크 {fmtDay(profile.access_link.expires_at)}까지</>}
          </p>
        </div>
      </div>
      <div className="seg tabs" role="tablist">
        <button role="tab" className={tab === 'matches' ? 'on' : ''} onClick={() => setTab('matches')}>맞는 공고</button>
        <button role="tab" className={tab === 'questions' ? 'on' : ''} onClick={() => setTab('questions')}>
          보완질문 {qCount > 0 && <span className="tab-count">{qCount}</span>}
        </button>
        <button role="tab" className={tab === 'profile' ? 'on' : ''} onClick={() => setTab('profile')}>내 정보</button>
      </div>

      {tab === 'matches' && (
        <Card title="지원할 만한 공고" actions={
          <>
            <label className="check small">
              <input type="checkbox" checked={includeClosed}
                onChange={(e) => { setIncludeClosed(e.target.checked); void loadMatches(e.target.checked) }} />
              마감 공고도
            </label>
            <button className="btn btn-sm" disabled={busy} onClick={() => void loadMatches(includeClosed, true)}>다시 판정</button>
          </>
        }>
          {!matches ? <div className="page-loading">판정하는 중…</div> : (
            <>
              <VerdictSummary run={matches} />
              {qCount > 0 && (
                <div className="notice">
                  정보가 부족해 판정하지 못한 요건이 {qCount}개 있습니다.{' '}
                  <button className="link-btn" onClick={() => setTab('questions')}>보완질문에 답하기 →</button>
                </div>
              )}
              {matches.recommendations.length === 0 ? <Empty>비교할 공고가 없습니다.</Empty> : (
                <ul className="match-list">
                  {matches.recommendations.map((r) => (
                    <MatchItem key={r.id} rec={r} title={
                      <span><strong>{r.announcement_title}</strong> <span className="small muted">{r.agency_name} · {r.receipt_state === 'CLOSED' ? '마감' : `마감 ${fmtDay(r.receipt_end)}`}</span></span>
                    } />
                  ))}
                </ul>
              )}
            </>
          )}
        </Card>
      )}

      {tab === 'questions' && (
        <QuestionsPanel token={token!} questions={questions} onAnswered={(res) => {
          setMatches(res)
          void loadQuestions()
        }} />
      )}

      {tab === 'profile' && (
        <ProfilePanel token={token!} profile={profile} onSaved={(p) => {
          setProfile(p)
          void loadMatches(includeClosed)
          void loadQuestions()
        }} />
      )}
    </CompanyShell>
  )
}

// ---------------------------------------------------------------------------
function QuestionsPanel({ token, questions, onAnswered }: {
  token: string
  questions: Question[] | null
  onAnswered: (res: MatchRun) => void
}) {
  const [values, setValues] = useState<Record<number, string>>({})
  const { busy, run } = useAction()
  const toast = useToast()

  if (!questions) return <div className="page-loading">불러오는 중…</div>
  if (questions.length === 0) {
    return <Card><Empty>남은 보완질문이 없습니다. 판정에 필요한 정보가 모두 있습니다.</Empty></Card>
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const answers = questions.filter((q) => values[q.requirement_id] !== undefined && values[q.requirement_id] !== '')
      .map((q) => ({
        requirement_id: q.requirement_id,
        value: q.answer_type === 'integer' ? Number(values[q.requirement_id]) : values[q.requirement_id] === 'yes',
      }))
    if (answers.length === 0) {
      toast.show({ kind: 'info', title: '답한 질문이 없습니다', message: '하나 이상 답한 뒤 저장하세요.' })
      return
    }
    void run(async () => {
      const res = await answerQuestions(token, answers)
      const counts = (['ELIGIBLE', 'NEEDS_INFO', 'INELIGIBLE'] as Verdict[])
        .map((v) => `${VERDICT_LABELS[v]} ${res.summary[v]}`).join(' · ')
      toast.show({ kind: 'success', title: `답 ${answers.length}개를 저장하고 다시 판정했습니다`, message: counts })
      setValues({})
      onAnswered(res)
    })
  }

  return (
    <Card title="보완질문">
      <p className="small muted">답은 "자가 신고"로 표시되며, 공고 접수 때 증빙을 요구받을 수 있습니다.</p>
      <form className="form" onSubmit={submit}>
        <ul className="question-list">
          {questions.map((q) => (
            <li key={q.requirement_id}>
              <div className="small muted">{q.announcement_title} · {q.mandatory_label} 요건 “{q.requirement}”</div>
              <div className="question-text">{q.question}</div>
              {q.answer_type === 'integer' ? (
                <label className="inline">TRL
                  <input type="number" min={1} max={9} value={values[q.requirement_id] ?? ''}
                    onChange={(e) => setValues({ ...values, [q.requirement_id]: e.target.value })} />
                </label>
              ) : (
                <div className="seg">
                  {[['yes', '예'], ['no', '아니오']].map(([v, l]) => (
                    <button type="button" key={v} className={values[q.requirement_id] === v ? 'on' : ''}
                      onClick={() => setValues({ ...values, [q.requirement_id]: v })}>{l}</button>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
        <div className="form-foot">
          <button className="btn btn-primary" disabled={busy}>{busy ? '다시 판정하는 중…' : '답 저장하고 다시 판정'}</button>
        </div>
      </form>
    </Card>
  )
}

// ---------------------------------------------------------------------------
type CertRow = { cert_type_code: string; cert_no: string; issued_on: string; expires_on: string }
type CreditRow = { agency: string; grade: string; rated_on: string; valid_until: string }
type RndRow = { title: string; funding_agency: string; start_date: string; end_date: string; role: 'LEAD' | 'PARTICIPANT' }

const ORIGIN_LABELS: Record<string, string> = { SELF: '자가입력', EXTERNAL: '외부 확인', INTERNAL: '기관 내부', STAFF: '담당자 입력' }
const s = (v: string | number | null | undefined) => (v == null ? '' : String(v))
const orNull = (v: string) => (v.trim() === '' ? null : v.trim())

function ProfilePanel({ token, profile, onSaved }: {
  token: string
  profile: FullProfile
  onSaved: (p: FullProfile) => void
}) {
  const [f, setF] = useState({
    company_name: profile.company_name, main_business: s(profile.main_business), homepage: s(profile.homepage),
    company_size: s(profile.company_size), established_on: s(profile.established_on),
    employee_count: s(profile.employee_count), annual_revenue_krw: s(profile.annual_revenue_krw),
    revenue_year: s(profile.revenue_year), region: s(profile.region), address: s(profile.address),
  })
  const [certs, setCerts] = useState<CertRow[]>(profile.certifications.filter((c) => c.origin === 'SELF').map((c) => ({
    cert_type_code: c.cert_type_code, cert_no: s(c.cert_no), issued_on: s(c.issued_on), expires_on: s(c.expires_on) })))
  const [credits, setCredits] = useState<CreditRow[]>(profile.credit_ratings.filter((c) => c.origin === 'SELF').map((c) => ({
    agency: c.agency, grade: c.grade, rated_on: s(c.rated_on), valid_until: s(c.valid_until) })))
  const [rnds, setRnds] = useState<RndRow[]>(profile.rnd_history.filter((r) => r.origin === 'SELF').map((r) => ({
    title: r.title, funding_agency: s(r.funding_agency), start_date: s(r.start_date), end_date: s(r.end_date), role: r.role })))
  const { busy, run } = useAction()
  const toast = useToast()
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })

  const save = (e: FormEvent) => {
    e.preventDefault()
    const body: ProfileUpdate = {
      company_name: f.company_name.trim(), main_business: orNull(f.main_business), homepage: orNull(f.homepage),
      company_size: orNull(f.company_size), established_on: orNull(f.established_on),
      employee_count: f.employee_count ? Number(f.employee_count) : null,
      annual_revenue_krw: f.annual_revenue_krw ? Number(f.annual_revenue_krw) : null,
      revenue_year: f.revenue_year ? Number(f.revenue_year) : null, region: orNull(f.region), address: orNull(f.address),
      certifications: certs.filter((c) => c.cert_type_code).map((c) => ({ cert_type_code: c.cert_type_code,
        cert_no: orNull(c.cert_no), issued_on: orNull(c.issued_on), expires_on: orNull(c.expires_on) })),
      credit_ratings: credits.filter((c) => c.grade.trim()).map((c) => ({ agency: c.agency, grade: c.grade.trim().toUpperCase(),
        rated_on: orNull(c.rated_on), valid_until: orNull(c.valid_until) })),
      rnd_history: rnds.filter((r) => r.title.trim()).map((r) => ({ title: r.title.trim(), funding_agency: orNull(r.funding_agency),
        start_date: orNull(r.start_date), end_date: orNull(r.end_date), role: r.role })),
    }
    void run(async () => {
      const p = await updateMyProfile(token, body)
      toast.show({ kind: 'success', title: '저장했습니다', message: '바뀐 정보로 맞는 공고를 다시 판정합니다.' })
      onSaved(p)
    })
  }

  const readonly = (origin: string) => origin !== 'SELF'
  return (
    <form className="stack" onSubmit={save}>
      <Card title="기본 정보" actions={<span className="small muted">바꾼 값은 "자가입력·미확인"으로 기록됩니다</span>}>
        <div className="form">
          <div className="form-row">
            <label className="grow">회사 이름<input required value={f.company_name} onChange={set('company_name')} /></label>
            <label>대표자명 (진위확인 값)<input value={s(profile.representative_name)} disabled /></label>
            <label>개업일 (진위확인 값)<input value={s(profile.opened_on)} disabled /></label>
          </div>
          <label>주요 사업<textarea rows={2} value={f.main_business} onChange={set('main_business')} /></label>
          <div className="form-row">
            <label>기업 규모
              <select value={f.company_size} onChange={set('company_size')}>
                <option value="">선택 안 함</option>
                {Object.entries(SIZE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <label>상시 근로자 수<input type="number" min={0} value={f.employee_count} onChange={set('employee_count')} /></label>
            <label>연매출 (원)<input type="number" min={0} value={f.annual_revenue_krw} onChange={set('annual_revenue_krw')} /></label>
            <label>매출 기준 연도<input type="number" value={f.revenue_year} onChange={set('revenue_year')} /></label>
          </div>
          <div className="form-row">
            <label>본사 시·도
              <select value={f.region} onChange={set('region')}>
                <option value="">선택 안 함</option>
                {REGIONS.map((r) => <option key={r}>{r}</option>)}
              </select>
            </label>
            <label className="grow">주소<input value={f.address} onChange={set('address')} /></label>
            <label className="grow">홈페이지<input value={f.homepage} onChange={set('homepage')} /></label>
          </div>
          {profile.field_sources.some((x) => x.differs) && (
            <div className="notice small">
              외부에서 확인된 값과 다른 칸이 있습니다: {profile.field_sources.filter((x) => x.differs).map((x) => x.field_name).join(', ')}.
              판정에는 외부에서 확인된 값을 먼저 씁니다.
            </div>
          )}
        </div>
      </Card>

      <Card title="인증·지정">
        <ReadonlyRows rows={profile.certifications.filter((c) => readonly(c.origin)).map((c) =>
          `${c.cert_type_name}${c.expires_on ? ` (만료 ${c.expires_on})` : ''} · ${ORIGIN_LABELS[c.origin] ?? c.origin}`)} />
        <EditRows rows={certs} setRows={setCerts} empty={{ cert_type_code: 'VENTURE', cert_no: '', issued_on: '', expires_on: '' }}
          addLabel="인증 추가" render={(r, upd) => (
            <>
              <label>종류
                <select value={r.cert_type_code} onChange={(e) => upd({ cert_type_code: e.target.value })}>
                  {Object.entries(CERT_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>
              <label>번호<input value={r.cert_no} onChange={(e) => upd({ cert_no: e.target.value })} /></label>
              <label>발급일<input type="date" value={r.issued_on} onChange={(e) => upd({ issued_on: e.target.value })} /></label>
              <label>만료일<input type="date" value={r.expires_on} onChange={(e) => upd({ expires_on: e.target.value })} /></label>
            </>
          )} />
      </Card>

      <Card title="신용등급" actions={<span className="small muted">우리 회사와 권한 있는 기관 담당자만 봅니다 · AI 에 보내지 않습니다</span>}>
        <ReadonlyRows rows={profile.credit_ratings.filter((c) => readonly(c.origin)).map((c) =>
          `${c.agency} ${c.grade} (${c.rated_on ?? '평가일 없음'}) · ${ORIGIN_LABELS[c.origin] ?? c.origin}`)} />
        <EditRows rows={credits} setRows={setCredits} empty={{ agency: 'SELF', grade: '', rated_on: '', valid_until: '' }}
          addLabel="등급 추가" render={(r, upd) => (
            <>
              <label>평가기관
                <select value={r.agency} onChange={(e) => upd({ agency: e.target.value })}>
                  {['NICE', 'KED', 'SELF', 'OTHER'].map((a) => <option key={a}>{a}</option>)}
                </select>
              </label>
              <label>등급<input value={r.grade} placeholder="예: BBB-" onChange={(e) => upd({ grade: e.target.value })} /></label>
              <label>평가일<input type="date" value={r.rated_on} onChange={(e) => upd({ rated_on: e.target.value })} /></label>
              <label>유효기간<input type="date" value={r.valid_until} onChange={(e) => upd({ valid_until: e.target.value })} /></label>
            </>
          )} />
      </Card>

      <Card title="R&D 수행 이력">
        <ReadonlyRows rows={profile.rnd_history.filter((r) => readonly(r.origin)).map((r) =>
          `${r.title} (${r.role === 'LEAD' ? '주관' : '참여'}, ~${r.end_date ?? '진행 중'}) · ${ORIGIN_LABELS[r.origin] ?? r.origin}`)} />
        <EditRows rows={rnds} setRows={setRnds}
          empty={{ title: '', funding_agency: '', start_date: '', end_date: '', role: 'LEAD' as const }}
          addLabel="과제 추가" render={(r, upd) => (
            <>
              <label className="grow">과제명<input value={r.title} onChange={(e) => upd({ title: e.target.value })} /></label>
              <label>전담기관<input value={r.funding_agency} onChange={(e) => upd({ funding_agency: e.target.value })} /></label>
              <label>역할
                <select value={r.role} onChange={(e) => upd({ role: e.target.value as 'LEAD' | 'PARTICIPANT' })}>
                  <option value="LEAD">주관</option><option value="PARTICIPANT">참여</option>
                </select>
              </label>
              <label>시작<input type="date" value={r.start_date} onChange={(e) => upd({ start_date: e.target.value })} /></label>
              <label>종료<input type="date" value={r.end_date} onChange={(e) => upd({ end_date: e.target.value })} /></label>
            </>
          )} />
      </Card>

      <Card title="특허">
        {profile.patents.length === 0 ? <Empty>등록된 특허가 없습니다.</Empty> : (
          <ul className="plain-list small">
            {profile.patents.map((p) => (
              <li key={p.application_no}>{p.title} <span className="muted">{p.application_no} · {p.ipc_codes.join(', ')}</span></li>
            ))}
          </ul>
        )}
        <p className="small muted">특허는 특허청(KIPRIS) 자동 수집(6단계)과 함께 고칠 수 있게 합니다.</p>
      </Card>

      <div className="form-foot sticky-foot">
        <button className="btn btn-primary" disabled={busy}>{busy ? '저장하는 중…' : '저장하고 다시 판정'}</button>
      </div>
    </form>
  )
}

function ReadonlyRows({ rows }: { rows: string[] }) {
  if (rows.length === 0) return null
  return (
    <ul className="plain-list small">
      {rows.map((r, i) => <li key={i}>🔒 {r}</li>)}
    </ul>
  )
}

function EditRows<T extends object>({ rows, setRows, empty, render, addLabel }: {
  rows: T[]
  setRows: (rows: T[]) => void
  empty: T
  addLabel: string
  render: (row: T, update: (patch: Partial<T>) => void) => ReactNode
}) {
  return (
    <div className="form">
      {rows.map((r, i) => (
        <div key={i} className="form-row edit-row">
          {render(r, (patch) => setRows(rows.map((x, j) => (j === i ? { ...x, ...patch } : x))))}
          <button type="button" className="btn btn-sm btn-ghost" aria-label="지우기"
            onClick={() => setRows(rows.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <div><button type="button" className="btn btn-sm" onClick={() => setRows([...rows, { ...empty }])}>+ {addLabel}</button></div>
    </div>
  )
}
