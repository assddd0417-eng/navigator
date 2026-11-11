import { Link } from 'react-router-dom'
import {
  getRecommendationKpi, getReviewQueue, getWorkTimeKpi, listCards, listDemands, listDocuments,
} from '../../api/endpoints'
import { useAuth } from '../../auth/AuthContext'
import { Card, Empty, PageHeader, pct, statusLabel, useAsync } from '../../components/ui'

const TASK_LABELS: Record<string, string> = {
  RESEARCH: '관련 성과·과제 조사', DOCUMENT_READING: '자료 읽기',
  CANDIDATE_LIST: '후보 목록 만들기', REVIEW_MATERIAL: '검토 자료 작성',
}

function countBy<T>(rows: T[], key: (r: T) => string): Record<string, number> {
  return rows.reduce<Record<string, number>>((acc, r) => {
    const k = key(r)
    acc[k] = (acc[k] ?? 0) + 1
    return acc
  }, {})
}

function StatusBar({ counts, order }: { counts: Record<string, number>; order: string[] }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  if (total === 0) return <Empty>아직 데이터가 없습니다</Empty>
  const keys = [...order.filter((k) => counts[k]), ...Object.keys(counts).filter((k) => !order.includes(k))]
  return (
    <>
      <div className="stack-bar">
        {keys.map((k) => (
          <div key={k} className={`stack-seg seg-${k.toLowerCase()}`} style={{ flex: counts[k] }}
            title={`${statusLabel(k)} ${counts[k]}`} />
        ))}
      </div>
      <ul className="legend">
        {keys.map((k) => (
          <li key={k}><span className={`dot seg-${k.toLowerCase()}`} />{statusLabel(k)} <strong>{counts[k]}</strong></li>
        ))}
      </ul>
    </>
  )
}

