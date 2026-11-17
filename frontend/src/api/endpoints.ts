import { api } from './client'

/** psycopg 는 numeric 을 문자열로 직렬화하므로 숫자 필드는 number | string 으로 받는다. */
export type Num = number | string

export interface Me {
  id: number
  name: string
  department_id: number | null
  clearance_code: string
  roles: string[]
}

export const getMe = (userId?: number) => api<Me>('/me', { userId, silent: userId !== undefined })
