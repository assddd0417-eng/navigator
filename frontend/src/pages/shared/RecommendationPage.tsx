import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  addComment, getRecommendation, getRecommendationHistory, regenerateRationale, submitDecision,
  type DecisionCode, type EvidenceRow, type RecommendationDetail,
} from '../../api/endpoints'
import { useAuth } from '../../auth/AuthContext'
import { homePath, ROLES, SEED_USERS } from '../../auth/roles'
import { useToast } from '../../components/Toast'
import {
  Card, CRITERIA_LABELS, DEPT_NAMES, Empty, Fit, fmtDate, LINKAGE_HELP, LINKAGE_TYPES, More, PageHeader,
  REVIEW_ROLE_LABELS, RoleHint, ScoreBar, StatusBadge, statusLabel, useAction, useAsync,
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

const DECISIONS: [DecisionCode, string, string][] = [
  ['ADOPT', '채택', '이어 쓰기 좋음'], ['HOLD', '보류', '지금은 판단 보류'], ['EXCLUDE', '제외', '맞지 않음'],
  ['NEEDS_INFO', '추가 정보 필요', '자료가 더 필요함'],
]

/** 1~5 점 고르기 (다시 누르면 지움) */
function Rating({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="rating">
      <span>{label}</span>
      <div className="rating-btns">
        {[1, 2, 3, 4, 5].map((n) => (
          <button type="button" key={n} className={value === String(n) ? 'on' : ''}
            onClick={() => onChange(value === String(n) ? '' : String(n))}>{n}</button>
        ))}
      </div>
      <span className="muted small">1 낮음 · 5 높음</span>
    </div>
  )
}

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
      toast.success(f.is_final ? '최종 결정을 등록했습니다' : '검토 의견을 등록했습니다',
        `${statusLabel(f.decision_code)}${f.opinion ? ` · ${f.opinion}` : ''}`)
      setF({ ...f, opinion: '' })
      onDone()
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <div className="decision-pick">
        {DECISIONS.map(([c, n, help]) => (
          <button type="button" key={c} className={`decision-btn decision-${c} ${f.decision_code === c ? 'on' : ''}`}
            onClick={() => setF({ ...f, decision_code: c })}><strong>{n}</strong><span>{help}</span></button>
        ))}
      </div>
      <label>의견 (왜 그렇게 판단했나요?)<textarea rows={3} value={f.opinion} onChange={(e) => setF({ ...f, opinion: e.target.value })}
        placeholder="예: 남은 기술 과제가 이번 수요와 바로 이어져 후속형으로 적절함" /></label>
      <div className="form-row">
        <Rating label="수요와 얼마나 관련 있나" value={f.relevance} onChange={(v) => setF({ ...f, relevance: v })} />
        <Rating label="근거 문서가 충분한가" value={f.adequacy} onChange={(v) => setF({ ...f, adequacy: v })} />
      </div>
      <label className="check final-check">
        <input type="checkbox" checked={f.is_final} onChange={(e) => setF({ ...f, is_final: e.target.checked })} />
        <span>이 판단을 <b>최종 결정</b>으로 등록 (등록하면 이 추천의 검토가 끝납니다)</span>
        <RoleHint roles={['DEPT_REVIEWER']} />
      </label>
      <More label="연계 방식 바꾸기 · 어느 요청에 대한 답인지 고르기">
        <div className="form-row">
          <label>연계 방식이 다르다고 보면<select value={f.override} onChange={(e) => setF({ ...f, override: e.target.value })}>
            <option value="">AI 판단 그대로 ({rec.linkage_type_name})</option>
            {Object.entries(LINKAGE_TYPES).map(([c, n]) => <option key={c} value={c}>{n} · {LINKAGE_HELP[c]}</option>)}
          </select></label>
          <label>어느 검토 요청에 대한 답인가요?<select value={f.assignment_id} onChange={(e) => setF({ ...f, assignment_id: e.target.value })}>
            <option value="">요청과 상관없이 의견만</option>
            {rec.assignments.map((a) => (
              <option key={a.id} value={a.id}>
                {REVIEW_ROLE_LABELS[a.review_role]} 앞 요청 · {statusLabel(a.status)}{mine.some((m) => m.id === a.id) ? ' (내 몫)' : ''}
              </option>
            ))}
          </select></label>
        </div>
      </More>
      <div className="form-foot">
        <RoleHint roles={['DEPT_REVIEWER', 'EXPERT']} />
        <button className="btn btn-primary" disabled={busy}>{busy ? '등록 중…' : f.is_final ? '최종 결정 등록' : '검토 의견 등록'}</button>
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
        <input value={body} onChange={(e) => setBody(e.target.value)} placeholder="자유롭게 의견이나 질문을 남기세요 (누구나 가능)" required />
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
    if (res.status === 'OK') toast.success('AI가 추천 이유를 새로 썼습니다', '근거 문서 내용만 사용했습니다')
    else toast.show({ kind: 'info', title: 'AI가 문장을 쓰지 못해 기본 문장을 그대로 둡니다', message: '잠시 뒤 다시 시도해 보세요.' })
    onDone()
  }
  return (
    <div className="form-row regen-row">
      <button type="button" className="btn" disabled={busy} onClick={click}>
        {busy ? 'AI가 쓰는 중…' : 'AI로 추천 이유 다시 쓰기'}
      </button>
      <RoleHint roles={['PLANNER']} />
    </div>
  )
}

