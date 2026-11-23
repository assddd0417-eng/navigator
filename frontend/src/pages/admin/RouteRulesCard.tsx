import { useState } from 'react'
import {
  deleteProgramRoute, routeRules, saveProgramRoute,
  type RouteRuleProgram, type RouteRules,
} from '../../api/navigator'
import { useAuth } from '../../auth/AuthContext'
import { useToast } from '../../components/Toast'
import { Card, useAction, useAsync } from '../../components/ui'

export function RouteRulesCard() {
  const { role } = useAuth()
  const canEdit = role === 'PROGRAM_OWNER' || role === 'AX_ADMIN'
  const rules = useAsync(() => routeRules(), [])
  return (
    <Card title="성장경로 기준">
      {!canEdit && <p className="small muted">수정은 지원사업 소관부서와 AX 주관부서가 합니다.</p>}
      {!rules.data ? <div className="page-loading">{rules.loading ? '불러오는 중…' : '불러오지 못했습니다.'}</div>
        : <RulesBody rules={rules.data} reload={() => void rules.reload()} canEdit={canEdit} />}
    </Card>
  )
}

function scoresText(p: RouteRuleProgram, rules: RouteRules) {
  const s = Object.entries(p.entry_min_scores ?? {})
  if (!s.length) return '없음'
  return s.map(([k, v]) => `${rules.areas.find((a) => a.code === k)?.label ?? k} ${v}`).join(' · ')
}

