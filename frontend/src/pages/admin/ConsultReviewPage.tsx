import { getReviewLog } from '../../api/navigator'
import { Card, Empty, fmtDate, PageHeader, useAsync } from '../../components/ui'
import { verdictText } from './ConsultReportPanel'

export function ConsultReviewPage() {
  const log = useAsync(() => getReviewLog(), [])
  const d = log.data
  return (
    <>
      <PageHeader title="상담 이력 점검" subtitle="담당자가 바꾼 판정과 결과서 문장을 모아 진단·판정·추천 기준 보정에 씁니다." />
      {!d ? <div className="page-loading">{log.loading ? '불러오는 중…' : '불러오지 못했습니다.'}</div> : (
        <div className="stack">
          <div className="grid-3">
            <Count label="전체 상담" value={d.total} />
            <Count label="확정" value={d.confirmed} />
            <Count label="판정 수정" value={`${d.counts.overrides}건`} />
            <Count label="결과서 수정" value={`${d.counts.edits}건`} />
            <Count label="의견" value={`${d.counts.feedback}건`} />
          </div>
          <Card title="점검 목록">
            {!d.items.length ? <Empty>판정을 바꾸거나 결과서를 고친 상담이 없습니다.</Empty> : (
              <table className="table">
                <thead><tr><th>기업</th><th>일시</th><th>판정 수정</th><th>고친 항목</th><th>의견</th></tr></thead>
                <tbody>
                  {d.items.map((it) => (
                    <tr key={it.consultation_id}>
                      <td>{it.company_name}<div className="small muted">{it.task_label} · {it.status_label}</div></td>
                      <td className="small">{fmtDate(it.created_at)}{it.created_by_name ? ` ${it.created_by_name}` : ''}</td>
                      <td className="small">
                        {it.overrides.length ? it.overrides.map((o) => (
                          <div key={o.announcement_id}>{o.title} : {verdictText(o.from)}에서 {verdictText(o.verdict)}
                            {o.reason && <span className="muted"> ({o.reason})</span>}</div>
                        )) : '–'}
                      </td>
                      <td className="small">{it.edited_sections.length ? it.edited_sections.join(', ') : '–'}</td>
                      <td className="small" style={{ whiteSpace: 'pre-wrap' }}>{it.feedback || '–'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
      )}
    </>
  )
}

function Count({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="card" style={{ textAlign: 'center' }}>
      <div className="small muted">{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700 }}>{value}</div>
    </div>
  )
}