/** 관리자(기획자·검수자) 대시보드: 전체 진행 현황과 PoC KPI */
export function DashboardPage() {
  const { role } = useAuth()
  const { data, loading } = useAsync(async () => {
    const [kpi, queue, mine, cards, demands, docs, work] = await Promise.all([
      getRecommendationKpi(), getReviewQueue(false), getReviewQueue(true), listCards(), listDemands(), listDocuments(),
      getWorkTimeKpi(),
    ])
    return { kpi, queue, mine, cards, demands, docs, work }
  })

  if (loading && !data) return <div className="page-loading">불러오는 중…</div>
  if (!data) return <Empty>화면을 불러오지 못했습니다. 잠시 뒤 새로고침해 주세요.</Empty>

  const { kpi, queue, mine, cards, demands, docs, work } = data
  const recTotal = kpi.reduce((a, r) => a + r.recommendations, 0)
  const withEvidence = kpi.reduce((a, r) => a + r.with_evidence, 0)
  const reviewed = kpi.reduce((a, r) => a + r.finally_reviewed, 0)
  const adopted = kpi.reduce((a, r) => a + r.adopted, 0)
  const ratio = (a: number, b: number) => (b ? (100 * a) / b : null)
  const overdue = queue.filter((q) => q.is_overdue).length
  const published = cards.filter((c) => c.status === 'PUBLISHED').length

  const mineOverdue = mine.filter((q) => q.is_overdue).length
  const flow = [
    { label: '올라온 보고서', value: docs.length, hint: '결과보고서 등 원문', to: null },
    { label: '발행된 성과카드', value: published, hint: `전체 ${cards.length}장 중`, to: '/projects?tab=cards' },
    { label: '기획수요', value: demands.length, hint: '새로 필요한 기술', to: '/projects' },
    { label: 'AI 추천', value: recTotal, hint: '이어 쓸 성과 후보', to: '/projects' },
    { label: '검토 중', value: queue.length, hint: overdue ? `기한 넘김 ${overdue}건` : '사람이 확인하는 단계', to: '/reviews?view=all' },
    { label: '최종 결정', value: reviewed, hint: `채택 ${adopted}건`, to: null },
  ]

  return (
    <>
      <PageHeader title="한눈에 보기" subtitle="보고서가 올라와서 최종 결정이 나기까지 지금 어디까지 왔는지 보여 줍니다." />

      <Card title="오늘 할 일" className="todo-card">
        <div className="todo">
          {role === 'DEPT_REVIEWER' ? (
            <Link to="/reviews" className={`todo-item ${mine.length ? 'todo-hot' : ''}`}>
              <strong>{mine.length}건</strong>
              <span>우리 부서로 온 검토 요청{mineOverdue ? ` (기한 넘김 ${mineOverdue}건)` : ''}</span>
              <span className="todo-go">검토하러 가기 →</span>
            </Link>
          ) : (
            <Link to="/projects" className="todo-item">
              <strong>{demands.length}건</strong>
              <span>등록된 기획수요 · AI로 이어 쓸 성과를 찾고 검토를 맡기세요</span>
              <span className="todo-go">연계 후보 찾기 →</span>
            </Link>
          )}
          <Link to={role === 'DEPT_REVIEWER' ? '/reviews?view=all' : '/reviews'} className="todo-item">
            <strong>{role === 'DEPT_REVIEWER' ? queue.length : mine.length}건</strong>
            <span>{role === 'DEPT_REVIEWER' ? '전체 검토 대기 (다른 부서 포함)' : '내가 맡은 검토'}</span>
            <span className="todo-go">목록 보기 →</span>
          </Link>
          <Link to="/gaps" className="todo-item">
            <strong>🌍</strong>
            <span>해외 수요와 비교해 우리 기술이 부족한 곳</span>
            <span className="todo-go">갭 분석 보기 →</span>
          </Link>
        </div>
      </Card>

      <div className="flow">
        {flow.map((s, i) => {
          const body = (<>
            <div className="flow-num">{i + 1}</div>
            <div className="flow-value">{s.value}</div>
            <div className="flow-label">{s.label}</div>
            <div className="flow-hint">{s.hint}</div>
          </>)
          return s.to
            ? <Link key={s.label} to={s.to} className="flow-step flow-link">{body}</Link>
            : <div key={s.label} className="flow-step">{body}</div>
        })}
      </div>

      <div className="kpi-row">
        <div className="kpi">
          <div className="kpi-label">근거 문서가 붙은 추천</div>
          <div className="kpi-value">{pct(ratio(withEvidence, recTotal))}</div>
          <div className="kpi-target">목표 100% · 추천 {recTotal}건 중 {withEvidence}건</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">최종 결정까지 끝난 추천</div>
          <div className="kpi-value">{pct(ratio(reviewed, recTotal))}</div>
          <div className="kpi-target">목표 100% · 추천 {recTotal}건 중 {reviewed}건</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">채택된 연계</div>
          <div className="kpi-value">{adopted}건</div>
          <div className="kpi-target">최종 결정 {reviewed}건 중</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">검토 기다리는 추천</div>
          <div className="kpi-value">{queue.length}건</div>
          <div className="kpi-target">{overdue ? `기한 넘김 ${overdue}건` : '기한 넘긴 건 없음'} · <Link to="/reviews?view=all">목록 →</Link></div>
        </div>
      </div>

      <div className="grid-2">
        <Card title="올라온 보고서 처리 상태">
          <StatusBar counts={countBy(docs, (d) => d.parse_status)} order={['EMBEDDED', 'CHUNKED', 'PARSED', 'PENDING', 'FAILED']} />
          <p className="muted small">내 부서·보안등급으로 볼 수 있는 문서만 셉니다. ‘검색 가능’이 되면 AI 추천의 근거로 쓰입니다.</p>
        </Card>
        <Card title="성과카드 상태">
          <StatusBar counts={countBy(cards, (c) => c.status)} order={['PUBLISHED', 'IN_REVIEW', 'DRAFT', 'ARCHIVED']} />
        </Card>
        <Card title="AI 추천을 받을 때마다의 결과">
          {kpi.length === 0 ? <Empty>아직 AI 추천을 받은 적이 없습니다. <Link to="/projects">연계 후보 찾기</Link>에서 시작하세요.</Empty> : (
            <table className="table">
              <thead><tr><th>회차</th><th>추천 수</th><th>근거 붙은 비율</th><th>최종 결정 비율</th><th>채택</th></tr></thead>
              <tbody>
                {[...kpi].sort((a, b) => b.match_run_id - a.match_run_id).map((r, i) => (
                  <tr key={r.match_run_id}>
                    <td>{kpi.length - i}회차{i === 0 ? ' (최근)' : ''}</td><td>{r.recommendations}건</td>
                    <td>{pct(r.evidence_coverage_pct)}</td><td>{pct(r.final_review_pct)}</td><td>{r.adopted}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="업무 시간이 얼마나 줄었나">
          {work.length === 0 ? <Empty>아직 잰 기록이 없습니다. (목표: 조사 시간 70%, 검토 자료 작성 60% 줄이기)</Empty> : (
            <table className="table">
              <thead><tr><th>업무</th><th>예전 방식(분)</th><th>이 시스템(분)</th><th>줄어든 비율</th></tr></thead>
              <tbody>
                {work.map((w) => (
                  <tr key={w.task_type}>
                    <td>{TASK_LABELS[w.task_type] ?? w.task_type}</td>
                    <td>{w.avg_manual_min == null ? '–' : Number(w.avg_manual_min).toFixed(0)}</td>
                    <td>{w.avg_ax_min == null ? '–' : Number(w.avg_ax_min).toFixed(0)}</td>
                    <td>{pct(w.reduction_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </>
  )
}
