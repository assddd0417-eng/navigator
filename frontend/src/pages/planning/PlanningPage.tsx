import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  briefToDemand, createTrend, getBrief, listTrends, type Brief, type BriefProject, type CompareStatus, type Comparator,
  type SuggestionKind, type TrendKind,
} from '../../api/planning'
import { useAuth } from '../../auth/AuthContext'
import { canAccessPath } from '../../auth/roles'
import { useToast } from '../../components/Toast'
import { Card, Empty, More, PageHeader, RoleHint, Steps, useAction, useAsync } from '../../components/ui'
import { GAP_STATUS } from '../gaps/gapText'

/** 동향 종류 (backend planning_brief.DEMAND_KIND_KO 와 같은 이름) */
const KINDS: { code: TrendKind; name: string; group: '해외' | '국내' }[] = [
  { code: 'ROADMAP', name: '해외 기술로드맵', group: '해외' },
  { code: 'CALL', name: '해외 공모', group: '해외' },
  { code: 'EXPORT_REQ', name: '수출 요구', group: '해외' },
  { code: 'DOMESTIC_PLAN', name: '국내 계획(국방부·방사청)', group: '국내' },
  { code: 'UPGRADE', name: '성능개량 요구', group: '국내' },
  { code: 'SUPPLY', name: '국산화·단종 대응', group: '국내' },
]
const DOMESTIC = new Set<TrendKind>(KINDS.filter((k) => k.group === '국내').map((k) => k.code))

const SUGGESTION_TONE: Record<SuggestionKind, string> = {
  CAUTION: 'bad', UPGRADE: 'warn', RESOLVE: 'warn', EVAL: 'info', LOCALIZE: 'info', NEW: 'muted', REUSE: 'ok',
}
const COMPARE_TONE: Record<CompareStatus, string> = {
  MET: 'ok', SHORT: 'warn', NO_DATA: 'bad', UNIT_DIFF: 'muted', TEXT: 'muted',
}
const EVAL_KIND: Record<string, string> = { RESULT: '결과평가', INTERIM: '중간평가', EXPERT: '전문가 의견', USER: '소요군 의견' }

const fmt = (v: number | null | undefined, unit?: string | null) =>
  v == null ? '–' : `${Number(v).toLocaleString('ko-KR', { maximumFractionDigits: 2 })}${unit ?? ''}`

interface PerfRow { metric_name: string; comparator: Comparator; value: string; unit: string; text: string }
const emptyPerf = (): PerfRow => ({ metric_name: '', comparator: 'GTE', value: '', unit: '', text: '' })

