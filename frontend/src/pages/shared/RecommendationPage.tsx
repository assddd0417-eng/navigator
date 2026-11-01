import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  addComment, getRecommendation, getRecommendationHistory, regenerateRationale, submitDecision,
  type DecisionCode, type EvidenceRow, type RecommendationDetail,
} from '../../api/endpoints'
import { useAuth } from '../../auth/AuthContext'
import { homePath, SEED_USERS } from '../../auth/roles'
import { useToast } from '../../components/Toast'
import {
  Card, CRITERIA_LABELS, DEPT_NAMES, Empty, fmtDate, LINKAGE_TYPES, num, PageHeader, REVIEW_ROLE_LABELS, RoleHint, score,
  StatusBadge, statusLabel, useAction, useAsync,
} from '../../components/ui'

/** 같은 문단이 성과·수요·RAG 근거로 여러 번 연결되면 한 번만 보이고 기준 표시만 모은다 */
function groupEvidence(rows: EvidenceRow[]) {
  const out: (EvidenceRow & { key: string; criteria: string[] })[] = []
  const seen = new Map<string, (typeof out)[number]>()
  for (const e of rows) {
    const key = `${e.document_id}|${e.page_start ?? ''}|${e.quote ?? e.evidence_id}`
    const hit = seen.get(key)
    const crit = e.criterion ? [e.criterion] : []
    if (hit) hit.criteria = [...new Set([...hit.criteria, ...crit])]
    else { const g = { ...e, key, criteria: crit }; seen.set(key, g); out.push(g) }
  }
  return out
}

const userName = (id: number | null) => SEED_USERS.find((u) => u.id === id)?.name ?? (id == null ? '–' : `사용자 ${id}`)

const DECISIONS: [DecisionCode, string][] = [
  ['ADOPT', '채택'], ['HOLD', '보류'], ['EXCLUDE', '제외'], ['NEEDS_INFO', '추가 정보 필요'],
]

function DecisionForm({ rec, onDone }: { rec: RecommendationDetail; onDone: () => void }) {
  const { user, role } = useAuth()
  const toast = useToast()
  const { busy, run } = useAction()
  const mine = rec.assignments.filter((a) =>
    ['PENDING', 'IN_PROGRESS'].includes(a.status)
    && (a.assignee_user_id === user?.id || (a.assignee_dept_id != null && a.assignee_dept_id === user?.department_id)))
  const [f, setF] = useState({
    decision_code: 'ADOPT' as DecisionCode, is_final: role === 'DEPT_REVIEWER',
    assignment_id: mine[0] ? String(mine[0].id) : '', override: '', opinion: '', relevance: '', adequacy: '',
  })

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const res = await run(() => submitDecision(rec.recommendation_id, {
      decision_code: f.decision_code, is_final: f.is_final,
      assignment_id: f.assignment_id === '' ? null : Number(f.assignment_id),
      linkage_type_override: f.override || null, opinion: f.opinion || null,
      relevance_rating: f.relevance ? Number(f.relevance) : null,
      evidence_adequacy: f.adequacy ? Number(f.adequacy) : null,
    }))
    if (res) {
      toast.success(f.is_final ? '최종 판정을 등록했습니다' : '검토 의견을 등록했습니다',
        `${statusLabel(f.decision_code)}${f.opinion ? ` · ${f.opinion}` : ''}`)
      setF({ ...f, opinion: '' })
      onDone()
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <div className="seg seg-wide">
        {DECISIONS.map(([c, n]) => (
          <button type="button" key={c} className={f.decision_code === c ? 'on' : ''}
            onClick={() => setF({ ...f, decision_code: c })}>{n}</button>
        ))}
      </div>
      <label className="check">
        <input type="checkbox" checked={f.is_final} onChange={(e) => setF({ ...f, is_final: e.target.checked })} />
        <span>최종 판정으로 등록</span>
        <RoleHint roles={['DEPT_REVIEWER']} />
      </label>
      <div className="form-row">
        <label>배정 건<select value={f.assignment_id} onChange={(e) => setF({ ...f, assignment_id: e.target.value })}>
          <option value="">(배정 없이)</option>
          {rec.assignments.map((a) => (
            <option key={a.id} value={a.id}>
              #{a.id} {REVIEW_ROLE_LABELS[a.review_role]} · {statusLabel(a.status)}
            </option>
          ))}
        </select></label>
        <label>연계유형 수정<select value={f.override} onChange={(e) => setF({ ...f, override: e.target.value })}>
          <option value="">(AI 판단 유지: {rec.linkage_type_name})</option>
          {Object.entries(LINKAGE_TYPES).map(([c, n]) => <option key={c} value={c}>{n}</option>)}
        </select></label>
        <label>관련성(1~5)<input type="number" min={1} max={5} value={f.relevance}
          onChange={(e) => setF({ ...f, relevance: e.target.value })} /></label>
        <label>근거 적절성(1~5)<input type="number" min={1} max={5} value={f.adequacy}
          onChange={(e) => setF({ ...f, adequacy: e.target.value })} /></label>
      </div>
      <label>검토 의견<textarea rows={3} value={f.opinion} onChange={(e) => setF({ ...f, opinion: e.target.value })}
        placeholder="예: 미해결 기술과 수요가 직결되어 후속형으로 적절함" /></label>
      <div className="form-foot">
        <RoleHint roles={['DEPT_REVIEWER', 'EXPERT']} />
        <button className="btn btn-primary" disabled={busy}>{busy ? '등록 중…' : f.is_final ? '최종 판정 등록' : '검토 의견 등록'}</button>
      </div>
    </form>
  )
}

