/**
 * 기관 담당자 역할과 화면 접근 규칙.
 * 화면 분기는 편의용이고, 실제 권한은 백엔드(require_roles)가 판단한다.
 */

export type RoleCode = 'STAFF'

export interface RoleMeta {
  code: RoleCode
  label: string
  description: string
  can: string[]
}

export const ROLES: Record<RoleCode, RoleMeta> = {
  STAFF: {
    code: 'STAFF',
    label: '기관 담당자',
    description: '공고를 등록하고 지원 조건을 확인한 뒤, 공고마다 맞는 기업을 찾아 참여를 권합니다.',
    can: ['공고 등록·조건 확인', '공고별 적합 기업 보기', '참여 권유 메일', '외부 수집 실행'],
  },
}

export interface SeedUser {
  id: number
  role: RoleCode
  name: string
  department: string
}

/** seeds/base.sql 의 사용자 (X-User-Id 값). 2번 열람자는 권한 거부 확인용이라 화면에 넣지 않는다 */
export const SEED_USERS: SeedUser[] = [
  { id: 1, role: 'STAFF', name: '공고담당', department: '사업지원팀' },
]

export const STAFF_ROLES: RoleCode[] = ['STAFF']

export interface MenuItem {
  path: string
  label: string
  icon: string
  roles: RoleCode[]
}

export const MENU: MenuItem[] = [
  { path: '/staff/navigator', label: '공고별 적합 기업', icon: '🧭', roles: STAFF_ROLES },
  { path: '/staff/announcements', label: '공고 등록·조건 확인', icon: '📋', roles: STAFF_ROLES },
  { path: '/staff/sources', label: '외부 수집', icon: '🔄', roles: STAFF_ROLES },
]

/** 경로별 허용 역할 (App.tsx 라우트와 같은 규칙). 로그인 뒤 원래 화면으로 돌려보낼지 정할 때 쓴다 */
const PATH_ROLES: [RegExp, RoleCode[]][] = [
  [/^\/staff\/(navigator|announcements|sources)(\/|$)/, STAFF_ROLES],
]

export function canAccessPath(role: RoleCode | null, pathname: string): boolean {
  const hit = PATH_ROLES.find(([re]) => re.test(pathname))
  return hit != null && canAccess(role, hit[1])
}

export function primaryRole(roles: string[]): RoleCode | null {
  return STAFF_ROLES.find((r) => roles.includes(r)) ?? null
}

export function homePath(_role: RoleCode): string {
  return '/staff/navigator'
}

export function canAccess(role: RoleCode | null, allowed: RoleCode[]): boolean {
  return role != null && allowed.includes(role)
}
