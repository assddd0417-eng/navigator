import { Fragment, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  CRITERION_LABELS, VERDICT_TONES,
  type CheckResult, type MatchEvidence, type MatchRec, type MatchRun, type Question, type Verdict,
} from '../../api/navigator'

export type Audience = 'company' | 'staff'

// 기업에게는 '지원 가능 여부'로, 담당자에게는 기관 판정 용어로 보여 준다
export const VERDICT_TEXT: Record<Audience, Record<Verdict, string>> = {
  company: { ELIGIBLE: '지원 가능', NEEDS_INFO: '확인 필요', INELIGIBLE: '지원 어려움' },
  staff: { ELIGIBLE: '적합', NEEDS_INFO: '확인 필요', INELIGIBLE: '부적격' },
}
export const VERDICTS: Verdict[] = ['ELIGIBLE', 'NEEDS_INFO', 'INELIGIBLE']

// 총점(0~1)을 사용자가 읽을 수 있는 말로. 알림 조건(min_score)도 같은 경계를 쓴다.
// 경계는 임베더마다 달라 서버에서 받는다 (components/levels.ts)
import { scoreLevel, simLevel } from '../../components/levels'
export { SIM_LEVELS as FIT_LEVELS, loadSimLevels as loadFitLevels, simLevel as fitLevel } from '../../components/levels'
const fitLevel = simLevel

// 마감 공고(참여할 수 있었던 사업)에서 쓰는 말
export const PAST_VERDICT_TEXT: Record<Verdict, string> = { ELIGIBLE: '지원할 수 있었음', NEEDS_INFO: '확인 필요', INELIGIBLE: '지원 어려움' }

export function VerdictBadge({ verdict, audience = 'staff', text }: { verdict: Verdict; audience?: Audience; text?: Record<Verdict, string> }) {
  return <span className={`badge badge-${VERDICT_TONES[verdict]}`}>{(text ?? VERDICT_TEXT[audience])[verdict]}</span>
}

// 관련도 구성 중 내용 유사도로 매기는 기준 (나머지는 충족 비율)
const SIM_CRITERIA = new Set(['TECH', 'PURPOSE'])

// value: 기관 화면에서만 원래 값(0.61)을 붙인다
export function FitBadge({ score, bare = false, value = false }: { score: number; bare?: boolean; value?: boolean }) {
  const l = fitLevel(score)
  return <span className={`badge badge-${l.tone}`} title="회사 기술·실적과 공고 내용이 얼마나 가까운지">{bare ? '' : '관련도 '}{l.label}{value && ` · ${score.toFixed(2)}`}</span>
}

export function VerdictSummary({ run, audience = 'staff' }: { run: MatchRun; audience?: Audience }) {
  return (
    <div className="verdict-summary">
      {VERDICTS.map((v) => (
        <div key={v} className={`verdict-count verdict-count-${VERDICT_TONES[v]}`}>
          <span>{VERDICT_TEXT[audience][v]}</span>
          <strong>{run.summary[v] ?? 0}</strong>
        </div>
      ))}
    </div>
  )
}

/** 마감일과 남은 날 */
export function Deadline({ end, state }: { end: string | null; state?: string }) {
  if (state === 'CLOSED') return <span className="muted">마감됨</span>
  if (!end) return <span className="muted">마감일 미정</span>
  const days = Math.ceil((new Date(`${end.slice(0, 10)}T23:59:59`).getTime() - Date.now()) / 86400000)
  return (
    <span>
      마감 {fmtDay(end)}
      {days >= 0 && <span className={`dday ${days <= 7 ? 'dday-soon' : ''}`}>{days === 0 ? '오늘' : `D-${days}`}</span>}
    </span>
  )
}

const SOURCE_LABELS: Record<string, string> = {
  company_patent: '특허', company_rnd_history: 'R&D 이력', project: '기관 과제', company_technology: '보유 기술',
}
const RESULT_MARK: Record<CheckResult, [string, string]> = {
  MET: ['충족', 'ok'], UNMET: ['미충족', 'bad'], UNKNOWN: ['확인 필요', 'warn'],
}

