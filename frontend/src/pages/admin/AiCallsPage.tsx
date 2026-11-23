import { Fragment, useState } from 'react'
import { listAiCalls, type AiCall } from '../../api/navigator'
import { Card, Empty, fmtDate, PageHeader, useAsync } from '../../components/ui'

const PURPOSES = [
  { code: '', label: '전체' },
  { code: 'ELIGIBILITY_JUDGE', label: '자격 판단' },
  { code: 'REPORT_DRAFT', label: '결과서 문장' },
]
const PURPOSE_KO: Record<string, string> = { ELIGIBILITY_JUDGE: '자격 판단', REPORT_DRAFT: '결과서 문장' }
const STATUS_KO: Record<string, string> = { OK: '정상', PARTIAL: '일부 차단', FALLBACK: '규칙 대체', CACHED: '캐시' }
const STATUS_TONE: Record<string, string> = { OK: 'ok', PARTIAL: 'warn', FALLBACK: 'bad', CACHED: 'muted' }

export function AiCallsPage() {
  const [purpose, setPurpose] = useState('')
  const [openId, setOpenId] = useState<number | null>(null)
  const calls = useAsync(() => listAiCalls(purpose), [purpose])
  const st = calls.data?.stats
  return (
    <>
      <PageHeader title="AI 호출 기록" subtitle="AI에 보낸 요청과 결과, 막은 판단을 확인합니다." />
      {st && (
        <div className="form-row" style={{ marginBottom: 12, gap: 8, flexWrap: 'wrap' }}>
          <span className="badge badge-muted">전체 {st.total}</span>
          <span className="badge badge-ok">정상 {st.ok}</span>
          <span className="badge badge-warn">일부 차단 {st.partial}</span>
          <span className="badge badge-bad">규칙 대체 {st.fallback}</span>
          <span className="badge badge-muted">캐시 {st.cached}</span>
          <span className="badge badge-info">차단 판단 수 {st.blocked}</span>
        </div>
      )}
      {calls.data?.per_task && (
        <Card title="상담 업무별 AI 호출">
          <p className="small muted">기준은 상담 1건당 호출 수 (진단은 AI를 쓰지 않음). AI 판단을 켜고 실행한 상담만 셉니다.</p>
          <table className="table">
            <thead><tr><th>상담 업무</th><th>기준</th><th>상담 수</th><th>호출 수</th><th>상담 1건 최대</th><th>판정</th></tr></thead>
            <tbody>
              {calls.data.per_task.map((t) => (
                <tr key={t.task}>
                  <td>{t.task_label}</td>
                  <td>{t.standard}회</td>
                  <td>{t.consultations}</td>
                  <td>{t.calls}</td>
                  <td>{t.max_calls ?? '–'}</td>
                  <td>{t.max_calls == null ? <span className="badge badge-muted">실행 없음</span>
                    : t.max_calls <= t.standard ? <span className="badge badge-ok">기준 이내</span>
                      : <span className="badge badge-bad">기준 초과</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      <Card title="호출 목록" actions={
        <select value={purpose} onChange={(e) => { setPurpose(e.target.value); setOpenId(null) }} aria-label="목적">
          {PURPOSES.map((p) => <option key={p.code} value={p.code}>{p.label}</option>)}
        </select>
      }>
        {calls.loading ? <div className="page-loading">불러오는 중…</div> : !calls.data?.items.length ? <Empty>호출 기록이 없습니다.</Empty> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>시각</th><th>목적</th><th>상담</th><th>기업</th><th>공고</th><th>프롬프트</th><th>모델</th><th>상태</th><th>차단</th><th>응답(ms)</th></tr></thead>
              <tbody>
                {calls.data.items.map((c) => (
                  <Fragment key={c.id}>
                    <tr style={{ cursor: 'pointer' }} onClick={() => setOpenId(openId === c.id ? null : c.id)}>
                      <td>{fmtDate(c.created_at)}</td>
                      <td>{PURPOSE_KO[c.purpose] ?? c.purpose}</td>
                      <td>{c.consultation_id ? `${c.consultation_id}번 ${c.consultation_task_label ?? ''}` : '–'}</td>
                      <td>{c.company_name ?? '–'}</td>
                      <td>{c.announcement_count > 1 ? `공고 ${c.announcement_count}건 묶음` : c.announcement_title ?? '–'}</td>
                      <td>{c.prompt_version != null ? `v${c.prompt_version}` : '–'}</td>
                      <td>{c.model ?? '–'}</td>
                      <td><span className={`badge badge-${STATUS_TONE[c.status] ?? 'muted'}`}>{STATUS_KO[c.status] ?? c.status}</span></td>
                      <td>{c.blocked?.length ?? 0}</td>
                      <td>{c.latency_ms ?? '–'}</td>
                    </tr>
                    {openId === c.id && <tr><td colSpan={10}><Detail c={c} /></td></tr>}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}

function Detail({ c }: { c: AiCall }) {
  const basis = c.input_refs?.basis ?? []
  return (
    <div className="stack small">
      {!!c.blocked?.length && (
        <div>
          <strong>막은 판단</strong>
          <ul>
            {c.blocked.map((b, i) => (
              <li key={i}>
                {b.announcement_id != null && `공고 ${b.announcement_id} `}{b.requirement_id != null && `요건 ${b.requirement_id}`}{b.section && `결과서 항목 ${b.section}`}: {b.reason}
                {b.llm_result && ` (AI ${b.llm_result}${b.rule_result ? `, 규칙 ${b.rule_result}` : ''})`}
                {b.quote && <div className="muted">인용: “{b.quote}”</div>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {c.error && <div><strong>오류</strong><div>{c.error}</div></div>}
      {(basis.length > 0 || !!c.input_refs?.sections?.length) && (
        <div>
          <strong>근거 출처</strong>
          <ul>
            {basis.map((b, i) => <li key={i}>{b.announcement_id != null ? `공고 ${b.announcement_id} · ` : ''}{b.source ?? '–'} · {b.ref ?? '–'} · {b.chars ?? 0}자</li>)}
            {c.input_refs?.sections?.map((s) => <li key={s}>결과서 항목 {s}</li>)}
          </ul>
        </div>
      )}
      <div>
        <strong>응답 원문</strong>
        <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 320, overflow: 'auto' }}>{JSON.stringify(c.output, null, 2)}</pre>
      </div>
    </div>
  )
}
