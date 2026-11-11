// 가짜 백엔드: 화면 흐름 점검용 (실제 서버 규칙 중 권한 403 만 흉내)
const now = () => new Date().toISOString()
module.exports = function makeMock() {
  const users = {
    1: { id: 1, name: '기획담당', department_id: 1, clearance_code: 'SECRET', roles: ['PLANNER'] },
    2: { id: 2, name: '부서검토자', department_id: 3, clearance_code: 'SECRET', roles: ['DEPT_REVIEWER'] },
    3: { id: 3, name: '기술전문가', department_id: 2, clearance_code: 'RESTRICTED', roles: ['EXPERT'] },
    4: { id: 4, name: '카드관리자', department_id: 1, clearance_code: 'SECRET', roles: ['CURATOR'] },
  }
  const S = {
    demands: [
      { id: 1, demand_no: 'SYN-DM-D09', title: '광대역 재밍 대응 전술통신 안테나·제어기 패키지', status: 'MATCHING', required_trl_min: 5, required_trl_max: 7, target_program_id: 2, requesting_dept_id: 1, updated_at: now(), tech_need: '광대역 재밍 환경에서 전술통신 링크 유지', match_runs: [{ id: 11, status: 'SUCCEEDED', created_at: now(), finished_at: now() }] },
      { id: 2, demand_no: 'SYN-DM-D10', title: '회전익 무인기 자동 착함 영상항법', status: 'OPEN', required_trl_min: 4, required_trl_max: 6, target_program_id: 2, requesting_dept_id: 1, updated_at: now(), tech_need: '함정 갑판 자동 착함', match_runs: [] },
    ],
    recs: {}, runs: {}, cards: [
      { id: 1, card_no: 'AC-001', title: '전술통신 고속 주파수도약 송수신기', project_no: 'PRJ-2022-001', project_title: '소형 무인기용 항재밍 데이터링크', trl: 6, status: 'PUBLISHED', updated_at: now() },
      { id: 2, card_no: 'AC-002', title: '전술 배터리 열관리 모듈', project_no: 'PRJ-2021-007', project_title: '전술 배터리 열관리 기술', trl: 5, status: 'DRAFT', updated_at: now() },
    ],
    docs: [{ id: 1, doc_type_code: 'FINAL_REPORT', doc_type_name: '결과보고서', title: '항재밍 데이터링크 결과보고서', project_id: 1, owner_dept_id: 3, parse_status: 'EMBEDDED', security_code: 'PUBLIC', created_at: now(), chunk_count: 42 }],
    gapStatus: { 101: 'DRAFT', 102: 'DRAFT', 103: 'CONFIRMED' },
    nextId: 500,
  }
  const mkRec = (id, rank, run, linkage, name, sc, status) => ({
    recommendation_id: id, match_run_id: run, rank, total_score: sc, linkage_type_code: linkage, linkage_type_name: name,
    final_linkage_type_code: null, status, final_decision_code: null, is_excluded: false, demand_id: 1,
    demand_title: S.demands[0].title, target_program_name: '핵심기술개발',
    rationale: '이전 과제의 미해결 기술(광대역 재밍 시 동기 유지)이 이번 수요와 바로 이어집니다.', rationale_source: 'TEMPLATE',
    rationale_generation: { status: null, generator: null, error: null }, development_needs: '광대역 재밍 대역 확장 시험',
    source_cards: [{ card_id: 1, card_no: 'AC-001', title: rank === 1 ? '전술통신 고속 주파수도약 송수신기' : `기존 성과 ${rank}`, project_no: 'PRJ-2022-001', role: 'PRIMARY' }],
    scores: { TECH: 0.82, PERFORMANCE: 0.7, TRL: 0.9, ENVIRONMENT: 0.6, PURPOSE: 0.75 }, owner_department: '무인미래통신기술팀',
    evidence_count: 2, open_confirmations: rank === 2 ? 1 : 0, created_at: now(),
    score_details: ['TECH', 'PERFORMANCE', 'TRL', 'ENVIRONMENT', 'PURPOSE'].map((c, i) => ({ criterion: c, score: [0.82, 0.7, 0.9, 0.6, 0.75][i], weight: 0.2, method: 'x' })),
    linkage_scores: [], departments: [], companies: [], confirmations: [],
    evidence: [{ evidence_id: 1, side: 'CARD', criterion: 'TECH', quote: '광대역 재밍 환경에서 주파수 도약 동기 유지 시간이 목표의 70%에 머물러 후속 연구가 필요하다.', page_start: 88, page_end: 88, document_id: 1, document_title: '항재밍 데이터링크 결과보고서', section_no: '4.3', section_heading: '미해결 기술' }],
    assignments: status === 'GENERATED' ? [] : [{ id: id * 10, review_role: 'DEPT_OWNER', assignee_user_id: null, assignee_dept_id: 3, status: 'PENDING', due_at: now() }],
    decisions: [], comments: [],
  })
  const addRun = (runId) => {
    const recs = [mkRec(runId * 10 + 1, 1, runId, 'FOLLOW_UP', '후속형', 0.81, 'ASSIGNED'), mkRec(runId * 10 + 2, 2, runId, 'ADVANCEMENT', '고도화형', 0.58, 'ASSIGNED'), mkRec(runId * 10 + 3, 3, runId, 'CONVERGENCE', '융합형', 0.44, 'GENERATED')]
    recs.forEach((r) => (S.recs[r.recommendation_id] = r))
    S.runs[runId] = { id: runId, status: 'SUCCEEDED', demand_id: 1, created_at: now(), recommendations: recs }
  }
  addRun(11)
  const overview = (r) => { const { score_details, evidence, assignments, decisions, comments, ...o } = r; return o }
  const queue = () => Object.values(S.recs).filter((r) => ['ASSIGNED', 'IN_REVIEW', 'NEEDS_INFO'].includes(r.status)).map((r) => ({
    assignment_id: r.recommendation_id * 10, review_role: 'DEPT_OWNER', assignee_user_id: null, assignee_dept_id: 3, assignment_status: 'PENDING',
    assigned_at: now(), due_at: now(), is_overdue: r.rank === 2, recommendation_id: r.recommendation_id, linkage_type_name: r.linkage_type_name,
    total_score: r.total_score, demand_title: r.demand_title, source_cards: r.source_cards, evidence_count: r.evidence_count,
    open_confirmations: r.open_confirmations, recommendation_status: r.status }))
  const gap = (id) => ({
    id, gap_run_id: 7, overseas_demand_id: id === 103 ? 2 : 1, demand_no: 'D0' + (id - 100), demand_title: id === 103 ? '루마니아 전차 현지 정비 패키지' : '폴란드 K2PL 파워팩 변속기 내구도',
    demand_kind: id === 103 ? 'EXPORT_REQ' : 'ROADMAP', region: id === 103 ? '루마니아' : '폴란드',
    gap_type_code: { 101: 'PERFORMANCE_SHORT', 102: 'MATURITY', 103: 'LOCALIZATION' }[id], gap_type_name: { 101: '성능미달', 102: '성숙도부족', 103: '국산화·현지화' }[id],
    severity: 0.8, score: { 101: 0.72, 102: 0.41, 103: 0.3 }[id], best_similarity: 0.78, summary: '비슷한 국내 성과가 있으나 성능이 모자랍니다: K2 변속기 — 자체 목표 미달 — 내구도 306h < 320h',
    security_code: 'PUBLIC', status: S.gapStatus[id], decided_by: S.gapStatus[id] === 'DRAFT' ? null : 2, decided_at: S.gapStatus[id] === 'DRAFT' ? null : now(),
    decision_reason: S.gapStatus[id] === 'DRAFT' ? null : '확인함', maybe_resolved_at: null, created_at: now(), card_count: 1,
  })
  const deny = (uid, roles) => !roles.some((r) => users[uid]?.roles.includes(r))
  return async function handle(method, path, query, body, uid) {
    const m = (re) => path.match(re)
    if (path === '/me') return users[uid] ? [200, users[uid]] : [401, { detail: '사용자 없음' }]
    if (!users[uid]) return [401, { detail: '로그인 필요' }]
    if (path === '/kpi/recommendations') return [200, [{ match_run_id: 11, recommendations: 3, with_evidence: 3, evidence_coverage_pct: 100, finally_reviewed: 0, final_review_pct: 0, adopted: 0 }]]
    if (path === '/kpi/work-time') return [200, [{ task_type: 'RESEARCH', avg_manual_min: 120, avg_ax_min: 30, reduction_pct: 75 }]]
    if (path === '/reviews/queue') return [200, query.get('mine') === 'true' && uid !== 2 ? [] : queue()]
    if (path === '/cards' && method === 'GET') return [200, query.get('status') ? S.cards.filter((c) => c.status === query.get('status')) : S.cards]
    if (path === '/cards' && method === 'POST') { if (deny(uid, ['CURATOR', 'PLANNER'])) return [403, { detail: '필요 역할: CURATOR, PLANNER' }]; const id = ++S.nextId; S.cards.push({ id, card_no: body.card_no, title: body.title, project_no: 'PRJ-2022-001', project_title: '소형 무인기용 항재밍 데이터링크', trl: body.trl, status: 'DRAFT', updated_at: now() }); return [201, { id }] }
    if (m(/^\/cards\/(\d+)\/publish$/)) { if (deny(uid, ['CURATOR'])) return [403, { detail: '필요 역할: CURATOR' }]; S.cards.find((c) => c.id === +m(/(\d+)/)[1]).status = 'PUBLISHED'; return [204, null] }
    if (path === '/demands' && method === 'GET') return [200, S.demands]
    if (path === '/demands' && method === 'POST') { if (deny(uid, ['PLANNER'])) return [403, { detail: '필요 역할: PLANNER' }]; const id = ++S.nextId; S.demands.push({ ...body, id, status: 'OPEN', updated_at: now(), match_runs: [] }); return [201, { id }] }
    if (m(/^\/demands\/(\d+)$/)) { const d = S.demands.find((x) => x.id === +m(/(\d+)/)[1]); return d ? [200, d] : [404, { detail: '없음' }] }
    if (m(/^\/demands\/(\d+)\/match$/)) { if (deny(uid, ['PLANNER'])) return [403, { detail: '필요 역할: PLANNER' }]; const d = S.demands.find((x) => x.id === +m(/(\d+)/)[1]); const id = ++S.nextId; addRun(id); S.runs[id].demand_id = d.id; d.match_runs.unshift({ id, status: 'SUCCEEDED', created_at: now(), finished_at: now() }); d.status = 'MATCHING'; return [201, { id }] }
    if (m(/^\/match-runs\/(\d+)$/)) { const r = S.runs[+m(/(\d+)/)[1]]; return r ? [200, { ...r, recommendations: r.recommendations.map((x) => overview(S.recs[x.recommendation_id])) }] : [404, { detail: '없음' }] }
    if (m(/^\/recommendations\/(\d+)$/)) { const r = S.recs[+m(/(\d+)/)[1]]; return r ? [200, r] : [404, { detail: '없음' }] }
    if (m(/^\/recommendations\/(\d+)\/history$/)) return [200, { status_history: [{ id: 1, from_status: null, to_status: 'GENERATED', changed_by: null, changed_by_name: null, changed_at: now(), reason: null }] }]
    if (m(/^\/recommendations\/(\d+)\/assignments$/)) { if (deny(uid, ['PLANNER'])) return [403, { detail: '필요 역할: PLANNER' }]; const r = S.recs[+m(/(\d+)/)[1]]; r.status = 'ASSIGNED'; r.assignments.push({ id: ++S.nextId, review_role: body.review_role, assignee_user_id: body.assignee_user_id ?? null, assignee_dept_id: body.assignee_dept_id ?? null, status: 'PENDING', due_at: now() }); return [201, { id: S.nextId }] }
    if (m(/^\/recommendations\/(\d+)\/decisions$/)) {
      if (deny(uid, ['DEPT_REVIEWER', 'EXPERT'])) return [403, { detail: '필요 역할: DEPT_REVIEWER, EXPERT' }]
      if (body.is_final && uid !== 2) return [403, { detail: '최종판정 권한 없음 (소관부서 검수자만)' }]
      const r = S.recs[+m(/(\d+)/)[1]]
      r.decisions.push({ id: ++S.nextId, reviewer_id: uid, reviewer_name: users[uid].name, decision_code: body.decision_code, is_final: body.is_final, opinion: body.opinion, linkage_type_override: body.linkage_type_override, created_at: now() })
      r.status = body.is_final ? 'DECIDED' : 'IN_REVIEW'; return [201, { id: S.nextId }]
    }
    if (m(/^\/recommendations\/(\d+)\/comments$/)) { const r = S.recs[+m(/(\d+)/)[1]]; r.comments.push({ id: ++S.nextId, author_id: uid, body: body.body, parent_id: null, created_at: now() }); return [201, { id: S.nextId }] }
    if (path === '/documents' && method === 'GET') return [200, S.docs]
    if (path === '/documents' && method === 'POST') { if (deny(uid, ['CURATOR', 'PLANNER'])) return [403, { detail: '필요 역할: CURATOR, PLANNER' }]; const id = ++S.nextId; S.docs.unshift({ id, doc_type_code: body.doc_type_code, doc_type_name: '결과보고서', title: body.title, project_id: body.project_id, owner_dept_id: 3, parse_status: 'EMBEDDED', security_code: 'PUBLIC', created_at: now(), chunk_count: body.chunks.length }); return [201, { id, chunk_ids: body.chunks.map((_, i) => 900 + i), embedded: body.chunks.length }] }
    if (path === '/documents/search') return [200, [{ chunk_id: 1, document_id: 1, document_title: '항재밍 데이터링크 결과보고서', heading: '미해결 기술', page_start: 88, content: '광대역 재밍 환경에서 동기 유지 시간이 부족했다.', similarity: 0.71 }]]
    if (path === '/gaps/summary') return [200, [
      { overseas_demand_id: 1, demand_no: 'D01', title: '폴란드 K2PL 파워팩 변속기 내구도', region: '폴란드', tech_area: '파워팩', gaps: { PERFORMANCE_SHORT: { finding_id: 101, status: S.gapStatus[101], score: 0.72 }, MATURITY: { finding_id: 102, status: S.gapStatus[102], score: 0.41 } } },
      { overseas_demand_id: 2, demand_no: 'D02', title: '루마니아 전차 현지 정비 패키지', region: '루마니아', tech_area: '정비', gaps: { LOCALIZATION: { finding_id: 103, status: S.gapStatus[103], score: 0.3 } } },
      { overseas_demand_id: 3, demand_no: 'D03', title: 'EU 차세대 전차 공모', region: 'EU', tech_area: null, gaps: {} }]]
    if (path === '/gaps/findings') return [200, [101, 102, 103].map(gap)]
    if (m(/^\/gaps\/findings\/(\d+)$/)) { const id = +m(/(\d+)/)[1]; if (!S.gapStatus[id]) return [404, { detail: '갭 없음' }]; return [200, { ...gap(id), detail: { items: ['K2 변속기: 자체 목표 미달 — 내구도 306시간 (목표 320시간)'] }, cards: [{ card_id: 1, card_no: 'K2T', title: 'K2 전차 변속기', trl: 7, project_title: 'K2 파워팩 국산화', similarity: 0.78, role: 'EVIDENCE', note: '자체 목표 미달 — 내구도 306h < 320h' }], pathways: [{ id: 1, linkage_type_code: 'ADVANCEMENT', linkage_name: '고도화형', description: '모자란 성능을 끌어올리는 고도화 과제', card_ids: [1] }], sources: [{ source_no: 'S01', issuer: '방위사업청', title: '제164회 방추위 결과', url: 'https://www.dapa.go.kr', license_note: '공공누리 1유형', is_primary: true }] }] }
    if (m(/^\/gaps\/findings\/(\d+)\/decision$/)) { if (deny(uid, ['DEPT_REVIEWER'])) return [403, { detail: '필요 역할: DEPT_REVIEWER' }]; S.gapStatus[+m(/(\d+)/)[1]] = body.decision === 'CONFIRM' ? 'CONFIRMED' : 'REJECTED'; return [204, null] }
    if (path === '/gaps/runs') { if (deny(uid, ['PLANNER', 'CURATOR'])) return [403, { detail: '필요 역할: PLANNER, CURATOR' }]; return [201, { id: 8, demand_count: 3, finding_count: 3 }] }
    return [404, { detail: `mock 없음 ${method} ${path}` }]
  }
}
