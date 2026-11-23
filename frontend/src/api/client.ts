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
  type?: string
  ctx?: Record<string, unknown>
}

/** 자주 나오는 입력 항목 이름 (나머지는 서버 이름 그대로) */
const FIELD_KO: Record<string, string> = {
  concern: '상담 내용', interest: '관심 지원사업', contact_name: '담당자 이름', contact: '연락처', reason: '이유',
  title: '제목', text: '본문', announcement_no: '공고번호', agency_name: '기관', receipt_start: '접수 시작',
  receipt_end: '접수 마감', email: '이메일', code: '확인 코드', note: '메모', feedback: '담당자 의견',
  grade_high: '적합도 상 경계', grade_mid: '적합도 중 경계', capability_full: '역량 충분 경계',
  capability_partial: '역량 부분 경계', partial_ratio: '부분 충족 비율',
}

/** 입력 검증 오류(pydantic)를 우리말로 */
function issueText(d: ValidationIssue): string {
  const c = d.ctx ?? {}
  switch (d.type) {
    case 'string_too_long': return `${c.max_length}자 이하로 적어 주세요`
    case 'string_too_short': return Number(c.min_length) <= 1 ? '비어 있습니다' : `${c.min_length}자 이상 적어 주세요`
    case 'missing': return '꼭 넣어야 합니다'
    case 'greater_than_equal': return `${c.ge} 이상이어야 합니다`
    case 'greater_than': return `${c.gt}보다 커야 합니다`
    case 'less_than_equal': return `${c.le} 이하여야 합니다`
    case 'less_than': return `${c.lt}보다 작아야 합니다`
    case 'int_parsing': case 'int_type': case 'float_parsing': case 'float_type': return '숫자로 적어 주세요'
    case 'date_parsing': case 'date_from_datetime_parsing': case 'date_type': return '날짜 형식이 아닙니다'
    case 'literal_error': case 'enum': return '고를 수 있는 값이 아닙니다'
    case 'string_pattern_mismatch': return '형식이 맞지 않습니다'
    default: return d.msg.replace(/^Value error, /, '')
  }
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly kind?: string,
    readonly requestId?: string | null,
    readonly method?: string,
    readonly path?: string,
    /** DB 제약 위반일 때 제약 이름 (백엔드 errors.py 의 constraint) */
    readonly constraint?: string,
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
      .map((d) => {
        const field = d.loc.filter((l) => l !== 'body' && l !== 'query' && typeof l === 'string').pop()
        const name = field ? FIELD_KO[field] ?? field : ''
        return name ? `${name}: ${issueText(d)}` : issueText(d)
      })
      .join('\n')
  }
  return detail == null ? '' : JSON.stringify(detail)
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  query?: Record<string, string | number | boolean | null | undefined>
  /** FormData 면 multipart/form-data 로 그대로 보낸다 (파일 업로드). 그 외는 JSON. */
  body?: unknown
  /** true 면 전역 토스트를 띄우지 않는다 (호출한 쪽에서 직접 처리할 때). */
  silent?: boolean
  /** 로그인 전 확인처럼 특정 사용자로 호출할 때 */
  userId?: number
  /** true 면 X-User-Id 를 싣지 않는다 (로그인 없는 기업 화면) */
  anonymous?: boolean
  /** 추가 헤더 (예: 기업 관리 링크 X-Manage-Token) */
  headers?: Record<string, string>
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? 'GET'
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    if (v !== undefined && v !== null && v !== '') params.set(k, String(v))
  }
  const url = `${BASE_URL}${path}${params.size ? `?${params}` : ''}`

  const headers: Record<string, string> = { Accept: 'application/json', ...(opts.headers ?? {}) }
  const userId = opts.anonymous ? null : opts.userId ?? currentUserId
  if (userId != null) headers['X-User-Id'] = String(userId)
  const isForm = opts.body instanceof FormData
  // multipart 경계(boundary)는 브라우저가 붙이므로 Content-Type 을 직접 지정하지 않는다
  if (opts.body !== undefined && !isForm) headers['Content-Type'] = 'application/json'

  let res: Response
  try {
    res = await fetch(url, {
      method,
      headers,
      body: opts.body === undefined ? undefined : isForm ? (opts.body as FormData) : JSON.stringify(opts.body),
    })
  } catch {
    throw emit(new ApiError(0, '백엔드 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.',
      'network', null, method, path), opts.silent)
  }

  if (res.status === 204) return undefined as T
  const text = await res.text()
  const data: unknown = text ? safeJson(text) : null

  if (!res.ok) {
    const body = (data ?? {}) as { detail?: unknown; kind?: string; constraint?: string }
    throw emit(new ApiError(res.status, formatDetail(body.detail) || res.statusText, body.kind,
      res.headers.get('X-Request-Id'), method, path, body.constraint), opts.silent)
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

/**
 * 파일 내려받기 (엑셀 등). api() 와 같은 X-User-Id·오류 처리를 거쳐, 받은 파일을 브라우저 저장으로 넘긴다.
 * 파일 이름은 서버의 Content-Disposition(filename*=UTF-8'') 을 따르고, 없으면 fallbackName.
 */
export async function downloadFile(path: string, fallbackName: string, opts: Pick<RequestOptions, 'query'> = {}): Promise<void> {
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    if (v !== undefined && v !== null && v !== '') params.set(k, String(v))
  }
  const url = `${BASE_URL}${path}${params.size ? `?${params}` : ''}`
  const headers: Record<string, string> = {}
  if (currentUserId != null) headers['X-User-Id'] = String(currentUserId)
  let res: Response
  try {
    res = await fetch(url, { headers })
  } catch {
    throw emit(new ApiError(0, '백엔드 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.', 'network', null, 'GET', path))
  }
  if (!res.ok) {
    const body = (safeJson(await res.text()) ?? {}) as { detail?: unknown; kind?: string }
    throw emit(new ApiError(res.status, formatDetail(body.detail) || res.statusText, body.kind,
      res.headers.get('X-Request-Id'), 'GET', path))
  }
  const cd = res.headers.get('Content-Disposition') ?? ''
  const m = /filename\*=UTF-8''([^;]+)/i.exec(cd)
  const name = m ? decodeURIComponent(m[1]) : fallbackName
  const blobUrl = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = blobUrl
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(blobUrl), 1000)
}
