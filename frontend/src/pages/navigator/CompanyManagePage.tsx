// /navigator/manage#t=<token>. 토큰은 sessionStorage 에 옮기고 주소창에서는 지운다.
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../../api/client'
import {
  answerQuestions, autofillProfile, createMyConsultRequest, getMyConsultations, CERT_TYPES, deleteEvidence, PRODUCT_CATEGORIES, SUPPORT_RESULTS, uploadEvidence, getMyAlerts, getMyDstate, getMyMatches, saveMyDstate, getMyProfile, getMyQuestions, REGIONS, SIZE_LABELS, updateMyProfile,
  type DstateVariable, type MyConsultation, type MyConsultRequest, type Evidence, type FullProfile, type MatchRun, type ProductCategory, type ProfileUpdate, type Question, type SupportResult,
} from '../../api/navigator'
import { useToast } from '../../components/Toast'
import { changedValues, DstateInput } from '../../components/DstateInput'
import { Card, Empty, fmtDate, useAction } from '../../components/ui'
import { AlertsPanel } from './AlertsPanel'
import { OutreachConsent } from './OutreachConsent'
import { PastPanel } from './PastPanel'
import { AGENCY_LABELS, bizStatus, CompanyShell, Deadline, fmtKrw, GroupedMatches, MatchCard } from './components'
import { RadarChart } from '../../components/RadarChart'

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

type Tab = 'matches' | 'past' | 'alerts' | 'manage'
/** 관리 탭 안의 화면 */
type ManageView = 'profile' | 'dstate' | 'consult' | 'recipients' | 'consent'