/** 동향 직접 입력 (국제동향 조사팀·기획자) */
function TrendForm({ onCreated, onCancel }: { onCreated: (id: number) => void; onCancel: () => void }) {
  const toast = useToast()
  const { busy, run } = useAction()
  const [f, setF] = useState({
    title: '', demand_kind: 'UPGRADE' as TrendKind, region: '', requirement: '', source_note: '',
    target_system: '', target_period: '',
  })
  const [perfs, setPerfs] = useState<PerfRow[]>([emptyPerf()])
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  const setPerf = (i: number, k: keyof PerfRow) => (e: { target: { value: string } }) =>
    setPerfs(perfs.map((p, j) => (j === i ? { ...p, [k]: e.target.value } : p)))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const res = await run(() => createTrend({
      ...f, target_system: f.target_system || null, target_period: f.target_period || null,
      performances: perfs.filter((p) => p.metric_name.trim()).map((p) => ({
        metric_name: p.metric_name.trim(), comparator: p.comparator,
        required_value: p.value.trim() ? Number(p.value) : null,
        required_text: p.text.trim() || null, unit: p.unit.trim() || null,
      })),
    }))
    if (res) {
      toast.success('동향을 저장했습니다', '관련된 과거 과제를 찾아 기획 참고서를 만들었습니다.')
      onCreated(res.id)
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <label>동향 제목<input value={f.title} onChange={set('title')} required
        placeholder="예: K2 전차 수출형 파워팩 고온 내구도 요구" /></label>
      <div className="form-row">
        <label>어떤 동향인가요?<select value={f.demand_kind} onChange={set('demand_kind')}>
          {(['해외', '국내'] as const).map((g) => (
            <optgroup key={g} label={g}>
              {KINDS.filter((k) => k.group === g).map((k) => <option key={k.code} value={k.code}>{k.name}</option>)}
            </optgroup>
          ))}
        </select></label>
        <label>나라·기관<input value={f.region} onChange={set('region')} required placeholder="예: 폴란드, 방위사업청, 육군" /></label>
      </div>
      <label>요구 내용<textarea value={f.requirement} onChange={set('requirement')} required rows={3}
        placeholder="예: 사막·고온 환경에서 파워팩 연속 운용 시간 확보, 현지 정비 가능해야 함" /></label>
      <label>출처 (기관·자료명·날짜)<input value={f.source_note} onChange={set('source_note')} required
        placeholder="예: 국방중기계획 2026~2030, 방위사업청 보도자료 2026.10.2" /></label>
      <div className="form-row">
        <label>무기체계·품목 (선택)<input value={f.target_system} onChange={set('target_system')} placeholder="예: K2 전차 파워팩" /></label>
        <label>목표 시기 (선택)<input value={f.target_period} onChange={set('target_period')} placeholder="예: 2028~2030" /></label>
      </div>
      <fieldset className="pl-perfs">
        <legend>요구 성능 (숫자가 있으면 과거 성과와 바로 견줘 봅니다)</legend>
        {perfs.map((p, i) => (
          <div key={i} className="pl-perf-row">
            <input value={p.metric_name} onChange={setPerf(i, 'metric_name')} placeholder="지표 (예: 최대출력)" aria-label="지표" />
            <select value={p.comparator} onChange={setPerf(i, 'comparator')} aria-label="조건">
              <option value="GTE">이상</option><option value="LTE">이하</option><option value="EQ">같음</option>
            </select>
            <input value={p.value} onChange={setPerf(i, 'value')} type="number" step="any" placeholder="값" aria-label="값" />
            <input value={p.unit} onChange={setPerf(i, 'unit')} placeholder="단위" aria-label="단위" />
            <input value={p.text} onChange={setPerf(i, 'text')} placeholder="숫자가 없으면 설명" aria-label="설명" />
            <button type="button" className="btn btn-ghost btn-sm" title="이 줄 빼기"
              onClick={() => setPerfs(perfs.length > 1 ? perfs.filter((_, j) => j !== i) : [emptyPerf()])}>✕</button>
          </div>
        ))}
        <button type="button" className="btn btn-sm" onClick={() => setPerfs([...perfs, emptyPerf()])}>+ 요구 성능 추가</button>
      </fieldset>
      <div className="form-foot">
        <RoleHint roles={['PLANNER', 'CURATOR']} />
        <button type="button" className="btn btn-ghost" onClick={onCancel}>취소</button>
        <button className="btn btn-primary" disabled={busy}>{busy ? '저장 중…' : '동향 저장'}</button>
      </div>
    </form>
  )
}

function ProjectBlock({ p }: { p: BriefProject }) {
  return (
    <li className={`pl-project ${p.outcome_is_failure ? 'pl-project-fail' : ''}`}>
      <div className="gap-item-head">
        <strong>{p.title}</strong>
        <span className="muted small">{[p.project_no, p.program_name, p.period, p.department].filter(Boolean).join(' · ')}</span>
        <span className="gap-item-right">
          <span className="badge badge-muted" title="이 동향과 비슷한 정도">비슷한 정도 {Math.round(p.similarity * 100)}%</span>
          <span className={`badge badge-${p.outcome_is_failure ? 'bad' : p.outcome_code ? 'ok' : 'muted'}`}
            title={p.outcome_note ?? undefined}>{p.outcome_name ?? '결과 미확인'}</span>
        </span>
      </div>
      {p.outcome_note && <p className="small">{p.outcome_is_failure ? '⚠ 실패 원인: ' : '결과: '}{p.outcome_note}</p>}
      {p.cards.map((c) => (
        <div key={c.card_id} className="pl-card">
          <div><strong>성과</strong> {c.title}{c.trl ? <span className="muted small"> · 기술성숙도 {c.trl}단계</span> : null}</div>
          {c.performances.length > 0 && (
            <div className="small">
              {c.performances.map((x) => (
                <span key={x.metric_name} className={`pl-perf ${x.is_achieved === false ? 'pl-perf-miss' : ''}`}>
                  {x.metric_name} {x.target_value != null && <>목표 {fmt(x.target_value, x.unit)} · </>}달성 {fmt(x.achieved_value, x.unit)}
                  {x.is_achieved === false && ' (미달)'}
                </span>
              ))}
            </div>
          )}
          {c.limits.length > 0 && (
            <ul className="pl-limits">
              {c.limits.map((l, i) => <li key={i}><span className="badge badge-muted">{l.issue_type_name}</span> {l.description}</li>)}
            </ul>
          )}
        </div>
      ))}
      {p.evaluations.length > 0 && (
        <div className="pl-evals">
          {p.evaluations.map((e) => (
            <blockquote key={e.id}>
              <div className="small"><strong>{EVAL_KIND[e.eval_kind]}</strong>{e.grade && ` · ${e.grade}`}
                {e.evaluator && ` · ${e.evaluator}`}{e.eval_date && ` · ${e.eval_date}`}</div>
              {e.opinion}
              {e.suggestion && <div className="small">→ 권고: {e.suggestion}</div>}
            </blockquote>
          ))}
        </div>
      )}
    </li>
  )
}