function Comments({ rec, onDone }: { rec: RecommendationDetail; onDone: () => void }) {
  const toast = useToast()
  const { busy, run } = useAction()
  const [body, setBody] = useState('')

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (await run(() => addComment(rec.recommendation_id, body))) {
      toast.success('의견을 남겼습니다')
      setBody('')
      onDone()
    }
  }

  return (
    <>
      {rec.comments.length === 0 ? <Empty>아직 의견이 없습니다.</Empty> : (
        <ul className="comments">
          {rec.comments.map((c) => (
            <li key={c.id}><strong>{userName(c.author_id)}</strong> <span className="muted small">{fmtDate(c.created_at)}</span><p>{c.body}</p></li>
          ))}
        </ul>
      )}
      <form className="form form-inline" onSubmit={submit}>
        <input value={body} onChange={(e) => setBody(e.target.value)} placeholder="의견을 입력하세요 (모든 역할 가능)" required />
        <button className="btn" disabled={busy}>등록</button>
      </form>
    </>
  )
}

/** AI 연계이유 다시 생성 (기획 담당, 검토 종료 전) — 실패하면 규칙 문장 유지 */
function RegenerateRationale({ rec, onDone }: { rec: RecommendationDetail; onDone: () => void }) {
  const toast = useToast()
  const { busy, run } = useAction()
  if (['DECIDED', 'WITHDRAWN'].includes(rec.status)) return null
  const click = async () => {
    const res = await run(() => regenerateRationale(rec.recommendation_id))
    if (!res) return
    if (res.status === 'OK') toast.success('AI 연계이유를 생성했습니다', '원문 근거만 사용해 작성했습니다')
    else toast.show({ kind: 'info', title: 'AI 문장을 쓰지 못해 규칙 문장을 유지합니다', message: res.error ?? '' })
    onDone()
  }
  return (
    <div className="form-row">
      <button type="button" className="btn" disabled={busy} onClick={click}>
        {busy ? 'AI 작성 중…' : 'AI 연계이유 다시 생성'}
      </button>
      <RoleHint roles={['PLANNER']} />
    </div>
  )
}