/** 추천 상세 · 검토/의견 작성 (모든 역할 열람, 판정 권한은 서버가 판단) */
export function RecommendationPage() {
  const id = Number(useParams().id)
  const { role } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const rec = useAsync(() => getRecommendation(id), [id])
  const hist = useAsync(() => getRecommendationHistory(id), [id])
  const reload = () => { void rec.reload(); void hist.reload() }
  const home = role ? homePath(role) : '/'
  const backTo = !role ? '/my-tasks' : ROLES[role].group === 'ADMIN' ? '/reviews' : homePath(role)
  // 앱 안에서 들어왔으면 이전 화면으로, 주소로 바로 들어왔으면(새 탭·공유 링크) 검토 목록으로
  const goBack = () => (location.key !== 'default' ? navigate(-1) : navigate(backTo))

  if (!Number.isInteger(id) || id <= 0) return <Empty>주소가 올바르지 않습니다. <Link to={home}>내 첫 화면으로</Link></Empty>
  if (rec.loading && !rec.data) return <div className="page-loading">불러오는 중…</div>
  const r = rec.data
  if (!r) return <Empty>이 추천을 열 수 없습니다. 지워졌거나 볼 권한이 없는 추천일 수 있습니다. <Link to={home}>내 첫 화면으로</Link></Empty>
  const hiddenEvidence = r.evidence_count > 0 && r.evidence.length === 0
  const evidence = groupEvidence(r.evidence)
  const finalDecision = r.decisions.find((d) => d.is_final)
  const cards = (r.source_cards ?? []).map((c) => c.title).join(' + ')
  const linkCode = r.final_linkage_type_code ?? r.linkage_type_code

  return (
    <>
      <button type="button" className="link-btn back-link" onClick={goBack}>← 목록으로 돌아가기</button>
      <PageHeader
        title={r.demand_title ?? '기획수요'}
        subtitle={`이 기술이 필요할 때, 기존 성과 ‘${cards}’를 ${LINKAGE_TYPES[linkCode] ?? r.linkage_type_name}으로 이어 쓰자는 AI 추천입니다.`}
        actions={<StatusBadge status={r.status} />} />

      <div className="grid-2">
        <Card title="AI가 이렇게 추천했어요">
          <div className="score-total">
            <span>적합도</span> <Fit value={r.total_score} big />
            <span className={`pill linkage-${linkCode}`}>{LINKAGE_TYPES[linkCode] ?? r.linkage_type_name}</span>
            {r.final_linkage_type_code && r.final_linkage_type_code !== r.linkage_type_code && <span className="muted small">(검토에서 바뀜)</span>}
          </div>
          <p className="muted small">{LINKAGE_HELP[linkCode]}</p>
          {r.rationale && <>
            <h4>추천 이유{r.rationale_source === 'LLM' && <span className="muted"> · AI가 근거 문서로 쓴 문장 (사람 확인 필요)</span>}</h4>
            <p>{r.rationale}</p>
            {r.rationale_source === 'TEMPLATE_RESTRICTED' &&
              <div className="notice">🔒 AI가 쓴 문장은 내가 볼 수 없는 문서를 참고해서 가렸고, 기본 문장을 보여 줍니다.</div>}
            {r.rationale_generation?.status === 'FALLBACK' &&
              <div className="muted small">AI가 문장을 쓰지 못해 기본 문장을 보여 줍니다.</div>}
            <RegenerateRationale rec={r} onDone={reload} />
          </>}
          <h4>항목별 점수</h4>
          <div className="bars">
            {r.score_details.map((s) => (
              <ScoreBar key={s.criterion} label={CRITERIA_LABELS[s.criterion] ?? s.criterion} value={s.score}
                sim={s.method.startsWith('cosine')} unknown={s.method === 'neutral'} />
            ))}
          </div>
          {r.development_needs && <><h4>더 개발해야 할 것</h4><p>{r.development_needs}</p></>}
          <div className="muted small">담당 부서 {r.owner_department ?? '–'}{r.open_confirmations > 0 && ` · 확인할 점 ${r.open_confirmations}건`}</div>
        </Card>

        <Card title={`근거 문서 ${hiddenEvidence ? r.evidence_count : evidence.length}건`}>
          {hiddenEvidence ? (
            <div className="notice">🔒 근거 문서 {r.evidence_count}건이 있지만 내 부서·보안등급으로는 볼 수 없어 가려졌습니다.</div>
          ) : evidence.length === 0 ? <Empty>연결된 근거 문서가 없습니다.</Empty> : (
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
        <Card title={finalDecision ? '최종 결정이 났습니다' : '내 판단 남기기'}>
          {finalDecision ? (
            <div className="final">
              <StatusBadge status={finalDecision.decision_code} /> <strong>{finalDecision.reviewer_name}</strong>
              <span className="muted small"> · {fmtDate(finalDecision.created_at)}</span>
              {finalDecision.opinion && <p>{finalDecision.opinion}</p>}
              <p><Link className="btn" to={backTo}>다른 검토 보러 가기 →</Link></p>
            </div>
          ) : r.status === 'GENERATED' ? (
            <Empty>아직 검토 요청 전입니다. 기획자가 ‘연계 후보 찾기’에서 전문가나 담당 부서에 요청하면 판단을 남길 수 있습니다.</Empty>
          ) : r.status === 'WITHDRAWN' ? (
            <Empty>철회된 추천이라 더 검토하지 않습니다.</Empty>
          ) : <DecisionForm rec={r} onDone={reload} />}
        </Card>

        <Card title="지금까지 진행">
          <h4>검토 요청</h4>
          {r.assignments.length === 0 ? <Empty>아직 없음</Empty> : (
            <ul className="timeline">
              {r.assignments.map((a) => (
                <li key={a.id}>{REVIEW_ROLE_LABELS[a.review_role]} · {a.assignee_user_id ? userName(a.assignee_user_id) : DEPT_NAMES[a.assignee_dept_id ?? 0] ?? '부서'} <StatusBadge status={a.status} />{a.due_at && <span className="muted small"> · 기한 {fmtDate(a.due_at)}</span>}</li>
              ))}
            </ul>
          )}
          <h4>판단·의견</h4>
          {r.decisions.length === 0 ? <Empty>아직 없음</Empty> : (
            <ul className="timeline">
              {r.decisions.map((d) => (
                <li key={d.id}>
                  <strong>{d.reviewer_name}</strong> {d.is_final ? '최종 결정' : '의견'} <StatusBadge status={d.decision_code} />
                  {d.linkage_type_override && <span className="pill">→ {LINKAGE_TYPES[d.linkage_type_override]}</span>}
                  {d.opinion && <div className="muted">{d.opinion}</div>}
                </li>
              ))}
            </ul>
          )}
          <More label="상태가 바뀐 기록 보기">
            <ul className="timeline">
              {hist.data?.status_history.map((h) => (
                <li key={h.id}>
                  {h.from_status ? `${statusLabel(h.from_status)} → ` : ''}<strong>{statusLabel(h.to_status)}</strong>
                  <span className="muted small"> · {h.changed_by_name ?? '자동'} · {fmtDate(h.changed_at)}</span>
                </li>
              ))}
            </ul>
          </More>
        </Card>
      </div>

      <Card title="자유 의견 · 질문">
        <Comments rec={r} onDone={reload} />
      </Card>
    </>
  )
}