function BriefView({ trendId, wide, onWide }: { trendId: number; wide: boolean; onWide: (v: boolean) => void }) {
  const toast = useToast()
  const navigate = useNavigate()
  const { role } = useAuth()
  const { busy, run } = useAction()
  const { data: b, loading } = useAsync<Brief>(() => getBrief(trendId, wide), [trendId, wide])
  const canOpenDemand = canAccessPath(role, '/projects')

  const handOff = async () => {
    const res = await run(() => briefToDemand(trendId, wide))
    if (!res) return
    toast.success(res.created ? '기획수요를 만들었습니다' : '이미 만든 기획수요가 있습니다',
      `${res.demand_no} · 기획 참고서를 붙여 두었고, 이어서 이어 쓸 성과를 찾을 수 있습니다.`)
    navigate(`/projects?demand=${res.demand_id}`)
  }

  if (loading && !b) return <div className="page-loading">기획 참고서 만드는 중…</div>
  if (!b) return null
  const t = b.trend
  const s = b.summary
  return (
    <>
      <Card title={t.title} actions={<span className="pill">{t.demand_kind_name}</span>}>
        <p>{t.requirement}</p>
        <div className="muted small">
          {[t.region, t.target_system, t.target_period && `목표 시기 ${t.target_period}`].filter(Boolean).join(' · ')}
        </div>
        <div className="muted small">출처: {t.sources.length
          ? t.sources.map((x, i) => <span key={x.source_no}>{i > 0 && ', '}<a href={x.url} target="_blank" rel="noreferrer">{x.issuer} 「{x.title}」</a></span>)
          : t.source_note ?? '–'}</div>
      </Card>

      <div className="kpi-row">
        <div className="kpi"><div className="kpi-label">관련 과거 과제</div><div className="kpi-value">{s.project_count}</div>
          <div className="kpi-target">{Object.entries(s.outcomes).map(([k, v]) => `${k} ${v}`).join(' · ') || '없음'}</div></div>
        <div className="kpi"><div className="kpi-label">요구 성능 충족</div><div className="kpi-value">{s.met}</div>
          <div className="kpi-target">과거 성과로 이미 달성</div></div>
        <div className="kpi"><div className="kpi-label">부족 · 자료 없음</div><div className="kpi-value">{s.short}<span className="kpi-sub"> · {s.no_data}</span></div>
          <div className="kpi-target">새 과제의 목표가 될 부분</div></div>
        <div className="kpi"><div className="kpi-label">먼저 풀 실패 원인</div><div className="kpi-value">{s.cautions}</div>
          <div className="kpi-target">원인 해결 방안이 기획서에 있어야 함</div></div>
      </div>

      <Card title="새 기획에 넣을 것" actions={<RoleHint roles={['PLANNER']} />}>
        <ul className="pl-suggestions">
          {b.suggestions.map((x, i) => (
            <li key={i}>
              <span className={`badge badge-${SUGGESTION_TONE[x.kind]}`}>{x.kind_name}</span>
              <div><strong>{x.title}</strong><div className="muted small">{x.detail}</div></div>
            </li>
          ))}
        </ul>
        <div className="form-foot">
          {b.planning_demand ? (
            canOpenDemand
              ? <Link to={`/projects?demand=${b.planning_demand.id}`} className="btn">기획수요 {b.planning_demand.demand_no} 열기 →</Link>
              : <span className="badge badge-ok">기획수요 {b.planning_demand.demand_no}로 넘김</span>
          ) : (
            <button className="btn btn-primary" disabled={busy} onClick={() => void handOff()}>
              {busy ? '만드는 중…' : '이 내용으로 기획수요 만들기'}</button>
          )}
        </div>
      </Card>

      {b.comparison.length > 0 && (
        <Card title="요구 성능 ↔ 과거 성과">
          <div className="table-scroll">
            <table className="table">
              <thead><tr><th>지표</th><th>요구</th><th className="num">과거 최고 달성</th><th>판단</th><th>근거 과제</th></tr></thead>
              <tbody>
                {b.comparison.map((r) => (
                  <tr key={r.metric_name}>
                    <td>{r.metric_name}</td>
                    <td>{r.required}</td>
                    <td className="num">{fmt(r.achieved_value, r.unit)}{r.ratio != null && r.ratio < 1 && <span className="muted small"> ({Math.round(r.ratio * 100)}%)</span>}</td>
                    <td><span className={`badge badge-${COMPARE_TONE[r.status]}`}>{r.status_name}</span>{r.note && <div className="muted small">{r.note}</div>}</td>
                    <td className="small">{r.project_title ?? '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card title={`관련 과거 과제 ${b.projects.length}건`}
        actions={<label className="pl-check small"><input type="checkbox" checked={wide} onChange={(e) => onWide(e.target.checked)} /> 덜 비슷한 과제도 보기</label>}>
        {b.projects.length === 0 ? (
          <Empty>이 동향과 가까운 과거 과제를 찾지 못했습니다. ‘덜 비슷한 과제도 보기’를 켜거나, 새 과제로 기획하세요.</Empty>
        ) : <ul className="pl-projects">{b.projects.map((p) => <ProjectBlock key={p.project_id} p={p} />)}</ul>}
      </Card>

      {b.gaps.length > 0 && (
        <More label={`이 동향의 갭 분석 결과 ${b.gaps.length}건`}>
          <ul className="pl-gaps">
            {b.gaps.map((g) => (
              <li key={g.id}>
                <span className={`gap-chip gap-${g.gap_type_code}`}>{g.gap_type_name}</span>{' '}
                <span className={`badge badge-${GAP_STATUS[g.status]?.tone ?? 'muted'}`}>{GAP_STATUS[g.status]?.label ?? g.status}</span>{' '}
                <Link to={`/gaps/${g.id}`}>{g.summary}</Link>
              </li>
            ))}
          </ul>
        </More>
      )}
    </>
  )
}

/**
 * 신규 과제 기획: 동향(해외·국내 요구)을 고르면 관련된 과거 과제의 결과·한계·평가 의견을 모아
 * 새 기획에 넣을 것을 정리하고, 그대로 기획수요로 넘긴다.
 * 고른 동향·보기 범위는 주소(?trend=&group=&wide=1)에 남긴다.
 */
export function PlanningPage() {
  const [params, setParams] = useSearchParams()
  const trends = useAsync(listTrends)
  const showForm = params.get('new') === '1'
  const group = params.get('group') as '해외' | '국내' | null
  const wide = params.get('wide') === '1'
  const all = trends.data ?? []
  const list = all.filter((t) => !group || (group === '국내') === DOMESTIC.has(t.demand_kind))
  const wanted = Number(params.get('trend')) || null
  const current = all.some((t) => t.id === wanted) ? wanted : list[0]?.id ?? null

  const go = (next: Record<string, string | null>, push = true) => {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(next)) { if (v == null) p.delete(k); else p.set(k, v) }
    setParams(p, { replace: !push })
  }

  return (
    <>
      <PageHeader title="신규 과제 기획"
        subtitle="해외·국내 동향을 고르면 관련된 과거 과제가 어떻게 끝났는지, 무엇이 모자랐는지, 평가에서 무슨 말을 들었는지 모아 새 기획에 넣을 것을 정리합니다."
        actions={!showForm && <button className="btn btn-primary" onClick={() => go({ new: '1' })}>+ 동향 입력</button>} />

      {showForm ? (
        <Card title="동향 입력">
          <TrendForm onCancel={() => go({ new: null }, false)}
            onCreated={(id) => { go({ new: null, trend: String(id), group: null }, false); void trends.reload() }} />
        </Card>
      ) : (<>
        <Steps items={[
          '왼쪽에서 동향을 고릅니다. 새 동향은 ‘+ 동향 입력’으로 직접 적습니다.',
          '관련 과거 과제의 결과(전력화·전환 실패 등)와 한계·평가 의견을 확인합니다.',
          '‘새 기획에 넣을 것’을 보고 ‘이 내용으로 기획수요 만들기’를 누르면 연계 후보 찾기로 이어집니다.',
        ]} />
        <div className="grid-side">
          <Card title={`동향 ${list.length}건`} className="list-card"
            actions={
              <div className="seg">
                <button className={!group ? 'on' : ''} onClick={() => go({ group: null }, false)}>전체</button>
                <button className={group === '해외' ? 'on' : ''} onClick={() => go({ group: '해외' }, false)}>해외</button>
                <button className={group === '국내' ? 'on' : ''} onClick={() => go({ group: '국내' }, false)}>국내</button>
              </div>
            }>
            {trends.loading && !trends.data && <div className="page-loading">불러오는 중…</div>}
            {trends.data && list.length === 0 && <Empty>동향이 없습니다. 오른쪽 위 ‘+ 동향 입력’으로 시작하세요.</Empty>}
            <ul className="select-list">
              {list.map((t) => (
                <li key={t.id}>
                  <button className={t.id === current ? 'on' : ''} onClick={() => go({ trend: String(t.id) })}>
                    <strong>{t.title}</strong>
                    <span className="muted small">{t.demand_kind_name} · {t.region}
                      {t.planning_demand_no && <> · <span className="badge badge-ok">기획수요 있음</span></>}</span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          <div className="stack">
            {current ? <BriefView key={current} trendId={current} wide={wide} onWide={(v) => go({ wide: v ? '1' : null }, false)} />
              : !trends.loading && <Empty>동향을 고르세요.</Empty>}
          </div>
        </div>
      </>)}
    </>
  )
}
