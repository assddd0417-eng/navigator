import { useState } from 'react'
import type { ReviewCheck, EligibilityResult, EligibilityReview, Tone } from '../../api/navigator'
import { Card } from '../../components/ui'
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
      {list.map((r, i) => <ResultCard key={r.announcement_id} r={r} defaultOpen={i === 0} />)}
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

function ResultCard({ r, defaultOpen }: { r: EligibilityResult; defaultOpen: boolean }) {
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
      <div className="grid-2">
        <Headline label="신청 가능 여부" value={r.q1_label} tone={VERDICT_TONE[r.verdict]} />
        <Headline label="선정 가능성(적합도)" value={fit.grade_label}
          tone={fit.grade == null ? 'muted' : fit.grade === '상' ? 'ok' : fit.grade === '중' ? 'warn' : 'bad'} />
      </div>
      {open && (
        <>
          <h4 style={{ marginTop: 16 }}>Q1. 신청할 수 있는가?</h4>
          <p>{r.q1_text}</p>
          <table className="table">
            <thead><tr><th>필수요건</th><th>결과</th><th>근거(공고문 조항)</th></tr></thead>
            <tbody>
              {mand.map((c) => (
                <tr key={c.requirement_id}>
                  <td>
                    {c.description}
                    {c.reason && <div className="small muted">{c.reason}</div>}
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
                  </li>
                ))}
              </ul>
            </>
          )}

          <h4 style={{ marginTop: 16 }}>Q2. 선정 가능성은?</h4>
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
            점수 = Σ(배점×충족도) ÷ 평가한 배점 합 × 100 + 우대 가점 · 상 70↑ / 중 50~69 / 하 50↓ · 신청서 기반 항목은 상담 단계 평가 제외
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
              ? g.submit_documents.map((d) => d.name + (d.required ? '' : ' (해당 시)')).join(', ') : '–'}</li>
          </ul>
        </>
      )}
    </Card>
  )
}

function Basis({ c }: { c: ReviewCheck }) {
  if (!c.has_basis) return <span className="badge badge-warn">근거 조항 없음 · 담당자 확인</span>
  const q = c.source_quote ?? ''
  return (
    <span title={q}>
      {q.length > 80 ? `${q.slice(0, 80)}…` : q}{c.source_page ? ` (p.${c.source_page})` : ''}
    </span>
  )
}