function RulesBody({ rules, reload, canEdit }: { rules: RouteRules; reload: () => void; canEdit: boolean }) {
  const [editing, setEditing] = useState<number | null>(null)
  const [removing, setRemoving] = useState<number | null>(null)
  const { busy, run } = useAction()
  const toast = useToast()
  const linked = rules.programs
    .filter((p) => p.stage_code)
    .sort((a, b) => rules.stages.findIndex((s) => s.code === a.stage_code) - rules.stages.findIndex((s) => s.code === b.stage_code) || a.sort_order - b.sort_order)
  const unlinked = rules.programs.filter((p) => !p.stage_code)
  const stageName = (c: string | null) => rules.stages.find((s) => s.code === c)?.name_ko ?? '–'

  const remove = (p: RouteRuleProgram) => run(async () => {
    await deleteProgramRoute(p.program_id)
    setRemoving(null)
    toast.show({ kind: 'success', title: '연계를 해제했습니다', message: p.name })
    reload()
  })
  const form = (p: RouteRuleProgram) => (
    <RouteForm p={p} rules={rules} onCancel={() => setEditing(null)}
      onSaved={() => { setEditing(null); reload() }} />
  )

  return (
    <>
      <table className="table">
        <thead><tr><th>단계</th><th>사업</th><th>진입조건</th><th>진입 점수</th><th>다음 연계사업</th><th>준비과제</th><th>반복 가능</th>{canEdit && <th />}</tr></thead>
        <tbody>
          {linked.map((p) => canEdit && editing === p.program_id ? (
            <tr key={p.program_id}><td colSpan={canEdit ? 8 : 7}>{form(p)}</td></tr>
          ) : (
            <tr key={p.program_id}>
              <td>{stageName(p.stage_code)}</td>
              <td>{p.name}</td>
              <td className="small">{p.entry_condition || '–'}</td>
              <td className="small">{scoresText(p, rules)}</td>
              <td className="small">{p.next_programs.map((n) => n.name).join(', ') || '–'}</td>
              <td className="small">{p.prep_tasks.join(', ') || '–'}</td>
              <td className="small">{p.repeatable ? '가능' : '불가'}</td>
              {canEdit && <td style={{ whiteSpace: 'nowrap' }}>
                {removing === p.program_id ? (
                  <>
                    <span className="small">해제할까요?</span>{' '}
                    <button className="btn btn-sm" disabled={busy} onClick={() => void remove(p)}>해제</button>
                    <button className="btn btn-sm" onClick={() => setRemoving(null)}>취소</button>
                  </>
                ) : (
                  <>
                    <button className="btn btn-sm" onClick={() => { setEditing(p.program_id); setRemoving(null) }}>수정</button>
                    <button className="btn btn-sm" onClick={() => setRemoving(p.program_id)}>연계 해제</button>
                  </>
                )}
              </td>}
            </tr>
          ))}
        </tbody>
      </table>
      <h4>연계 기준 없음</h4>
      {!unlinked.length ? <p className="small muted">모든 사업에 기준이 있습니다.</p> : (
        <table className="table">
          <tbody>
            {unlinked.map((p) => canEdit && editing === p.program_id ? (
              <tr key={p.program_id}><td>{form(p)}</td></tr>
            ) : (
              <tr key={p.program_id}>
                <td>{p.name}</td>
                <td className="small muted">{p.purpose ?? ''}</td>
                {canEdit && <td style={{ textAlign: 'right' }}>
                  <button className="btn btn-sm" onClick={() => setEditing(p.program_id)}>추가</button>
                </td>}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}

function RouteForm({ p, rules, onCancel, onSaved }:
  { p: RouteRuleProgram; rules: RouteRules; onCancel: () => void; onSaved: () => void }) {
  const [stage, setStage] = useState(p.stage_code ?? rules.stages[0]?.code ?? '')
  const [next, setNext] = useState<number[]>(p.next_program_ids ?? [])
  const [cond, setCond] = useState(p.entry_condition ?? '')
  const [mins, setMins] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(p.entry_min_scores ?? {}).map(([k, v]) => [k, String(v)])))
  const [tasks, setTasks] = useState((p.prep_tasks ?? []).join('\n'))
  const [out, setOut] = useState(p.expected_output ?? '')
  const [rep, setRep] = useState(p.repeatable)
  const [order, setOrder] = useState(String(p.sort_order ?? 0))
  const { busy, run } = useAction()
  const toast = useToast()

  const save = () => run(async () => {
    const entry_min_scores: Record<string, number> = {}
    for (const [k, v] of Object.entries(mins)) {
      if (v.trim() !== '' && !Number.isNaN(Number(v))) entry_min_scores[k] = Math.round(Number(v))
    }
    await saveProgramRoute(p.program_id, {
      stage_code: stage,
      next_program_ids: next,
      entry_condition: cond.trim(),
      entry_min_scores,
      prep_tasks: tasks.split('\n').map((t) => t.trim()).filter(Boolean),
      expected_output: out.trim(),
      repeatable: rep,
      sort_order: Number(order) || 0,
    })
    toast.show({ kind: 'success', title: '기준을 저장했습니다', message: p.name })
    onSaved()
  })

  return (
    <div className="stack" style={{ padding: '8px 0' }}>
      <strong>{p.name}</strong>
      <div className="form-row">
        <label>단계
          <select value={stage} onChange={(e) => setStage(e.target.value)}>
            {rules.stages.map((s) => <option key={s.code} value={s.code}>{s.name_ko}</option>)}
          </select>
        </label>
        <label>정렬 순서
          <input type="number" value={order} onChange={(e) => setOrder(e.target.value)} />
        </label>
        <label className="inline-check check">
          <input type="checkbox" checked={rep} onChange={(e) => setRep(e.target.checked)} /> 반복 가능
        </label>
      </div>
      <div>
        <div className="small muted">다음 연계사업</div>
        <div className="chips" style={{ marginTop: 4 }}>
          {rules.programs.filter((o) => o.program_id !== p.program_id).map((o) => (
            <label key={o.program_id} className="check small">
              <input type="checkbox" checked={next.includes(o.program_id)}
                onChange={(e) => setNext(e.target.checked ? [...next, o.program_id] : next.filter((x) => x !== o.program_id))} />
              {o.name}
            </label>
          ))}
        </div>
      </div>
      <label className="small muted">진입조건
        <input value={cond} onChange={(e) => setCond(e.target.value)} />
      </label>
      <div>
        <div className="small muted">진입 점수 (비우면 기준 없음)</div>
        <div className="form-row">
          {rules.areas.map((a) => (
            <label key={a.code} className="small">{a.label}
              <input type="number" min={0} max={100} value={mins[a.code] ?? ''}
                onChange={(e) => setMins({ ...mins, [a.code]: e.target.value })} />
            </label>
          ))}
        </div>
      </div>
      <label className="small muted">준비과제 (한 줄에 하나)
        <textarea rows={3} value={tasks} onChange={(e) => setTasks(e.target.value)} />
      </label>
      <label className="small muted">예상 산출물
        <input value={out} onChange={(e) => setOut(e.target.value)} />
      </label>
      <div>
        <button className="btn btn-primary btn-sm" disabled={busy || !stage} onClick={() => void save()}>{busy ? '저장 중…' : '저장'}</button>
        <button className="btn btn-sm" disabled={busy} onClick={onCancel}>취소</button>
      </div>
    </div>
  )
}
