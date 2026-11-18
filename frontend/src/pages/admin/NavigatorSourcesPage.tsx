import { listSources } from '../../api/navigator'
import { Card, Empty, fmtDate, PageHeader, useAsync } from '../../components/ui'

const KIND_LABELS: Record<string, string> = {
  BIZ_STATUS: '휴·폐업', PATENT: '특허', CREDIT: '신용등급', FINANCE: '재무', RND: 'R&D 과제',
  CERTIFICATION: '인증', ANNOUNCEMENT: '공고',
}
const RESULT_LABELS: Record<string, string> = {
  records: '원본', inserted: '추가', updated: '갱신', changed: '변경', not_found: '없음', skipped: '제외',
}
const STATUS: Record<string, [string, string]> = {
  SUCCEEDED: ['성공', 'ok'], FAILED: ['실패', 'bad'], RUNNING: ['실행 중', 'warn'],
}

const fmtInterval = (v: string | null) => {
  if (!v) return '요청 시'
  const m = v.match(/^(\d+) days?$/)
  return m ? `${m[1]}일` : v
}
const fmtEvery = (m: number) => (m % 60 === 0 ? `${m / 60}시간` : `${m}분`)
const fmtResult = (r: Record<string, number> | null) =>
  r && Object.keys(r).length ? Object.entries(r).map(([k, n]) => `${RESULT_LABELS[k] ?? k} ${n}`).join(' · ') : '–'

export function NavigatorSourcesPage() {
  const sources = useAsync(listSources, [])
  const auto = sources.data?.[0]?.auto_minutes ?? 0

  return (
    <>
      <PageHeader title="외부 수집" subtitle="공공 API로 기업 정보와 공고를 자동으로 가져옵니다" />
      <Card title="출처">
        <p className="small muted">
          API로 연결되는 출처만 표시합니다. ‘시험 데이터’는 키를 넣기 전이라 가상 자료로 동작하는 출처입니다.{' '}
          {auto
            ? `서버가 ${fmtEvery(auto)}마다 확인해서 주기가 된 출처를 자동으로 가져옵니다.`
            : '자동 수집이 꺼져 있습니다.'}
        </p>
        {sources.loading ? <div className="page-loading">불러오는 중…</div> : !sources.data?.length ? <Empty>출처가 없습니다.</Empty> : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>출처</th><th>데이터</th><th>연결</th><th>주기</th><th>마지막 수집</th><th>결과</th><th>다음 수집</th></tr>
              </thead>
              <tbody>
                {sources.data.map((s) => (
                  <tr key={s.code}>
                    <td>
                      <strong>{s.name}</strong>
                      <div className="small muted">{s.provider}{s.is_paid ? ' · 유료' : ''}</div>
                    </td>
                    <td className="nowrap">{KIND_LABELS[s.data_kind] ?? s.data_kind}</td>
                    <td>
                      {s.implemented
                        ? <span className={`badge badge-${s.mode === 'live' ? 'ok' : 'muted'}`}>{s.mode === 'live' ? '실제 연결' : '시험 데이터'}</span>
                        : <span className="badge badge-warn">미연결</span>}
                    </td>
                    <td className="nowrap">{fmtInterval(s.fetch_interval)}</td>
                    <td className="nowrap">
                      {s.last_status ? (
                        <>
                          <span className={`badge badge-${STATUS[s.last_status][1]}`}>{STATUS[s.last_status][0]}</span>{' '}
                          <span className="small">{fmtDate(s.last_started_at)}</span>
                        </>
                      ) : '–'}
                    </td>
                    <td className="small">{s.last_error ? <span className="bad-text">{s.last_error}</span> : fmtResult(s.last_result)}</td>
                    <td className="nowrap small">{auto && s.implemented && s.fetch_interval ? (s.next_due_at ? fmtDate(s.next_due_at) : '다음 실행 때') : '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}
