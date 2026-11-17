import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  assignReview, createDemand, getDemand, getMatchRun, getRecommendation, listCards, listDemands, runMatch,
  searchDocuments, type AssignmentCreate, type ChunkHit, type RecommendationOverview,
} from '../../api/endpoints'
import { useToast } from '../../components/Toast'
import {
  Card, CRITERIA_LABELS, Empty, Fit, fmtDate, LINKAGE_HELP, More, PageHeader, pct100, RoleHint, scoreText, SimBadge, StatusBadge, Steps,
  trlText, useAction, useAsync,
} from '../../components/ui'

/** 시드 사업 (seeds/init_test_data.sql) */
const PROGRAMS = [
  { id: 1, name: '부품국산화개발지원' },
  { id: 2, name: '핵심기술개발' },
]

/** 검토 배정 대상 (시드: 전문가 사용자 3, 소관부서 3 = 무인미래통신기술팀) */
const ASSIGN_PRESETS: { label: string; short: string; body: AssignmentCreate }[] = [
  { label: '기술전문가', short: '전문가에게', body: { review_role: 'EXPERT', assignee_user_id: 3 } },
  { label: '담당 부서(무인미래통신기술팀)', short: '담당 부서에', body: { review_role: 'DEPT_OWNER', assignee_dept_id: 3 } },
]

