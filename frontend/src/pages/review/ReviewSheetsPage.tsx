import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { listDemands } from '../../api/endpoints'
import {
  createMeeting, createSheet, listMeetings, listSheets, SCOPES, type SheetScope,
} from '../../api/reviewSheets'
import { useToast } from '../../components/Toast'
import { Card, DEPT_NAMES, Empty, fmtDate, PageHeader, RoleHint, Steps, useAction, useAsync } from '../../components/ui'

const MEETING_STATUS: Record<string, string> = { SCHEDULED: '예정', HELD: '열림', CANCELLED: '취소' }

/**
 * 통합기획 검토 (기획자·담당부서 검수자): AI 추천을 부서별 '이어달리기 후보 검토표'로 묶고,
 * 통합기획 회의에 올려 결정·후속조치를 남긴다. 만들기는 기획자만 (서버가 판단).
 */
export function ReviewSheetsPage() {
  const toast = useToast()
  const navigate = useNavigate()
  const { busy, run } = useAction()
  const sheets = useAsync(listSheets, [])
  const meetings = useAsync(listMeetings, [])
  const demands = useAsync(listDemands, [])

  const [scope, setScope] = useState<SheetScope>('CUSTOM')
  const [dept, setDept] = useState('')
  const [demand, setDemand] = useState('')
  const [meeting, setMeeting] = useState('')
  const [perTarget, setPerTarget] = useState(5)
  const [mTitle, setMTitle] = useState('')
  const [mDate, setMDate] = useState('')
  const [mDepts, setMDepts] = useState<number[]>([])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const res = await run(() => createSheet({
      sheet_scope: scope, department_id: dept ? Number(dept) : null, demand_id: demand ? Number(demand) : null,
      meeting_id: meeting ? Number(meeting) : null, per_target: perTarget }))
    if (!res) return
    toast.success('검토표를 만들었습니다', '후보별 근거·담당부서·검토 상태가 함께 들어 있습니다.')
    navigate(`/review-sheets/${res.id}`)
  }

  const submitMeeting = async (e: FormEvent) => {
    e.preventDefault()
    const res = await run(() => createMeeting({ title: mTitle, held_at: mDate ? `${mDate}T10:00:00+09:00` : null,
      department_ids: mDepts }))
    if (!res) return
    toast.success('통합기획 회의를 만들었습니다', '검토표를 만들 때 이 회의를 고르면 회의 자료로 묶입니다.')
    setMTitle('')
    setMDate('')
    setMDepts([])
    void meetings.reload()
  }

  const list = sheets.data ?? []
  const mlist = meetings.data ?? []
  const scopeHelp = SCOPES.find((s) => s.code === scope)?.help

  return (
    <>
      <PageHeader title="통합기획 검토"
        subtitle="AI가 찾은 이어달리기 후보를 부서별 검토표로 묶고, 통합기획 회의 자료 초안까지 만듭니다. 사업 추진 여부는 담당부서와 회의가 정합니다." />
      <Steps items={[
        '‘연계 후보 찾기’에서 기획수요마다 AI 추천을 먼저 받아 둡니다.',
        '아래에서 범위와 부서를 골라 검토표를 만듭니다. 후보·연계유형·원문 근거·담당부서·판정이 한 표에 모입니다.',
        '검토표에서 통합기획 자료 초안을 만들고, 회의 결정과 후속조치를 기록합니다.',
      ]} />

      <Card title="검토표 만들기" actions={<RoleHint roles={['PLANNER']} />}>
        <form className="stack" onSubmit={(e) => void submit(e)}>
          <div className="form-row">
            <label>범위<select value={scope} onChange={(e) => setScope(e.target.value as SheetScope)}>
              {SCOPES.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
            </select></label>
            <label>대상 부서<select value={dept} onChange={(e) => setDept(e.target.value)}>
              <option value="">전체 부서</option>
              {Object.entries(DEPT_NAMES).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
            </select></label>
            <label className="grow">기획수요{scope === 'DEMAND' ? ' (필수)' : ' (선택)'}
              <select value={demand} onChange={(e) => setDemand(e.target.value)} required={scope === 'DEMAND'}>
                <option value="">모든 기획수요</option>
                {(demands.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.demand_no} · {d.title}</option>)}
              </select></label>
          </div>
          <div className="form-row">
            <label>수요마다 상위 몇 건<input type="number" min={1} max={20} value={perTarget}
              onChange={(e) => setPerTarget(Number(e.target.value) || 5)} /></label>
            <label className="grow">통합기획 회의 (선택)<select value={meeting} onChange={(e) => setMeeting(e.target.value)}>
              <option value="">아직 안 정함</option>
              {mlist.filter((m) => m.status !== 'CANCELLED').map((m) => <option key={m.id} value={m.id}>{m.title}</option>)}
            </select></label>
          </div>
          <p className="muted small">{scopeHelp}. 내 열람 등급으로 볼 수 있는 추천만 들어갑니다.</p>
          <div><button className="btn btn-primary" disabled={busy}>검토표 만들기</button></div>
        </form>
      </Card>

      <Card title={`검토표 (${list.length}건)`}>
        {sheets.loading && !sheets.data ? <div className="page-loading">불러오는 중…</div> : list.length === 0 ? (
          <Empty>아직 만든 검토표가 없습니다.</Empty>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead><tr><th>검토표</th><th>범위</th><th>부서</th><th className="num">후보</th>
                <th className="num">최종 검토</th><th>회의</th><th>상태</th><th>만든 때</th></tr></thead>
              <tbody>
                {list.map((s) => (
                  <tr key={s.id}>
                    <td><Link to={`/review-sheets/${s.id}`}><strong>{s.title}</strong></Link></td>
                    <td>{SCOPES.find((x) => x.code === s.sheet_scope)?.name}</td>
                    <td>{s.department_name ?? '전체'}</td>
                    <td className="num">{s.item_count}</td>
                    <td className="num">{s.decided_count}/{s.item_count}</td>
                    <td>{s.meeting_title ?? <span className="muted">–</span>}</td>
                    <td><span className={`badge badge-${s.status === 'FINALIZED' ? 'ok' : 'muted'}`}>
                      {s.status === 'FINALIZED' ? '확정' : '작성 중'}</span></td>
                    <td className="small">{fmtDate(s.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="통합기획 회의" actions={<RoleHint roles={['PLANNER']} />}>
        <form className="form-row" onSubmit={(e) => void submitMeeting(e)}>
          <label className="grow">회의 이름<input value={mTitle} onChange={(e) => setMTitle(e.target.value)} required
            minLength={2} placeholder="예: 12월 통합기획 회의" /></label>
          <label>날짜<input type="date" value={mDate} onChange={(e) => setMDate(e.target.value)} /></label>
          <fieldset className="inline-checks"><legend>참석 부서</legend>
            {Object.entries(DEPT_NAMES).map(([id, name]) => (
              <label key={id} className="check"><input type="checkbox" checked={mDepts.includes(Number(id))}
                onChange={(e) => setMDepts(e.target.checked ? [...mDepts, Number(id)] : mDepts.filter((x) => x !== Number(id)))} />
                {name}</label>
            ))}
          </fieldset>
          <div className="form-end"><button className="btn" disabled={busy}>회의 만들기</button></div>
        </form>
        {mlist.length === 0 ? <Empty>등록된 회의가 없습니다.</Empty> : (
          <table className="table">
            <thead><tr><th>회의</th><th>날짜</th><th>주관</th><th className="num">검토표</th>
              <th className="num">결정</th><th className="num">진행 중 후속조치</th><th>상태</th></tr></thead>
            <tbody>
              {mlist.map((m) => (
                <tr key={m.id}>
                  <td><strong>{m.title}</strong></td>
                  <td className="small">{m.held_at ? new Date(m.held_at).toLocaleDateString('ko-KR') : '미정'}</td>
                  <td>{m.host_dept_name ?? '–'}</td>
                  <td className="num">{m.sheet_count}</td>
                  <td className="num">{m.decision_count}</td>
                  <td className="num">{m.open_count}</td>
                  <td>{MEETING_STATUS[m.status]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  )
}
