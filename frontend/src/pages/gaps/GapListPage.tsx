import { Link, useSearchParams } from 'react-router-dom'
import { getGapSummary, listGapFindings, runGapAnalysis } from '../../api/gaps'
import { useToast } from '../../components/Toast'
import { Card, Empty, PageHeader, RoleHint, Steps, useAction, useAsync } from '../../components/ui'
import { DEMAND_KIND, GAP_STATUS, GAP_TYPES, urgency } from './gapText'

const GapBadge = ({ status }: { status: string }) => (
  <span className={`badge badge-${GAP_STATUS[status]?.tone ?? 'muted'}`}>{GAP_STATUS[status]?.label ?? status}</span>
)

/**
 * 해외 수요 갭 분석 (기관용): 해외에서 원하는 기술 ↔ 국내 R&D 성과를 비교해 모자란 곳을 보여 준다.
 * 보기(?view=todo|all)는 주소에 남겨 새로고침·뒤로가기 때 유지한다.
 */
export function GapListPage() {
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const view = params.get('view') === 'all' ? 'all' : 'todo'
  const { busy, run } = useAction()
  const data = useAsync(async () => {
    const [summary, findings] = await Promise.all([getGapSummary(), listGapFindings('open')])
    return { summary, findings }
  })

  const rerun = async () => {
    const res = await run(() => runGapAnalysis())
    if (res) {
      toast.success('갭 분석을 다시 했습니다', `해외 수요 ${res.demand_count}건을 비교해 갭 ${res.finding_count}건을 찾았습니다. 모두 검수 전입니다.`)
      void data.reload()
    }
  }

  const summary = data.data?.summary ?? []
  const findings = data.data?.findings ?? []
  const shown = view === 'todo' ? findings.filter((f) => f.status === 'DRAFT') : findings
  const drafts = findings.filter((f) => f.status === 'DRAFT').length

  return (
    <>
      <PageHeader title="해외 수요 갭 분석"
        subtitle="해외에서 원하는 기술(로드맵·공모·수출 요구)과 국내 R&D 성과를 비교해, 우리가 모자란 곳과 메울 방법을 보여 줍니다."
        actions={<><RoleHint roles={['PLANNER', 'CURATOR']} />
          <button className="btn" disabled={busy} onClick={() => void rerun()}>{busy ? '비교하는 중…' : '↻ 지금 다시 분석'}</button></>} />
      <Steps items={[
        '아래 표에서 해외 수요마다 어떤 종류의 갭이 있는지 봅니다. 빈칸은 그 부분은 국내 성과로 충분하다는 뜻입니다.',
        '갭을 누르면 이유, 가장 가까운 국내 성과, 메울 방법(추천 연계 방식)과 출처가 나옵니다.',
        'AI가 찾은 갭은 모두 ‘검수 전’ 상태입니다. 담당 부서 검수자가 확정하거나 기각해야 공식 결과가 됩니다.',
      ]} />

      <Card title="갭 종류">
        <ul className="gap-legend">
          {GAP_TYPES.map((g) => <li key={g.code}><span className={`gap-chip gap-${g.code}`}>{g.name}</span> {g.help}</li>)}
        </ul>
      </Card>

      <Card title={`해외 수요 ${summary.length}건 × 갭 종류`}>
        {data.loading && !data.data ? <div className="page-loading">불러오는 중…</div> : summary.length === 0 ? (
          <Empty>등록된 해외 수요가 없습니다. 해외 수요 자료(엑셀)를 올리면 자동으로 비교합니다.</Empty>
        ) : (
          <table className="table gap-matrix">
            <thead>
              <tr><th>해외 수요</th>{GAP_TYPES.map((g) => <th key={g.code} title={g.help}>{g.name}</th>)}</tr>
            </thead>
            <tbody>
              {summary.map((d) => (
                <tr key={d.overseas_demand_id}>
                  <td><strong>{d.title}</strong><div className="muted small">{d.region}{d.tech_area ? ` · ${d.tech_area}` : ''}</div></td>
                  {GAP_TYPES.map((g) => {
                    const hit = d.gaps[g.code]
                    if (!hit) return <td key={g.code} className="gap-none" title="이 부분은 갭 없음">–</td>
                    const u = urgency(hit.score)
                    return (
                      <td key={g.code}>
                        <Link to={`/gaps/${hit.finding_id}`} className={`gap-cell gap-cell-${u.tone}`}>
                          <span>{u.label}</span>
                          <GapBadge status={hit.status} />
                        </Link>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="갭 목록 (급한 순)"
        actions={
          <div className="seg">
            <button className={view === 'todo' ? 'on' : ''} onClick={() => setParams({}, { replace: true })}>검수 기다리는 것 {drafts}</button>
            <button className={view === 'all' ? 'on' : ''} onClick={() => setParams({ view: 'all' }, { replace: true })}>확정 포함 전체 {findings.length}</button>
          </div>
        }>
        {shown.length === 0 ? <Empty>{view === 'todo' ? '검수를 기다리는 갭이 없습니다.' : '열려 있는 갭이 없습니다.'}</Empty> : (
          <ul className="gap-list">
            {shown.map((f) => {
              const u = urgency(f.score)
              return (
                <li key={f.id}>
                  <Link to={`/gaps/${f.id}`} className="gap-item">
                    <div className="gap-item-head">
                      <span className={`gap-chip gap-${f.gap_type_code}`}>{f.gap_type_name}</span>
                      <strong>{f.demand_title}</strong>
                      <span className="muted small">{f.region} · {DEMAND_KIND[f.demand_kind] ?? ''}</span>
                      <span className="gap-item-right"><span className={`badge badge-${u.tone}`}>{u.label}</span> <GapBadge status={f.status} /></span>
                    </div>
                    <p className="gap-summary">{f.summary}</p>
                  </Link>
                </li>
              )
            })}
          </ul>
        )}
      </Card>
    </>
  )
}
