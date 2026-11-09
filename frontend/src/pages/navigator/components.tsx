import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  CRITERION_LABELS, VERDICT_LABELS, VERDICT_TONES,
  type CheckResult, type MatchRec, type MatchRun, type Verdict,
} from '../../api/navigator'

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return <span className={`badge badge-${VERDICT_TONES[verdict]}`}>{VERDICT_LABELS[verdict]}</span>
}

const RESULT_TONES: Record<CheckResult, string> = { MET: 'ok', UNMET: 'bad', UNKNOWN: 'warn' }

export function ResultBadge({ result, label }: { result: CheckResult | null; label: string }) {
  return <span className={`badge badge-${result ? RESULT_TONES[result] : 'muted'}`}>{label}</span>
}

export function VerdictSummary({ run }: { run: MatchRun }) {
  return (
    <div className="verdict-summary">
      {(['ELIGIBLE', 'NEEDS_INFO', 'INELIGIBLE'] as Verdict[]).map((v) => (
        <div key={v} className={`verdict-count verdict-count-${VERDICT_TONES[v]}`}>
          <span>{VERDICT_LABELS[v]}</span>
          <strong>{run.summary[v] ?? 0}</strong>
        </div>
      ))}
    </div>
  )
}

const SOURCE_LABELS: Record<string, string> = {
  company_patent: '특허', company_rnd_history: 'R&D 이력', project: '기관 내부 과제', company_technology: '보유기술',
}

export function MatchItem({ rec, title, onTitle, extra, defaultOpen = false }: {
  rec: MatchRec
  title: ReactNode
  onTitle?: () => void
  extra?: ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const tech = rec.evidence.filter((e) => e.kind !== 'REQUIREMENT')
  return (
    <li className={`match-item match-${VERDICT_TONES[rec.verdict]}`}>
      <div className="match-head">
        <span className="match-rank">{rec.rank}</span>
        <VerdictBadge verdict={rec.verdict} />
        <div className="match-title">
          {onTitle ? <button className="link-btn" onClick={onTitle}>{title}</button> : title}
          <div className="small muted">
            필수 요건 {rec.mandatory_met}/{rec.mandatory_total} 충족
            {rec.preferred_total > 0 && ` · 우대 ${rec.preferred_met}/${rec.preferred_total}`}
            {rec.hidden_requirements ? ` · 비공개 요건 ${rec.hidden_requirements}개` : ''}
          </div>
        </div>
        <div className="match-score" title="가중합">
          <strong>{rec.total_score.toFixed(2)}</strong>
          <span className="small muted">총점</span>
        </div>
        <button className="btn btn-sm" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? '접기' : '자세히'}
        </button>
      </div>
      <p className="match-rationale">{rec.rationale}</p>
      {extra}
      {open && (
        <div className="match-detail">
          <div>
            <h4>자격요건 판정</h4>
            <table className="table">
              <thead><tr><th>구분</th><th>요건</th><th>판정</th><th>이유</th></tr></thead>
              <tbody>
                {rec.checks.map((c) => (
                  <tr key={c.requirement_id}>
                    <td className="nowrap">{c.mandatory_label}</td>
                    <td>
                      {c.description}
                      {c.source_quote && (
                        <div className="small muted">공고 원문{c.source_page ? ` ${c.source_page}쪽` : ''}: “{c.source_quote}”</div>
                      )}
                    </td>
                    <td className="nowrap">
                      <ResultBadge result={c.result} label={c.result_label} />
                      {c.self_declared && <span className="pill">자가 신고</span>}
                    </td>
                    <td>
                      {c.reason}
                      {c.question && <div className="question-inline">보완질문: {c.question}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid-2">
            <div>
              <h4>기준별 점수</h4>
              <div className="bars">
                {Object.entries(rec.scores).map(([k, s]) => (
                  <div key={k} className="bar-row" title={s.method}>
                    <span>{CRITERION_LABELS[k] ?? k} <span className="small muted">×{s.weight.toFixed(2)}</span></span>
                    <div className="bar"><div style={{ width: `${Math.round(s.score * 100)}%` }} /></div>
                    <span className="num">{s.score.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <h4>기술 근거</h4>
              {tech.length === 0 ? <p className="muted small">요구기술 없음</p> : (
                <ul className="evidence">
                  {tech.map((e, i) => (
                    <li key={i}>
                      <div className="evidence-src">
                        {e.kind === 'IPC_MATCH' ? '특허 분류 일치' : `요구기술 “${e.tech_name}”`}
                        {e.similarity != null && <span className="pill">유사도 {Number(e.similarity).toFixed(2)}</span>}
                      </div>
                      <blockquote>
                        {e.kind === 'IPC_MATCH' ? `${e.tech_name ?? ''} ↔ 기업 특허 IPC ${e.company_text}`
                          : `${SOURCE_LABELS[e.company_source_table ?? ''] ?? '주요사업'}: ${e.company_text}`}
                      </blockquote>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}
    </li>
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
          <Link to="/login" className="btn btn-ghost">기관 담당자 로그인</Link>
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
