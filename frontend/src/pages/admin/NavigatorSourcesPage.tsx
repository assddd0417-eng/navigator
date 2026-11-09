import { useState } from 'react'
import { listFetchJobs, listSources, runSource, type FetchJob, type RunResult, type SourceRow } from '../../api/navigator'
import { Card, Empty, fmtDate, PageHeader, RoleHint, useAction, useAsync } from '../../components/ui'

const KIND_LABELS: Record<string, string> = {
  BIZ_STATUS: '휴·폐업', PATENT: '특허', CREDIT: '신용등급', FINANCE: '재무', RND: 'R&D 과제',
  CERTIFICATION: '인증', ANNOUNCEMENT: '공고',
}
const TRIGGER_LABELS: Record<string, string> = { ON_DEMAND: '수동', SCHEDULED: '주기', REGISTRATION: '등록' }
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
const fmtResult = (r: Record<string, number> | null) =>
  r && Object.keys(r).length ? Object.entries(r).map(([k, n]) => `${RESULT_LABELS[k] ?? k} ${n}`).join(' · ') : '–'

export function NavigatorSourcesPage() {
  const sources = useAsync(listSources, [])
  const [filter, setFilter] = useState<string | null>(null)
  const jobs = useAsync(() => listFetchJobs(filter ?? undefined), [filter])
  const [last, setLast] = useState<RunResult | null>(null)
  const { busy, run } = useAction()

  const runNow = (s: SourceRow) => run(async () => {
    setLast(await runSource(s.code))
    sources.reload(); jobs.reload()
  })

  return (
    <>
      <PageHeader title="외부 수집" subtitle="Navigator 기업·공고 외부 출처" actions={<RoleHint roles={['PLANNER']} />} />
      {last && (
        <div className={`notice ${last.status === 'SUCCEEDED' ? 'notice-ok' : ''}`}>
          {last.source} ({last.mode}) {last.status === 'SUCCEEDED' ? `완료: ${fmtResult(last.counts)}` : `실패: ${last.error}`}
        </div>
      )}
      <Card title="출처">
        <p className="small muted">
          mock 은 가상 데이터, live 는 실제 API 입니다. 서버 설정 SOURCE_&lt;코드&gt;=mock|live 와 API 키로 바꿉니다.
          주기 수집은 서버에서 <code>python -m app.collect --due</code> 를 정기 실행합니다.
        </p>
        {sources.loading ? <div className="page-loading">불러오는 중…</div> : !sources.data?.length ? <Empty>출처가 없습니다.</Empty> : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>출처</th><th>데이터</th><th>모드</th><th>주기</th><th>마지막 수집</th><th>결과</th><th>다음 주기</th><th /></tr>
              </thead>
              <tbody>
                {sources.data.map((s) => (
                  <tr key={s.code}>
                    <td>
                      <button className="link-btn" onClick={() => setFilter(filter === s.code ? null : s.code)}>
                        <strong>{s.name}</strong>
                      </button>
                      <div className="small muted">{s.code} · {s.provider}{s.is_paid ? ' · 유료' : ''}</div>
                    </td>
                    <td className="nowrap">{KIND_LABELS[s.data_kind] ?? s.data_kind}</td>
                    <td>
                      {s.implemented
                        ? <span className={`badge badge-${s.mode === 'live' ? 'ok' : 'muted'}`}>{s.mode}</span>
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
                    <td className="nowrap small">{s.implemented && s.fetch_interval ? (s.next_due_at ? fmtDate(s.next_due_at) : '다음 실행 때') : '–'}</td>
                    <td>
                      {s.implemented && (
                        <button className="btn btn-sm" disabled={busy} onClick={() => void runNow(s)}>지금 수집</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {sources.data?.some((s) => !s.implemented) && (
          <p className="small muted">미연결: 유료 계약(NICE·KED) 또는 비용 확인(NTIS) 후 연결합니다. 그 전까지는 기업 자가입력과 증빙으로 받습니다.</p>
        )}
      </Card>

      <Card title={filter ? `수집 기록 (${filter})` : '수집 기록'} actions={filter &&
        <button className="btn btn-sm" onClick={() => setFilter(null)}>전체 보기</button>}>
        {jobs.loading ? <div className="page-loading">불러오는 중…</div> : !jobs.data?.length ? <Empty>기록이 없습니다.</Empty> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>시각</th><th>출처</th><th>대상</th><th>방식</th><th>상태</th><th>결과</th></tr></thead>
              <tbody>
                {jobs.data.map((j: FetchJob) => (
                  <tr key={j.id}>
                    <td className="nowrap small">{fmtDate(j.started_at)}</td>
                    <td className="nowrap">{j.source} <span className="small muted">{j.mode.toLowerCase()}</span></td>
                    <td>{j.company_name ?? '전체'}</td>
                    <td className="nowrap">{TRIGGER_LABELS[j.trigger_kind]}</td>
                    <td><span className={`badge badge-${STATUS[j.status][1]}`}>{STATUS[j.status][0]}</span></td>
                    <td className="small">{j.error_message ?? (j.result ? fmtResult(j.result) : `원본 ${j.records_count}`)}</td>
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
