import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  downloadPortfolioXlsx, getPolicyActions, getPortfolioAreas, getPortfolioDomestic, getPortfolioOverview,
  handOffToDemand, type Direction, type PolicyAction,
} from '../../api/portfolio'
import { useAuth } from '../../auth/AuthContext'
import { canAccessPath } from '../../auth/roles'
import { useToast } from '../../components/Toast'
import { Card, Empty, PageHeader, RoleHint, Steps, useAction, useAsync } from '../../components/ui'
import { GAP_STATUS, GAP_TYPES, urgency } from '../gaps/gapText'

/** 대응 방향 (backend portfolio.DIRECTIONS 와 같은 묶음·순서) */
const DIRECTIONS: { code: Direction; name: string; help: string }[] = [
  { code: 'NEW_PROJECT', name: '신규 과제 기획', help: '공백: 국내에 비슷한 성과가 없어 새 과제가 필요함' },
  { code: 'FOLLOW_UP', name: '후속·고도화 과제', help: '성능미달: 있는 성과를 요구 성능까지 끌어올림' },
  { code: 'LOCALIZATION', name: '국산화·현지화 사업', help: '국산화·현지화: 해외 부품 대체, 수출국 현지 생산·정비 대응' },
  { code: 'PILOT', name: '시험·실증', help: '성숙도부족: 성숙도를 올리고 남은 숙제를 푸는 시험·실증' },
]

/** 건수 → 칸 진하기 (0 = 비움) */
const heat = (n: number) => (n <= 0 ? '' : n === 1 ? 'heat-1' : n === 2 ? 'heat-2' : 'heat-3')

/**
 * 기관 포트폴리오 (기관용): 전국 R&D 성과와 해외 수요를 견줘 갭이 몰린 분야와 메울 사업 방향을 보여 준다.
 * 상태(?draft=1 검수 전 포함, ?area= 분야)는 주소에 남겨 새로고침·뒤로가기 때 유지한다.
 */