/** 추천 상세 · 검수/의견 작성 (모든 역할 열람, 판정은 역할별로 서버가 판단) */
export function RecommendationPage() {
  const id = Number(useParams().id)
  const { role } = useAuth()
  const rec = useAsync(() => getRecommendation(id), [id])
  const hist = useAsync(() => getRecommendationHistory(id), [id])
  const reload = () => { void rec.reload(); void hist.reload() }

  if (rec.loading && !rec.data) return <div className="page-loading">불러오는 중…</div>
  const r = rec.data
  if (!r) return <Empty>추천을 불러오지 못했습니다. <Link to={role ? homePath(role) : '/'}>돌아가기</Link></Empty>
  const hiddenEvidence = r.evidence_count > 0 && r.evidence.length === 0
  const evidence = groupEvidence(r.evidence)
  const finalDecision = r.decisions.find((d) => d.is_final)

  return (
    <>
      <PageHeader
        title={`추천 #${r.recommendation_id} · ${r.linkage_type_name}`}
        subtitle={`${r.demand_title ?? '기획수요'} ← ${(r.source_cards ?? []).map((c) => c.title).join(' + ')}`}
        actions={<StatusBadge status={r.status} />} />

      <div className="grid-2">
        <Card title="AI 추천 근거">
          <div className="score-total">종합 점수 <strong>{score(r.total_score)}</strong>
            {r.final_linkage_type_code && <span className="pill">최종 유형: {LINKAGE_TYPES[r.final_linkage_type_code]}</span>}</div>
          <div className="bars">
            {r.score_details.map((s) => (
              <div key={s.criterion} className="bar-row">
                <span>{CRITERIA_LABELS[s.criterion] ?? s.criterion}</span>
                <div className="bar"><div style={{ width: `${Math.round((num(s.score) ?? 0) * 100)}%` }} /></div>
                <span className="num">{score(s.score)}</span>
              </div>
            ))}
          </div>
          {r.rationale && <>
            <h4>연계 이유{r.rationale_source === 'LLM' && <span className="muted"> · AI 작성(원문 근거 기반, 검토 필요)</span>}</h4>
            <p>{r.rationale}</p>
            {r.rationale_source === 'TEMPLATE_RESTRICTED' &&
              <div className="notice">🔒 AI 작성 문장은 열람 권한이 없는 근거 문서를 참고해 가려졌고, 규칙 기반 문장을 표시합니다.</div>}
            {r.rationale_generation?.status === 'FALLBACK' &&
              <div className="muted small">AI 문장 생성에 실패해 규칙 기반 문장을 표시합니다 ({r.rationale_generation.error})</div>}
            <RegenerateRationale rec={r} onDone={reload} />
          </>}
          {r.development_needs && <><h4>개발 필요사항</h4><p>{r.development_needs}</p></>}
          <div className="muted small">소관부서 {r.owner_department ?? '–'} · 미해결 확인사항 {r.open_confirmations}건</div>
        </Card>

        <Card title={`원문 근거 (${hiddenEvidence ? r.evidence_count : evidence.length}건)`}>
          {hiddenEvidence ? (
            <div className="notice">🔒 근거 문서 {r.evidence_count}건이 있지만 현재 계정의 부서·보안등급으로는 열람할 수 없어 가려졌습니다.</div>
          ) : evidence.length === 0 ? <Empty>연결된 원문 근거가 없습니다.</Empty> : (
            <ul className="evidence">
              {evidence.map((e) => (
                <li key={e.key}>
                  <div className="evidence-src">
                    📄 {e.document_title}
                    {e.section_no && ` · ${e.section_no}${e.section_heading ? ` ${e.section_heading}` : ''}`}
                    {e.page_start && ` · ${e.page_start}쪽`}
                    {e.criteria.map((c) => <span key={c} className="pill">{CRITERIA_LABELS[c] ?? c}</span>)}
                  </div>
                  {e.quote && <blockquote>{e.quote}</blockquote>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid-2">
        <Card title={finalDecision ? '판정 완료' : '검토 판정 · 의견 작성'}>
          {finalDecision ? (
            <div className="final">
              <StatusBadge status={finalDecision.decision_code} /> {finalDecision.reviewer_name}
              <span className="muted small"> · {fmtDate(finalDecision.created_at)}</span>
              {finalDecision.opinion && <p>{finalDecision.opinion}</p>}
            </div>
          ) : r.status === 'GENERATED' ? (
            <Empty>아직 검토자가 배정되지 않았습니다. 기획자가 프로젝트 관리에서 배정하면 판정할 수 있습니다.</Empty>
          ) : <DecisionForm rec={r} onDone={reload} />}
        </Card>

        <Card title="검토 이력">
          <h4>배정</h4>
          {r.assignments.length === 0 ? <Empty>배정 없음</Empty> : (
            <ul className="timeline">
              {r.assignments.map((a) => (
                <li key={a.id}>{REVIEW_ROLE_LABELS[a.review_role]} · {a.assignee_user_id ? userName(a.assignee_user_id) : DEPT_NAMES[a.assignee_dept_id ?? 0] ?? `부서 ${a.assignee_dept_id}`} <StatusBadge status={a.status} /></li>
              ))}
            </ul>
          )}
          <h4>판정·의견</h4>
          {r.decisions.length === 0 ? <Empty>아직 없음</Empty> : (
            <ul className="timeline">
              {r.decisions.map((d) => (
                <li key={d.id}>
                  <strong>{d.reviewer_name}</strong> {d.is_final ? '최종 판정' : '의견'} <StatusBadge status={d.decision_code} />
                  {d.linkage_type_override && <span className="pill">→ {LINKAGE_TYPES[d.linkage_type_override]}</span>}
                  {d.opinion && <div className="muted">{d.opinion}</div>}
                </li>
              ))}
            </ul>
          )}
          <h4>상태 변경</h4>
          <ul className="timeline">
            {hist.data?.status_history.map((h) => (
              <li key={h.id}>
                {h.from_status ? `${statusLabel(h.from_status)} → ` : ''}<strong>{statusLabel(h.to_status)}</strong>
                <span className="muted small"> · {h.changed_by_name ?? '시스템'} · {fmtDate(h.changed_at)}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card title="토론 · 의견">
        <Comments rec={r} onDone={reload} />
      </Card>
    </>
  )
}
