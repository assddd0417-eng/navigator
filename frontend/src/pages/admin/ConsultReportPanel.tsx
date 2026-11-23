import { useState } from 'react'
import { confirmConsultation, updateConsultation, type Consultation } from '../../api/navigator'
import { useToast } from '../../components/Toast'
import { Card, fmtDate, useAction } from '../../components/ui'

export const VERDICT_OPTIONS: { code: string; label: string }[] = [
  { code: 'ELIGIBLE', label: '신청 가능' },
  { code: 'NEEDS_INFO', label: '확인 필요' },
  { code: 'INELIGIBLE', label: '신청 불가' },
]
export const verdictText = (v: string) => VERDICT_OPTIONS.find((o) => o.code === v)?.label ?? v

const fmtDelta = (n: number) => (n > 0 ? `+${n}` : n < 0 ? `${n}` : '변동 없음')

type OverrideDraft = Record<number, { verdict: string; reason: string }>

export function ConsultReportPanel({ data, onChange }: { data: Consultation; onChange: (c: Consultation) => void }) {
  const locked = data.status === 'CONFIRMED'
  const [texts, setTexts] = useState<Record<string, string>>(() => Object.fromEntries(data.report.map((s) => [s.key, s.text])))
  const [ovr, setOvr] = useState<OverrideDraft>(() =>
    Object.fromEntries(data.overrides.map((o) => [o.announcement_id, { verdict: o.verdict, reason: o.reason }])))
  const [feedback, setFeedback] = useState(data.feedback ?? '')
  const [notify, setNotify] = useState(true)
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null)
  const { busy, run } = useAction()
  const toast = useToast()

  const draftOf = (key: string) => data.draft.find((d) => d.key === key)?.text ?? ''
  const results = data.eligibility?.results ?? []
  const missingReason = results.some((r) => {
    const o = ovr[r.announcement_id]
    return o && o.verdict !== r.verdict && !o.reason.trim()
  })

  const body = () => ({
    report: texts,
    overrides: results
      .filter((r) => ovr[r.announcement_id] && ovr[r.announcement_id].verdict !== r.verdict)
      .map((r) => ({ announcement_id: r.announcement_id, verdict: ovr[r.announcement_id].verdict, reason: ovr[r.announcement_id].reason.trim() })),
    feedback: feedback.trim(),
  })

  const save = () => run(async () => {
    onChange(await updateConsultation(data.id, body()))
    toast.show({ kind: 'success', title: '저장했습니다' })
  })
  const confirm = () => run(async () => {
    await updateConsultation(data.id, body())
    const c = await confirmConsultation(data.id, notify)
    onChange(c)
    const n = c.notify
    setNotice(notify
      ? n.sent ? { ok: true, text: `확정했습니다. ${n.to ?? '기업 이메일'}로 안내했습니다.` }
        : { ok: false, text: `확정했습니다. 안내 메일은 보내지 못했습니다${n.reason ? `: ${n.reason}` : '.'}` }
      : { ok: true, text: '확정했습니다. 안내 메일은 보내지 않았습니다.' })
  })

  const cmp = data.compare
  return (
    <>
      <Card title={`${data.company_name} 상담결과서`} actions={
        <span className={`badge badge-${locked ? 'ok' : 'warn'}`}>{data.status_label}</span>
      }>
        <p className="small muted">
          {data.task_label} · 작성 {fmtDate(data.created_at)}{data.created_by_name ? ` ${data.created_by_name}` : ''}
          {locked && <> · 확정 {fmtDate(data.confirmed_at)}{data.confirmed_by_name ? ` ${data.confirmed_by_name}` : ''}
            {data.notified_at ? ` · 안내 ${fmtDate(data.notified_at)}` : ''}</>}
        </p>
        {data.concern && <p className="small">상담 내용: {data.concern}</p>}
        {notice && <div className={`notice ${notice.ok ? 'notice-ok' : 'notice-warn'}`}>{notice.text}</div>}
      </Card>

      {data.evidence && data.evidence.length > 0 && (
        <Card title="상담에 쓴 보완자료">
          <ul>
            {data.evidence.map((e) => (
              <li key={e.id}>
                {e.file_name}
                <span className="small muted"> {[e.origin_label, e.kind_label, e.note].filter(Boolean).join(' · ')}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {cmp && (
        <Card title="직전 상담 대비">
          <p>
            종합 {cmp.total_before}점에서 {cmp.total_after}점, <strong>{fmtDelta(cmp.total_after - cmp.total_before)}</strong>
            {cmp.state_before !== cmp.state_after && <> · 상태유형 {cmp.state_before}에서 {cmp.state_after}</>}
          </p>
          <div className="chips" style={{ marginTop: 0 }}>
            {cmp.areas.map((a) => (
              <span key={a.label} className={`badge badge-${a.delta > 0 ? 'ok' : a.delta < 0 ? 'bad' : 'muted'}`}>{a.label} {fmtDelta(a.delta)}</span>
            ))}
          </div>
          {cmp.verdict_changes.length > 0 && (
            <>
              <h4>판정이 달라진 공고</h4>
              <ul>{cmp.verdict_changes.map((v) => <li key={v.title}>{v.title} : {v.before}에서 {v.after}</li>)}</ul>
            </>
          )}
        </Card>
      )}

      <Card title="결과서 내용">
        <div className="stack">
          {data.report.map((s) => {
            const edited = texts[s.key] !== draftOf(s.key)
            return (
              <div key={s.key}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <strong>{s.title}</strong>
                  {s.drafted_by === 'LLM' && <span className="small muted">AI 문장 다듬기</span>}
                  {edited && <span className="badge badge-info">수정함</span>}
                  {edited && !locked && (
                    <button className="btn btn-sm" onClick={() => setTexts({ ...texts, [s.key]: draftOf(s.key) })}>초안으로 되돌리기</button>
                  )}
                </div>
                {locked ? <p style={{ whiteSpace: 'pre-wrap' }}>{texts[s.key]}</p> : (
                  <textarea rows={Math.min(12, Math.max(3, (texts[s.key] ?? '').split('\n').length + 1))} value={texts[s.key] ?? ''}
                    aria-label={s.title} onChange={(e) => setTexts({ ...texts, [s.key]: e.target.value })} />
                )}
              </div>
            )
          })}
        </div>
      </Card>

      {results.length > 0 && (
        <Card title="판정 수정">
          <p className="small muted">자동 판정을 바꿀 때는 이유를 적습니다. 바꾼 내용은 상담 이력 점검에 모입니다.</p>
          <table className="table">
            <thead><tr><th>공고</th><th>자동 판정</th><th>담당자 판정</th><th>이유</th></tr></thead>
            <tbody>
              {results.map((r) => {
                const cur = ovr[r.announcement_id]?.verdict ?? r.verdict
                const changed = cur !== r.verdict
                return (
                  <tr key={r.announcement_id}>
                    <td>{r.title}</td>
                    <td>{r.q1_label}</td>
                    <td>
                      {locked ? verdictText(cur) : (
                        <select value={cur} aria-label={`${r.title} 판정`} onChange={(e) =>
                          setOvr({ ...ovr, [r.announcement_id]: { verdict: e.target.value, reason: ovr[r.announcement_id]?.reason ?? '' } })}>
                          {VERDICT_OPTIONS.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
                        </select>
                      )}
                    </td>
                    <td>
                      {changed && (locked ? ovr[r.announcement_id].reason : (
                        <input value={ovr[r.announcement_id].reason} placeholder="이유 (필수)" aria-label={`${r.title} 이유`}
                          onChange={(e) => setOvr({ ...ovr, [r.announcement_id]: { verdict: cur, reason: e.target.value } })} />
                      ))}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </Card>
      )}

      <Card title="담당자 의견 (이력 점검용)">
        {locked ? <p style={{ whiteSpace: 'pre-wrap' }}>{data.feedback || '없음'}</p> : (
          <textarea rows={3} value={feedback} aria-label="담당자 의견" onChange={(e) => setFeedback(e.target.value)}
            placeholder="진단·판정·추천이 맞지 않았던 점을 적습니다." />
        )}
        {!locked && (
          <>
            {missingReason && <div className="notice">바꾼 판정에는 이유를 적어야 저장할 수 있습니다.</div>}
            <div className="form-row" style={{ marginTop: 12, alignItems: 'center' }}>
              <button className="btn" disabled={busy || missingReason} onClick={() => void save()}>{busy ? '처리 중…' : '저장'}</button>
              <button className="btn btn-primary" disabled={busy || missingReason} onClick={() => void confirm()}>확정</button>
              <label className="check small">
                <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} /> 기업 이메일로 안내
              </label>
            </div>
          </>
        )}
        <p className="small muted" style={{ marginTop: 10 }}>확정한 결과만 기업 화면에 보입니다. 확정 후에는 고칠 수 없고 새로 상담합니다.</p>
      </Card>
    </>
  )
}