const simLabel = (v: MatchEvidence['similarity']) => {
  if (v == null) return null
  const n = Number(v)
  return n >= 0.6 ? '매우 가까움' : n >= 0.4 ? '가까움' : '일부 관련'
}

/** 가장 가까운 기술 근거 1건 */
function topEvidence(rec: MatchRec) {
  const tech = rec.evidence.filter((e) => e.kind === 'TECH_MATCH' && e.company_text)
  tech.sort((a, b) => Number(b.similarity ?? 0) - Number(a.similarity ?? 0))
  return tech[0] ?? null
}

/** 조건 설명을 한 줄로. 문장으로 끝나는 설명은 끝 마침표를 빼고 잇는다 */
const clauses = (cs: { description: string }[]) => cs.map((c) => c.description.trim().replace(/[.。]+$/, '')).join(', ')

/** 판정 이유 한두 줄. 서버 rationale 대신 판정 결과에서 직접 만든다 */
function Summary({ rec, audience }: { rec: MatchRec; audience: Audience }) {
  const mand = rec.checks.filter((c) => c.is_mandatory && c.result)
  const unmet = mand.filter((c) => c.result === 'UNMET')
  const unknown = mand.filter((c) => c.result === 'UNKNOWN')
  const top = topEvidence(rec)
  let line: ReactNode
  if (rec.verdict === 'ELIGIBLE') {
    line = <>필수 조건 {rec.mandatory_total}개를 모두 충족합니다.{rec.preferred_total > 0 && ` 우대 조건 ${rec.preferred_met}/${rec.preferred_total}개.`}</>
  } else if (rec.verdict === 'INELIGIBLE') {
    line = <>충족하지 못한 조건: <strong>{clauses(unmet)}</strong></>
  } else {
    line = <>확인이 필요한 조건: <strong>{clauses(unknown)}</strong></>
  }
  return (
    <div className="match-summary">
      <div>{line}</div>
      {top && (
        <div className="small muted">
          {audience === 'company' ? '관련 실적' : '근거'}: {SOURCE_LABELS[top.company_source_table ?? ''] ?? '주요 사업'}
          {' '}“{(top.company_text ?? '').split('\n')[0].slice(0, 60)}”
        </div>
      )}
      {!!rec.hidden_requirements && (
        <div className="small muted">신용등급·매출 조건 {rec.hidden_requirements}개는 ‘회사 정보 입력·수정’에서 확인됩니다.</div>
      )}
    </div>
  )
}

