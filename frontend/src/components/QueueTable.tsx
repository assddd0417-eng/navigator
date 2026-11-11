import { Link } from 'react-router-dom'
import type { ReviewQueueRow } from '../api/endpoints'
import { Empty, Fit, fmtDate, REVIEW_ROLE_LABELS, StatusBadge } from './ui'

/** 검토 요청 목록. 한 줄 = 기획수요 하나에 AI가 추천한 기존 성과 하나 */
export function QueueTable({ rows, empty }: { rows: ReviewQueueRow[]; empty: string }) {
  if (rows.length === 0) return <Empty>{empty}</Empty>
  return (
    <table className="table">
      <thead>
        <tr><th>필요한 기술 (기획수요)</th><th>AI가 추천한 기존 성과</th><th>연계 방식</th><th>적합도</th><th>맡은 쪽</th><th>상태</th><th>기한</th><th /></tr>
      </thead>
      <tbody>
        {rows.map((q) => (
          <tr key={q.assignment_id} className={q.is_overdue ? 'row-overdue' : ''}>
            <td>{q.demand_title ?? '–'}</td>
            <td>
              {(q.source_cards ?? []).map((c) => c.title).join(' + ')}
              <div className="muted small">
                근거 문서 {q.evidence_count}건{q.open_confirmations > 0 && <span className="warn-text"> · 확인할 점 {q.open_confirmations}건</span>}
              </div>
            </td>
            <td><span className="pill">{q.linkage_type_name}</span></td>
            <td className="nowrap"><Fit value={q.total_score} /></td>
            <td>{REVIEW_ROLE_LABELS[q.review_role]}</td>
            <td><StatusBadge status={q.recommendation_status} /></td>
            <td className="nowrap">{q.is_overdue ? <span className="warn-text">기한 넘김 </span> : null}{fmtDate(q.due_at)}</td>
            <td><Link className="btn btn-sm btn-primary" to={`/recommendations/${q.recommendation_id}`}>검토하기</Link></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
