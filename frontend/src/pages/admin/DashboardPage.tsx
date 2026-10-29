import { Link } from 'react-router-dom'
import {
  getRecommendationKpi, getReviewQueue, getWorkTimeKpi, listCards, listDemands, listDocuments,
} from '../../api/endpoints'
import { Card, Empty, PageHeader, pct, statusLabel, useAsync } from '../../components/ui'

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
  const { data, loading } = useAsync(async () => {
    const [kpi, queue, cards, demands, docs, work] = await Promise.all([
      getRecommendationKpi(), getReviewQueue(false), listCards(), listDemands(), listDocuments(), getWorkTimeKpi(),
    ])
    return { kpi, queue, cards, demands, docs, work }
  })

  if (loading && !data) return <div className="page-loading">불러오는 중…</div>
  if (!data) return <Empty>대시보드를 불러오지 못했습니다. 백엔드 연결을 확인하세요.</Empty>

  const { kpi, queue, cards, demands, docs, work } = data
  const recTotal = kpi.reduce((a, r) => a + r.recommendations, 0)
  const withEvidence = kpi.reduce((a, r) => a + r.with_evidence, 0)
  const reviewed = kpi.reduce((a, r) => a + r.finally_reviewed, 0)
  const adopted = kpi.reduce((a, r) => a + r.adopted, 0)
  const ratio = (a: number, b: number) => (b ? (100 * a) / b : null)
  const overdue = queue.filter((q) => q.is_overdue).length
  const published = cards.filter((c) => c.status === 'PUBLISHED').length

  const flow = [
    { label: '원문 문서', value: docs.length, hint: '등록·청킹' },
    { label: '성과카드', value: published, hint: `발행 / 전체 ${cards.length}` },
    { label: '기획수요', value: demands.length, hint: '등록' },
    { label: 'AI 추천', value: recTotal, hint: '매칭 결과' },
    { label: '검토 대기', value: queue.length, hint: overdue ? `기한 초과 ${overdue}` : '배정됨' },
    { label: '최종 판정', value: reviewed, hint: `채택 ${adopted}` },
  ]

  return (
    <>
      <PageHeader title="전체 진행 현황" subtitle="문서 등록부터 최종 판정까지 이어달리기 전 과정을 한눈에 봅니다." />

      <div className="flow">
        {flow.map((s, i) => (
          <div key={s.label} className="flow-step">
            <div className="flow-num">{i + 1}</div>
            <div className="flow-value">{s.value}</div>
            <div className="flow-label">{s.label}</div>
            <div className="flow-hint">{s.hint}</div>
          </div>
        ))}
      </div>

      <div className="kpi-row">
        <div className="kpi">
          <div className="kpi-label">추천 원문 근거 연결률</div>
          <div className="kpi-value">{pct(ratio(withEvidence, recTotal))}</div>
          <div className="kpi-target">목표 100% · {withEvidence}/{recTotal}건</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">최종 검토율</div>
          <div className="kpi-value">{pct(ratio(reviewed, recTotal))}</div>
          <div className="kpi-target">목표 100% · {reviewed}/{recTotal}건</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">채택된 연계 후보</div>
          <div className="kpi-value">{adopted}</div>
          <div className="kpi-target">최종 판정 {reviewed}건 중</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">검토 대기</div>
          <div className="kpi-value">{queue.length}</div>
          <div className="kpi-target">{overdue ? `기한 초과 ${overdue}건` : '기한 초과 없음'} · <Link to="/reviews">검토 큐 →</Link></div>
        </div>
      </div>

      <div className="grid-2">
        <Card title="문서 처리 상태">
          <StatusBar counts={countBy(docs, (d) => d.parse_status)} order={['EMBEDDED', 'CHUNKED', 'PARSED', 'PENDING', 'FAILED']} />
          <p className="muted small">현재 계정이 열람할 수 있는 문서만 집계됩니다.</p>
        </Card>
        <Card title="성과카드 상태">
          <StatusBar counts={countBy(cards, (c) => c.status)} order={['PUBLISHED', 'IN_REVIEW', 'DRAFT', 'ARCHIVED']} />
        </Card>
        <Card title="매칭 실행별 KPI">
          {kpi.length === 0 ? <Empty>아직 매칭 실행이 없습니다. 프로젝트 관리에서 매칭을 실행하세요.</Empty> : (
            <table className="table">
              <thead><tr><th>실행</th><th>추천</th><th>근거 연결률</th><th>최종 검토율</th><th>채택</th></tr></thead>
              <tbody>
                {kpi.map((r) => (
                  <tr key={r.match_run_id}>
                    <td>#{r.match_run_id}</td><td>{r.recommendations}</td>
                    <td>{pct(r.evidence_coverage_pct)}</td><td>{pct(r.final_review_pct)}</td><td>{r.adopted}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="업무시간 단축률">
          {work.length === 0 ? <Empty>측정 데이터가 없습니다 (조사 70%·검토자료 60% 단축 목표).</Empty> : (
            <table className="table">
              <thead><tr><th>업무</th><th>기존(분)</th><th>AX(분)</th><th>단축률</th></tr></thead>
              <tbody>
                {work.map((w) => (
                  <tr key={w.task_type}>
                    <td>{w.task_type}</td>
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
