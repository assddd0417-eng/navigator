import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  assignReview, createDemand, getDemand, getMatchRun, getRecommendation, listCards, listDemands, runMatch,
  searchDocuments, type AssignmentCreate, type ChunkHit, type RecommendationOverview,
} from '../../api/endpoints'
import { useToast } from '../../components/Toast'
import {
  Card, CRITERIA_LABELS, Empty, fmtDate, PageHeader, RoleHint, score, StatusBadge, useAction, useAsync,
} from '../../components/ui'

/** 시드 사업 (seeds/init_test_data.sql) */
const PROGRAMS = [
  { id: 1, name: '부품국산화개발지원' },
  { id: 2, name: '핵심기술개발' },
]

/** 검토 배정 대상 (시드: 전문가 사용자 3, 소관부서 3 = 무인미래통신기술팀) */
const ASSIGN_PRESETS: { label: string; body: AssignmentCreate }[] = [
  { label: '전문가(기술전문가)', body: { review_role: 'EXPERT', assignee_user_id: 3 } },
  { label: '소관부서(무인미래통신기술팀)', body: { review_role: 'DEPT_OWNER', assignee_dept_id: 3 } },
]

function DemandForm({ onCreated }: { onCreated: (id: number) => void }) {
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
      toast.success('기획수요를 등록했습니다', `${f.demand_no} · ${f.title}`)
      onCreated(res.id)
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <div className="form-row">
        <label>수요번호<input value={f.demand_no} onChange={set('demand_no')} required /></label>
        <label className="grow">제목<input value={f.title} onChange={set('title')} required
          placeholder="예: 광대역 재밍 대응 정찰드론 데이터링크" /></label>
      </div>
      <label>필요 기술<textarea value={f.tech_need} onChange={set('tech_need')} required rows={2}
        placeholder="예: 광대역 재밍 환경에서 드론 데이터링크 주파수 도약 동기 유지 시간 확보" /></label>
      <label>기술요소 (쉼표로 구분, 2개 이상이면 융합형도 탐색)<input value={f.techs} onChange={set('techs')}
        placeholder="주파수 도약 항재밍 데이터링크, EO/IR 영상 딥러닝 표적 자동탐지" /></label>
      <div className="form-row">
        <label>사업목적<input value={f.business_purpose} onChange={set('business_purpose')} placeholder="미래 핵심기술 확보" /></label>
        <label>요구 TRL<span className="inline">
          <input type="number" min={1} max={9} value={f.trl_min} onChange={set('trl_min')} />~
          <input type="number" min={1} max={9} value={f.trl_max} onChange={set('trl_max')} /></span></label>
        <label>대상 사업<select value={f.program} onChange={set('program')}>
          {PROGRAMS.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select></label>
      </div>
      <div className="form-foot">
        <RoleHint roles={['PLANNER']} />
        <button className="btn btn-primary" disabled={busy}>{busy ? '등록 중…' : '기획수요 등록'}</button>
      </div>
    </form>
  )
}