function DemandForm({ onCreated, onCancel }: { onCreated: (id: number) => void; onCancel: () => void }) {
  const toast = useToast()
  const { busy, run } = useAction()
  const [f, setF] = useState({
    demand_no: `DM-${new Date().getFullYear()}-${String(Date.now()).slice(-4)}`,
    title: '', tech_need: '', business_purpose: '', trl_min: '5', trl_max: '7', program: '2', techs: '',
  })
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const res = await run(() => createDemand({
      demand_no: f.demand_no, title: f.title, tech_need: f.tech_need,
      business_purpose: f.business_purpose || null,
      required_trl_min: f.trl_min ? Number(f.trl_min) : null,
      required_trl_max: f.trl_max ? Number(f.trl_max) : null,
      target_program_id: Number(f.program),
      technologies: f.techs.split(',').map((t) => t.trim()).filter(Boolean).map((tech_name) => ({ tech_name })),
    }))
    if (res) {
      toast.success('기획수요를 등록했습니다', `이제 ‘AI로 이어 쓸 성과 찾기’를 눌러 보세요`)
      onCreated(res.id)
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <label>무엇이 필요한가요? (제목)<input value={f.title} onChange={set('title')} required
        placeholder="예: 광대역 재밍 대응 정찰드론 데이터링크" /></label>
      <label>필요한 기술을 한두 문장으로<textarea value={f.tech_need} onChange={set('tech_need')} required rows={2}
        placeholder="예: 광대역 재밍 환경에서 드론 데이터링크 주파수 도약 동기 유지 시간 확보" /></label>
      <label>핵심 기술 낱말 (쉼표로 구분 · 2개 이상 적으면 여러 성과를 합치는 ‘융합형’도 찾아봅니다)
        <input value={f.techs} onChange={set('techs')} placeholder="주파수 도약 항재밍 데이터링크, EO/IR 영상 표적 자동탐지" /></label>
      <div className="form-row">
        <label>어느 사업으로 할까요?<select value={f.program} onChange={set('program')}>
          {PROGRAMS.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select></label>
        <label>필요한 기술 성숙도(TRL)<span className="inline">
          <input type="number" min={1} max={9} value={f.trl_min} onChange={set('trl_min')} />단계 ~
          <input type="number" min={1} max={9} value={f.trl_max} onChange={set('trl_max')} />단계</span>
          <span className="hint">1단계 아이디어 · 4단계 실험실 시험 · 6단계 시제품 · 9단계 실전 배치</span></label>
      </div>
      <More label="더 적기 (선택)">
        <div className="form-row">
          <label>사업 목적<input value={f.business_purpose} onChange={set('business_purpose')} placeholder="미래 핵심기술 확보" /></label>
          <label>관리 번호 (자동으로 만들어짐)<input value={f.demand_no} onChange={set('demand_no')} required /></label>
        </div>
      </More>
      <div className="form-foot">
        <RoleHint roles={['PLANNER']} />
        <button type="button" className="btn btn-ghost" onClick={onCancel}>취소</button>
        <button className="btn btn-primary" disabled={busy}>{busy ? '등록 중…' : '기획수요 등록'}</button>
      </div>
    </form>
  )
}

/** 상위 3건: 어떤 방식으로 이어 쓰는지·적합도·근거 문장 한 줄 */
function TopThree({ recs }: { recs: RecommendationOverview[] }) {
  const top = recs.slice(0, 3)
  const ids = top.map((r) => r.recommendation_id).join(',')
  const { data } = useAsync(() => Promise.all(top.map((r) => getRecommendation(r.recommendation_id))), [ids])
  if (top.length === 0) return null
  return (
    <div className="top3">
      {top.map((r, i) => {
        const d = data?.[i]
        const ev = d?.evidence.find((e) => e.quote)
        return (
          <Link key={r.recommendation_id} to={`/recommendations/${r.recommendation_id}`} className="top3-card">
            <div className="top3-head">
              <span className="top3-rank">{r.rank}위</span>
              <span className={`pill linkage-${r.linkage_type_code}`} title={LINKAGE_HELP[r.linkage_type_code]}>{r.linkage_type_name}</span>
              <span className="top3-score"><Fit value={r.total_score} /></span>
            </div>
            <strong>{(r.source_cards ?? []).map((c) => c.title).join(' + ')}</strong>
            <div className="muted small">{LINKAGE_HELP[r.linkage_type_code]}{r.owner_department ? ` · 담당 ${r.owner_department}` : ''}</div>
            {r.scores && (
              <div className="top3-scores">
                {Object.entries(CRITERIA_LABELS).map(([k, label]) => (
                  <span key={k} title={pct100(r.scores?.[k] ?? null)}>{label} <b>{scoreText(k, r.scores?.[k])}</b></span>
                ))}
              </div>
            )}
            {d && d.evidence.length === 0 && r.evidence_count > 0 && <div className="notice small">🔒 근거 문서는 내 열람 권한 밖이라 가려졌습니다</div>}
            {ev && (
              <div className="top3-ev">
                <div className="evidence-src">📄 {ev.document_title}{ev.page_start && ` · ${ev.page_start}쪽`}</div>
                <blockquote>{ev.quote && ev.quote.length > 90 ? `${ev.quote.slice(0, 90)}…` : ev.quote}</blockquote>
              </div>
            )}
            <span className="top3-go">자세히 보고 검토하기 →</span>
          </Link>
        )
      })}
    </div>
  )
}

function Recommendations({ runId }: { runId: number }) {
  const toast = useToast()
  const { busy, run } = useAction()
  const { data, loading, reload } = useAsync(() => getMatchRun(runId), [runId])

  const assign = async (rec: RecommendationOverview, preset: (typeof ASSIGN_PRESETS)[number]) => {
    const res = await run(() => assignReview(rec.recommendation_id, preset.body))
    if (res) {
      toast.success('검토를 요청했습니다', `${rec.rank}위 추천 → ${preset.label}`)
      void reload()
    }
  }

  if (loading && !data) return <div className="page-loading">추천 결과 불러오는 중…</div>
  if (!data) return null
  const recs = data.recommendations.filter((r) => !r.is_excluded)
  return (
    <Card title="AI가 찾은 이어 쓸 성과" actions={<span className="muted small">{fmtDate(data.created_at)} 기준</span>}>
      {recs.length === 0 ? <Empty>조건에 맞는 기존 성과를 찾지 못했습니다. 필요한 기술 설명을 조금 넓혀 다시 등록해 보세요.</Empty> : (<>
        <TopThree recs={recs} />
        <h4>전체 후보 {recs.length}건 · 마음에 드는 후보에 검토를 요청하세요</h4>
        <table className="table">
          <thead>
            <tr><th>순위</th><th>이어 쓸 성과</th><th>연계 방식</th><th>적합도</th><th>근거 문서</th><th>진행 상태</th><th>검토 요청 <RoleHint roles={['PLANNER']} /></th></tr>
          </thead>
          <tbody>
            {recs.map((r) => (
              <tr key={r.recommendation_id}>
                <td>{r.rank}</td>
                <td>
                  <Link to={`/recommendations/${r.recommendation_id}`}>
                    {(r.source_cards ?? []).map((c) => c.title).join(' + ')}
                  </Link>
                  <div className="muted small">{r.owner_department ?? ''}</div>
                </td>
                <td><span className={`pill linkage-${r.linkage_type_code}`} title={LINKAGE_HELP[r.linkage_type_code]}>{r.linkage_type_name}</span></td>
                <td className="nowrap"><Fit value={r.total_score} /></td>
                <td>{r.evidence_count > 0 ? `${r.evidence_count}건` : <span className="warn-text">없음</span>}</td>
                <td><StatusBadge status={r.status} /></td>
                <td className="nowrap">
                  {r.status === 'DECIDED' || r.status === 'WITHDRAWN' ? <span className="muted small">끝난 건</span> :
                    ASSIGN_PRESETS.map((p) => (
                      <button key={p.label} className="btn btn-sm" disabled={busy} title={`${p.label}에게 검토 요청`}
                        onClick={() => void assign(r, p)}>{p.short}</button>
                    ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </>)}
      <p className="muted small">근거 문서가 없는 추천, 성과가 하나뿐인 융합형은 규칙상 검토를 요청할 수 없습니다.</p>
    </Card>
  )
}

function DemandDetailPanel({ demandId, runId, onRun }:
  { demandId: number; runId: number | null; onRun: (id: number, push: boolean) => void }) {
  const toast = useToast()
  const { busy, run } = useAction()
  const { data, reload } = useAsync(() => getDemand(demandId), [demandId])
  // 주소에 회차가 없거나 이 수요의 회차가 아니면 가장 최근 회차
  const latest = data?.match_runs.some((m) => m.id === runId) ? runId : data?.match_runs[0]?.id ?? null

  const match = async () => {
    const res = await run(() => runMatch(demandId, 10))
    if (res) {
      toast.success('AI가 이어 쓸 성과를 찾았습니다')
      onRun(res.id, true)
      void reload()
    }
  }

  if (!data) return <div className="page-loading">불러오는 중…</div>
  const runs = data.match_runs
  return (
    <>
      <Card title={data.title} actions={<StatusBadge status={data.status} />}>
        <p>{data.tech_need}</p>
        <div className="muted small">필요한 기술 성숙도 {trlText(data.required_trl_min, data.required_trl_max)} · 관리 번호 {data.demand_no}
          {data.origin_overseas_demand_id != null && data.origin_gap_finding_id == null && (
            <> · <Link to={`/planning?trend=${data.origin_overseas_demand_id}`}>📝 기획 참고서 보기</Link></>)}</div>
        <div className="form-foot">
          <RoleHint roles={['PLANNER']} />
          <button className="btn btn-primary" disabled={busy} onClick={() => void match()}>
            {busy ? 'AI가 찾는 중…' : runs.length ? '🔎 AI로 다시 찾기' : '🔎 AI로 이어 쓸 성과 찾기'}</button>
        </div>
        {runs.length > 1 && (
          <div className="chips">
            <span className="muted small">이전 결과 보기:</span>
            {runs.map((m, i) => (
              <button key={m.id} className={`chip ${m.id === latest ? 'chip-on' : ''}`} onClick={() => onRun(m.id, false)}>
                {runs.length - i}회차 · {fmtDate(m.created_at)}
              </button>
            ))}
          </div>
        )}
      </Card>
      {latest ? <Recommendations key={latest} runId={latest} />
        : <Empty>아직 AI 추천을 받지 않았습니다. 위의 ‘AI로 이어 쓸 성과 찾기’를 눌러 보세요.</Empty>}
    </>
  )
}

/** R&D 성과물 원문 검색: 결과보고서 문단을 뜻으로 찾는다 (열람 권한이 있는 문서만) */
function OutcomeSearch() {
  const { busy, run } = useAction()
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<ChunkHit[] | null>(null)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!q.trim()) return
    const res = await run(() => searchDocuments(q.trim()))
    if (res) setHits(res)
  }
  return (
    <Card title="결과보고서 내용 검색">
      <p className="muted small">낱말이 정확히 같지 않아도 뜻이 비슷한 문단을 찾아 줍니다. 내가 볼 수 있는 문서만 나옵니다.</p>
      <form className="search-row" onSubmit={submit}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="예: 광대역 재밍 환경 통신 유지, 회전익 자동비행" />
        <button className="btn btn-primary" disabled={busy}>{busy ? '찾는 중…' : '검색'}</button>
      </form>
      {hits && (hits.length === 0 ? <Empty>찾은 문단이 없습니다. 다른 말로 검색해 보세요.</Empty> : (
        <ul className="evidence">
          {hits.map((h) => (
            <li key={h.chunk_id}>
              <div className="evidence-src">
                📄 {h.document_title}{h.heading && ` · ${h.heading}`}{h.page_start && ` · ${h.page_start}쪽`}
                <SimBadge value={h.similarity} title="검색어와 뜻이 비슷한 정도" />
              </div>
              <blockquote>{h.content}</blockquote>
            </li>
          ))}
        </ul>
      ))}
    </Card>
  )
}

function CardList() {
  const cards = useAsync(() => listCards())
  const [all, setAll] = useState(false)
  const rows = cards.data ?? []
  return (
    <Card title={`성과카드 ${rows.length}장 (끝난 과제의 성과 요약)`}
      actions={rows.length > 10 && (
        <button className="btn btn-sm" onClick={() => setAll((v) => !v)}>{all ? '10장만 보기' : '전체 보기'}</button>)}>
      {cards.loading && !cards.data ? <div className="page-loading">불러오는 중…</div> : rows.length === 0
        ? <Empty>성과카드가 없습니다. 큐레이터가 ‘문서 올리기’에서 만들 수 있습니다.</Empty> : (
        <table className="table">
          <thead><tr><th>성과</th><th>과제</th><th>기술 성숙도</th><th>상태</th><th>고친 날</th></tr></thead>
          <tbody>
            {rows.slice(0, all ? undefined : 10).map((c) => (
              <tr key={c.id}>
                <td>{c.title}<div className="muted small">{c.card_no}</div></td>
                <td>{c.project_title}<div className="muted small">{c.project_no}</div></td>
                <td>{c.trl == null ? '–' : `${c.trl}단계`}</td><td><StatusBadge status={c.status} /></td><td>{fmtDate(c.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted small">‘발행됨’ 카드만 AI 추천 대상이 됩니다.</p>
    </Card>
  )
}

const TABS = [['match', '기획수요별 추천'], ['search', '보고서 내용 검색'], ['cards', '성과카드 목록']] as const
type Tab = (typeof TABS)[number][0]

/**
 * 연계 후보 찾기: 기획수요 → AI 추천 → 검토 요청.
 * 고른 수요·회차·탭은 주소(?demand=&run=&tab=)에 남겨 새로고침·뒤로가기·링크 공유 때도 같은 화면이 나온다.
 */
export function ProjectsPage() {
  const [params, setParams] = useSearchParams()
  const demands = useAsync(listDemands)
  const tab: Tab = (TABS.find(([k]) => k === params.get('tab'))?.[0]) ?? 'match'
  const showForm = params.get('new') === '1'
  const wanted = Number(params.get('demand')) || null
  const list = demands.data ?? []
  const current = list.some((d) => d.id === wanted) ? wanted : list[0]?.id ?? null
  const runId = Number(params.get('run')) || null

  const go = (next: Record<string, string | null>, push = true) => {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(next)) { if (v == null) p.delete(k); else p.set(k, v) }
    setParams(p, { replace: !push })
  }

  return (
    <>
      <PageHeader title="연계 후보 찾기" subtitle="새로 필요한 기술(기획수요)에 이어 쓸 수 있는 기존 R&D 성과를 AI로 찾고, 검토를 맡깁니다."
        actions={!showForm && <button className="btn btn-primary" onClick={() => go({ new: '1', tab: null })}>+ 기획수요 등록</button>} />

      {showForm ? (
        <Card title="새 기획수요 등록">
          <DemandForm onCancel={() => go({ new: null }, false)}
            onCreated={(id) => { go({ new: null, demand: String(id), run: null }, false); void demands.reload() }} />
        </Card>
      ) : (
        <div className="seg tabs">
          {TABS.map(([k, label]) => (
            <button key={k} className={tab === k ? 'on' : ''} onClick={() => go({ tab: k === 'match' ? null : k })}>{label}</button>
          ))}
        </div>
      )}

      {!showForm && tab === 'match' && (<>
        <Steps items={[
          '왼쪽 목록에서 기획수요를 고릅니다. 없으면 ‘+ 기획수요 등록’.',
          '‘AI로 이어 쓸 성과 찾기’를 누릅니다.',
          '추천 카드를 눌러 근거를 확인하고, 괜찮으면 전문가나 담당 부서에 검토를 요청합니다.',
        ]} />
        <div className="grid-side">
          <Card title={`기획수요 ${list.length}건`} className="list-card">
            {demands.loading && !demands.data && <div className="page-loading">불러오는 중…</div>}
            {demands.data?.length === 0 && <Empty>등록된 기획수요가 없습니다. 오른쪽 위 ‘+ 기획수요 등록’으로 시작하세요.</Empty>}
            <ul className="select-list">
              {list.map((d) => (
                <li key={d.id}>
                  <button className={d.id === current ? 'on' : ''} onClick={() => go({ demand: String(d.id), run: null })}>
                    <strong>{d.title}</strong>
                    <span className="muted small"><StatusBadge status={d.status} /> {d.demand_no}</span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          <div className="stack">
            {current ? <DemandDetailPanel key={current} demandId={current} runId={runId}
              onRun={(id, push) => go({ demand: String(current), run: String(id) }, push)} />
              : !demands.loading && <Empty>기획수요를 고르세요.</Empty>}
          </div>
        </div>
      </>)}
      {!showForm && tab === 'search' && <OutcomeSearch />}
      {!showForm && tab === 'cards' && <CardList />}
    </>
  )
}