export function CompanyManagePage() {
  const [token] = useState(readToken)
  const [tab, setTab] = useState<Tab>('matches')
  const [manageView, setManageView] = useState<ManageView>('profile')
  const openProfile = () => { setTab('manage'); setManageView('profile') }
  const [profile, setProfile] = useState<FullProfile | null>(null)
  const [invalid, setInvalid] = useState<string | null>(token ? null : '회사가 선택되지 않았습니다.')
  const [matches, setMatches] = useState<MatchRun | null>(null)
  const [questions, setQuestions] = useState<Question[] | null>(null)
  const [unread, setUnread] = useState(0)
  const [dstateMissing, setDstateMissing] = useState<number | null>(null)
  const [profileKey, setProfileKey] = useState(0)
  const { run } = useAction()
  const toast = useToast()

  const loadMatches = useCallback(() => run(async () => setMatches(await getMyMatches(token!))), [run, token])
  const loadQuestions = useCallback(() => run(async () => setQuestions((await getMyQuestions(token!)).questions)),
    [run, token])

  useEffect(() => {
    if (!token) return
    getMyProfile(token)
      .then((p) => {
        setProfile(p); void loadMatches(); void loadQuestions()
        getMyAlerts(token).then((a) => setUnread(a.unread)).catch(() => undefined)
        getMyDstate(token).then((d) => setDstateMissing(d.missing.length)).catch(() => undefined)
      })
      .catch((e) => setInvalid(e instanceof ApiError ? e.detail : '회사 정보를 불러오지 못했습니다.'))
  }, [token, loadMatches, loadQuestions])

  const answer = async (answers: { requirement_id: number; value: number | boolean }[]) => {
    const before = matches?.summary.ELIGIBLE ?? 0
    const res = await answerQuestions(token!, answers)
    const gained = (res.summary.ELIGIBLE ?? 0) - before
    toast.show({ kind: 'success', title: '답변을 반영했습니다',
      message: gained > 0 ? `지원 가능 공고가 ${gained}건 늘었습니다.` : `지원 가능 ${res.summary.ELIGIBLE}건 · 확인 필요 ${res.summary.NEEDS_INFO}건` })
    setMatches(res)
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
        <button role="tab" className={tab === 'past' ? 'on' : ''} onClick={() => setTab('past')}>
          참여할 수 있었던 사업
        </button>
        <button role="tab" className={tab === 'alerts' ? 'on' : ''} onClick={() => setTab('alerts')}>
          알림 {unread > 0 && <span className="tab-count">{unread}</span>}
        </button>
        <button role="tab" className={tab === 'manage' ? 'on' : ''} onClick={() => setTab('manage')}>
          관리 {missing.length > 0 && <span className="tab-count">{missing.length}</span>}
        </button>
      </div>

      {tab === 'matches' && (
        <Card title="지원 가능 공고" actions={
          <button className="link-btn small" onClick={() => setTab('past')}>마감된 공고는 ‘참여할 수 있었던 사업’에서</button>
        }>
          {missing.length > 0 && (
            <div className="notice small">
              회사 정보에 비어 있는 항목({missing.join(', ')})이 있어 일부 공고는 판정하지 못했습니다.{' '}
              <button className="link-btn" onClick={openProfile}>회사 정보 채우기</button>
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
                  questions={questions ?? []} onAnswer={answer} onEditProfile={openProfile} />
              )} />
          )}
        </Card>
      )}

      {tab === 'past' && (
        <PastPanel key={profileKey} token={token!} onOpenCurrent={() => setTab('matches')} onEditProfile={openProfile} />
      )}

      {tab === 'alerts' && <AlertsPanel token={token!} onUnread={setUnread} part="alerts" />}

      {tab === 'manage' && (
        <div className="seg sub-tabs" role="tablist">
          <button role="tab" className={manageView === 'profile' ? 'on' : ''} onClick={() => setManageView('profile')}>
            회사 정보 {missing.length > 0 && <span className="tab-count">{missing.length}</span>}
          </button>
          <button role="tab" className={manageView === 'dstate' ? 'on' : ''} onClick={() => setManageView('dstate')}>
            성장 진단 정보 {dstateMissing != null && dstateMissing > 0 && <span className="tab-count">{dstateMissing}</span>}
          </button>
          <button role="tab" className={manageView === 'consult' ? 'on' : ''} onClick={() => setManageView('consult')}>
            상담
          </button>
          <button role="tab" className={manageView === 'recipients' ? 'on' : ''} onClick={() => setManageView('recipients')}>
            알림 받는 사람
          </button>
          <button role="tab" className={manageView === 'consent' ? 'on' : ''} onClick={() => setManageView('consent')}>
            참여 권유 동의
          </button>
        </div>
      )}

      {tab === 'manage' && manageView === 'dstate' && <DstatePanel token={token!} onMissing={setDstateMissing} />}

      {tab === 'manage' && manageView === 'consult' && <ConsultPanel token={token!} />}

      {tab === 'manage' && manageView === 'recipients' && <AlertsPanel token={token!} onUnread={setUnread} part="recipients" />}

      {tab === 'manage' && manageView === 'consent' && (
        <OutreachConsent token={token!} profile={profile} onChange={(at) => setProfile({ ...profile, outreach_consent_at: at })} />
      )}

      {tab === 'manage' && manageView === 'profile' && (
        <ProfilePanel key={profileKey} token={token!} profile={profile} missing={missing} onSaved={(p) => {
          setProfile(p)
          setProfileKey((k) => k + 1)
          void loadMatches()
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
  if (p.products.length === 0 && p.technologies.length === 0) out.push('제품·보유 기술')
  return out
}

type CertRow = { cert_type_code: string; cert_no: string; issued_on: string; expires_on: string; company_evidence_id: number | null }
type CreditRow = { agency: string; grade: string; rated_on: string; valid_until: string; company_evidence_id: number | null }
type ProductRow = { name: string; category: ProductCategory; description: string; is_defense: boolean; customers: string }
type TechRow = { tech_name: string; description: string; trl: string }
type SupportRow = { program_name: string; agency: string; year: string; result: SupportResult; amount_krw: string }
type RndRow = { title: string; funding_agency: string; start_date: string; end_date: string; role: 'LEAD' | 'PARTICIPANT' }

const ORIGIN_LABELS: Record<string, string> = { SELF: '직접 입력', EXTERNAL: '공공데이터 확인', INTERNAL: '기관 보유 자료', STAFF: '담당자 입력' }
const FIELD_LABELS: Record<string, string> = {
  annual_revenue_krw: '매출', employee_count: '근로자 수', company_size: '기업 규모', region: '소재지', established_on: '설립일',
  company_name: '회사 이름', main_business: '주요 사업', address: '주소',
}
const s = (v: string | number | boolean | null | undefined) => (v == null ? '' : String(v))
const orNull = (v: string) => (v.trim() === '' ? null : v.trim())
const tri = (v: string) => (v === '' ? null : v === 'true')
const num = (v: string) => (v === '' ? null : Number(v))

function ProfilePanel({ token, profile, missing, onSaved }: {
  token: string
  profile: FullProfile
  missing: string[]
  onSaved: (p: FullProfile) => void
}) {
  const { busy, run } = useAction()
  const toast = useToast()
  const autofill = () => void run(async () => {
    const res = await autofillProfile(token)
    const ok = res.results.filter((r) => r.ok).map((r) => r.label)
    const failed = res.results.filter((r) => !r.ok).map((r) => r.label)
    toast.show({ kind: failed.length ? 'error' : 'success', title: '공공데이터로 채웠습니다',
      message: [ok.length && `가져옴: ${ok.join(', ')}`, failed.length && `연결 안 됨: ${failed.join(', ')}`].filter(Boolean).join(' · ') })
    onSaved(res.profile)
  })
  return (
    <CompanyInfoForm profile={profile} missing={missing} token={token} submitLabel="저장하고 다시 판정"
      top={<>
        <Card title="회사 역량 한눈에" actions={<span className="small muted">저장하면 다시 계산합니다</span>}>
          <RadarChart radar={profile.radar} />
        </Card>
        <div className="manage-box">
          <div>
            <strong>공공데이터로 자동 채우기</strong>
            <div className="small muted">국세청(휴·폐업), 특허청(특허), DART(매출·근로자 수)에서 가져와 ‘공공데이터 확인’으로 표시합니다. 인증·R&amp;D 이력은 아래에 직접 입력해 주세요.</div>
          </div>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={autofill}>{busy ? '가져오는 중…' : '자동 채우기'}</button>
        </div>
      </>}
      onSubmit={async (body) => {
        const p = await updateMyProfile(token, body)
        toast.show({ kind: 'success', title: '저장했습니다', message: '바뀐 정보로 공고를 다시 판정했습니다.' })
        onSaved(p)
      }} />
  )
}

/** 등록 화면에서만 쓰는 칸 (국세청 확인용 + 알림 이메일) */
export type Identity = { business_reg_no: string; representative_name: string; opened_on: string; email: string }

/** 회사 정보 입력 양식. 등록(profile 없음, identity 있음)과 수정에 같이 쓴다. */
export function CompanyInfoForm({ profile, missing = [], token, identity, setIdentity, top, submitLabel, onSubmit }: {
  profile: FullProfile | null
  missing?: string[]
  /** 관리 링크 (있으면 증빙 올리기를 보여 준다) */
  token?: string
  identity?: Identity
  setIdentity?: (i: Identity) => void
  top?: ReactNode
  submitLabel: string
  onSubmit: (body: ProfileUpdate) => Promise<void>
}) {
  const [f, setF] = useState({
    company_name: profile?.company_name ?? '', main_business: s(profile?.main_business), homepage: s(profile?.homepage),
    company_size: s(profile?.company_size), established_on: s(profile?.established_on),
    employee_count: s(profile?.employee_count), annual_revenue_krw: s(profile?.annual_revenue_krw),
    revenue_year: s(profile?.revenue_year), region: s(profile?.region), address: s(profile?.address),
    tax_delinquent: s(profile?.tax_delinquent), insolvent: s(profile?.insolvent), rnd_restricted: s(profile?.rnd_restricted),
    procurement_sanctioned: s(profile?.procurement_sanctioned),
    defense_goods: s(profile?.defense_goods), military_supply_krw: s(profile?.military_supply_krw),
    export_krw: s(profile?.export_krw), export_year: s(profile?.export_year),
  })
  const [certs, setCerts] = useState<CertRow[]>((profile?.certifications ?? []).filter((c) => c.origin === 'SELF').map((c) => ({
    cert_type_code: c.cert_type_code, cert_no: s(c.cert_no), issued_on: s(c.issued_on), expires_on: s(c.expires_on),
    company_evidence_id: c.company_evidence_id })))
  const [credits, setCredits] = useState<CreditRow[]>((profile?.credit_ratings ?? []).filter((c) => c.origin === 'SELF').map((c) => ({
    agency: c.agency, grade: c.grade, rated_on: s(c.rated_on), valid_until: s(c.valid_until), company_evidence_id: c.company_evidence_id })))
  const self = <T extends { origin: string }>(rows: T[] | undefined) => (rows ?? []).filter((r) => r.origin === 'SELF')
  const [products, setProducts] = useState<ProductRow[]>(self(profile?.products).map((p) => ({
    name: p.name, category: p.category, description: s(p.description), is_defense: p.is_defense, customers: s(p.customers) })))
  const [techs, setTechs] = useState<TechRow[]>(self(profile?.technologies).map((t) => ({
    tech_name: t.tech_name, description: s(t.description), trl: s(t.trl) })))
  const [supports, setSupports] = useState<SupportRow[]>(self(profile?.support_history).map((h) => ({
    program_name: h.program_name, agency: s(h.agency), year: s(h.year), result: h.result, amount_krw: s(h.amount_krw) })))
  const [evidence, setEvidence] = useState<Evidence[]>(profile?.evidence ?? [])
  const [rnds, setRnds] = useState<RndRow[]>((profile?.rnd_history ?? []).filter((r) => r.origin === 'SELF').map((r) => ({
    title: r.title, funding_agency: s(r.funding_agency), start_date: s(r.start_date), end_date: s(r.end_date), role: r.role })))
  const { busy, run } = useAction()
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  const setId = (k: keyof Identity) => (e: { target: { value: string } }) => setIdentity?.({ ...identity!, [k]: e.target.value })

  const save = (e: FormEvent) => {
    e.preventDefault()
    const body: ProfileUpdate = {
      company_name: f.company_name.trim(), main_business: orNull(f.main_business), homepage: orNull(f.homepage),
      company_size: orNull(f.company_size), established_on: orNull(f.established_on),
      employee_count: f.employee_count ? Number(f.employee_count) : null,
      annual_revenue_krw: f.annual_revenue_krw ? Number(f.annual_revenue_krw) : null,
      revenue_year: f.revenue_year ? Number(f.revenue_year) : null, region: orNull(f.region), address: orNull(f.address),
      tax_delinquent: tri(f.tax_delinquent), insolvent: tri(f.insolvent), rnd_restricted: tri(f.rnd_restricted), procurement_sanctioned: tri(f.procurement_sanctioned),
      defense_goods: tri(f.defense_goods), military_supply_krw: num(f.military_supply_krw),
      export_krw: num(f.export_krw), export_year: num(f.export_year),
      certifications: certs.filter((c) => c.cert_type_code).map((c) => ({ cert_type_code: c.cert_type_code,
        cert_no: orNull(c.cert_no), issued_on: orNull(c.issued_on), expires_on: orNull(c.expires_on),
        company_evidence_id: c.company_evidence_id })),
      credit_ratings: credits.filter((c) => c.grade.trim()).map((c) => ({ agency: c.agency, grade: c.grade.trim().toUpperCase(),
        rated_on: orNull(c.rated_on), valid_until: orNull(c.valid_until), company_evidence_id: c.company_evidence_id })),
      products: products.filter((p) => p.name.trim()).map((p) => ({ name: p.name.trim(), category: p.category,
        description: orNull(p.description), is_defense: p.is_defense, customers: orNull(p.customers) })),
      technologies: techs.filter((t) => t.tech_name.trim()).map((t) => ({ tech_name: t.tech_name.trim(),
        description: orNull(t.description), trl: num(t.trl) })),
      support_history: supports.filter((h) => h.program_name.trim()).map((h) => ({ program_name: h.program_name.trim(),
        agency: orNull(h.agency), year: num(h.year), result: h.result, amount_krw: num(h.amount_krw) })),
      rnd_history: rnds.filter((r) => r.title.trim()).map((r) => ({ title: r.title.trim(), funding_agency: orNull(r.funding_agency),
        start_date: orNull(r.start_date), end_date: orNull(r.end_date), role: r.role })),
    }
    void run(() => onSubmit(body))
  }

  const readonly = (origin: string) => origin !== 'SELF'
  const [evMsg, setEvMsg] = useState<string | null>(null)
  const onEvidence = (file: File | undefined) => {
    if (!file || !token) return
    void run(async () => {
      const e = await uploadEvidence(token, file)
      setEvidence((xs) => [e, ...xs.filter((x) => x.id !== e.id)])
      const d = e.detected ?? {}
      if (e.detected_kind === 'CERTIFICATION') {
        const row = { cert_type_code: d.cert_type_code, cert_no: d.cert_no ?? '', issued_on: d.issued_on ?? '',
          expires_on: d.expires_on ?? '', company_evidence_id: e.id }
        // 같은 종류를 이미 적어 두었으면 그 줄을 바꾼다 (갱신한 확인서)
        setCerts((rs) => rs.some((r) => r.cert_type_code === row.cert_type_code)
          ? rs.map((r) => (r.cert_type_code === row.cert_type_code ? row : r)) : [...rs, row])
        setEvMsg(`${CERT_TYPES[d.cert_type_code] ?? '인증'}을(를) 아래 칸에 채웠습니다. 값을 확인하고 저장하세요.`)
      } else if (e.detected_kind === 'CREDIT_RATING') {
        setCredits((rs) => [...rs, { agency: d.agency ?? 'OTHER', grade: d.grade ?? '', rated_on: d.rated_on ?? '',
          valid_until: d.valid_until ?? '', company_evidence_id: e.id }])
        setEvMsg('신용등급을 아래 칸에 채웠습니다. 값을 확인하고 저장하세요.')
      } else {
        setEvMsg(e.parse_note ?? '어떤 증빙인지 알아보지 못했습니다. 값을 직접 입력하세요.')
      }
    })
  }
  const removeEvidence = (id: number) => token && void run(async () => {
    await deleteEvidence(token, id)
    setEvidence((xs) => xs.filter((x) => x.id !== id))
    setCerts((rs) => rs.map((r) => (r.company_evidence_id === id ? { ...r, company_evidence_id: null } : r)))
    setCredits((rs) => rs.map((r) => (r.company_evidence_id === id ? { ...r, company_evidence_id: null } : r)))
  })
  const evName = (id: number | null) => (id == null ? null : evidence.find((e) => e.id === id)?.file_name ?? '증빙')
  return (
    <form className="stack" onSubmit={save}>
      {top}
      {missing.length > 0 && (
        <div className="notice small">비어 있는 항목: {missing.join(', ')}. 채울수록 판정이 정확해집니다.</div>
      )}
      <Card title="기본 정보" actions={<span className="small muted">직접 입력한 값은 기관 확인 전까지 ‘직접 입력’으로 표시됩니다</span>}>
        <div className="form">
          {identity ? (
            <>
              <div className="form-row">
                <label>사업자등록번호 *<input required value={identity.business_reg_no} onChange={setId('business_reg_no')} placeholder="123-45-67890" /></label>
                <label className="grow">회사 이름 *<input required value={f.company_name} onChange={set('company_name')} /></label>
              </div>
              <div className="form-row">
                <label title="국세청 사업자 확인에 씁니다">대표자명 *<input required value={identity.representative_name} onChange={setId('representative_name')} /></label>
                <label title="국세청 사업자 확인에 씁니다">개업일 *<input required type="date" value={identity.opened_on} onChange={setId('opened_on')} /></label>
                <label className="grow">새 공고 알림 받을 이메일 *<input required type="email" value={identity.email} onChange={setId('email')} />
                  <span className="field-hint">조건에 맞는 공고가 올라오면 이 주소로 알려 드립니다</span></label>
              </div>
            </>
          ) : (
            <div className="form-row">
              <label className="grow">회사 이름<input required value={f.company_name} onChange={set('company_name')} /></label>
              <label title="국세청 확인에 쓴 값이라 바꿀 수 없습니다">대표자명<input value={s(profile?.representative_name)} disabled /></label>
              <label title="국세청 확인에 쓴 값이라 바꿀 수 없습니다">개업일<input value={s(profile?.opened_on)} disabled /></label>
            </div>
          )}
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
          {profile?.field_sources.some((x) => x.differs) && (
            <div className="notice small">
              {profile!.field_sources.filter((x) => x.differs).map((x) => FIELD_LABELS[x.field_name] ?? x.field_name).join(', ')}이(가)
              공공데이터 값과 다릅니다. 판정은 공공데이터 값으로 합니다.
            </div>
          )}
        </div>
      </Card>

      <Card title="결격사유·실적" actions={<span className="small muted">공고 대부분이 이 항목으로 신청 자격을 거릅니다. 모르면 비워 두세요</span>}>
        <div className="form">
          <div className="form-row">
            {([['tax_delinquent', '국세·지방세 체납'], ['insolvent', '부도·자본잠식'], ['rnd_restricted', '국가 R&D 참여제한'], ['procurement_sanctioned', '부정당제재']] as const).map(([k, label]) => (
              <label key={k}>{label}
                <select value={f[k]} onChange={set(k)}>
                  <option value="">모름</option><option value="false">해당 없음</option><option value="true">해당</option>
                </select>
              </label>
            ))}
          </div>
          <div className="form-row">
            <label>방산물자 생산
              <select value={f.defense_goods} onChange={set('defense_goods')}>
                <option value="">모름</option><option value="true">예</option><option value="false">아니오</option>
              </select>
            </label>
            <label>최근 3년 군 납품 실적 (원)
              <input type="number" min={0} step={1000000} value={f.military_supply_krw} onChange={set('military_supply_krw')} />
              {f.military_supply_krw && <span className="field-hint">{fmtKrw(Number(f.military_supply_krw))}</span>}</label>
            <label>최근 연도 수출액 (원)
              <input type="number" min={0} step={1000000} value={f.export_krw} onChange={set('export_krw')} />
              {f.export_krw && <span className="field-hint">{fmtKrw(Number(f.export_krw))}</span>}</label>
            <label>수출 기준 연도<input type="number" value={f.export_year} onChange={set('export_year')} /></label>
          </div>
        </div>
      </Card>

      <Card title="제품" actions={<span className="small muted">공고의 요구 기술과 비교해 관련도를 계산합니다</span>}>
        <ReadonlyRows rows={(profile?.products ?? []).filter((p) => readonly(p.origin)).map((p) => [p.name, ORIGIN_LABELS[p.origin] ?? p.origin])} />
        <EditRows rows={products} setRows={setProducts}
          empty={{ name: '', category: 'COMPONENT' as ProductCategory, description: '', is_defense: false, customers: '' }}
          addLabel="제품 추가" render={(r, upd) => (
            <>
              <label className="grow">제품명<input value={r.name} placeholder="예: Ku 밴드 저잡음 증폭기" onChange={(e) => upd({ name: e.target.value })} /></label>
              <label>분류
                <select value={r.category} onChange={(e) => upd({ category: e.target.value as ProductCategory })}>
                  {Object.entries(PRODUCT_CATEGORIES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>
              <label className="grow">설명<input value={r.description} placeholder="쓰임새·성능" onChange={(e) => upd({ description: e.target.value })} /></label>
              <label>주요 납품처<input value={r.customers} placeholder="예: 육군, 체계업체" onChange={(e) => upd({ customers: e.target.value })} /></label>
              <label className="check inline-check"><input type="checkbox" checked={r.is_defense} onChange={(e) => upd({ is_defense: e.target.checked })} />군 납품·국방용</label>
            </>
          )} />
      </Card>

      <Card title="보유 기술">
        <ReadonlyRows rows={(profile?.technologies ?? []).filter((t) => readonly(t.origin)).map((t) => [t.tech_name, ORIGIN_LABELS[t.origin] ?? t.origin])} />
        <EditRows rows={techs} setRows={setTechs} empty={{ tech_name: '', description: '', trl: '' }}
          addLabel="기술 추가" render={(r, upd) => (
            <>
              <label className="grow">기술명<input value={r.tech_name} placeholder="예: GaN 고출력 증폭 설계" onChange={(e) => upd({ tech_name: e.target.value })} /></label>
              <label className="grow">설명<input value={r.description} onChange={(e) => upd({ description: e.target.value })} /></label>
              <label title="1 기초 연구 ~ 9 실전 운용">기술성숙도(TRL)
                <select value={r.trl} onChange={(e) => upd({ trl: e.target.value })}>
                  <option value="">모름</option>
                  {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </label>
            </>
          )} />
      </Card>

      <Card title="지원사업 참여 이력" actions={<span className="small muted">R&amp;D 과제가 아닌 컨설팅·수출·시험평가 같은 지원사업</span>}>
        <ReadonlyRows rows={(profile?.support_history ?? []).filter((h) => readonly(h.origin)).map((h) =>
          [`${h.program_name}${h.year ? ` (${h.year})` : ''} · ${SUPPORT_RESULTS[h.result]}`, ORIGIN_LABELS[h.origin] ?? h.origin])} />
        <EditRows rows={supports} setRows={setSupports}
          empty={{ program_name: '', agency: '', year: '', result: 'SELECTED' as SupportResult, amount_krw: '' }}
          addLabel="이력 추가" render={(r, upd) => (
            <>
              <label className="grow">사업명<input value={r.program_name} placeholder="예: 방산 중소기업 컨설팅 지원사업" onChange={(e) => upd({ program_name: e.target.value })} /></label>
              <label>주관 기관<input value={r.agency} placeholder="예: 국방기술진흥연구소" onChange={(e) => upd({ agency: e.target.value })} /></label>
              <label>연도<input type="number" min={1990} max={2100} value={r.year} onChange={(e) => upd({ year: e.target.value })} /></label>
              <label>결과
                <select value={r.result} onChange={(e) => upd({ result: e.target.value as SupportResult })}>
                  {Object.entries(SUPPORT_RESULTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>
              <label>지원금 (원)<input type="number" min={0} value={r.amount_krw} onChange={(e) => upd({ amount_krw: e.target.value })} /></label>
            </>
          )} />
      </Card>

      {token && (
        <Card title="증빙으로 채우기" actions={<span className="small muted">회사와 기관 담당자만 볼 수 있습니다</span>}>
          <p className="small muted">벤처기업확인서, 기업부설연구소 인정서, ISO 인증서, 신용평가 등급확인서 PDF·한글 파일을 올리면 종류·번호·날짜·등급을 읽어 아래 칸에 채웁니다. 사진·스캔본은 읽지 못하니 직접 입력하세요. 원본 파일은 보관하지 않습니다.</p>
          <label className="btn btn-sm file-btn">
            {busy ? '읽는 중…' : '파일 올리기'}
            <input type="file" accept=".pdf,.hwp,.hwpx,.png,.jpg,.jpeg" hidden disabled={busy}
              onChange={(e) => { onEvidence(e.target.files?.[0]); e.target.value = '' }} />
          </label>
          {evMsg && <div className="notice small" style={{ marginTop: 8 }}>{evMsg}</div>}
          {evidence.length > 0 && (
            <ul className="plain-list small" style={{ marginTop: 8 }}>
              {evidence.map((e) => (
                <li key={e.id}>
                  {e.file_name}{' '}
                  {e.parse_status === 'PARSED' ? <span className="badge badge-ok">글자 읽음</span> : <span className="badge badge-muted">{e.parse_note ?? '읽지 않음'}</span>}{' '}
                  <button type="button" className="link-btn small" onClick={() => removeEvidence(e.id)}>지우기</button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      <Card title="인증·지정">
        <ReadonlyRows rows={(profile?.certifications ?? []).filter((c) => readonly(c.origin)).map((c) =>
          [`${c.cert_type_name}${c.expires_on ? ` (만료 ${c.expires_on})` : ''}`, ORIGIN_LABELS[c.origin] ?? c.origin])} />
        <EditRows rows={certs} setRows={setCerts} empty={{ cert_type_code: 'VENTURE', cert_no: '', issued_on: '', expires_on: '', company_evidence_id: null }}
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
              {r.company_evidence_id != null && <span className="badge badge-info evidence-tag" title="올린 증빙에서 읽은 값">증빙: {evName(r.company_evidence_id)}</span>}
            </>
          )} />
      </Card>

      <Card title="신용등급" actions={<span className="small muted">회사와 기관 담당자만 볼 수 있습니다</span>}>
        <ReadonlyRows rows={(profile?.credit_ratings ?? []).filter((c) => readonly(c.origin)).map((c) =>
          [`${AGENCY_LABELS[c.agency] ?? c.agency} ${c.grade}${c.rated_on ? ` (${c.rated_on} 평가)` : ''}`, ORIGIN_LABELS[c.origin] ?? c.origin])} />
        <EditRows rows={credits} setRows={setCredits} empty={{ agency: 'NICE', grade: '', rated_on: '', valid_until: '', company_evidence_id: null }}
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
              {r.company_evidence_id != null && <span className="badge badge-info evidence-tag" title="올린 증빙에서 읽은 값">증빙: {evName(r.company_evidence_id)}</span>}
            </>
          )} />
      </Card>

      <Card title="R&D 수행 이력">
        <ReadonlyRows rows={(profile?.rnd_history ?? []).filter((r) => readonly(r.origin)).map((r) =>
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
        {!profile?.patents.length ? <Empty>등록된 특허가 없습니다. 등록 후 ‘자동 채우기’로 특허청에서 가져올 수 있습니다.</Empty> : (
          <ul className="plain-list small">
            {profile!.patents.map((p) => (
              <li key={p.application_no}>{p.title} <span className="muted">{p.registration_no ? `등록 ${p.registration_no}` : `출원 ${p.application_no}`}</span></li>
            ))}
          </ul>
        )}
        <p className="small muted">특허는 특허청 자료에서 가져옵니다. 빠진 특허가 있으면 기관 담당자에게 알려 주세요.</p>
      </Card>

      <div className="form-foot sticky-foot">
        <button className="btn btn-primary" disabled={busy}>{busy ? '저장 중…' : submitLabel}</button>
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

/** 기관 담당자가 상담에 쓰는 진단 변수. 점수는 보여 주지 않는다 */
function DstatePanel({ token, onMissing }: { token: string; onMissing: (n: number) => void }) {
  const [vars, setVars] = useState<DstateVariable[] | null>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const { busy, run } = useAction()
  const toast = useToast()

  useEffect(() => {
    getMyDstate(token).then((d) => { setVars(d.variables); onMissing(d.missing.length) }).catch(() => undefined)
  }, [token, onMissing])

  if (!vars) return <div className="page-loading">불러오는 중…</div>
  const values = changedValues(vars, drafts)
  const count = Object.keys(values).length
  const save = () => run(async () => {
    const d = await saveMyDstate(token, values)
    setVars(d.variables)
    onMissing(d.missing.length)
    setDrafts({})
    toast.show({ kind: 'success', title: '저장했습니다' })
  })
  return (
    <Card title="성장 진단 정보" actions={
      <button className="btn btn-primary" disabled={busy || count === 0} onClick={() => void save()}>
        {busy ? '저장 중…' : count ? `${count}개 저장` : '저장'}
      </button>
    }>
      <p className="small muted">기관 담당자가 상담할 때 쓰는 정보입니다. 모르는 항목은 비워 두세요.</p>
      <div className="stack">
        {vars.map((v) => (
          <div key={v.code}>
            <strong>{v.name}</strong>
            {v.value_type === 'PROFILE' ? (
              <div>
                {v.missing ? <span className="badge badge-warn">미확보</span> : v.display}
                <div className="small muted">회사 정보에서 고칩니다</div>
              </div>
            ) : (
              <>
                <div className="small muted">{v.question}</div>
                <DstateInput v={v} draft={drafts[v.code]} onChange={(d) => setDrafts({ ...drafts, [v.code]: d })} />
                <div className="small muted">
                  {v.missing ? '아직 비어 있음' : `현재 ${v.display}`}{v.source_label ? ` · ${v.source_label}` : ''}
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </Card>
  )
}

function ConsultPanel({ token }: { token: string }) {
  const [data, setData] = useState<{ consultations: MyConsultation[]; requests: MyConsultRequest[] } | null>(null)
  const [concern, setConcern] = useState('')
  const [interest, setInterest] = useState('')
  const [contactName, setContactName] = useState('')
  const [contactPhone, setContactPhone] = useState('')
  const { busy, run } = useAction()
  const toast = useToast()
  const load = useCallback(() => getMyConsultations(token).then(setData).catch(() => undefined), [token])
  useEffect(() => { void load() }, [load])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      await createMyConsultRequest(token, {
        concern: concern.trim(), interest: interest.trim() || undefined,
        contact_name: contactName.trim() || undefined, contact_phone: contactPhone.trim() || undefined,
      })
      setConcern(''); setInterest('')
      toast.show({ kind: 'success', title: '상담을 요청했습니다', message: '담당자가 확인 후 안내합니다.' })
      await load()
    })
  }
  const tone: Record<string, string> = { REQUESTED: 'warn', IN_PROGRESS: 'info', DONE: 'ok', CANCELED: 'muted' }

  return (
    <div className="stack">
      <Card title="상담 요청">
        <form className="stack" onSubmit={submit}>
          <label>애로사항
            <textarea rows={3} required value={concern} onChange={(e) => setConcern(e.target.value)}
              placeholder="어려운 점이나 궁금한 점을 적어 주세요." />
          </label>
          <div className="form-row">
            <label>관심 지원사업<input value={interest} onChange={(e) => setInterest(e.target.value)} /></label>
            <label>담당자 이름<input value={contactName} onChange={(e) => setContactName(e.target.value)} /></label>
            <label>연락처<input value={contactPhone} onChange={(e) => setContactPhone(e.target.value)} /></label>
          </div>
          <div><button className="btn btn-primary" disabled={busy || !concern.trim()}>{busy ? '요청 중…' : '상담 요청'}</button></div>
        </form>
      </Card>

      <Card title="내 상담 요청">
        {!data ? <div className="page-loading">불러오는 중…</div> : !data.requests.length ? <Empty>요청한 상담이 없습니다.</Empty> : (
          <table className="table">
            <thead><tr><th>요청일</th><th>애로사항</th><th>관심 지원사업</th><th>상태</th></tr></thead>
            <tbody>
              {data.requests.map((r) => (
                <tr key={r.id}>
                  <td className="small">{fmtDate(r.created_at)}</td>
                  <td style={{ whiteSpace: 'pre-wrap' }}>{r.concern}</td>
                  <td>{r.interest ?? '–'}</td>
                  <td><span className={`badge badge-${tone[r.status] ?? 'muted'}`}>{r.status_label}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {data && !data.consultations.length && <Card><Empty>확정된 상담 결과가 없습니다. 상담을 요청하면 담당자가 확인 후 안내합니다.</Empty></Card>}
      {data?.consultations.map((c) => (
        <Card key={c.id} title={`${c.task_label} 상담 결과`} actions={<span className="small muted">{fmtDate(c.confirmed_at)}</span>}>
          {c.state_label && <p className="small muted">상태유형 {c.state_label}</p>}
          {c.report.map((s) => (
            <div key={s.key}>
              <h4>{s.title}</h4>
              <p style={{ whiteSpace: 'pre-wrap' }}>{s.text}</p>
            </div>
          ))}
          {c.announcements.length > 0 && (
            <>
              <h4>검토한 지원사업</h4>
              <table className="table">
                <thead><tr><th>공고</th><th>기관</th><th>마감일</th><th>신청 가능 여부</th><th>적합도</th></tr></thead>
                <tbody>
                  {c.announcements.map((a) => (
                    <tr key={a.announcement_id}>
                      <td>{a.title}{a.todo.length > 0 && <ul className="small">{a.todo.map((t) => <li key={t}>{t}</li>)}</ul>}</td>
                      <td>{a.agency_name}</td>
                      <td>{a.receipt_end ?? '–'}</td>
                      <td><span className="badge badge-info">{a.q1_label}</span></td>
                      <td>{a.fit_grade ? `적합도 ${a.fit_grade}` : '–'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {c.steps.length > 0 && (
            <>
              <h4>성장 경로</h4>
              <div className="stack">
                {c.steps.map((st, i) => (
                  <div key={i}>
                    <strong>{st.horizon} · {st.stage_label}</strong>
                    <div>{st.goal}</div>
                    {st.programs.length > 0 && (
                      <div className="chips">{st.programs.map((p) => <span key={p.name} className="badge badge-muted">{p.name} · {p.readiness_label}</span>)}</div>
                    )}
                    {st.tasks.length > 0 && <ul className="small">{st.tasks.map((t) => <li key={t}>{t}</li>)}</ul>}
                  </div>
                ))}
              </div>
            </>
          )}
        </Card>
      ))}
    </div>
  )
}
