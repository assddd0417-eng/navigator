import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  createExecution, EXEC_STATUS, EXEC_TYPES, getExecutionKpi, getLineage, listAdoptedCandidates, listExecutions,
  patchExecution, type AdoptedCandidate, type ExecStatus, type ExecType,
} from '../../api/reviewSheets'
import { useToast } from '../../components/Toast'
import { Card, Empty, PageHeader, RoleHint, Steps, useAction, useAsync } from '../../components/ui'

const tone = (s: ExecStatus) => (s === 'COMPLETED' ? 'ok' : s === 'DROPPED' ? 'bad' : s === 'IN_PROGRESS' ? 'warn' : 'muted')

/**
 * 연계 실행 결과 (기획자·담당부서 검수자): 채택된 추천이 실제 과제·사업화로 이어졌는지 기록하고,
 * 이어진 과제의 새 성과가 다시 기존 성과가 되는 순환(계보)을 보여 준다.
 */
export function ExecutionsPage() {
  const toast = useToast()
  const { busy, run } = useAction()
  const kpi = useAsync(getExecutionKpi, [])
  const cands = useAsync(listAdoptedCandidates, [])
  const execs = useAsync(listExecutions, [])
  const [target, setTarget] = useState<AdoptedCandidate | null>(null)
  const [f, setF] = useState({ execution_type: 'NEW_PROJECT' as ExecType, status: 'PLANNED' as ExecStatus,
    project_no: '', project_title: '', executed_on: '', note: '' })
  const [lineageCard, setLineageCard] = useState<number | null>(null)
  const lineage = useAsync(async () => (lineageCard ? getLineage(lineageCard) : null), [lineageCard])

  const reload = () => { void kpi.reload(); void cands.reload(); void execs.reload() }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!target) return
    const res = await run(() => createExecution({
      recommendation_id: target.recommendation_id, execution_type: f.execution_type, status: f.status,
      new_project: f.project_no ? { project_no: f.project_no, title: f.project_title || f.project_no } : null,
      executed_on: f.executed_on || null, note: f.note || undefined }))
    if (!res) return
    toast.success('연계 실행을 기록했습니다', res.project_relation_id ? '기존 과제 → 이어진 과제 관계도 남겼습니다.' : undefined)
    setTarget(null)
    setF({ execution_type: 'NEW_PROJECT', status: 'PLANNED', project_no: '', project_title: '', executed_on: '', note: '' })
    reload()
  }

  const setStatus = async (id: number, status: ExecStatus) => {
    const res = await run(() => patchExecution(id, { status }))
    if (!res) return
    toast.success('상태를 바꿨습니다', res.eval_case_id && status === 'COMPLETED'
      ? '실제 연계 사례로 검증 자료에 추가했습니다. 다음 추천 적중률 측정에 쓰입니다.' : undefined)
    reload()
  }

  const k = kpi.data
  const waiting = (cands.data ?? []).filter((c) => c.execution_count === 0)
  const list = execs.data ?? []
  return (
    <>
      <PageHeader title="연계 실행 결과"
        subtitle="채택된 후보가 실제 과제·사업화·수출로 이어졌는지 기록합니다. 이어진 과제의 새 성과는 다시 기존 성과가 되어 다음 이어달리기 후보로 돌아옵니다." />
      <Steps items={[
        '담당부서가 채택한 후보 가운데 아직 결과를 남기지 않은 것을 골라 실행을 기록합니다.',
        '이어진 과제가 있으면 과제번호를 적습니다. 기존 과제 → 이어진 과제 관계가 자동으로 남습니다.',
        '완료로 바꾸면 실제 연계 사례로 검증 자료에 들어가, 추천이 맞았는지 다시 재는 데 쓰입니다.',
      ]} />

      <div className="kpi-row">
        <div className="kpi"><div className="kpi-label">채택 → 실행 기록</div>
          <div className="kpi-value">{k ? `${k.conversion_pct}%` : '–'}</div>
          <div className="kpi-target">채택 {k?.adopted ?? '–'}건 중 {k?.adopted_executed ?? '–'}건</div></div>
        <div className="kpi"><div className="kpi-label">연계 실행</div><div className="kpi-value">{k?.executions ?? '–'}</div>
          <div className="kpi-target">완료 {k?.completed ?? 0} · 진행 {k?.ongoing ?? 0} · 중단 {k?.dropped ?? 0}</div></div>
        <div className="kpi"><div className="kpi-label">AI 추천으로 발굴</div><div className="kpi-value">{k?.discovered_by_ax ?? '–'}</div>
          <div className="kpi-target">추가 연계후보 성과</div></div>
        <div className="kpi"><div className="kpi-label">순환</div>
          <div className="kpi-value">{k?.resulting_projects ?? '–'}<span className="kpi-sub"> 과제</span></div>
          <div className="kpi-target">새 성과 {k?.resulting_cards ?? 0}건 · 검증 사례 {k?.eval_cases ?? 0}건</div></div>
      </div>

      <Card title={`실행 기록을 기다리는 채택 후보 (${waiting.length}건)`} actions={<RoleHint roles={['PLANNER', 'DEPT_REVIEWER']} />}>
        {waiting.length === 0 ? <Empty>모든 채택 후보에 결과를 남겼습니다.</Empty> : (
          <table className="table">
            <thead><tr><th>기존 성과</th><th>연계 대상</th><th>연계유형</th><th>담당부서</th><th /></tr></thead>
            <tbody>
              {waiting.map((c) => (
                <tr key={c.recommendation_id} className={target?.recommendation_id === c.recommendation_id ? 'pf-row-on' : ''}>
                  <td>{c.source_cards.map((s) => <div key={s.card_id}><strong>{s.title}</strong> <span className="muted small">{s.project_no}</span></div>)}</td>
                  <td>{c.demand_title ?? c.target_program_name ?? '–'}</td>
                  <td>{c.linkage_type_name}</td>
                  <td>{c.owner_department ?? '–'}</td>
                  <td><button className="btn" onClick={() => setTarget(c)}>결과 기록</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {target && (
          <form className="stack rs-decision-form" onSubmit={(e) => void submit(e)}>
            <p><strong>{target.source_cards[0]?.title}</strong> → {target.demand_title ?? target.target_program_name}</p>
            <div className="form-row">
              <label>어떻게 이어졌나요<select value={f.execution_type} onChange={(e) => setF({ ...f, execution_type: e.target.value as ExecType })}>
                {Object.entries(EXEC_TYPES).map(([c, n]) => <option key={c} value={c}>{n}</option>)}
              </select></label>
              <label>상태<select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value as ExecStatus })}>
                {Object.entries(EXEC_STATUS).map(([c, n]) => <option key={c} value={c}>{n}</option>)}
              </select></label>
              <label>날짜<input type="date" value={f.executed_on} onChange={(e) => setF({ ...f, executed_on: e.target.value })} /></label>
            </div>
            <div className="form-row">
              <label>이어진 과제번호 (있으면)<input value={f.project_no} onChange={(e) => setF({ ...f, project_no: e.target.value })}
                placeholder="예: PRJ-2027-001" /></label>
              <label className="grow">이어진 과제 이름<input value={f.project_title} onChange={(e) => setF({ ...f, project_title: e.target.value })} /></label>
            </div>
            <label>메모<input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} placeholder="예: 12월 통합기획 회의 결정에 따라 기획 착수" /></label>
            <div><button className="btn btn-primary" disabled={busy}>기록</button>{' '}
              <button type="button" className="btn btn-ghost" onClick={() => setTarget(null)}>취소</button></div>
          </form>
        )}
      </Card>

      <Card title={`연계 실행 기록 (${list.length}건)`}>
        {list.length === 0 ? <Empty>아직 기록이 없습니다.</Empty> : (
          <div className="table-scroll">
            <table className="table">
              <thead><tr><th>기존 성과</th><th>이어진 곳</th><th>방식</th><th>연계유형</th><th>날짜</th><th>상태</th><th /></tr></thead>
              <tbody>
                {list.map((x) => (
                  <tr key={x.id}>
                    <td><strong>{x.card_title}</strong><div className="muted small">{x.source_project_no}</div></td>
                    <td>{x.resulting_project_no ? <>{x.resulting_project_title}<div className="muted small">{x.resulting_project_no}
                      {x.resulting_cards > 0 ? ` · 새 성과 ${x.resulting_cards}건` : ''}</div></> : (x.organization_name ?? x.demand_title ?? '–')}</td>
                    <td>{x.execution_type_name}{!x.discovered_by_ax && <div className="muted small">직접 발굴</div>}</td>
                    <td>{x.linkage_type_name}</td>
                    <td className="small">{x.executed_on ?? '–'}</td>
                    <td><select value={x.status} disabled={busy} onChange={(e) => void setStatus(x.id, e.target.value as ExecStatus)}
                      className={`sel-${tone(x.status)}`}>
                      {Object.entries(EXEC_STATUS).map(([c, n]) => <option key={c} value={c}>{n}</option>)}
                    </select>{x.eval_case_id && <div><span className="badge badge-ok">검증 사례</span></div>}</td>
                    <td><button className="btn btn-ghost" onClick={() => setLineageCard(x.source_card_id)}>계보 보기</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {lineageCard && lineage.data && (
        <Card title={`이어달리기 계보: ${lineage.data.card.title}`}
          actions={<button className="btn btn-ghost" onClick={() => setLineageCard(null)}>닫기 ✕</button>}>
          <ol className="lineage">
            {lineage.data.ancestors.map((a) => (
              <li key={a.project_no} className="lineage-up">
                <strong>{a.project_title}</strong> <span className="muted small">{a.project_no}</span>
                <div className="small">성과: {a.cards.map((c) => c.title).join(', ') || '–'}{a.linkage_type_name ? ` → ${a.linkage_type_name}` : ''}</div>
              </li>
            ))}
            <li className="lineage-me"><strong>{lineage.data.card.title}</strong>
              <span className="muted small"> {lineage.data.card.project_no} · {lineage.data.card.project_title}</span></li>
            {lineage.data.descendants.map((d) => (
              <li key={d.id} className="lineage-down" style={{ marginLeft: d.level * 16 }}>
                <span className="badge badge-info">{d.execution_type_name}</span>{' '}
                <span className={`badge badge-${tone(d.status)}`}>{d.status_name}</span>{' '}
                {d.resulting_project_title ?? d.organization_name ?? d.demand_title}
                {d.resulting_project_no && <span className="muted small"> {d.resulting_project_no}</span>}
                {d.next_cards.length > 0 && <div className="small">→ 새 성과: {d.next_cards.map((c) => c.title).join(', ')}
                  <span className="muted"> (다시 이어달리기 후보가 됩니다)</span></div>}
              </li>
            ))}
          </ol>
          <p className="muted small">위는 이 성과를 낳은 앞 과제, 아래는 이 성과에서 이어진 실행과 그 결과입니다. <Link to="/projects">연계 후보 찾기</Link>에서 새 성과로 다시 추천을 받을 수 있습니다.</p>
        </Card>
      )}
    </>
  )
}
