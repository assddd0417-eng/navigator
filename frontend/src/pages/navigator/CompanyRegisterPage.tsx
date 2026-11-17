import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { registerCompany } from '../../api/navigator'
import { Card } from '../../components/ui'
import { CompanyInfoForm, type Identity } from './CompanyManagePage'
import { CompanyShell } from './components'

// 회사 정보는 이 한 페이지에서 모두 입력한다. 이메일은 새 공고 알림용.
export function CompanyRegisterPage() {
  const [params] = useSearchParams()
  const [identity, setIdentity] = useState<Identity>({
    business_reg_no: params.get('brn') ?? '', representative_name: '', opened_on: '', email: '' })
  const navigate = useNavigate()

  return (
    <CompanyShell>
      <div className="page-header">
        <div>
          <h1>회사 등록</h1>
          <p>회사 정보를 모두 여기서 입력합니다. 채울수록 지원 가능 공고를 정확하게 판정합니다.</p>
        </div>
        <Link to="/navigator" className="btn btn-ghost">취소</Link>
      </div>
      <CompanyInfoForm profile={null} identity={identity} setIdentity={setIdentity} submitLabel="등록하고 공고 보기"
        top={<Card title="안내"><p className="small muted">대표자명·개업일은 국세청 사업자 확인에만 씁니다. 등록 후 ‘자동 채우기’로 특허·매출 같은 공공데이터를 더 가져올 수 있습니다.</p></Card>}
        onSubmit={async (body) => {
          const res = await registerCompany({ ...body, ...identity, company_name: body.company_name! })
          navigate(`/navigator/manage#t=${encodeURIComponent(res.manage_token)}`)
        }} />
    </CompanyShell>
  )
}
