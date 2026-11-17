import { useEffect, useState, type FormEvent } from 'react'
import { listDemands } from '../../api/endpoints'
import {
  addSurvey, addWorkTime, ASPECTS, deleteWorkTime, downloadMeasureXlsx, getMeasureSummary, listWorkTime, TASKS,
  type TaskType,
} from '../../api/measurements'
import { useAuth } from '../../auth/AuthContext'
import { useToast } from '../../components/Toast'
import { Card, Empty, PageHeader, Steps, useAction, useAsync } from '../../components/ui'

const fmtClock = (sec: number) =>
  `${String(Math.floor(sec / 3600)).padStart(2, '0')}:${String(Math.floor((sec % 3600) / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`

/**
 * 효과 측정: 같은 업무를 기존 방식(수작업)과 이 시스템(AX)으로 했을 때 걸린 시간과 만족도를 남긴다.
 * 기획자·검수자는 업무별 단축률과 제안서 목표 달성 여부, 만족도를 함께 본다.
 */
export function MeasurementsPage() {
  const toast = useToast()
  const { role } = useAuth()
  const { busy, run } = useAction()
  const canSeeAll = role === 'PLANNER' || role === 'DEPT_REVIEWER'
  const summary = useAsync(async () => (canSeeAll ? getMeasureSummary() : null), [canSeeAll])
  const mine = useAsync(() => listWorkTime(true), [])
  const demands = useAsync(listDemands, [])

  const [f, setF] = useState({ task_type: 'RESEARCH' as TaskType, method: 'AX' as 'MANUAL' | 'AX', minutes: '',
    candidates: '', demand: '', note: '' })
  const [startAt, setStartAt] = useState<number | null>(null)
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (startAt == null) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [startAt])
  const elapsed = startAt ? Math.floor((now - startAt) / 1000) : 0

  const stop = () => {
    if (startAt == null) return
    setF({ ...f, minutes: String(Math.max(1, Math.round(elapsed / 60))) })
    setStartAt(null)
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const ok = await run(() => addWorkTime({ task_type: f.task_type, method: f.method, minutes: Number(f.minutes),
      candidates_found: f.candidates ? Number(f.candidates) : null, demand_id: f.demand ? Number(f.demand) : null,
      note: f.note || undefined }))
    if (!ok) return
    toast.success('측정 시간을 남겼습니다')
    setF({ ...f, minutes: '', candidates: '', note: '' })
    void mine.reload()
    void summary.reload()
  }

  const [sv, setSv] = useState<{ score: number; aspects: Record<string, number>; comment: string }>(
    { score: 4, aspects: {}, comment: '' })
  const submitSurvey = async (e: FormEvent) => {
    e.preventDefault()
    const ok = await run(() => addSurvey({ score: sv.score, aspects: sv.aspects, comment: sv.comment || undefined }))
    if (!ok) return
    toast.success('만족도를 남겼습니다', '고맙습니다.')
    setSv({ score: 4, aspects: {}, comment: '' })
    void summary.reload()
  }

  const s = summary.data
  const rows = mine.data ?? []
  return (
    <>
      <PageHeader title="효과 측정"
        subtitle="같은 일을 예전 방식과 이 시스템으로 했을 때 걸린 시간, 그리고 써 본 느낌을 남깁니다. 모인 값으로 제안서 목표(조사 70%·검토자료 60% 단축) 달성 여부를 봅니다."
        actions={canSeeAll ? <button className="btn" disabled={busy} onClick={() => void run(downloadMeasureXlsx)}>⬇ 엑셀로 받기</button> : undefined} />
      <Steps items={[
        '일을 시작할 때 ‘시작’을 누르고, 끝나면 ‘끝’을 누릅니다. 걸린 분이 자동으로 들어갑니다. 직접 적어도 됩니다.',
        '예전 방식으로 한 시간은 ‘수작업’, 이 시스템으로 한 시간은 ‘AX’로 고릅니다.',
        '찾은 연계 후보 수도 적으면 ‘추가 연계후보 수’ 비교에 쓰입니다.',
      ]} />

      {s && (
        <Card title="측정 결과 (업무별 평균)">
          <div className="table-scroll">
            <table className="table">
              <thead><tr><th>업무</th><th className="num">수작업 평균</th><th className="num">AX 평균</th>
                <th className="num">단축률</th><th>목표</th><th className="num">찾은 후보 (수작업 → AX)</th><th className="num">측정 수</th></tr></thead>
              <tbody>
                {s.tasks.map((t) => (
                  <tr key={t.task_type}>
                    <td><strong>{t.task_name}</strong></td>
                    <td className="num">{t.manual_avg == null ? '–' : `${t.manual_avg}분`}</td>
                    <td className="num">{t.ax_avg == null ? '–' : `${t.ax_avg}분`}</td>
                    <td className="num">{t.reduction_pct == null ? '–' : `${t.reduction_pct}%`}</td>
                    <td>{t.target_pct == null ? <span className="muted">–</span> : t.met == null
                      ? <span className="muted">{t.target_pct}% (측정 부족)</span>
                      : <span className={`badge badge-${t.met ? 'ok' : 'warn'}`}>{t.target_pct}% {t.met ? '달성' : '미달'}</span>}</td>
                    <td className="num">{t.manual_candidates ?? '–'} → {t.ax_candidates ?? '–'}</td>
                    <td className="num">{t.manual_n} / {t.ax_n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small">전체 단축률 <strong>{s.overall_reduction_pct == null ? '–' : `${s.overall_reduction_pct}%`}</strong>
            {' · '}만족도 <strong>{s.survey.avg_score ?? '–'}</strong>/5 ({s.survey.n}명)
            {s.survey.aspects.length > 0 && <> · {s.survey.aspects.map((a) => `${a.name} ${a.avg}`).join(' · ')}</>}</p>
          <p className="muted small">수작업과 AX 둘 다 측정한 업무만 단축률을 냅니다. 같은 기획수요로 두 방식을 재면 비교가 정확합니다.</p>
        </Card>
      )}

      <Card title="업무시간 남기기">
        <form className="stack" onSubmit={(e) => void submit(e)}>
          <div className="form-row">
            <label className="grow">어떤 일<select value={f.task_type} onChange={(e) => setF({ ...f, task_type: e.target.value as TaskType })}>
              {Object.entries(TASKS).map(([c, t]) => <option key={c} value={c}>{t.name}</option>)}
            </select></label>
            <label>방식<span className="seg">
              <button type="button" className={f.method === 'MANUAL' ? 'on' : ''} onClick={() => setF({ ...f, method: 'MANUAL' })}>수작업</button>
              <button type="button" className={f.method === 'AX' ? 'on' : ''} onClick={() => setF({ ...f, method: 'AX' })}>AX</button>
            </span></label>
            <label>재기<span className="inline">
              {startAt == null
                ? <button type="button" className="btn" onClick={() => { setStartAt(Date.now()); setNow(Date.now()) }}>▶ 시작</button>
                : <button type="button" className="btn btn-primary" onClick={stop}>■ 끝 ({fmtClock(elapsed)})</button>}
            </span></label>
          </div>
          <p className="muted small">{TASKS[f.task_type].help}</p>
          <div className="form-row">
            <label>걸린 시간(분)<input type="number" min={1} step="0.5" required value={f.minutes}
              onChange={(e) => setF({ ...f, minutes: e.target.value })} /></label>
            <label>찾은 연계 후보 수<input type="number" min={0} value={f.candidates}
              onChange={(e) => setF({ ...f, candidates: e.target.value })} /></label>
            <label className="grow">기획수요 (선택)<select value={f.demand} onChange={(e) => setF({ ...f, demand: e.target.value })}>
              <option value="">–</option>
              {(demands.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.demand_no} · {d.title}</option>)}
            </select></label>
          </div>
          <label>메모<input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} placeholder="예: PMS·DTiMS 따로 검색" /></label>
          <div><button className="btn btn-primary" disabled={busy || startAt != null}>남기기</button></div>
        </form>
        {rows.length === 0 ? <Empty>아직 남긴 측정이 없습니다.</Empty> : (
          <table className="table">
            <thead><tr><th>날짜</th><th>일</th><th>방식</th><th className="num">분</th><th className="num">후보</th><th>메모</th><th /></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="small">{r.measured_on}</td><td>{r.task_name}</td>
                  <td>{r.method === 'MANUAL' ? '수작업' : 'AX'}</td><td className="num">{r.minutes}</td>
                  <td className="num">{r.candidates_found ?? '–'}</td><td className="small">{r.note ?? ''}</td>
                  <td><button className="btn btn-sm" disabled={busy}
                    onClick={() => void run(async () => { await deleteWorkTime(r.id); await mine.reload(); await summary.reload() })}>지우기</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="써 본 느낌 (만족도)">
        <form className="stack" onSubmit={(e) => void submitSurvey(e)}>
          <div className="form-row">
            <label>전체 만족도<select value={sv.score} onChange={(e) => setSv({ ...sv, score: Number(e.target.value) })}>
              {[5, 4, 3, 2, 1].map((n) => <option key={n} value={n}>{n}점</option>)}
            </select></label>
            {Object.entries(ASPECTS).map(([k, name]) => (
              <label key={k}>{name}<select value={sv.aspects[k] ?? ''} onChange={(e) => {
                const a = { ...sv.aspects }
                if (e.target.value) a[k] = Number(e.target.value)
                else delete a[k]
                setSv({ ...sv, aspects: a })
              }}>
                <option value="">–</option>
                {[5, 4, 3, 2, 1].map((n) => <option key={n} value={n}>{n}점</option>)}
              </select></label>
            ))}
          </div>
          <label>하고 싶은 말<input value={sv.comment} onChange={(e) => setSv({ ...sv, comment: e.target.value })} /></label>
          <div><button className="btn" disabled={busy}>보내기</button></div>
        </form>
      </Card>
    </>
  )
}
