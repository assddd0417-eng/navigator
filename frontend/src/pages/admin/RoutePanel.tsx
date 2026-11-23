import type { GrowthRoute, RouteProgram, RouteReadiness } from '../../api/navigator'
import { Card, docName } from '../../components/ui'

const READY_TONE: Record<RouteReadiness, string> = { IMMEDIATE: 'ok', AFTER_FIX: 'warn', PREPARE: 'muted' }
const READY_LABEL: Record<RouteReadiness, string> = { IMMEDIATE: '즉시 신청', AFTER_FIX: '보완 후 신청', PREPARE: '진입조건 준비' }

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="card" style={{ textAlign: 'center' }}>
      <div className="small muted">{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700 }}>{value}</div>
    </div>
  )
}

const docs = (p: RouteProgram) =>
  p.submit_documents.map(docName).join(', ')

export function RoutePanel({ data }: { data: GrowthRoute }) {
  const details = data.steps.flatMap((s) => s.programs.map((p) => ({ p, stage: s.stage_label })))
  const fix = (f: string | string[] | null) => (Array.isArray(f) ? f.join(' / ') : f)
  return (
    <>
      <Card title={`${data.company_name} D-ROUTE 성장경로`}>
        <div className="grid-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
          <Tile label="상태유형" value={data.state_label} />
          <Tile label="종합 준비도" value={`${data.total_score}점`} />
          <Tile label="우선 보완영역" value={data.weakest_label ?? '–'} />
          <Tile label="강점 영역" value={data.strength ? `${data.strength.label} ${data.strength.score}점` : '–'} />
        </div>
        <h4>경로 요약</h4>
        <p>{data.summary}</p>
      </Card>

      <div className="grid-3" style={{ alignItems: 'stretch' }}>
        {data.steps.map((s) => (
          <Card key={s.order} className="route-step">
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              <strong>{s.order}</strong>
              <span className="small muted">{s.horizon}</span>
              {s.is_current && <span className="badge badge-info">현재 위치</span>}
            </div>
            <h4 style={{ margin: '8px 0 2px' }}>{s.stage_label}</h4>
            <p className="small">목표 : {s.goal}</p>
            <div className="small muted" style={{ marginTop: 10 }}>추천 사업</div>
            {s.programs.length ? (
              <ul style={{ margin: '4px 0', paddingLeft: 18 }}>
                {s.programs.map((p) => (
                  <li key={p.program_id}>{p.name} <span className={`badge badge-${READY_TONE[p.readiness]}`}>{READY_LABEL[p.readiness]}</span></li>
                ))}
              </ul>
            ) : <p className="small muted">추천할 사업이 없습니다.</p>}
            {s.other_programs.length > 0 && (
              <p className="small muted">그 밖의 사업 : {s.other_programs.map((p) => `${p.name} (${READY_LABEL[p.readiness]})`).join(', ')}</p>
            )}
            <div className="small muted" style={{ marginTop: 10 }}>준비과제</div>
            {s.tasks.length ? (
              <ul style={{ margin: '4px 0', paddingLeft: 0, listStyle: 'none' }}>
                {s.tasks.map((t, i) => <li key={i}>{'☐'} {t}</li>)}
              </ul>
            ) : <p className="small muted">없음</p>}
            {s.basis && <p className="small muted" style={{ marginTop: 10 }}>근거 : {s.basis}</p>}
          </Card>
        ))}
      </div>

      <Card title="추천 사업 상세">
        {!details.length ? <p className="muted">추천 사업이 없습니다.</p> : (
          <table className="table table-wide">
            <thead>
              <tr><th>사업</th><th>단계</th><th>준비 상태</th><th>근거 공고</th><th>신청 가능 여부 / 적합도</th>
                <th>진입조건</th><th>준비서류</th><th>예상 산출물</th><th>유사 기업</th></tr>
            </thead>
            <tbody>
              {details.map(({ p, stage }) => (
                <tr key={p.program_id}>
                  <td style={{ minWidth: 120 }}>{p.name}</td>
                  <td className="small">{stage}</td>
                  <td><span className={`badge badge-${READY_TONE[p.readiness]}`}>{READY_LABEL[p.readiness]}</span></td>
                  <td className="small">{p.announcement_title ?? '–'}</td>
                  <td className="small">{[p.q1_label, p.fit_grade].filter(Boolean).join(' · ') || '–'}</td>
                  <td className="small" style={{ minWidth: 140 }}>
                    {p.entry_condition ?? '–'}
                    {p.entry_unmet.map((u) => <div key={u.area} style={{ color: "var(--warn)" }}>미달: {u.label} {u.score}점 (기준 {u.min}점)</div>)}
                  </td>
                  <td className="small">{docs(p) || '–'}</td>
                  <td className="small">{p.expected_output ?? '–'}</td>
                  <td className="small">
                    {p.similar.count}/{p.similar.total}개사 참여
                    {p.similar.avg_gap_years != null && <div>평균 간격 {p.similar.avg_gap_years}년</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {data.not_recommended.length > 0 && (
        <Card title="미추천 사업">
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {data.not_recommended.map((n) => (
              <li key={n.program_id}>
                <strong>{n.name}</strong> : {n.reason}
                {fix(n.fix) && <div className="small muted">확인할 내용 : {fix(n.fix)}</div>}
              </li>
            ))}
          </ul>
        </Card>
      )}
      {data.notice && <p className="small muted">{data.notice}</p>}
    </>
  )
}
