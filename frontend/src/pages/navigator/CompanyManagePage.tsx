// /navigator/manage#t=<token>. 토큰은 sessionStorage 에 옮기고 주소창에서는 지운다.
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../../api/client'
import {
  answerQuestions, autofillProfile, CERT_TYPES, getMyAlerts, getMyMatches, getMyProfile, getMyQuestions, REGIONS, SIZE_LABELS, updateMyProfile,
  type FullProfile, type MatchRun, type ProfileUpdate, type Question,
} from '../../api/navigator'
import { useToast } from '../../components/Toast'
import { Card, Empty, useAction } from '../../components/ui'
import { AlertsPanel } from './AlertsPanel'
import { AGENCY_LABELS, bizStatus, CompanyShell, Deadline, fmtKrw, GroupedMatches, MatchCard } from './components'

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

type Tab = 'matches' | 'alerts' | 'profile'

export function CompanyManagePage() {
  const [token] = useState(readToken)
  const [tab, setTab] = useState<Tab>('matches')
  const [profile, setProfile] = useState<FullProfile | null>(null)
  const [invalid, setInvalid] = useState<string | null>(token ? null : '회사가 선택되지 않았습니다.')
  const [matches, setMatches] = useState<MatchRun | null>(null)
  const [questions, setQuestions] = useState<Question[] | null>(null)
  const [includeClosed, setIncludeClosed] = useState(false)
  const [unread, setUnread] = useState(0)
  const [profileKey, setProfileKey] = useState(0)
  const { run } = useAction()
  const toast = useToast()

  const loadMatches = useCallback((closed: boolean) => run(async () => {
    setMatches(await getMyMatches(token!, { include_closed: closed }))
  }), [run, token])
  const loadQuestions = useCallback(() => run(async () => setQuestions((await getMyQuestions(token!)).questions)),
    [run, token])

  useEffect(() => {
    if (!token) return
    getMyProfile(token)
      .then((p) => {
        setProfile(p); void loadMatches(false); void loadQuestions()
        getMyAlerts(token).then((a) => setUnread(a.unread)).catch(() => undefined)
      })
      .catch((e) => setInvalid(e instanceof ApiError ? e.detail : '회사 정보를 불러오지 못했습니다.'))
  }, [token, loadMatches, loadQuestions])

  const answer = async (answers: { requirement_id: number; value: number | boolean }[]) => {
    const before = matches?.summary.ELIGIBLE ?? 0
    const res = await answerQuestions(token!, answers)
    const gained = (res.summary.ELIGIBLE ?? 0) - before
    toast.show({ kind: 'success', title: '답변을 반영했습니다',
      message: gained > 0 ? `지원 가능 공고가 ${gained}건 늘었습니다.` : `지원 가능 ${res.summary.ELIGIBLE}건 · 확인 필요 ${res.summary.NEEDS_INFO}건` })
    if (includeClosed) void loadMatches(true)
    else setMatches(res)
    void loadQuestions()
  }

  const logout = () => {
    try { sessionStorage.removeItem(TOKEN_KEY) } catch { /* 무시 */ }
    window.location.assign('/navigator')
  }

  if (invalid) {
    return (
      <CompanyShell>
        <Card title="회사 정보를 열 수 없습니다">
          <p>{invalid}</p>
          <p className="muted">시간이 지났거나 다른 창에서 다시 열었을 수 있습니다. 사업자번호로 다시 조회해 주세요.</p>
          <Link className="btn btn-primary" to="/navigator">사업자번호로 조회</Link>
        </Card>
      </CompanyShell>
    )
  }
  if (!profile) return <CompanyShell><div className="page-loading">불러오는 중…</div></CompanyShell>

  const missing = missingFields(profile)
  const eligible = matches?.summary.ELIGIBLE ?? 0
  return (
    <CompanyShell right={<button className="topbar-link" onClick={logout}>나가기</button>}>
      <div className="page-header">
        <div>
          <h1>{profile.company_name}</h1>
          <p>
            사업자번호 {profile.business_reg_no} · 국세청 {profile.biz_verify_label} · {bizStatus(profile.business_status_label)}
          </p>
        </div>
      </div>
      <div className="seg tabs" role="tablist">
        <button role="tab" className={tab === 'matches' ? 'on' : ''} onClick={() => setTab('matches')}>
          지원 가능 공고 {matches && <span className="tab-count tab-count-ok">{eligible}</span>}
        </button>
        <button role="tab" className={tab === 'alerts' ? 'on' : ''} onClick={() => setTab('alerts')}>
          알림 {unread > 0 && <span className="tab-count">{unread}</span>}
        </button>
        <button role="tab" className={tab === 'profile' ? 'on' : ''} onClick={() => setTab('profile')}>
          회사 정보 {missing.length > 0 && <span className="tab-count">{missing.length}</span>}
        </button>
      </div>

      {tab === 'matches' && (
        <Card title="지원 가능 공고" actions={
          <label className="check small">
            <input type="checkbox" checked={includeClosed}
              onChange={(e) => { setIncludeClosed(e.target.checked); void loadMatches(e.target.checked) }} />
            마감된 공고도 보기
          </label>
        }>
          {missing.length > 0 && (
            <div className="notice small">
              회사 정보에 비어 있는 항목({missing.join(', ')})이 있어 일부 공고는 판정하지 못했습니다.{' '}
              <button className="link-btn" onClick={() => setTab('profile')}>회사 정보 채우기</button>
            </div>
          )}
          {!matches ? <div className="page-loading">불러오는 중…</div> : matches.recommendations.length === 0 ? (
            <div className="empty">지금 접수 중인 공고가 없습니다. 새 공고가 올라오면 알림으로 알려 드립니다.</div>
          ) : (
            <GroupedMatches run={matches} audience="company"
              hints={{ NEEDS_INFO: '아래 질문에 답하면 바로 다시 판정합니다' }}
              renderCard={(r) => (
                <MatchCard rec={r} audience="company" title={<strong>{r.announcement_title}</strong>}
                  meta={<>{r.agency_name} · <Deadline end={r.receipt_end} state={r.receipt_state} /></>}
                  questions={questions ?? []} onAnswer={answer} onEditProfile={() => setTab('profile')} />
              )} />
          )}
        </Card>
      )}

      {tab === 'alerts' && <AlertsPanel token={token!} onUnread={setUnread} />}

      {tab === 'profile' && (
        <ProfilePanel key={profileKey} token={token!} profile={profile} missing={missing} onSaved={(p) => {
          setProfile(p)
          setProfileKey((k) => k + 1)
          void loadMatches(includeClosed)
          void loadQuestions()
        }} />
      )}
    </CompanyShell>
  )
}

