/**
 * 백엔드 API 클라이언트.
 *
 * - 로그인한 사용자의 ID 를 모든 요청의 X-User-Id 헤더에 자동으로 싣는다 (PoC 인증).
 *   운영 전환 시 이 파일의 헤더 주입만 Authorization: Bearer 로 바꾸면 된다.
 * - 실패 응답은 ApiError 로 통일하고, 등록된 리스너(토스트)에 알린다.
 */

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '')

let currentUserId: number | null = null

export function setApiUserId(id: number | null): void {
  currentUserId = id
}

/** FastAPI 오류 본문: 업무 규칙 오류는 detail 이 문자열, 입력 검증 오류(422)는 배열이다. */
interface ValidationIssue {
  loc: (string | number)[]
  msg: string
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly kind?: string,
    readonly requestId?: string | null,
    readonly method?: string,
    readonly path?: string,
  ) {
    super(detail)
    this.name = 'ApiError'
  }
}

type ErrorListener = (error: ApiError) => void
const listeners = new Set<ErrorListener>()

export function onApiError(listener: ErrorListener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function formatDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return (detail as ValidationIssue[])
      .map((d) => `${d.loc.filter((l) => l !== 'body').join('.')}: ${d.msg}`)
      .join('\n')
  }
  return detail == null ? '' : JSON.stringify(detail)
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  query?: Record<string, string | number | boolean | null | undefined>
  body?: unknown
  /** true 면 전역 토스트를 띄우지 않는다 (호출한 쪽에서 직접 처리할 때). */
  silent?: boolean
  /** 로그인 전 확인처럼 특정 사용자로 호출할 때 */
  userId?: number
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? 'GET'
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    if (v !== undefined && v !== null && v !== '') params.set(k, String(v))
  }
  const url = `${BASE_URL}${path}${params.size ? `?${params}` : ''}`

  const headers: Record<string, string> = { Accept: 'application/json' }
  const userId = opts.userId ?? currentUserId
  if (userId != null) headers['X-User-Id'] = String(userId)
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'

  let res: Response
  try {
    res = await fetch(url, {
      method,
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    })
  } catch {
    throw emit(new ApiError(0, '백엔드 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.',
      'network', null, method, path), opts.silent)
  }

  if (res.status === 204) return undefined as T
  const text = await res.text()
  const data: unknown = text ? safeJson(text) : null

  if (!res.ok) {
    const body = (data ?? {}) as { detail?: unknown; kind?: string }
    throw emit(new ApiError(res.status, formatDetail(body.detail) || res.statusText, body.kind,
      res.headers.get('X-Request-Id'), method, path), opts.silent)
  }
  return data as T
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return { detail: text }
  }
}

function emit(error: ApiError, silent?: boolean): ApiError {
  if (!silent) listeners.forEach((l) => l(error))
  return error
}
