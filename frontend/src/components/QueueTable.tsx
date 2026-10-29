import { Link } from 'react-router-dom'
import type { ReviewQueueRow } from '../api/endpoints'
import { Empty, fmtDate, REVIEW_ROLE_LABELS, score, StatusBadge } from './ui'

export function QueueTable({ rows, empty }: { rows: ReviewQueueRow[]; empty: string }) {
  if (rows.length === 0) return <Empty>{empty}</Empty>
  return (
    <table className="table">
      <thead>
        <tr><th>배정</th><th>기획수요</th><th>추천 성과</th><th>연계유형</th><th>점수</th><th>근거</th><th>상태</th><th>기한</th><th /></tr>
      </thead>
      <tbody>
        {rows.map((q) => (
          <tr key={q.assignment_id} className={q.is_overdue ? 'row-overdue' : ''}>
            <td>{REVIEW_ROLE_LABELS[q.review_role]}</td>
            <td>{q.demand_title ?? '–'}</td>
            <td>{(q.source_cards ?? []).map((c) => c.title).join(' + ')}</td>
            <td><span className="pill">{q.linkage_type_name}</span></td>
            <td>{score(q.total_score)}</td>
            <td>{q.evidence_count}건{q.open_confirmations > 0 && <span className="warn-text"> · 확인 {q.open_confirmations}</span>}</td>
            <td><StatusBadge status={q.recommendation_status} /></td>
            <td>{q.is_overdue ? <span className="warn-text">초과 </span> : null}{fmtDate(q.due_at)}</td>
            <td><Link className="btn btn-sm" to={`/recommendations/${q.recommendation_id}`}>검토하기</Link></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
