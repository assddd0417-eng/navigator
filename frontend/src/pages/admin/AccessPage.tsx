import { useEffect, useState } from 'react'
import { getCompanyAccess, saveCompanyAccess, searchConsultCompanies, type CompanyAccess } from '../../api/navigator'
import { useToast } from '../../components/Toast'
import { Card, Empty, PageHeader, useAction, useAsync } from '../../components/ui'

export function AccessPage() {
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')
  const companies = useAsync(() => searchConsultCompanies(query), [query])
  const [orgId, setOrgId] = useState<number | null>(null)
  return (
    <>
      <PageHeader title="기업정보 열람 권한" subtitle="기업별로 정보를 볼 수 있는 담당 부서를 정합니다." />
      <div className="grid-side">
        <Card title="기업 선택">
          <form className="form-row" style={{ marginBottom: 10 }} onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()) }}>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="상호 또는 사업자번호" aria-label="기업 검색" />
          </form>
          {companies.loading ? <div className="page-loading">불러오는 중…</div> : !companies.data?.length ? <Empty>기업이 없습니다.</Empty> : (
            <ul className="select-list">
              {companies.data.map((c) => (
                <li key={c.organization_id}>
                  <button className={c.organization_id === orgId ? 'on' : ''} onClick={() => setOrgId(c.organization_id)}>
                    <span>{c.name}</span>
                    <span className="small muted">{[c.business_reg_no, c.region].filter(Boolean).join(' · ')}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        {orgId == null ? <Card><Empty>왼쪽에서 기업을 고르세요.</Empty></Card> : <AccessEditor key={orgId} orgId={orgId} />}
      </div>
    </>
  )
}

function AccessEditor({ orgId }: { orgId: number }) {
  const [data, setData] = useState<CompanyAccess | null>(null)
  const [failed, setFailed] = useState(false)
  const [picked, setPicked] = useState<number[]>([])
  const { busy, run } = useAction()
  const toast = useToast()

  const apply = (d: CompanyAccess) => { setData(d); setPicked(d.departments.filter((x) => x.allowed).map((x) => x.id)) }
  useEffect(() => {
    getCompanyAccess(orgId).then(apply).catch(() => setFailed(true))
  }, [orgId])

  const save = () => run(async () => {
    apply(await saveCompanyAccess(orgId, picked))
    toast.show({ kind: 'success', title: '열람 권한을 저장했습니다' })
  })

  return (
    <Card title="열람 가능 부서" actions={
      <button className="btn btn-primary" disabled={busy || !data} onClick={() => void save()}>{busy ? '저장 중…' : '저장'}</button>
    }>
      {!data ? <div className="page-loading">{failed ? '불러오지 못했습니다.' : '불러오는 중…'}</div> : (
        <div className="stack">
          <p className="small muted">부서를 지정하면 그 부서와 AX 주관부서만 기업정보를 보고 상담할 수 있습니다. 비우면 모든 담당 부서가 봅니다.</p>
          <div className="form">
            {data.departments.map((d) => (
              <label key={d.id} className="check">
                <input type="checkbox" checked={picked.includes(d.id)}
                  onChange={(e) => setPicked(e.target.checked ? [...picked, d.id] : picked.filter((x) => x !== d.id))} />
                {d.name}
              </label>
            ))}
          </div>
          <div className="notice">{data.text}</div>
        </div>
      )}
    </Card>
  )
}
