/**
 * 기관 담당자 역할과 화면 접근 규칙.
 * 화면 분기는 편의용이고, 실제 권한은 백엔드(require_roles)가 판단한다.
 */

export type RoleCode = 'STAFF' | 'PROGRAM_OWNER' | 'AX_ADMIN'

export interface RoleMeta {
  code: RoleCode
  label: string
  description: string
  can: string[]
}

export const ROLES: Record<RoleCode, RoleMeta> = {
  STAFF: {
    code: 'STAFF',
    label: '기업지원 담당자',
    description: '기업과 상담해 성장준비도를 진단하고, 자격요건과 성장경로를 근거와 함께 확인해 안내합니다.',
    can: ['성장경로 상담', '상담 이력 점검', '공고 등록·조건 확인', '공고별 적합 기업 보기', '참여 권유 메일', '외부 수집 실행'],
  },
  PROGRAM_OWNER: {
    code: 'PROGRAM_OWNER',
    label: '지원사업 소관부서',
    description: '공고·운영규정을 등록하고 예외 요건과 판단기준, 사업 연계관계를 관리합니다.',
    can: ['공고 등록·조건 확인', '성장경로 기준 수정', '외부 수집 실행', '서비스 안내 보기'],
  },
  AX_ADMIN: {
    code: 'AX_ADMIN',
    label: 'AX 주관부서',
    description: '상담이력을 점검해 기준을 보정하고, 기업정보 열람 권한을 관리합니다.',
    can: ['상담 이력 점검', '성장경로 기준 수정', '기업정보 열람 권한 관리', '서비스 안내 보기'],
  },
}

export interface SeedUser {
  id: number
  role: RoleCode
  name: string
  department: string
}

/** seeds/base.sql 의 사용자 (X-User-Id 값). 2번 열람자는 역할이 없어 화면에 넣지 않는다 */
export const SEED_USERS: SeedUser[] = [
  { id: 1, role: 'STAFF', name: '공고담당', department: '사업지원팀' },
  { id: 3, role: 'PROGRAM_OWNER', name: '사업담당', department: '방산사업팀' },
  { id: 4, role: 'AX_ADMIN', name: 'AX담당', department: 'AX추진팀' },
]

const ALL_ROLES: RoleCode[] = ['STAFF', 'PROGRAM_OWNER', 'AX_ADMIN']
export const STAFF_ROLES: RoleCode[] = ALL_ROLES
const STAFF_ONLY: RoleCode[] = ['STAFF']
const STAFF_OWNER: RoleCode[] = ['STAFF', 'PROGRAM_OWNER']
const STAFF_AX: RoleCode[] = ['STAFF', 'AX_ADMIN']
const AX_ONLY: RoleCode[] = ['AX_ADMIN']

export interface MenuItem {
  path: string
  label: string
  icon: string
  roles: RoleCode[]
  /** 사이드바 묶음: 업무 / 관리 / 부가 기능 */
  section: 'work' | 'manage' | 'extra'
}

export const MENU: MenuItem[] = [
  { path: '/staff/consult', label: '성장경로 상담', icon: '🗂️', roles: STAFF_ONLY, section: 'work' },
  { path: '/staff/consult/review', label: '상담 이력 점검', icon: '📝', roles: STAFF_AX, section: 'work' },
  { path: '/staff/service', label: '서비스 안내', icon: '📖', roles: ALL_ROLES, section: 'work' },
  { path: '/staff/announcements', label: '공고 등록·조건 확인', icon: '📋', roles: STAFF_OWNER, section: 'manage' },
  { path: '/staff/route-rules', label: '성장경로 기준', icon: '🛤️', roles: ALL_ROLES, section: 'manage' },
  { path: '/staff/access', label: '기업정보 열람 권한', icon: '🔐', roles: AX_ONLY, section: 'manage' },
  { path: '/staff/sources', label: '외부 수집', icon: '🔄', roles: STAFF_OWNER, section: 'manage' },
  { path: '/staff/navigator', label: '공고별 적합 기업', icon: '🧭', roles: STAFF_ONLY, section: 'extra' },
]

/** 경로별 허용 역할 (App.tsx 라우트와 같은 규칙). 긴 경로를 먼저 둔다 */
const PATH_ROLES: [RegExp, RoleCode[]][] = [
  [/^\/staff\/consult\/review(\/|$)/, STAFF_AX],
  [/^\/staff\/consult(\/|$)/, STAFF_ONLY],
  [/^\/staff\/navigator(\/|$)/, STAFF_ONLY],
  [/^\/staff\/(announcements|sources)(\/|$)/, STAFF_OWNER],
  [/^\/staff\/(service|route-rules)(\/|$)/, ALL_ROLES],
  [/^\/staff\/access(\/|$)/, AX_ONLY],
]

export function canAccessPath(role: RoleCode | null, pathname: string): boolean {
  const hit = PATH_ROLES.find(([re]) => re.test(pathname))
  return hit != null && canAccess(role, hit[1])
}

export function primaryRole(roles: string[]): RoleCode | null {
  return STAFF_ROLES.find((r) => roles.includes(r)) ?? null // 여러 역할이면 위쪽 역할 우선
}

export function homePath(role: RoleCode): string {
  if (role === 'PROGRAM_OWNER') return '/staff/announcements'
  if (role === 'AX_ADMIN') return '/staff/consult/review'
  return '/staff/consult'
}

export function canAccess(role: RoleCode | null, allowed: RoleCode[]): boolean {
  return role != null && allowed.includes(role)
}
