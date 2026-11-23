import { useState } from 'react'
import type { AiJudgeInfo, FitRule, ReviewCheck, EligibilityResult, EligibilityReview, Tone } from '../../api/navigator'
import { Card, docName } from '../../components/ui'
import { fmtDay, fmtKrw } from '../navigator/components'

const VERDICT_TONE: Record<string, Tone> = { ELIGIBLE: 'ok', NEEDS_INFO: 'warn', INELIGIBLE: 'bad' }
const CHECK_TONE: Record<string, Tone> = { MET: 'ok', NOT_MET: 'bad' }
const RECEIPT_KO: Record<string, string> = { OPEN: '접수중', UPCOMING: '접수 예정', CLOSED: '마감' }
const SHOW_FIRST = 3

export function EligibilityPanel({ data }: { data: EligibilityReview }) {
  const [all, setAll] = useState(false)
  const list = all ? data.results : data.results.slice(0, SHOW_FIRST)
  return (
    <>
      {data.ai_mode === 'rules' && <p className="small muted">AI 판단 꺼짐: 규칙으로 판정함</p>}
      <Card title={`${data.company_name ?? ''} 자격요건 검토`} actions={
        data.diagnosis && <span className="small muted">D-STATE {data.diagnosis.total_score}점 · {data.diagnosis.state_label}</span>
      }>
        <div className="grid-3">
          <Headline label="신청 가능" value={`${data.summary.ELIGIBLE}건`} tone="ok" />
          <Headline label="확인 필요" value={`${data.summary.NEEDS_INFO}건`} tone="warn" />
          <Headline label="신청 불가" value={`${data.summary.INELIGIBLE}건`} tone="bad" />
        </div>
        {data.concern && <p className="small muted" style={{ marginTop: 10 }}>상담 내용: {data.concern}</p>}
      </Card>
      {!data.results.length && <Card><p className="muted">검토할 공고가 없습니다.</p></Card>}
      {list.map((r, i) => <ResultCard key={r.announcement_id} r={r} rule={data.fit_rule} defaultOpen={i === 0} />)}
      {data.results.length > SHOW_FIRST && (
        <button className="btn" onClick={() => setAll(!all)}>
          {all ? '접기' : `더 보기 (${data.results.length - SHOW_FIRST}건)`}
        </button>
      )}
      {data.notice && <p className="small muted">{data.notice}</p>}
    </>
  )
}

function Headline({ label, value, tone }: { label: string; value: string; tone?: Tone | 'muted' }) {
  return (
    <div className="card" style={{ textAlign: 'center' }}>
      <div className="small muted">{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700 }}>
        {tone ? <span className={`badge badge-${tone}`} style={{ fontSize: 'inherit' }}>{value}</span> : value}
      </div>
    </div>
  )
}

