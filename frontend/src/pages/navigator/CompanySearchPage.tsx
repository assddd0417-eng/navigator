/** 기업 첫 화면 (로그인 없음): 사업자번호 → 공개 정보 + 맞는 공고. 자세한 내 정보는 관리 링크로. */
import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import {
  getPublicCompany, getPublicMatches, requestAccessLink,
  type LinkSent, type MatchRun, type PublicProfile,
} from '../../api/navigator'
import { Card, Empty, useAction } from '../../components/ui'
import { CompanyShell, fmtDay, MatchItem, VerdictSummary } from './components'

/** seeds/navigator_companies.sql 의 가상 기업 (시연용) */
const DEMO = [
  { brn: '999-81-00015', name: '(가상)한빛전자통신' },
  { brn: '999-82-00026', name: '(가상)누리복합소재' },
  { brn: '999-83-00038', name: '(가상)새봄비전AI' },
]

export function CompanySearchPage() {
  const [params, setParams] = useSearchParams()
  const [brn, setBrn] = useState(params.get('brn') ?? '')
  const [profile, setProfile] = useState<PublicProfile | null>(null)
  const [matches, setMatches] = useState<MatchRun | null>(null)
  const [notFound, setNotFound] = useState<string | null>(null)
  const [sent, setSent] = useState<LinkSent | null>(null)
  const { busy, run } = useAction()

  const search = async (value: string) => {
    const digits = value.replace(/[^0-9]/g, '')
    if (digits.length !== 10) {
      setNotFound('사업자등록번호 10자리를 입력하세요 (예: 123-45-67890).')
      return
    }
    setProfile(null); setMatches(null); setNotFound(null); setSent(null)
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

  const sendLink = () => run(async () => setSent(await requestAccessLink(profile!.business_reg_no)))

  return (
    <CompanyShell>
      <section className="hero">
        <h1>사업자등록번호만 넣으면, 지원할 수 있는 공고를 찾아 드립니다</h1>
        <p className="muted">로그인은 필요 없습니다. 신용등급·매출 같은 민감한 정보는 등록 이메일로 받은 관리 링크로만 볼 수 있습니다.</p>
        <form className="search-row hero-search" onSubmit={submit}>
          <input value={brn} onChange={(e) => setBrn(e.target.value)} placeholder="사업자등록번호 (예: 123-45-67890)"
            inputMode="numeric" aria-label="사업자등록번호" />
          <button className="btn btn-primary" disabled={busy}>{busy ? '찾는 중…' : '맞는 공고 찾기'}</button>
        </form>
        <div className="chips">
          <span className="small muted">시연용 가상 기업:</span>
          {DEMO.map((d) => (
            <button key={d.brn} type="button" className="chip" onClick={() => { setBrn(d.brn); void search(d.brn) }}>
              {d.name}
            </button>
          ))}
        </div>
      </section>

      {notFound && (
        <Card>
          <p>{notFound}</p>
          <p className="muted">아직 등록하지 않은 회사라면 1분이면 등록할 수 있습니다.</p>
          <Link className="btn btn-primary" to={`/navigator/register?brn=${encodeURIComponent(brn)}`}>회사 등록하기</Link>
        </Card>
      )}

      {profile && (
        <Card title={profile.company_name} actions={
          <>
            <span className={`badge badge-${profile.biz_verify_status === 'VERIFIED' ? 'ok' : 'warn'}`}>
              국세청 {profile.biz_verify_label}
            </span>
            <span className="badge badge-muted">{profile.business_status_label}</span>
          </>
        }>
          <div className="profile-line">
            <span>사업자번호 <strong>{profile.business_reg_no}</strong></span>
            <span>특허 <strong>{profile.patents.length}</strong>건</span>
          </div>
          {profile.patents.length > 0 && (
            <ul className="plain-list small">
              {profile.patents.slice(0, 5).map((p) => (
                <li key={p.application_no}>{p.title} <span className="muted">({p.status === 'REGISTERED' ? `등록 ${fmtDay(p.registered_on)}` : '출원'})</span></li>
              ))}
            </ul>
          )}
          <div className="manage-box">
            <div>
              <strong>우리 회사 담당자이신가요?</strong>
              <div className="small muted">관리 링크로 정보를 고치고, 보완질문에 답하면 판정이 바로 다시 나옵니다. {profile.note}</div>
            </div>
            <button className="btn" disabled={busy} onClick={() => void sendLink()}>관리 링크 이메일로 받기</button>
          </div>
          {sent && (
            <div className="notice notice-ok">
              {sent.sent_to} 로 관리 링크를 보냈습니다 (유효기간 {fmtDay(sent.expires_at)}까지). 이전 링크는 더 이상 쓸 수 없습니다.
              {sent.dev_management_link && (
                <div className="small">개발용: <a href={sent.dev_management_link.replace(/^https?:\/\/[^/]+/, '')}>관리 링크 바로 열기</a></div>
              )}
            </div>
          )}
        </Card>
      )}

      {matches && (
        <Card title="지원할 만한 공고" actions={<VerdictSummary run={matches} />}>
          <p className="small muted">
            공개 정보만으로 판정했습니다. 적합 → 정보부족 → 부적격, 그 안에서는 총점 순입니다.
          </p>
          {matches.recommendations.length === 0 ? <Empty>지금 접수 중이거나 곧 열릴 공고 중 비교할 공고가 없습니다.</Empty> : (
            <ul className="match-list">
              {matches.recommendations.map((r) => (
                <MatchItem key={r.id} rec={r} title={
                  <span><strong>{r.announcement_title}</strong> <span className="small muted">{r.agency_name} · 마감 {fmtDay(r.receipt_end)}</span></span>
                } />
              ))}
            </ul>
          )}
        </Card>
      )}
    </CompanyShell>
  )
}