/** 상위 3건: 연계유형·기준별 점수·첫 원문 근거를 한눈에 (시연 핵심 화면) */
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
              <span className={`pill linkage-${r.linkage_type_code}`}>{r.linkage_type_name}</span>
              <span className="top3-score">{score(r.total_score)}</span>
            </div>
            <strong>{(r.source_cards ?? []).map((c) => c.title).join(' + ')}</strong>
            <div className="muted small">{r.owner_department ?? ''}</div>
            {r.scores && (
              <div className="top3-scores">
                {Object.entries(CRITERIA_LABELS).map(([k, label]) => (
                  <span key={k} title={label}>{label} {score(r.scores?.[k] ?? null)}</span>
                ))}
              </div>
            )}
            {d && d.evidence.length === 0 && r.evidence_count > 0 && <div className="notice small">🔒 근거 문서 열람 권한 없음</div>}
            {ev && (
              <div className="top3-ev">
                <div className="evidence-src">📄 {ev.document_title}{ev.section_heading && ` · ${ev.section_heading}`}{ev.page_start && ` · ${ev.page_start}쪽`}</div>
                <blockquote>{ev.quote && ev.quote.length > 90 ? `${ev.quote.slice(0, 90)}…` : ev.quote}</blockquote>
              </div>
            )}
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
      toast.success('검토를 배정했습니다', `추천 #${rec.recommendation_id} → ${preset.label}`)
      void reload()
    }
  }

  if (loading && !data) return <div className="page-loading">추천 결과 불러오는 중…</div>
  if (!data) return null
  const recs = data.recommendations.filter((r) => !r.is_excluded)
  return (
    <Card title={`매칭 실행 #${data.id} 추천 결과`} actions={<StatusBadge status={data.status} />}>
      {recs.length === 0 ? <Empty>기준 점수를 넘은 추천이 없습니다.</Empty> : (<>
        <TopThree recs={recs} />
        <h4>전체 추천 ({recs.length}건)</h4>
        <table className="table">
          <thead>
            <tr><th>순위</th><th>연계유형</th><th>기존 성과</th><th>점수</th><th>근거</th><th>상태</th><th>검토 배정 <RoleHint roles={['PLANNER']} /></th></tr>
          </thead>
          <tbody>
            {recs.map((r) => (
              <tr key={r.recommendation_id}>
                <td>{r.rank}</td>
                <td><span className="pill">{r.linkage_type_name}</span></td>
                <td>
                  <Link to={`/recommendations/${r.recommendation_id}`}>
                    {(r.source_cards ?? []).map((c) => c.title).join(' + ')}
                  </Link>
                  <div className="muted small">{r.owner_department ?? ''}</div>
                </td>
                <td>{score(r.total_score)}</td>
                <td>{r.evidence_count > 0 ? `${r.evidence_count}건` : <span className="warn-text">없음</span>}</td>
                <td><StatusBadge status={r.status} /></td>
                <td className="nowrap">
                  {ASSIGN_PRESETS.map((p) => (
                    <button key={p.label} className="btn btn-sm" disabled={busy || r.status === 'DECIDED'}
                      onClick={() => void assign(r, p)}>{p.body.review_role === 'EXPERT' ? '전문가' : '소관부서'}</button>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </>)}
      <p className="muted small">근거가 없는 추천이나 성과카드 1개짜리 융합형은 DB 규칙에 따라 배정이 거부됩니다 (422).</p>
    </Card>
  )
}

function DemandDetailPanel({ demandId }: { demandId: number }) {
  const toast = useToast()
  const { busy, run } = useAction()
  const { data, reload } = useAsync(() => getDemand(demandId), [demandId])
  const [runId, setRunId] = useState<number | null>(null)
  const latest = runId ?? data?.match_runs[0]?.id ?? null

  const match = async () => {
    const res = await run(() => runMatch(demandId, 10))
    if (res) {
      toast.success('AI 매칭을 실행했습니다', `매칭 실행 #${res.id}`)
      setRunId(res.id)
      void reload()
    }
  }

  if (!data) return null
  return (
    <>
      <Card title={`${data.demand_no} · ${data.title}`}
        actions={<><RoleHint roles={['PLANNER']} />
          <button className="btn btn-primary" disabled={busy} onClick={() => void match()}>
            {busy ? '매칭 중…' : '🔎 AI 매칭 실행'}</button></>}>
        <p>{data.tech_need}</p>
        <div className="muted small">
          요구 TRL {data.required_trl_min ?? '–'}~{data.required_trl_max ?? '–'} · 매칭 실행 {data.match_runs.length}회
        </div>
        {data.match_runs.length > 1 && (
          <div className="chips">
            {data.match_runs.map((m) => (
              <button key={m.id} className={`chip ${m.id === latest ? 'chip-on' : ''}`} onClick={() => setRunId(m.id)}>
                #{m.id} {fmtDate(m.created_at)}
              </button>
            ))}
          </div>
        )}
      </Card>
      {latest && <Recommendations key={latest} runId={latest} />}
    </>
  )
}

/** R&D 성과물 원문 검색: 결과보고서 문단을 의미로 찾는다 (열람 권한이 있는 문서만) */
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
    <Card title="🔍 R&D 성과물 검색">
      <form className="search-row" onSubmit={submit}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="예: 광대역 재밍 환경 통신 유지, 회전익 자동비행" />
        <button className="btn btn-primary" disabled={busy}>{busy ? '검색 중…' : '검색'}</button>
      </form>
      {hits && (hits.length === 0 ? <Empty>찾은 원문이 없습니다.</Empty> : (
        <ul className="evidence">
          {hits.map((h) => (
            <li key={h.chunk_id}>
              <div className="evidence-src">
                📄 {h.document_title}{h.heading && ` · ${h.heading}`}{h.page_start && ` · ${h.page_start}쪽`}
                <span className="pill">유사도 {score(h.similarity)}</span>
              </div>
              <blockquote>{h.content}</blockquote>
            </li>
          ))}
        </ul>
      ))}
    </Card>
  )
}

/** 프로젝트 관리: 기획수요 → AI 매칭 → 검토 배정, 성과카드 현황 */
export function ProjectsPage() {
  const demands = useAsync(listDemands)
  const cards = useAsync(() => listCards())
  const [selected, setSelected] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [allCards, setAllCards] = useState(false)
  const current = selected ?? demands.data?.[0]?.id ?? null

  return (
    <>
      <PageHeader title="프로젝트 관리" subtitle="신규 기획수요에 맞는 기존 성과를 AI 로 찾고, 검토자를 배정합니다."
        actions={<button className="btn" onClick={() => setShowForm((v) => !v)}>{showForm ? '닫기' : '+ 기획수요 등록'}</button>} />

      {showForm && (
        <Card title="신규 기획수요 등록">
          <DemandForm onCreated={(id) => { setShowForm(false); setSelected(id); void demands.reload() }} />
        </Card>
      )}

      <div className="grid-side">
        <Card title="기획수요" className="list-card">
          {demands.data?.length === 0 && <Empty>등록된 기획수요가 없습니다.</Empty>}
          <ul className="select-list">
            {demands.data?.map((d) => (
              <li key={d.id}>
                <button className={d.id === current ? 'on' : ''} onClick={() => setSelected(d.id)}>
                  <strong>{d.title}</strong>
                  <span className="muted small">{d.demand_no} · <StatusBadge status={d.status} /></span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
        <div className="stack">
          {current ? <DemandDetailPanel key={current} demandId={current} /> : <Empty>기획수요를 선택하세요.</Empty>}
        </div>
      </div>

      <OutcomeSearch />

      <Card title={`성과 활용카드 (기존 과제 성과 ${cards.data?.length ?? 0}건)`}
        actions={(cards.data?.length ?? 0) > 10 && (
          <button className="btn btn-sm" onClick={() => setAllCards((v) => !v)}>{allCards ? '10건만 보기' : '전체 보기'}</button>)}>
        {cards.data?.length === 0 ? <Empty>성과카드가 없습니다. 큐레이터가 문서 업로드 화면에서 만들 수 있습니다.</Empty> : (
          <table className="table">
            <thead><tr><th>카드번호</th><th>제목</th><th>과제</th><th>TRL</th><th>상태</th><th>수정일</th></tr></thead>
            <tbody>
              {cards.data?.slice(0, allCards ? undefined : 10).map((c) => (
                <tr key={c.id}>
                  <td>{c.card_no}</td><td>{c.title}</td>
                  <td>{c.project_no} <span className="muted small">{c.project_title}</span></td>
                  <td>{c.trl ?? '–'}</td><td><StatusBadge status={c.status} /></td><td>{fmtDate(c.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  )
}
