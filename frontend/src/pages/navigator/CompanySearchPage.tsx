import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import {
  getPublicCompany, getPublicMatches, openCompany,
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
  ['사업자번호로 조회', '공개 정보로 지원 가능한 공고를 먼저 보여 드립니다.'],
  ['회사 정보 보완', '공공데이터로 자동으로 채우고, 인증·R&D 이력은 바로 입력하면 판정이 정확해집니다.'],
  ['새 공고 알림', '조건에 맞는 공고가 올라오면 이메일로 알려 드립니다.'],
]

export function CompanySearchPage() {
  const [params, setParams] = useSearchParams()
  const [brn, setBrn] = useState(params.get('brn') ?? '')
  const [profile, setProfile] = useState<PublicProfile | null>(null)
  const [matches, setMatches] = useState<MatchRun | null>(null)
  const [notFound, setNotFound] = useState<string | null>(null)
  const { busy, run } = useAction()

  const search = async (value: string) => {
    const digits = value.replace(/[^0-9]/g, '')
    if (digits.length !== 10) {
      setNotFound('사업자등록번호 10자리를 입력하세요. (예: 123-45-67890)')
      return
    }
    setProfile(null); setMatches(null); setNotFound(null)
    setParams({ brn: value })
    await run(async () => {
      try {
        const p = await getPublicCompany(digits)
        setProfile(p)
        setMatches(await getPublicMatches(digits))
      } catch (e) {
        if (e instanceof ApiError && (e.status === 404 || e.status === 422)) setNotFound(e.detail)
        else throw e
      }
    })
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void search(brn)
  }

  const navigate = useNavigate()
  const openManage = () => run(async () => {
    const { token } = await openCompany(profile!.business_reg_no)
    navigate(`/navigator/manage#t=${encodeURIComponent(token)}`)
  })
  const found = profile || notFound

  return (
    <CompanyShell>
      <section className="hero">
        <h1>우리 회사가 지원할 수 있는 국방 사업 공고</h1>
        <p className="muted">사업자등록번호만 넣으면 지원 조건과 회사 정보를 비교해 드립니다.</p>
        <form className="search-row hero-search" onSubmit={submit}>
          <input value={brn} onChange={(e) => setBrn(e.target.value)} placeholder="사업자등록번호 (예: 123-45-67890)"
            inputMode="numeric" aria-label="사업자등록번호" />
          <button className="btn btn-primary" disabled={busy}>{busy ? '조회 중…' : '조회'}</button>
        </form>
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
          <p>회사를 등록하면 지원 가능한 공고를 바로 볼 수 있습니다. 1분 정도 걸립니다.</p>
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
            <button className="btn btn-primary" disabled={busy} onClick={() => void openManage()}>회사 정보 입력·수정</button>
          </div>
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
