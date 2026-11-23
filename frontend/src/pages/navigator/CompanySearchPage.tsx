import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import {
  getPublicCompany, getPublicMatches, loginWithCode, sendLoginCode,
  type MatchRun, type PublicProfile,
} from '../../api/navigator'
import { Card, useAction } from '../../components/ui'
import { bizStatus, CompanyShell, Deadline, GroupedMatches, MatchCard } from './components'

// 시연용 가상 기업 (seeds/navigator_companies.sql)
const DEMO = [
  { brn: '999-81-00015', name: '(가상)한빛전자통신' },
  { brn: '999-82-00026', name: '(가상)누리복합소재' },
  { brn: '999-83-00038', name: '(가상)새봄비전AI' },
]

const STEPS = [
  ['사업자번호로 조회', '공개 정보로 지원 가능한 공고를 먼저 보여 줍니다.'],
  ['회사 정보 보완', '특허·매출은 공공데이터로 자동으로 채우고, 인증·R&D 이력은 직접 입력합니다.'],
  ['새 공고 알림', '조건에 맞는 공고가 올라오면 이메일로 알립니다.'],
]

export function CompanySearchPage() {
  const [params, setParams] = useSearchParams()
  const [brn, setBrn] = useState(params.get('brn') ?? '')
  const [profile, setProfile] = useState<PublicProfile | null>(null)
  const [matches, setMatches] = useState<MatchRun | null>(null)
  const [notFound, setNotFound] = useState<string | null>(null)
  const [badFormat, setBadFormat] = useState<string | null>(null) // 형식 오류는 '등록되지 않음'과 따로 안내
  const { busy, run } = useAction()

  const search = async (value: string) => {
    const digits = value.replace(/[^0-9]/g, '')
    setProfile(null); setMatches(null); setNotFound(null); setBadFormat(null); setCodeSent(null); setCode(''); setCodeError(null)
    if (digits.length !== 10) {
      setBadFormat(digits ? '사업자등록번호는 숫자 10자리입니다. (예: 123-45-67890)' : '사업자등록번호를 넣어 주세요.')
      return
    }
    setParams({ brn: value })
    await run(async () => {
      try {
        const p = await getPublicCompany(digits)
        setProfile(p)
        setMatches(await getPublicMatches(digits))
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) setNotFound(e.detail)
        else if (e instanceof ApiError && e.status === 422) setBadFormat(e.detail)
        else throw e
      }
    })
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void search(brn)
  }

  const navigate = useNavigate()
  const [codeSent, setCodeSent] = useState<{ sent_to: string; dev_code?: string } | null>(null)
  const [code, setCode] = useState('')
  const [codeError, setCodeError] = useState<string | null>(null)
  const askCode = () => run(async () => {
    setCodeError(null)
    try {
      const r = await sendLoginCode(profile!.business_reg_no)
      setCodeSent(r); setCode(r.dev_code ?? '')
    } catch (e) {
      if (e instanceof ApiError && (e.status === 409 || e.status === 429)) setCodeError(e.detail)
      else throw e
    }
  })
  const openManage = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      try {
        const { token } = await loginWithCode(profile!.business_reg_no, code.trim())
        navigate(`/navigator/manage#t=${encodeURIComponent(token)}`)
      } catch (err) {
        if (err instanceof ApiError && (err.status === 400 || err.status === 410 || err.status === 422)) {
          setCodeError(err.status === 422 ? '숫자 6자리를 넣으세요' : err.detail)
          if (err.status === 410) setCodeSent(null)
        } else throw err
      }
    })
  }
  const found = profile || notFound

  return (
    <CompanyShell>
      <section className="hero">
        <h1>우리 회사가 지원할 수 있는 국방 사업 공고</h1>
        <p className="muted">사업자등록번호를 넣으면 공고 지원 조건과 회사 정보를 비교합니다.</p>
        <form className="search-row hero-search" onSubmit={submit}>
          <input value={brn} onChange={(e) => setBrn(e.target.value)} placeholder="사업자등록번호 (예: 123-45-67890)"
            inputMode="numeric" aria-label="사업자등록번호" />
          <button className="btn btn-primary" disabled={busy}>{busy ? '조회 중…' : '조회'}</button>
        </form>
        {badFormat && <div className="notice notice-warn small">{badFormat}</div>}
        <div className="chips">
          <span className="small muted">시연용 기업:</span>
          {DEMO.map((d) => (
            <button key={d.brn} type="button" className="chip" onClick={() => { setBrn(d.brn); void search(d.brn) }}>
              {d.name}
            </button>
          ))}
        </div>
      </section>

      {!found && (
        <ol className="steps">
          {STEPS.map(([t, d], i) => (
            <li key={t}><span className="step-num">{i + 1}</span><div><strong>{t}</strong><div className="small muted">{d}</div></div></li>
          ))}
        </ol>
      )}

      {notFound && (
        <Card title="등록되지 않은 사업자번호입니다">
          <p className="muted">{notFound}</p>
          <p>회사를 등록하면 지원 가능한 공고를 바로 볼 수 있습니다.</p>
          <Link className="btn btn-primary" to={`/navigator/register?brn=${encodeURIComponent(brn)}`}>회사 등록</Link>
        </Card>
      )}

      {profile && (
        <Card title={profile.company_name} actions={
          <>
            <span className={`badge badge-${profile.biz_verify_status === 'VERIFIED' ? 'ok' : 'warn'}`}>
              국세청 {profile.biz_verify_label}
            </span>
            <span className="badge badge-muted">{bizStatus(profile.business_status_label)}</span>
          </>
        }>
          <div className="profile-line small muted">
            <span>사업자번호 {profile.business_reg_no}</span>
            <span>특허 {profile.patents.length}건</span>
          </div>
          <div className="manage-box">
            <div>
              <strong>이 회사 담당자이신가요?</strong>
              <div className="small muted">
                회사 정보를 공공데이터로 자동으로 채우거나 직접 입력하고, 확인 필요 항목에 답하고, 알림을 설정할 수 있습니다.
              </div>
            </div>
            {!codeSent && <button className="btn btn-primary" disabled={busy} onClick={() => void askCode()}>회사 정보 입력·수정</button>}
          </div>
          {codeSent && (
            <form className="search-row" onSubmit={openManage}>
              <span className="small muted">{codeSent.sent_to} 로 보낸 확인 코드 6자리 (10분 유효)</span>
              <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" maxLength={6}
                autoComplete="one-time-code" aria-label="확인 코드" placeholder="123456" />
              <button className="btn btn-primary" disabled={busy || code.trim().length !== 6}>열기</button>
              <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => void askCode()}>코드 다시 받기</button>
            </form>
          )}
          {codeSent?.dev_code && <div className="small muted">시연용 주소라 메일은 보내지 않고 코드를 미리 채웠습니다.</div>}
          {codeError && <div className="notice notice-warn small">{codeError}</div>}
        </Card>
      )}

      {matches && (
        <Card title="지원 가능 공고">
          {matches.recommendations.length === 0 ? <div className="empty">지금 접수 중인 공고가 없습니다.</div> : (
            <GroupedMatches run={matches} audience="company"
              hints={{ NEEDS_INFO: '‘회사 정보 입력·수정’에서 몇 가지만 답하면 판정됩니다' }}
              renderCard={(r) => (
                <MatchCard rec={r} audience="company" title={<strong>{r.announcement_title}</strong>}
                  meta={<>{r.agency_name} · <Deadline end={r.receipt_end} state={r.receipt_state} /></>} />
              )} />
          )}
        </Card>
      )}
    </CompanyShell>
  )
}
