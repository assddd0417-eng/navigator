/**
 * 역할(RBAC) 정의와 화면 접근 규칙.
 *
 * 화면 분기는 사용자 편의를 위한 것이고, 실제 권한은 항상 백엔드(require_roles + DB 트리거)가 판단한다.
 * 그래서 일부 버튼은 일부러 권한 없는 역할에게도 보여 주고, 서버의 403 을 알림으로 보여 준다 (시연용).
 */

export type RoleCode = 'PLANNER' | 'DEPT_REVIEWER' | 'EXPERT' | 'CURATOR'
export type RoleGroup = 'ADMIN' | 'WORKER'

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
    description: '신규 기획수요를 등록하고 AI 매칭을 실행해 검토를 배정합니다.',
    can: ['기획수요 등록', '매칭 실행', '검토 배정', '추천 철회'],
  },
  DEPT_REVIEWER: {
    code: 'DEPT_REVIEWER',
    label: '조직 관리자·검수자',
    group: 'ADMIN',
    description: '소관 부서의 추천을 검토하고 최종 판정(채택·보류·제외)을 내립니다.',
    can: ['검토 의견', '최종 판정'],
  },
  EXPERT: {
    code: 'EXPERT',
    label: '전문가',
    group: 'WORKER',
    description: '배정된 추천을 기술적으로 검토하고 의견을 남깁니다. 최종 판정은 할 수 없습니다.',
    can: ['검토 의견', '연계유형 수정 제안'],
  },
  CURATOR: {
    code: 'CURATOR',
    label: '큐레이터·작업자',
    group: 'WORKER',
    description: '원문 문서를 올리고 성과 활용카드를 만들어 검수 후 발행합니다.',
    can: ['문서 업로드', '성과카드 작성', '성과카드 발행'],
  },
}

export interface SeedUser {
  id: number
  role: RoleCode
  name: string
  department: string
}

/** seeds/init_test_data.sql 의 사용자 1~4 (X-User-Id 값) */
export const SEED_USERS: SeedUser[] = [
  { id: 1, role: 'PLANNER', name: '기획담당', department: '과제기획팀' },
  { id: 2, role: 'DEPT_REVIEWER', name: '부서검토자', department: '무인미래통신기술팀' },
  { id: 3, role: 'EXPERT', name: '기술전문가', department: '지휘정찰기술팀' },
  { id: 4, role: 'CURATOR', name: '카드관리자', department: '과제기획팀' },
]

export const ADMIN_ROLES: RoleCode[] = ['PLANNER', 'DEPT_REVIEWER']
export const WORKER_ROLES: RoleCode[] = ['CURATOR', 'EXPERT']
export const ALL_ROLES: RoleCode[] = [...ADMIN_ROLES, ...WORKER_ROLES]

export interface MenuItem {
  path: string
  label: string
  icon: string
  roles: RoleCode[]
}

export const MENU: MenuItem[] = [
  { path: '/dashboard', label: '진행 현황', icon: '📊', roles: ADMIN_ROLES },
  { path: '/projects', label: '프로젝트 관리', icon: '🗂️', roles: ADMIN_ROLES },
  { path: '/reviews', label: '검토 큐', icon: '📥', roles: ADMIN_ROLES },
  { path: '/my-tasks', label: '내 작업', icon: '✅', roles: WORKER_ROLES },
  { path: '/documents/upload', label: '문서 업로드', icon: '📤', roles: WORKER_ROLES },
]

export function primaryRole(roles: string[]): RoleCode | null {
  return ALL_ROLES.find((r) => roles.includes(r)) ?? null
}

export function homePath(role: RoleCode): string {
  return ROLES[role].group === 'ADMIN' ? '/dashboard' : '/my-tasks'
}

export function canAccess(role: RoleCode | null, allowed: RoleCode[]): boolean {
  return role != null && allowed.includes(role)
}
