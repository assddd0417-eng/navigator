import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import {
  getPublicCompany, getPublicMatches, requestAccessLink,
  type LinkSent, type MatchRun, type PublicProfile,
} from '../../api/navigator'
import { Card, Empty, useAction } from '../../components/ui'
import { CompanyShell, fmtDay, MatchItem, VerdictSummary } from './components'

// seeds/navigator_companies.sql
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
        <h1>사업자등록번호로 지원 가능 공고 조회</h1>
        <p className="muted">신용등급·매출은 등록 이메일로 받은 관리 링크에서만 조회됩니다.</p>
        <form className="search-row hero-search" onSubmit={submit}>
          <input value={brn} onChange={(e) => setBrn(e.target.value)} placeholder="사업자등록번호 (예: 123-45-67890)"
            inputMode="numeric" aria-label="사업자등록번호" />
          <button className="btn btn-primary" disabled={busy}>{busy ? '조회 중…' : '조회'}</button>
        </form>
        <div className="chips">
          <span className="small muted">테스트 기업:</span>
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
          <p className="muted">등록되지 않은 사업자번호입니다.</p>
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
              <strong>관리 링크</strong>
              <div className="small muted">등록 이메일로 발송됩니다. 정보 수정, 보완질문 답변, 신용등급 조회는 관리 링크에서 합니다.</div>
            </div>
            <button className="btn" disabled={busy} onClick={() => void sendLink()}>관리 링크 받기</button>
          </div>
          {sent && (
            <div className="notice notice-ok">
              {sent.sent_to} 로 발송했습니다. 유효기간 {fmtDay(sent.expires_at)}, 이전 링크는 만료됩니다.
              {sent.dev_management_link && (
                <div className="small">[DEV] <a href={sent.dev_management_link.replace(/^https?:\/\/[^/]+/, '')}>관리 링크 열기</a></div>
              )}
            </div>
          )}
        </Card>
      )}

      {matches && (
        <Card title="추천 공고" actions={<VerdictSummary run={matches} />}>
          <p className="small muted">
            공개 정보 기준 판정입니다. 판정, 총점 순으로 정렬.
          </p>
          {matches.recommendations.length === 0 ? <Empty>대상 공고가 없습니다.</Empty> : (
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
