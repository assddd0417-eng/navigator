import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { decideGap, getGapFinding, type GapFindingDetail } from '../../api/gaps'
import { useAuth } from '../../auth/AuthContext'
import { SEED_USERS } from '../../auth/roles'
import { useToast } from '../../components/Toast'
import {
  Card, Empty, fmtDate, LINKAGE_HELP, PageHeader, pct100, RoleHint, useAction, useAsync,
} from '../../components/ui'
import { DEMAND_KIND, GAP_STATUS, GAP_TYPES, urgency } from './gapText'

const GapBadge = ({ status }: { status: string }) => (
  <span className={`badge badge-${GAP_STATUS[status]?.tone ?? 'muted'}`}>{GAP_STATUS[status]?.label ?? status}</span>
)

function DecisionBox({ f, onDone }: { f: GapFindingDetail; onDone: () => void }) {
  const toast = useToast()
  const { busy, run } = useAction()
  const [reason, setReason] = useState('')
  const [mode, setMode] = useState<'CONFIRM' | 'REJECT'>('CONFIRM')

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const ok = await run(() => decideGap(f.id, mode, reason.trim() || null).then(() => true))
    if (ok) {
      toast.success(mode === 'CONFIRM' ? '갭을 확정했습니다' : '갭을 기각했습니다', reason.trim() || undefined)
      onDone()
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <div className="decision-pick">
        <button type="button" className={`decision-btn decision-ADOPT ${mode === 'CONFIRM' ? 'on' : ''}`} onClick={() => setMode('CONFIRM')}>
          <strong>확정</strong><span>실제로 모자란 부분이 맞음</span></button>
        <button type="button" className={`decision-btn decision-EXCLUDE ${mode === 'REJECT' ? 'on' : ''}`} onClick={() => setMode('REJECT')}>
          <strong>기각</strong><span>이미 국내에 있거나 잘못 찾음</span></button>
      </div>
      <label>{mode === 'REJECT' ? '기각 이유 (꼭 적어 주세요)' : '의견 (선택)'}
        <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} required={mode === 'REJECT'}
          placeholder={mode === 'REJECT' ? '예: ○○ 과제에서 이미 해결됨' : '예: 수출 협상 전에 꼭 메워야 함'} /></label>
      <div className="form-foot">
        <RoleHint roles={['DEPT_REVIEWER']} />
        <button className="btn btn-primary" disabled={busy}>{busy ? '등록 중…' : mode === 'CONFIRM' ? '확정하기' : '기각하기'}</button>
      </div>
    </form>
  )
}

/** 갭 하나: 이유·가까운 국내 성과·메울 방법·출처·검수 */
export function GapDetailPage() {
  const id = Number(useParams().id)
  const { role } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const { data: f, loading, reload } = useAsync(() => getGapFinding(id), [id])
  const goBack = () => (location.key !== 'default' ? navigate(-1) : navigate('/gaps'))

  if (!Number.isInteger(id) || id <= 0) return <Empty>주소가 올바르지 않습니다. <Link to="/gaps">갭 분석 목록으로</Link></Empty>
  if (loading && !f) return <div className="page-loading">불러오는 중…</div>
  if (!f) return <Empty>이 갭을 열 수 없습니다. 새 분석으로 바뀌었거나 볼 권한이 없을 수 있습니다. <Link to="/gaps">갭 분석 목록으로</Link></Empty>
  const type = GAP_TYPES.find((g) => g.code === f.gap_type_code)
  const u = urgency(f.score)
  const items = f.detail?.items ?? []
  const decider = SEED_USERS.find((x) => x.id === f.decided_by)?.name

  return (
    <>
      <button type="button" className="link-btn back-link" onClick={goBack}>← 갭 분석 목록으로</button>
      <PageHeader title={`${f.demand_title}`}
        subtitle={`${f.region} · ${DEMAND_KIND[f.demand_kind] ?? ''} · 갭 종류: ${f.gap_type_name} (${type?.help ?? ''})`}
        actions={<><span className={`badge badge-${u.tone}`}>{u.label}</span> <GapBadge status={f.status} /></>} />

      {f.status === 'SUPERSEDED' && <div className="notice">이 갭은 더 새로운 분석 결과로 바뀌었습니다. <Link to="/gaps">최신 결과 보기</Link></div>}

      <div className="grid-2">
        <Card title="왜 갭인가요?">
          {items.length > 0 ? <ul className="plain-list">{items.map((t) => <li key={t}>{t}</li>)}</ul> : <p>{f.summary}</p>}
          {f.best_similarity != null && (
            <p className="muted small">가장 비슷한 국내 성과와 내용이 겹치는 정도: {pct100(f.best_similarity)}</p>
          )}
          {(f.detail?.unchecked?.length ?? 0) > 0 && (
            <p className="muted small">자료가 없어 비교하지 못한 항목: {f.detail.unchecked!.join(', ')}</p>
          )}
        </Card>

        <Card title="이렇게 메울 수 있어요">
          {f.pathways.length === 0 ? <Empty>제안된 방법이 없습니다.</Empty> : (
            <ul className="evidence">
              {f.pathways.map((p) => (
                <li key={p.id}>
                  <div className="evidence-src">
                    <span className={`pill linkage-${p.linkage_type_code ?? 'NEW'}`}>{p.linkage_name}</span>
                    {p.linkage_type_code && <span className="muted small"> {LINKAGE_HELP[p.linkage_type_code]}</span>}
                  </div>
                  <p>{p.description}</p>
                </li>
              ))}
            </ul>
          )}
          {role === 'PLANNER' && <p className="muted small">새 과제로 이어 가려면 <Link to="/projects?new=1">기획수요로 등록</Link>한 뒤 AI 추천을 받아 보세요.</p>}
        </Card>
      </div>

      <div className="grid-2">
        <Card title={`비교한 국내 성과 ${f.cards.length}건`}>
          {f.cards.length === 0 ? <Empty>비슷한 국내 성과가 없습니다.</Empty> : (
            <table className="table">
              <thead><tr><th>국내 성과</th><th>기술 성숙도</th><th>겹치는 정도</th></tr></thead>
              <tbody>
                {f.cards.map((c) => (
                  <tr key={c.card_id}>
                    <td>{c.title}{c.project_title && <div className="muted small">{c.project_title}</div>}
                      {c.note && <div className="small warn-text">{c.note}</div>}</td>
                    <td>{c.trl == null ? '–' : `${c.trl}단계`}</td>
                    <td>{pct100(c.similarity)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="해외 자료 출처">
          {f.sources.length === 0 ? <Empty>출처 정보가 없습니다.</Empty> : (
            <ul className="evidence">
              {f.sources.map((s) => (
                <li key={s.source_no}>
                  <div className="evidence-src">{s.is_primary && <span className="pill">주 출처</span>} {s.issuer}</div>
                  <div>{s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.title} ↗</a> : s.title}</div>
                  {s.license_note && <div className="muted small">이용 조건: {s.license_note}</div>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title={f.status === 'DRAFT' ? '검수: 확정 또는 기각' : '검수 결과'}>
        {f.status === 'DRAFT' ? <DecisionBox f={f} onDone={() => void reload()} /> : f.status === 'SUPERSEDED' ? (
          <Empty>새 분석 결과에서 다시 검수해 주세요.</Empty>
        ) : (
          <div className="final">
            <GapBadge status={f.status} /> {decider ?? '검수자'}
            <span className="muted small"> · {fmtDate(f.decided_at)}</span>
            {f.decision_reason && <p>{f.decision_reason}</p>}
          </div>
        )}
      </Card>
    </>
  )
}
