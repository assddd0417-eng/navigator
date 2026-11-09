import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { REGIONS, registerCompany, SIZE_LABELS, type RegisterResult } from '../../api/navigator'
import { Card, useAction } from '../../components/ui'
import { CompanyShell, fmtDay } from './components'

export function CompanyRegisterPage() {
  const [params] = useSearchParams()
  const [form, setForm] = useState({
    business_reg_no: params.get('brn') ?? '', company_name: '', representative_name: '', opened_on: '', email: '',
    main_business: '', company_size: '', employee_count: '', region: '',
  })
  const [done, setDone] = useState<RegisterResult | null>(null)
  const { busy, run } = useAction()
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => setDone(await registerCompany({
      business_reg_no: form.business_reg_no, company_name: form.company_name,
      representative_name: form.representative_name, opened_on: form.opened_on, email: form.email,
      main_business: form.main_business || null, company_size: form.company_size || null,
      employee_count: form.employee_count ? Number(form.employee_count) : null, region: form.region || null,
    })))
  }

  if (done) {
    return (
      <CompanyShell>
        <Card title="등록 완료">
          <p>
            <strong>{done.business_reg_no}</strong> · 국세청 진위확인 <strong>{done.biz_verify_label}</strong> ({done.message})
          </p>
          <p>관리 링크 발송: {done.sent_to} (유효기간 {fmtDay(done.expires_at)})</p>
          <div className="form-foot" style={{ justifyContent: 'flex-start' }}>
            {done.dev_management_link && (
              <a className="btn btn-primary" href={done.dev_management_link.replace(/^https?:\/\/[^/]+/, '')}>[DEV] 관리 링크 열기</a>
            )}
            <Link className="btn" to={`/navigator?brn=${encodeURIComponent(done.business_reg_no)}`}>추천 공고 보기</Link>
          </div>
        </Card>
      </CompanyShell>
    )
  }

  return (
    <CompanyShell>
      <Card title="회사 등록">
        <p className="muted small">대표자명·개업일은 국세청 진위확인에 사용됩니다. 수정은 등록 이메일로 받은 관리 링크에서 합니다.</p>
        <form className="form" onSubmit={submit}>
          <div className="form-row">
            <label>사업자등록번호 *<input required value={form.business_reg_no} onChange={set('business_reg_no')} placeholder="123-45-67890" /></label>
            <label className="grow">회사 이름 *<input required value={form.company_name} onChange={set('company_name')} /></label>
          </div>
          <div className="form-row">
            <label>대표자명 *<input required value={form.representative_name} onChange={set('representative_name')} /></label>
            <label>개업일 *<input required type="date" value={form.opened_on} onChange={set('opened_on')} /></label>
            <label className="grow">이메일 *<input required type="email" value={form.email} onChange={set('email')} /></label>
          </div>
          <label>주요 사업<textarea rows={2} value={form.main_business} onChange={set('main_business')} /></label>
          <div className="form-row">
            <label>기업 규모
              <select value={form.company_size} onChange={set('company_size')}>
                <option value="">선택 안 함</option>
                {Object.entries(SIZE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <label>상시 근로자 수<input type="number" min={0} value={form.employee_count} onChange={set('employee_count')} /></label>
            <label>본사 시·도
              <select value={form.region} onChange={set('region')}>
                <option value="">선택 안 함</option>
                {REGIONS.map((r) => <option key={r}>{r}</option>)}
              </select>
            </label>
          </div>
          <p className="small muted">인증·신용등급·R&amp;D 이력은 등록 후 관리 링크에서 입력합니다.</p>
          <div className="form-foot">
            <Link to="/navigator" className="btn btn-ghost">취소</Link>
            <button className="btn btn-primary" disabled={busy}>{busy ? '처리 중…' : '등록'}</button>
          </div>
        </form>
      </Card>
    </CompanyShell>
  )
}
