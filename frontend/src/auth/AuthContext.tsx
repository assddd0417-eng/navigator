import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { setApiUserId } from '../api/client'
import { getMe, type Me } from '../api/endpoints'
import { primaryRole, SEED_USERS, type RoleCode } from './roles'

const STORAGE_KEY = 'navigator.userId'

interface AuthState {
  user: Me | null
  role: RoleCode | null
  /** 저장된 로그인 복원 중 */
  restoring: boolean
  login: (userId: number) => Promise<Me>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

function readStoredId(): number | null {
  try {
    const v = Number(localStorage.getItem(STORAGE_KEY))
    return SEED_USERS.some((u) => u.id === v) ? v : null
  } catch {
    return null
  }
}

function storeId(id: number | null): void {
  try {
    if (id == null) localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, String(id))
  } catch {
    /* 저장소를 못 써도 로그인은 이 탭에서 유지된다 */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null)
  const [restoring, setRestoring] = useState(() => readStoredId() != null)

  /** 백엔드 /me 로 사용자와 역할을 확인한 뒤에만 로그인 상태가 된다. */
  const login = useCallback(async (userId: number) => {
    const me = await getMe(userId)
    setApiUserId(me.id)
    storeId(me.id)
    setUser(me)
    return me
  }, [])

  const logout = useCallback(() => {
    setApiUserId(null)
    storeId(null)
    setUser(null)
  }, [])

  useEffect(() => {
    const stored = readStoredId()
    if (stored == null) return
    login(stored)
      .catch(() => storeId(null))
      .finally(() => setRestoring(false))
  }, [login])

  const value = useMemo<AuthState>(
    () => ({ user, role: user ? primaryRole(user.roles) : null, restoring, login, logout }),
    [user, restoring, login, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth 는 AuthProvider 안에서만 쓸 수 있습니다')
  return ctx
}