function ResultCard({ r, rule, defaultOpen }: { r: EligibilityResult; rule?: FitRule; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const mand = r.checks.filter((c) => c.is_mandatory)
  const pref = r.checks.filter((c) => !c.is_mandatory)
  const g = r.guide
  const fit = r.fit
  return (
    <Card title={r.title} actions={
      <button className="btn btn-sm" onClick={() => setOpen(!open)}>{open ? '접기' : '펼치기'}</button>
    }>
      <div className="small muted" style={{ marginBottom: 10 }}>
        {r.agency_name} · {RECEIPT_KO[r.receipt_state] ?? r.receipt_state}
        {r.receipt_end ? ` · 마감 ${fmtDay(r.receipt_end)}` : ''}
      </div>
      <CriteriaLine r={r} />
      {r.ai && <AiLine ai={r.ai} checks={r.checks} />}
      <div className="grid-2">
        <Headline label="신청 가능 여부" value={r.q1_label} tone={VERDICT_TONE[r.verdict]} />
        <Headline label="선정 가능성(적합도)" value={fit.grade_label}
          tone={fit.grade == null ? 'muted' : fit.grade === '상' ? 'ok' : fit.grade === '중' ? 'warn' : 'bad'} />
      </div>
      {open && (
        <>
          <h4 style={{ marginTop: 16 }}>1. 신청할 수 있는가?</h4>
          <p>{r.q1_text}</p>
          <RegulationBlock list={r.regulations ?? []} />
          <table className="table">
            <thead><tr><th>필수요건</th><th>결과</th><th>근거(공고문 조항)</th></tr></thead>
            <tbody>
              {mand.map((c) => (
                <tr key={c.requirement_id}>
                  <td>
                    {c.description}
                    {c.regulation_ref && <> <span className="badge badge-info">공통 참여제한</span></>}
                    {c.reason && <div className="small muted">{c.reason}</div>}
                    <AiNote c={c} />
                    {c.question && <div className="small muted">확인 질문: {c.question}</div>}
                  </td>
                  <td><span className={`badge badge-${CHECK_TONE[c.result ?? ""] ?? 'warn'}`}>{c.result_label}</span></td>
                  <td className="small"><Basis c={c} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {pref.length > 0 && (
            <>
              <h4>우대 요건</h4>
              <ul className="small">
                {pref.map((c) => (
                  <li key={c.requirement_id}>
                    <span className={`badge badge-${CHECK_TONE[c.result ?? ""] ?? 'warn'}`}>{c.result_label}</span> {c.description}
                    {c.bonus_points ? <> <strong>+{c.bonus_points}점</strong></> : null}
                    <AiNote c={c} />
                  </li>
                ))}
              </ul>
            </>
          )}

          <h4 style={{ marginTop: 16 }}>2. 선정 가능성은?</h4>
          <p>상담 단계 적합도 : {fit.grade_label}</p>
          {fit.items.length > 0 && (
            <table className="table">
              <thead><tr><th>평가항목(배점)</th><th>충족도</th><th>근거</th></tr></thead>
              <tbody>
                {fit.items.map((it) => (
                  <tr key={it.id}>
                    <td>{it.name} ({it.points}점) <span className="small muted">{it.kind_label}</span></td>
                    <td><span className={`badge badge-${it.level === 'FULL' ? 'ok' : it.level === 'PARTIAL' ? 'warn' : it.level ? 'bad' : 'muted'}`}>{it.level_label}</span></td>
                    <td className="small">{it.basis}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="small muted">
            점수 = Σ(배점×충족도) ÷ 평가한 배점 합 × 100 + 우대 가점 · {rule ? `상 ${rule.grade_high}점 이상, 중 ${rule.grade_mid}~${rule.grade_high - 1}점, 하 ${rule.grade_mid}점 미만` : '상 70점 이상, 중 50~69점, 하 50점 미만'} · 신청서 기반 항목은 상담 단계 평가 제외
          </p>

          {r.todo.length > 0 && (
            <>
              <h4>보완 포인트</h4>
              <ul>{r.todo.map((t, i) => <li key={i}>{t.text}{t.question && <div className="small muted">확인 질문: {t.question}</div>}</li>)}</ul>
            </>
          )}

          <h4>신청 안내</h4>
          <ul className="small">
            <li>지원 한도: {fmtKrw(g.support_amount_krw)}</li>
            <li>기간: {g.support_period_months ? `${g.support_period_months}개월` : '–'}</li>
            <li>기업부담: {g.company_burden || '–'}</li>
            <li>제출서류: {g.submit_documents.length
              ? g.submit_documents.map((d) => docName(d)).join(', ') : '–'}</li>
          </ul>
        </>
      )}
    </Card>
  )
}

function CriteriaLine({ r }: { r: EligibilityResult }) {
  const cr = r.criteria
  if (!cr) return null
  return (
    <div className="small muted" style={{ marginBottom: 8 }}>
      판단기준 확인: 공고 요건 {cr.requirements_confirmed_at ? `확인 ${fmtDay(cr.requirements_confirmed_at)}` : '확인 전'}
      {' · '}운영규정 {cr.regulations_confirmed_at ? `확인 ${fmtDay(cr.regulations_confirmed_at)}` : '확인된 규정 없음'}
      {cr.unconfirmed_regulations.length > 0 && (
        <div><span className="badge badge-warn">확인 전 규정 (판정에 쓰지 않음)</span> {cr.unconfirmed_regulations.join(', ')}</div>
      )}
    </div>
  )
}

function RegulationBlock({ list }: { list: { ref: string; text: string; confirmed_at: string | null }[] }) {
  if (!list.length) return null
  return (
    <>
      <h4>근거 규정</h4>
      <ul className="small">
        {list.map((g, i) => (
          <li key={i}>
            <strong>{g.ref}</strong>{g.confirmed_at ? ` · 확인 ${fmtDay(g.confirmed_at)}` : ' · 확인 전'}
            {g.text.length > 120
              ? <details><summary>{g.text.slice(0, 120)}…</summary>{g.text}</details>
              : <div className="muted">{g.text}</div>}
          </li>
        ))}
      </ul>
    </>
  )
}

function Basis({ c }: { c: ReviewCheck }) {
  if (c.regulation_ref) {
    return (
      <span>
        {c.regulation_ref}
        {c.source_quote && <div className="muted" title={c.source_quote}>{c.source_quote.length > 80 ? `${c.source_quote.slice(0, 80)}…` : c.source_quote}</div>}
      </span>
    )
  }
  if (!c.has_basis) return <span className="badge badge-warn">근거 조항 없음 · 담당자 확인</span>
  const q = c.source_quote ?? ''
  return (
    <span title={q}>
      {q.length > 80 ? `${q.slice(0, 80)}…` : q}{c.source_page ? ` (p.${c.source_page})` : ''}
    </span>
  )
}

function AiNote({ c }: { c: ReviewCheck }) {
  return (
    <>
      {c.judged_by && c.judged_label && (
        <div>
          <span className={`badge badge-${c.judged_by === 'LLM' ? 'info' : c.judged_by === 'CALC' ? 'warn' : 'muted'}`}>{c.judged_label}</span>
        </div>
      )}
      {c.ai_quote && <div className="small muted">AI 인용: “{c.ai_quote}”</div>}
      {c.ai_reason && c.ai_reason !== c.reason && <div className="small muted">{c.ai_reason}</div>}
    </>
  )
}

function AiLine({ ai, checks }: { ai: AiJudgeInfo; checks: ReviewCheck[] }) {
  if (ai.status === 'FALLBACK') return <div className="small muted" style={{ marginBottom: 8 }}>AI 판단 못 함, 규칙 결과 사용</div>
  return (
    <div className="small muted" style={{ marginBottom: 8 }}>
      AI 판단 · 프롬프트 v{ai.prompt_version ?? '–'} · {ai.model ?? '–'}
      {ai.blocked.length > 0 && (
        <details>
          <summary>결과에서 뺀 AI 판단 {ai.blocked.length}건</summary>
          <ul>
            {ai.blocked.map((b, i) => (
              <li key={i}>
                {b.requirement_id == null ? 'AI 응답에 이 공고가 없음' : checks.find((c) => c.requirement_id === b.requirement_id)?.description ?? `요건 ${b.requirement_id}`}
                <div>{b.reason}</div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