export function MatchCard({ rec, audience, title, meta, onTitle, rank, questions, onAnswer, onEditProfile, defaultOpen = false, verdictText }: {
  rec: MatchRec
  audience: Audience
  verdictText?: Record<Verdict, string>
  title: ReactNode
  meta?: ReactNode
  onTitle?: () => void
  rank?: number
  questions?: Question[]
  onAnswer?: (answers: { requirement_id: number; value: number | boolean }[]) => Promise<unknown>
  onEditProfile?: () => void
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const qs = (questions ?? []).filter((q) => q.announcement_id === rec.announcement_id)
  const unknownWithoutQ = rec.verdict === 'NEEDS_INFO'
    && rec.checks.some((c) => c.is_mandatory && c.result === 'UNKNOWN' && !qs.some((q) => q.requirement_id === c.requirement_id))

  return (
    <li className={`match-item match-${VERDICT_TONES[rec.verdict]}`}>
      <div className="match-head">
        {rank != null && <span className="match-rank">{rank}</span>}
        <div className="match-title">
          {onTitle ? <button className="link-btn" onClick={onTitle}>{title}</button> : title}
          {meta && <div className="small muted">{meta}</div>}
        </div>
        <div className="match-badges">
          <VerdictBadge verdict={rec.verdict} audience={audience} text={verdictText} />
          <FitBadge score={rec.total_score} value={audience === 'staff'} />
        </div>
      </div>
      <Summary rec={rec} audience={audience} />

      {qs.length > 0 && onAnswer && <InlineQuestions questions={qs} onAnswer={onAnswer} />}
      {unknownWithoutQ && onEditProfile && (
        <div className="inline-hint">
          회사 정보가 비어 있어 판단하지 못한 조건이 있습니다.{' '}
          <button className="link-btn" onClick={onEditProfile}>회사 정보 입력</button>
        </div>
      )}

      <button className="link-btn small detail-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? '조건 접기' : '조건별로 보기'}
      </button>
      {open && <MatchDetail rec={rec} audience={audience} />}
    </li>
  )
}

function MatchDetail({ rec, audience }: { rec: MatchRec; audience: Audience }) {
  const tech = rec.evidence.filter((e) => e.kind !== 'REQUIREMENT')
  return (
    <div className="match-detail">
      <table className="table">
        <thead><tr><th>조건</th><th>결과</th><th>설명</th></tr></thead>
        <tbody>
          {rec.checks.filter((c) => c.result).map((c) => (
            <tr key={c.requirement_id}>
              <td>
                <span className="small muted">{c.is_mandatory ? '필수' : '우대'}</span> {c.description}
                {c.source_quote && (
                  <div className="small muted">공고문{c.source_page ? ` ${c.source_page}쪽` : ''}: “{c.source_quote}”</div>
                )}
              </td>
              <td className="nowrap">
                <span className={`badge badge-${RESULT_MARK[c.result!][1]}`}>{RESULT_MARK[c.result!][0]}</span>
                {c.self_declared && <div className="small muted">직접 입력</div>}
              </td>
              <td>{c.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {tech.length > 0 && (
        <div>
          <h4>공고 기술과 가까운 회사 실적</h4>
          <ul className="evidence">
            {tech.map((e, i) => (
              <li key={i}>
                <div className="evidence-src">
                  {e.kind === 'IPC_MATCH' ? '특허 분야 일치' : `공고 요구 기술 “${e.tech_name}”`}
                  {simLabel(e.similarity) && <span className="pill">{simLabel(e.similarity)}</span>}
                </div>
                <blockquote>
                  {e.kind === 'IPC_MATCH' ? `보유 특허 분류 ${e.company_text}`
                    : `${SOURCE_LABELS[e.company_source_table ?? ''] ?? '주요 사업'}: ${e.company_text}`}
                </blockquote>
              </li>
            ))}
          </ul>
        </div>
      )}
      {audience === 'staff' && (
        <div>
          <h4>관련도 구성</h4>
          <div className="bars">
            {Object.entries(rec.scores).map(([k, s]) => (
              <div key={k} className="bar-row" title={`반영 비율 ${s.weight.toFixed(2)}`}>
                <span>{CRITERION_LABELS[k] ?? k}</span>
                <div className="bar"><div style={{ width: `${Math.round(s.score * 100)}%` }} /></div>
                <span className="num">{(SIM_CRITERIA.has(k) ? simLevel : scoreLevel)(s.score).label} · {s.score.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function InlineQuestions({ questions, onAnswer }: {
  questions: Question[]
  onAnswer: (answers: { requirement_id: number; value: number | boolean }[]) => Promise<unknown>
}) {
  const [values, setValues] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState(false)
  const ready = questions.filter((q) => (values[q.requirement_id] ?? '') !== '')
  const submit = async () => {
    setBusy(true)
    try {
      await onAnswer(ready.map((q) => ({
        requirement_id: q.requirement_id,
        value: q.answer_type === 'integer' ? Number(values[q.requirement_id]) : values[q.requirement_id] === 'yes',
      })))
      setValues({})
    } finally { setBusy(false) }
  }
  return (
    <div className="inline-questions">
      {questions.map((q) => (
        <div key={q.requirement_id} className="iq-row">
          <span className="iq-text">{q.question}</span>
          {q.answer_type === 'integer' ? (
            <select value={values[q.requirement_id] ?? ''} aria-label={q.question}
              onChange={(e) => setValues({ ...values, [q.requirement_id]: e.target.value })}>
              <option value="">선택</option>
              {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => <option key={n} value={n}>TRL {n}</option>)}
            </select>
          ) : (
            <div className="seg">
              {[['yes', '예'], ['no', '아니오']].map(([v, l]) => (
                <button type="button" key={v} className={values[q.requirement_id] === v ? 'on' : ''}
                  onClick={() => setValues({ ...values, [q.requirement_id]: v })}>{l}</button>
              ))}
            </div>
          )}
        </div>
      ))}
      <div className="iq-foot">
        <span className="small muted">답한 내용은 ‘직접 입력’으로 남고, 바로 다시 판정합니다.</span>
        <button className="btn btn-sm btn-primary" disabled={busy || ready.length === 0} onClick={() => void submit()}>
          {busy ? '확인 중…' : '답하고 다시 판정'}
        </button>
      </div>
    </div>
  )
}

/** 판정별 목록. '지원 어려움/부적격'은 접어 둔다 */
export function GroupedMatches({ run, audience, renderCard, hints, verdictText }: {
  run: MatchRun
  audience: Audience
  verdictText?: Record<Verdict, string>
  renderCard: (rec: MatchRec, indexInGroup: number) => ReactNode
  hints?: Partial<Record<Verdict, string>>
}) {
  const [showBad, setShowBad] = useState(false)
  return (
    <div className="stack">
      {VERDICTS.map((v) => {
        const recs = run.recommendations.filter((r) => r.verdict === v).sort((a, b) => b.total_score - a.total_score)
        if (v !== 'ELIGIBLE' && recs.length === 0) return null
        const folded = v === 'INELIGIBLE' && !showBad
        return (
          <section key={v}>
            <div className="group-head">
              <VerdictBadge verdict={v} audience={audience} text={verdictText} />
              <strong>{recs.length}건</strong>
              {hints?.[v] && <span className="small muted">{hints[v]}</span>}
              {v === 'INELIGIBLE' && (
                <button className="btn btn-sm" style={{ marginLeft: 'auto' }} onClick={() => setShowBad(!showBad)}>
                  {showBad ? '접기' : '보기'}
                </button>
              )}
            </div>
            {folded ? null : recs.length === 0 ? <div className="empty small">해당 없음</div> : (
              <ul className="match-list">{recs.map((r, i) => <Fragment key={r.id}>{renderCard(r, i)}</Fragment>)}</ul>
            )}
          </section>
        )
      })}
    </div>
  )
}

export function CompanyShell({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="app-shell">
      <header className="topbar topbar-company">
        <Link to="/navigator" className="brand brand-link">
          <span className="brand-mark">AX</span>
          <span>Navigator</span>
        </Link>
        <div className="topbar-right">
          {right}
          <Link to="/login" className="topbar-link">기관 담당자</Link>
        </div>
      </header>
      <main className="company-main">{children}</main>
    </div>
  )
}

export const fmtDay = (s: string | null | undefined) => (s ? s.slice(0, 10) : '–')
export const fmtKrw = (v: number | null | undefined) =>
  v == null ? '–' : v >= 1e8 ? `${(v / 1e8).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}억 원`
    : `${v.toLocaleString('ko-KR')}원`
export const fmtBrn = (v?: string | null) =>
  v && /^\d{10}$/.test(v) ? `${v.slice(0, 3)}-${v.slice(3, 5)}-${v.slice(5)}` : v ?? ''
export const bizStatus = (label: string) => (label === '모름' ? '휴·폐업 미확인' : label)
export const AGENCY_LABELS: Record<string, string> = { NICE: 'NICE평가정보', KED: '한국기업데이터', OTHER: '기타 평가기관', SELF: '기관 미기재' }
