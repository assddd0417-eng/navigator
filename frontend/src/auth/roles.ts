/**
 * 역할(RBAC) 정의와 화면 접근 규칙.
 *
 * 화면 분기는 사용자 편의를 위한 것이고, 실제 권한은 항상 백엔드(require_roles + DB 트리거)가 판단한다.
 * 그래서 일부 버튼은 일부러 권한 없는 역할에게도 보여 주고, 서버의 403 을 알림으로 보여 준다 (시연용).
 */

export type RoleCode = 'PLANNER' | 'DEPT_REVIEWER' | 'EXPERT' | 'CURATOR' | 'VIEWER'
export type RoleGroup = 'ADMIN' | 'WORKER' | 'VIEW'

export interface RoleMeta {
  code: RoleCode
  label: string
  group: RoleGroup
  description: string
  can: string[]
}

export const ROLES: Record<RoleCode, RoleMeta> = {
  PLANNER: {
    code: 'PLANNER',
    label: '기획자',
    group: 'ADMIN',
    description: '새로 필요한 기술(기획수요)을 등록하고, AI가 찾아 준 기존 성과 중 쓸 만한 것을 골라 검토를 맡깁니다.',
    can: ['기획 참고서 보기', '기획수요 등록', 'AI로 연계 후보 찾기', '검토 요청', '갭 분석 다시 돌리기'],
  },
  DEPT_REVIEWER: {
    code: 'DEPT_REVIEWER',
    label: '조직 관리자·검수자',
    group: 'ADMIN',
    description: '우리 부서로 온 추천과 갭 분석 결과를 검토하고 최종 결정(채택·보류·제외, 확정·기각)을 내립니다.',
    can: ['검토 의견', '추천 최종 판정', '갭 확정·기각'],
  },
  EXPERT: {
    code: 'EXPERT',
    label: '전문가',
    group: 'WORKER',
    description: '나에게 온 추천을 기술 눈으로 검토하고 의견을 남깁니다. 최종 결정은 부서 검수자가 합니다.',
    can: ['검토 의견', '연계유형 수정 제안'],
  },
  CURATOR: {
    code: 'CURATOR',
    label: '큐레이터·작업자',
    group: 'WORKER',
    description: '과제 결과보고서를 올리고, 그 내용으로 성과카드를 만들어 확인 후 발행합니다.',
    can: ['문서 올리기', '성과카드 작성', '성과카드 발행', '동향 입력', '갭 분석 다시 돌리기'],
  },
  VIEWER: {
    code: 'VIEWER',
    label: '기관 열람자',
    group: 'VIEW',
    description: '기관 전체의 R&D 성과와 해외 수요 갭을 한눈에 보고, 정책·예산 기획 자료를 내려받습니다. 고치거나 결정하지는 않습니다.',
    can: ['기관 포트폴리오 보기', '엑셀로 받기', '해외 수요 갭 보기'],
  },
}

export interface SeedUser {
  id: number
  role: RoleCode
  name: string
  department: string
}

/** seeds/init_test_data.sql 의 사용자 1~4·6 (X-User-Id 값). 5번 열람자(공개 등급)는 권한 거부 확인용이라 화면에 안 넣는다 */
export const SEED_USERS: SeedUser[] = [
  { id: 1, role: 'PLANNER', name: '기획담당', department: '과제기획팀' },
  { id: 2, role: 'DEPT_REVIEWER', name: '부서검토자', department: '무인미래통신기술팀' },
  { id: 3, role: 'EXPERT', name: '기술전문가', department: '지휘정찰기술팀' },
  { id: 4, role: 'CURATOR', name: '카드관리자', department: '과제기획팀' },
  { id: 6, role: 'VIEWER', name: '정책기획 열람자', department: '과제기획팀' },
]

export const ADMIN_ROLES: RoleCode[] = ['PLANNER', 'DEPT_REVIEWER']
export const WORKER_ROLES: RoleCode[] = ['CURATOR', 'EXPERT']
/** 기관 포트폴리오를 보는 역할: 관리자 + 기관 열람자 (넘기기는 기획자만, 서버가 판단) */
export const PORTFOLIO_ROLES: RoleCode[] = [...ADMIN_ROLES, 'VIEWER']
export const ALL_ROLES: RoleCode[] = [...ADMIN_ROLES, ...WORKER_ROLES, 'VIEWER']
/** 신규 과제 기획: 관리자 + 큐레이터(동향 입력). 기획수요로 넘기기는 기획자만 (서버가 판단) */
export const PLANNING_ROLES: RoleCode[] = [...ADMIN_ROLES, 'CURATOR']

export interface MenuItem {
  path: string
  label: string
  icon: string
  roles: RoleCode[]
}

export const MENU: MenuItem[] = [
  { path: '/dashboard', label: '한눈에 보기', icon: '🏠', roles: ADMIN_ROLES },
  { path: '/planning', label: '신규 과제 기획', icon: '📝', roles: PLANNING_ROLES },
  { path: '/portfolio', label: '기관 포트폴리오', icon: '🗺️', roles: PORTFOLIO_ROLES },
  { path: '/reviews', label: '검토할 추천', icon: '📥', roles: ADMIN_ROLES },
  { path: '/projects', label: '연계 후보 찾기', icon: '🔎', roles: ADMIN_ROLES },
  { path: '/my-tasks', label: '내 할 일', icon: '✅', roles: WORKER_ROLES },
  { path: '/documents/upload', label: '문서 올리기', icon: '📤', roles: WORKER_ROLES },
  { path: '/gaps', label: '해외 수요 갭 분석', icon: '🌍', roles: ALL_ROLES },
  { path: '/staff/navigator', label: '공고별 적합 기업', icon: '🧭', roles: ADMIN_ROLES },
  { path: '/staff/sources', label: '외부 수집', icon: '🔄', roles: ADMIN_ROLES },
]

/**
 * 경로별 허용 역할 (App.tsx 라우트와 같은 규칙).
 * 로그인 직후 원래 가려던 화면으로 돌려보낼지, 역할을 바꾼 뒤 지금 화면에 머물지 정할 때 쓴다.
 */
const PATH_ROLES: [RegExp, RoleCode[]][] = [
  [/^\/(dashboard|projects|reviews|staff\/navigator|staff\/sources)(\/|$)/, ADMIN_ROLES],
  [/^\/(my-tasks|documents\/upload)(\/|$)/, WORKER_ROLES],
  [/^\/portfolio(\/|$)/, PORTFOLIO_ROLES],
  [/^\/planning(\/|$)/, PLANNING_ROLES],
  [/^\/(recommendations|gaps)(\/|$)/, ALL_ROLES],
]

export function canAccessPath(role: RoleCode | null, pathname: string): boolean {
  const hit = PATH_ROLES.find(([re]) => re.test(pathname))
  return hit != null && canAccess(role, hit[1])
}

export function primaryRole(roles: string[]): RoleCode | null {
  return ALL_ROLES.find((r) => roles.includes(r)) ?? null
}

export function homePath(role: RoleCode): string {
  const group = ROLES[role].group
  return group === 'ADMIN' ? '/dashboard' : group === 'VIEW' ? '/portfolio' : '/my-tasks'
}

export function canAccess(role: RoleCode | null, allowed: RoleCode[]): boolean {
  return role != null && allowed.includes(role)
}