/** 판정에 쓰는데 비어 있는 항목 */
function missingFields(p: FullProfile): string[] {
  const out: string[] = []
  if (!p.main_business) out.push('주요 사업')
  if (!p.company_size) out.push('기업 규모')
  if (p.employee_count == null) out.push('근로자 수')
  if (p.annual_revenue_krw == null) out.push('매출')
  if (!p.region) out.push('소재지')
  if (p.rnd_history.length === 0) out.push('R&D 이력')
  return out
}

type CertRow = { cert_type_code: string; cert_no: string; issued_on: string; expires_on: string }
type CreditRow = { agency: string; grade: string; rated_on: string; valid_until: string }
type RndRow = { title: string; funding_agency: string; start_date: string; end_date: string; role: 'LEAD' | 'PARTICIPANT' }

const ORIGIN_LABELS: Record<string, string> = { SELF: '직접 입력', EXTERNAL: '공공데이터 확인', INTERNAL: '기관 보유 자료', STAFF: '담당자 입력' }
const FIELD_LABELS: Record<string, string> = {
  annual_revenue_krw: '매출', employee_count: '근로자 수', company_size: '기업 규모', region: '소재지', established_on: '설립일',
  company_name: '회사 이름', main_business: '주요 사업', address: '주소',
}
const s = (v: string | number | null | undefined) => (v == null ? '' : String(v))
const orNull = (v: string) => (v.trim() === '' ? null : v.trim())