export function PortfolioPage() {
  const toast = useToast()
  const navigate = useNavigate()
  const { role } = useAuth()
  const [params, setParams] = useSearchParams()
  const includeDraft = params.get('draft') === '1'
  const area = params.get('area')
  const { busy, run } = useAction()

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value == null) next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: true })
  }

  const top = useAsync(async () => {
    const [overview, areas, domestic] = await Promise.all([
      getPortfolioOverview(), getPortfolioAreas(includeDraft), getPortfolioDomestic()])
    return { overview, areas, domestic }
  }, [includeDraft])
  const actions = useAsync(() => getPolicyActions(includeDraft, area), [includeDraft, area])

  const handOff = async (a: PolicyAction) => {
    const res = await run(() => handOffToDemand(a.finding_id))
    if (!res) return
    toast.success(res.created ? '신규 기획수요로 넘겼습니다' : '이미 넘긴 갭입니다',
      `${res.demand_no} · 연계 후보 찾기 화면에서 AI 추천을 바로 돌릴 수 있습니다.`)
    navigate(`/projects?demand=${res.demand_id}`)
  }

  const download = async () => {
    const ok = await run(async () => { await downloadPortfolioXlsx(includeDraft); return true })
    if (ok) toast.success('엑셀을 내려받았습니다', '분야별 대조 · 국내 성과 분포 · 기획 후보 시트가 들어 있습니다.')
  }

  const ov = top.data?.overview
  const areas = top.data?.areas ?? []
  const domestic = top.data?.domestic ?? []
  const list = actions.data ?? []
  const canOpenDemand = canAccessPath(role, '/projects')

  return (
    <>
      <PageHeader title="기관 포트폴리오"
        subtitle="전국 국방 R&D 성과가 어느 분야에 쌓여 있는지, 해외 수요와 견줘 어디가 비었는지, 그래서 어떤 사업을 기획하면 되는지 한 화면에 모았습니다."
        actions={<button className="btn" disabled={busy} onClick={() => void download()}>⬇ 엑셀로 받기</button>} />
      <Steps items={[
        '위 숫자와 분야별 대조표에서 갭이 몰린 분야를 찾습니다. 칸이 진할수록 갭이 많습니다.',
        '분야를 누르면 아래 ‘정책·예산 기획 후보’가 그 분야로 좁혀집니다.',
        '확정된 갭은 기획자가 ‘신규 기획수요로 넘기기’를 눌러 바로 과제 기획을 시작할 수 있습니다.',
      ]} />

      <div className="kpi-row">
        <div className="kpi"><div className="kpi-label">국내 성과 카드 (발행)</div>
          <div className="kpi-value">{ov?.cards_published ?? '–'}</div><div className="kpi-target">검수를 마친 성과</div></div>
        <div className="kpi"><div className="kpi-label">해외 수요</div>
          <div className="kpi-value">{ov?.overseas_demands ?? '–'}</div><div className="kpi-target">공식 기관 자료에서 정리</div></div>
        <div className="kpi"><div className="kpi-label">열린 갭</div>
          <div className="kpi-value">{ov ? ov.gaps_confirmed : '–'}<span className="kpi-sub"> 확정</span></div>
          <div className="kpi-target">검수 전 {ov?.gaps_draft ?? '–'}건 더 있음</div></div>
        <div className="kpi"><div className="kpi-label">기획수요로 넘긴 갭</div>
          <div className="kpi-value">{ov?.handed_off ?? '–'}</div><div className="kpi-target">과제 기획이 시작된 갭</div></div>
      </div>

      <Card title="분야별 대조표 (해외 수요 기술분류 기준)"
        actions={
          <div className="seg">
            <button className={!includeDraft ? 'on' : ''} onClick={() => setParam('draft', null)}>확정된 갭만</button>
            <button className={includeDraft ? 'on' : ''} onClick={() => setParam('draft', '1')}>검수 전 포함</button>
          </div>
        }>
        {top.loading && !top.data ? <div className="page-loading">불러오는 중…</div> : areas.length === 0 ? (
          <Empty>등록된 해외 수요가 없습니다. 해외 수요 자료를 올리면 자동으로 비교합니다.</Empty>
        ) : (
          <div className="table-scroll">
            <table className="table pf-matrix">
              <thead>
                <tr>
                  <th>기술분류</th><th className="num">해외 수요</th><th className="num">갭 있는 수요</th>
                  {GAP_TYPES.map((g) => <th key={g.code} className="num" title={g.help}>{g.name}</th>)}
                  <th className="num" title="갭의 근거로 묶인 국내 성과 카드 수">근거 국내 성과</th><th>가장 급한 갭</th>
                </tr>
              </thead>
              <tbody>
                {areas.map((a) => (
                  <tr key={a.area} className={`pf-row ${area === a.area ? 'pf-row-on' : ''}`}
                    onClick={() => setParam('area', area === a.area ? null : a.area)} title="누르면 아래 기획 후보를 이 분야로 좁힙니다">
                    <td><strong>{a.area}</strong></td>
                    <td className="num">{a.demand_count}</td>
                    <td className="num">{a.demands_with_gap}</td>
                    {GAP_TYPES.map((g) => (
                      <td key={g.code} className={`num pf-heat ${heat(a.by_type[g.code])}`}>{a.by_type[g.code] || '–'}</td>
                    ))}
                    <td className="num">{a.card_count}</td>
                    <td>{a.max_score == null ? <span className="muted">갭 없음</span> : (
                      <span className={`badge badge-${urgency(a.max_score).tone}`}>{urgency(a.max_score).label}</span>)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="국내 성과 분포 (무기체계별)">
        {top.loading && !top.data ? <div className="page-loading">불러오는 중…</div> : domestic.length === 0 ? (
          <Empty>발행된 국내 성과 카드가 없습니다.</Empty>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr><th>무기체계</th><th className="num">성과 카드</th><th className="num">평균 기술성숙도</th>
                  <th className="num">성숙도 7 이상</th><th className="num">미해결 과제</th><th>해외 수요와 연결</th></tr>
              </thead>
              <tbody>
                {domestic.map((d) => (
                  <tr key={d.weapon_system}>
                    <td>{d.weapon_system}</td>
                    <td className="num">{d.card_count}</td>
                    <td className="num">{d.avg_trl == null ? '–' : `${d.avg_trl}단계`}</td>
                    <td className="num">{d.mature_count}</td>
                    <td className="num">{d.open_issue_count}</td>
                    <td>{d.linked_demand_count > 0
                      ? <span>해외 수요 {d.linked_demand_count}건 · 갭 {d.linked_gap_count}건</span>
                      : <span className="badge badge-muted" title="국내 성과는 있으나 아직 확인된 해외 수요가 없음 (수출·활용 발굴 후보)">해외 수요 확인 안 됨</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title={`정책·예산 기획 후보${area ? ` · ${area}` : ''} (${list.length}건)`}
        actions={<>{area && <button className="btn btn-ghost" onClick={() => setParam('area', null)}>분야 거르기 풀기 ✕</button>}
          <RoleHint roles={['PLANNER']} /></>}>
        {actions.loading && !actions.data ? <div className="page-loading">불러오는 중…</div> : list.length === 0 ? (
          <Empty>{includeDraft ? '열려 있는 갭이 없습니다.'
            : '확정된 갭이 아직 없습니다. 위에서 ‘검수 전 포함’을 누르면 검수를 기다리는 갭도 볼 수 있습니다.'}</Empty>
        ) : DIRECTIONS.map((dir) => {
          const rows = list.filter((a) => a.direction === dir.code)
          if (rows.length === 0) return null
          return (
            <section key={dir.code} className="pf-group">
              <h4 className="pf-group-title">{dir.name} <span className="muted small">{rows.length}건 · {dir.help}</span></h4>
              <ul className="gap-list">
                {rows.map((a) => {
                  const u = urgency(a.score)
                  const st = GAP_STATUS[a.status]
                  return (
                    <li key={a.finding_id} className="pf-item">
                      <div className="gap-item-head">
                        <span className={`gap-chip gap-${a.gap_type_code}`}>{a.gap_type_name}</span>
                        <strong>{a.demand_title}</strong>
                        <span className="muted small">{a.region}{a.target_period ? ` · ${a.target_period}` : ''}</span>
                        <span className="gap-item-right"><span className={`badge badge-${u.tone}`}>{u.label}</span>{' '}
                          <span className={`badge badge-${st?.tone ?? 'muted'}`}>{st?.label ?? a.status}</span></span>
                      </div>
                      <p className="gap-summary">{a.summary}</p>
                      <dl className="pf-facts">
                        <dt>이어 갈 국내 성과</dt>
                        <dd>{a.cards.length ? a.cards.map((c) => c.title).join(', ') : '없음 (새로 개발)'}</dd>
                        {a.pathways[0] && <><dt>제안 경로</dt><dd><strong>{a.pathways[0].linkage_name}</strong> — {a.pathways[0].description}</dd></>}
                        <dt>소관부서</dt><dd>{a.departments.length ? a.departments.join(', ') : '–'}</dd>
                      </dl>
                      <div className="pf-actions">
                        <Link to={`/gaps/${a.finding_id}`} className="btn btn-ghost">상세 보기</Link>
                        {a.planning_demand_id ? (
                          canOpenDemand
                            ? <Link to={`/projects?demand=${a.planning_demand_id}`} className="btn">기획수요 {a.planning_demand_no} 보기 →</Link>
                            : <span className="badge badge-ok">기획수요 {a.planning_demand_no}로 넘김</span>
                        ) : a.status === 'CONFIRMED' ? (
                          <button className="btn btn-primary" disabled={busy} onClick={() => void handOff(a)}>신규 기획수요로 넘기기</button>
                        ) : (
                          <span className="muted small">검수자가 확정하면 기획수요로 넘길 수 있습니다</span>
                        )}
                      </div>
                    </li>
                  )
                })}
              </ul>
            </section>
          )
        })}
      </Card>
      <p className="muted small">숫자와 목록은 내 열람 등급 안에서 집계한 값입니다. 예산 금액은 과제 예산 자료가 들어오면 함께 보여 줄 예정입니다.</p>
    </>
  )
}
