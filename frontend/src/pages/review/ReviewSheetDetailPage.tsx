import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  addMeetingDecision, attachSheet, createDraft, downloadDraftMd, downloadSheetXlsx, finalizeSheet, getDraft, getMeeting,
  getSheet, listMeetings, removeSheetItem, setDecisionStatus, setDraftStatus, type MeetingDecision,
} from '../../api/reviewSheets'
import { useAuth } from '../../auth/AuthContext'
import { SimpleMarkdown } from '../../components/SimpleMarkdown'
import { useToast } from '../../components/Toast'
import { Card, DEPT_NAMES, Empty, fmtDate, LINKAGE_HELP, PageHeader, RoleHint, score, useAction, useAsync } from '../../components/ui'

const DECISION_STATUS: Record<MeetingDecision['status'], string> = { OPEN: '진행', DONE: '완료', DROPPED: '취소' }
const DRAFT_STATUS: Record<string, string> = { DRAFT: '초안', REVIEWED: '검토함', FINAL: '최종' }
const tone = (code: string | null) => (code === 'ADOPT' ? 'ok' : code === 'HOLD' ? 'warn' : code === 'EXCLUDE' ? 'bad' : 'muted')

/** 이어달리기 후보 검토표 한 건: 후보 표 · 확정 · 엑셀 · 통합기획 자료 초안 · 회의 결정 */
export function ReviewSheetDetailPage() {
  const id = Number(useParams().id)
  const toast = useToast()
  const { role } = useAuth()
  const { busy, run } = useAction()
  const sheet = useAsync(() => getSheet(id), [id])
  const meetings = useAsync(listMeetings, [])
  const meetingId = sheet.data?.meeting_id ?? null
  const meeting = useAsync(async () => (meetingId ? getMeeting(meetingId) : null), [meetingId])
  const [draftId, setDraftId] = useState<number | null>(null)
  const latestDraft = draftId ?? sheet.data?.drafts[0]?.id ?? null
  const draft = useAsync(async () => (latestDraft ? getDraft(latestDraft) : null), [latestDraft])
  const [dec, setDec] = useState({ decision: '', recommendation_id: '', follow_up_action: '', owner_dept_id: '', due_date: '' })

  const s = sheet.data
  if (sheet.loading && !s) return <div className="page-loading">불러오는 중…</div>
  if (!s) return <Empty>검토표를 볼 수 없습니다. 없거나 내 열람 등급 밖의 자료입니다.</Empty>
  const editable = s.status === 'DRAFT'
  const isPlanner = role === 'PLANNER'

  const act = async (fn: () => Promise<unknown>, title: string, body?: string) => {
    const ok = await run(async () => { await fn(); return true })
    if (ok) {
      toast.success(title, body)
      void sheet.reload()
      void meeting.reload()
    }
    return ok
  }

  const makeDraft = async () => {
    const res = await run(() => createDraft(id))
    if (!res) return
    toast.success('통합기획 자료 초안을 만들었습니다', '후보 요약·후보별 내용·회의 상정 사항·원문 근거가 들어 있습니다.')
    setDraftId(res.id)
    void sheet.reload()
  }

  const submitDecision = async (e: FormEvent) => {
    e.preventDefault()
    if (!meetingId) return
    const ok = await act(() => addMeetingDecision(meetingId, {
      decision: dec.decision, recommendation_id: dec.recommendation_id ? Number(dec.recommendation_id) : null,
      follow_up_action: dec.follow_up_action || undefined, owner_dept_id: dec.owner_dept_id ? Number(dec.owner_dept_id) : null,
      due_date: dec.due_date || null }), '회의 결정을 기록했습니다')
    if (ok) setDec({ decision: '', recommendation_id: '', follow_up_action: '', owner_dept_id: '', due_date: '' })
  }

  const sm = s.summary
  return (
    <>
      <PageHeader title={s.title}
        subtitle={`${s.scope_name}${s.department_name ? ` · ${s.department_name}` : ''} · ${s.created_by_name ?? ''} 작성 ${fmtDate(s.created_at)}`
          + (s.finalized_at ? ` · ${s.finalized_by_name} 확정 ${fmtDate(s.finalized_at)}` : '')}
        actions={<>
          <Link to="/review-sheets" className="btn btn-ghost">← 목록</Link>
          <button className="btn" disabled={busy} onClick={() => void run(() => downloadSheetXlsx(id))}>⬇ 엑셀로 받기</button>
          {editable && <button className="btn btn-primary" disabled={busy}
            onClick={() => void act(() => finalizeSheet(id), '검토표를 확정했습니다', '이제 후보를 빼거나 바꿀 수 없습니다.')}>
            검토표 확정</button>}
        </>} />

      <div className="kpi-row">
        <div className="kpi"><div className="kpi-label">후보</div><div className="kpi-value">{sm.candidates}</div>
          <div className="kpi-target">{Object.entries(sm.by_linkage_type).map(([k, v]) => `${k} ${v}`).join(' · ')}</div></div>
        <div className="kpi"><div className="kpi-label">담당부서 최종 검토율</div>
          <div className="kpi-value">{sm.final_review_rate_pct}%</div><div className="kpi-target">목표 100% · 판정 {sm.decided}건</div></div>
        <div className="kpi"><div className="kpi-label">채택</div><div className="kpi-value">{sm.adopted}</div>
          <div className="kpi-target">후속 기획으로 넘어갈 후보</div></div>
        <div className="kpi"><div className="kpi-label">원문 근거 연결</div>
          <div className="kpi-value">{sm.candidates ? Math.round((sm.evidence_linked * 100) / sm.candidates) : 0}%</div>
          <div className="kpi-target">목표 100%</div></div>
      </div>

      <Card title="이어달리기 후보" actions={editable ? <RoleHint roles={['PLANNER']} /> : <span className="badge badge-ok">확정됨</span>}>
        {s.items.length === 0 ? <Empty>볼 수 있는 후보가 없습니다.</Empty> : (
          <div className="table-scroll">
            <table className="table rs-table">
              <thead><tr><th>#</th><th>기존 성과</th><th>연계 대상</th><th>연계유형</th><th className="num">점수</th>
                <th>연계이유·원문 근거</th><th>담당부서</th><th>검토 상태</th>{editable && <th />}</tr></thead>
              <tbody>
                {s.items.map((it, n) => {
                  const sn = it.snapshot
                  const lv = it.live
                  return (
                    <tr key={it.recommendation_id}>
                      <td>{n + 1}</td>
                      <td>{sn.source_cards.map((c) => (
                        <div key={c.card_id}><strong>{c.title}</strong>
                          <div className="muted small">{c.project_no} · {c.department ?? ''}{c.project_status === 'COMPLETED' ? ' · 종료' : ''}</div></div>
                      ))}</td>
                      <td>{sn.demand_title ?? sn.target_program_name ?? '–'}</td>
                      <td title={LINKAGE_HELP[sn.linkage_type_code]}>{lv.final_linkage_type_name && lv.final_linkage_type_name !== sn.linkage_type_name
                        ? <>{lv.final_linkage_type_name}<div className="muted small">추천 {sn.linkage_type_name}</div></>
                        : sn.linkage_type_name}</td>
                      <td className="num">{score(sn.total_score)}</td>
                      <td className="rs-why">
                        <div>{sn.rationale}</div>
                        {sn.development_needs && <div className="small"><strong>개발 필요:</strong> {sn.development_needs}</div>}
                        {sn.evidence.map((e) => (
                          <div key={e.evidence_id} className="muted small">📄 {e.document_title}{e.page_start ? ` p.${e.page_start}` : ''}: “{e.quote}”</div>
                        ))}
                        {sn.open_confirmations > 0 && <span className="badge badge-warn">확인 필요 {sn.open_confirmations}</span>}
                      </td>
                      <td>{sn.owner_departments.join(', ') || '미지정'}
                        {sn.collab_departments.length > 0 && <div className="muted small">협업 {sn.collab_departments.join(', ')}</div>}</td>
                      <td>
                        <Link to={`/recommendations/${it.recommendation_id}`}>
                          <span className={`badge badge-${tone(lv.final_decision_code)}`}>{lv.final_decision_name ?? lv.status_name}</span></Link>
                        {lv.final_decision?.opinion && <div className="muted small">{lv.final_decision.opinion}</div>}
                      </td>
                      {editable && <td><button className="btn btn-ghost" disabled={busy || !isPlanner} title="이 후보 빼기"
                        onClick={() => void act(() => removeSheetItem(id, it.recommendation_id), '후보를 뺐습니다')}>빼기</button></td>}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted small">후보 내용은 검토표를 만든 때의 추천 그대로이고, 검토 상태는 지금 상태입니다. 상태를 누르면 추천 상세에서 판정할 수 있습니다.</p>
      </Card>

      <Card title="통합기획 자료 초안" actions={<>
        {s.drafts.length > 1 && <select value={latestDraft ?? ''} onChange={(e) => setDraftId(Number(e.target.value))}>
          {s.drafts.map((d) => <option key={d.id} value={d.id}>{d.version}판 · {fmtDate(d.created_at)}</option>)}
        </select>}
        <button className="btn btn-primary" disabled={busy} onClick={() => void makeDraft()}>
          {s.drafts.length ? '새로 만들기 (판 올림)' : '초안 만들기'}</button>
        <RoleHint roles={['PLANNER']} /></>}>
        {!draft.data ? <Empty>검토표 내용으로 회의 자료 초안을 만듭니다. 연계이유는 추천에 붙은 문장을 그대로 쓰고, 원문 근거를 각주로 답니다.</Empty> : (
          <>
            <div className="rs-draft-head">
              <span className="badge badge-info">{draft.data.version}판</span>
              <span className="badge badge-muted">{DRAFT_STATUS[draft.data.status]}</span>
              <span className="muted small">원문 근거 {draft.data.evidence_count}건 · {fmtDate(draft.data.created_at)}</span>
              <span className="grow" />
              {draft.data.status === 'DRAFT' && <button className="btn btn-ghost" disabled={busy}
                onClick={() => void run(async () => { await setDraftStatus(draft.data!.id, 'REVIEWED'); await draft.reload() })}>검토함으로 표시</button>}
              <button className="btn" disabled={busy} onClick={() => void run(() => downloadDraftMd(draft.data!.id))}>⬇ 문서 파일로 받기</button>
            </div>
            <div className="rs-draft"><SimpleMarkdown text={draft.data.content_md} /></div>
          </>
        )}
      </Card>

      <Card title="통합기획 회의 결정·후속조치">
        {!meetingId ? (
          <div className="form-row">
            <label className="grow">이 검토표를 올릴 회의<select defaultValue="" disabled={busy}
              onChange={(e) => e.target.value && void act(() => attachSheet(id, Number(e.target.value)), '회의에 올렸습니다')}>
              <option value="">회의 고르기…</option>
              {(meetings.data ?? []).filter((m) => m.status !== 'CANCELLED').map((m) => <option key={m.id} value={m.id}>{m.title}</option>)}
            </select></label>
            <p className="muted small">회의가 없으면 ‘통합기획 검토’ 목록 화면에서 먼저 만듭니다.</p>
          </div>
        ) : (
          <>
            <p><strong>{meeting.data?.title}</strong> <span className="muted small">
              {meeting.data?.held_at ? new Date(meeting.data.held_at).toLocaleDateString('ko-KR') : '날짜 미정'}
              {meeting.data?.departments.length ? ` · 참석 ${meeting.data.departments.map((d) => d.name).join(', ')}` : ''}</span></p>
            {(meeting.data?.decisions ?? []).length === 0 ? <Empty>아직 기록한 결정이 없습니다.</Empty> : (
              <table className="table">
                <thead><tr><th>결정</th><th>대상 후보</th><th>후속조치</th><th>담당</th><th>기한</th><th>상태</th></tr></thead>
                <tbody>
                  {meeting.data!.decisions.map((d) => {
                    const idx = s.items.findIndex((i) => i.recommendation_id === d.recommendation_id)
                    return (
                      <tr key={d.id}>
                        <td>{d.decision}</td>
                        <td>{d.recommendation_id ? (idx >= 0 ? `${idx + 1}번` : '다른 검토표') : '–'}</td>
                        <td>{d.follow_up_action ?? '–'}</td>
                        <td>{d.owner_dept_name ?? '–'}</td>
                        <td>{d.due_date ?? '–'}</td>
                        <td><select value={d.status} disabled={busy}
                          onChange={(e) => void act(() => setDecisionStatus(d.id, e.target.value as MeetingDecision['status']), '후속조치 상태를 바꿨습니다')}>
                          {Object.entries(DECISION_STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                        </select></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
            <form className="stack rs-decision-form" onSubmit={(e) => void submitDecision(e)}>
              <div className="form-row">
                <label className="grow">결정 내용<input value={dec.decision} required minLength={2}
                  onChange={(e) => setDec({ ...dec, decision: e.target.value })} placeholder="예: 후속 과제로 기획 착수" /></label>
                <label>대상 후보<select value={dec.recommendation_id} onChange={(e) => setDec({ ...dec, recommendation_id: e.target.value })}>
                  <option value="">전체·기타</option>
                  {s.items.map((i, n) => <option key={i.recommendation_id} value={i.recommendation_id}>{n + 1}번 {i.snapshot.source_cards[0]?.title}</option>)}
                </select></label>
              </div>
              <div className="form-row">
                <label className="grow">후속조치<input value={dec.follow_up_action} onChange={(e) => setDec({ ...dec, follow_up_action: e.target.value })}
                  placeholder="예: 기획서 초안 작성" /></label>
                <label>담당 부서<select value={dec.owner_dept_id} onChange={(e) => setDec({ ...dec, owner_dept_id: e.target.value })}>
                  <option value="">–</option>
                  {Object.entries(DEPT_NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select></label>
                <label>기한<input type="date" value={dec.due_date} onChange={(e) => setDec({ ...dec, due_date: e.target.value })} /></label>
              </div>
              <div><button className="btn" disabled={busy}>결정 기록</button> <RoleHint roles={['PLANNER']} /></div>
            </form>
            <p className="muted small">회의 결정은 후속조치 기록입니다. 후보의 채택·보류·제외 판정은 담당부서 검수자가 추천 상세에서 합니다.</p>
          </>
        )}
      </Card>
    </>
  )
}