function ProfilePanel({ token, profile, missing, onSaved }: {
  token: string
  profile: FullProfile
  missing: string[]
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
      toast.show({ kind: 'success', title: '저장했습니다', message: '바뀐 정보로 공고를 다시 판정했습니다.' })
      onSaved(p)
    })
  }

  const autofill = () => void run(async () => {
    const res = await autofillProfile(token)
    const ok = res.results.filter((r) => r.ok).map((r) => r.label)
    const failed = res.results.filter((r) => !r.ok).map((r) => r.label)
    toast.show({ kind: failed.length ? 'error' : 'success', title: '공공데이터로 채웠습니다',
      message: [ok.length && `가져옴: ${ok.join(', ')}`, failed.length && `연결 안 됨: ${failed.join(', ')}`].filter(Boolean).join(' · ') })
    onSaved(res.profile)
  })

  const readonly = (origin: string) => origin !== 'SELF'
  return (
    <form className="stack" onSubmit={save}>
      <div className="manage-box">
        <div>
          <strong>공공데이터로 자동 채우기</strong>
          <div className="small muted">국세청(휴·폐업), 특허청(특허), DART(매출·근로자 수)에서 가져와 ‘공공데이터 확인’으로 표시합니다. 인증·R&amp;D 이력은 아래에 직접 입력해 주세요.</div>
        </div>
        <button type="button" className="btn btn-primary" disabled={busy} onClick={autofill}>{busy ? '가져오는 중…' : '자동 채우기'}</button>
      </div>
      {missing.length > 0 && (
        <div className="notice small">비어 있는 항목: {missing.join(', ')}. 채울수록 판정이 정확해집니다.</div>
      )}
      <Card title="기본 정보" actions={<span className="small muted">직접 입력한 값은 기관 확인 전까지 ‘직접 입력’으로 표시됩니다</span>}>
        <div className="form">
          <div className="form-row">
            <label className="grow">회사 이름<input required value={f.company_name} onChange={set('company_name')} /></label>
            <label title="국세청 확인에 쓴 값이라 바꿀 수 없습니다">대표자명<input value={s(profile.representative_name)} disabled /></label>
            <label title="국세청 확인에 쓴 값이라 바꿀 수 없습니다">개업일<input value={s(profile.opened_on)} disabled /></label>
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
            <label>연매출 (원)
              <input type="number" min={0} step={1000000} value={f.annual_revenue_krw} onChange={set('annual_revenue_krw')} />
              {f.annual_revenue_krw && <span className="field-hint">{fmtKrw(Number(f.annual_revenue_krw))}</span>}</label>
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
              {profile.field_sources.filter((x) => x.differs).map((x) => FIELD_LABELS[x.field_name] ?? x.field_name).join(', ')}이(가)
              공공데이터 값과 다릅니다. 판정은 공공데이터 값으로 합니다.
            </div>
          )}
        </div>
      </Card>

      <Card title="인증·지정">
        <ReadonlyRows rows={profile.certifications.filter((c) => readonly(c.origin)).map((c) =>
          [`${c.cert_type_name}${c.expires_on ? ` (만료 ${c.expires_on})` : ''}`, ORIGIN_LABELS[c.origin] ?? c.origin])} />
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

      <Card title="신용등급" actions={<span className="small muted">회사와 기관 담당자만 볼 수 있습니다</span>}>
        <ReadonlyRows rows={profile.credit_ratings.filter((c) => readonly(c.origin)).map((c) =>
          [`${AGENCY_LABELS[c.agency] ?? c.agency} ${c.grade}${c.rated_on ? ` (${c.rated_on} 평가)` : ''}`, ORIGIN_LABELS[c.origin] ?? c.origin])} />
        <EditRows rows={credits} setRows={setCredits} empty={{ agency: 'NICE', grade: '', rated_on: '', valid_until: '' }}
          addLabel="등급 추가" render={(r, upd) => (
            <>
              <label>평가기관
                <select value={r.agency} onChange={(e) => upd({ agency: e.target.value })}>
                  {['NICE', 'KED', 'OTHER', ...(r.agency === 'SELF' ? ['SELF'] : [])].map((a) => <option key={a} value={a}>{AGENCY_LABELS[a]}</option>)}
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
          [`${r.title} (${r.role === 'LEAD' ? '주관' : '참여'}, ${r.end_date ? `~${r.end_date}` : '진행 중'})`, ORIGIN_LABELS[r.origin] ?? r.origin])} />
        <EditRows rows={rnds} setRows={setRnds}
          empty={{ title: '', funding_agency: '', start_date: '', end_date: '', role: 'LEAD' as const }}
          addLabel="과제 추가" render={(r, upd) => (
            <>
              <label className="grow">과제명<input value={r.title} onChange={(e) => upd({ title: e.target.value })} /></label>
              <label>지원 기관<input value={r.funding_agency} onChange={(e) => upd({ funding_agency: e.target.value })} /></label>
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
              <li key={p.application_no}>{p.title} <span className="muted">{p.registration_no ? `등록 ${p.registration_no}` : `출원 ${p.application_no}`}</span></li>
            ))}
          </ul>
        )}
        <p className="small muted">특허는 특허청 자료에서 가져옵니다. 빠진 특허가 있으면 기관 담당자에게 알려 주세요.</p>
      </Card>

      <div className="form-foot sticky-foot">
        <button className="btn btn-primary" disabled={busy}>{busy ? '저장 중…' : '저장하고 다시 판정'}</button>
      </div>
    </form>
  )
}

function ReadonlyRows({ rows }: { rows: [string, string][] }) {
  if (rows.length === 0) return null
  return (
    <ul className="plain-list small">
      {rows.map(([text, origin], i) => (
        <li key={i}>{text} <span className="badge badge-muted" title="확인된 자료라 여기서는 고칠 수 없습니다">{origin}</span></li>
      ))}
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
          <button type="button" className="btn btn-sm btn-ghost"
            onClick={() => setRows(rows.filter((_, j) => j !== i))}>삭제</button>
        </div>
      ))}
      <div><button type="button" className="btn btn-sm" onClick={() => setRows([...rows, { ...empty }])}>+ {addLabel}</button></div>
    </div>
  )
}
