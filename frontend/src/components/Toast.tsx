import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { ApiError, onApiError } from '../api/client'

type ToastKind = 'success' | 'info' | 'error' | 'forbidden'

interface Toast {
  id: number
  kind: ToastKind
  title: string
  message?: string
  meta?: string
}

interface ToastApi {
  show: (t: Omit<Toast, 'id'>) => void
  success: (title: string, message?: string) => void
}

const ToastContext = createContext<ToastApi | null>(null)

/** CHECK·FK 제약은 PostgreSQL 영어 메시지가 그대로 오므로 시연에 나올 만한 것만 한국어로 바꾼다. (트리거 메시지는 이미 한국어) */
const CONSTRAINT_REASONS: Record<string, string> = {
  planning_demand_check: '요구 TRL 최소값이 최대값보다 클 수 없습니다.',
}

function reasonOf(e: ApiError): string {
  if (!e.constraint) return e.detail
  return CONSTRAINT_REASONS[e.constraint] ?? '입력값이 정해진 규칙에 맞지 않습니다.'
}

/** API 오류를 비전공자도 이해할 수 있는 문장으로 바꾼다. 서버의 한국어 사유(detail)는 그대로 덧붙인다. */
export function describeApiError(e: ApiError): Omit<Toast, 'id'> {
  const meta = e.requestId ? `문의 시 알려 줄 번호: ${e.requestId}` : undefined
  switch (e.status) {
    case 0:
      return { kind: 'error', title: '서버에 연결하지 못했습니다', message: '잠시 뒤 다시 시도해 주세요. 계속되면 담당자에게 서버가 켜져 있는지 확인해 달라고 해 주세요.' }
    case 401:
      return { kind: 'error', title: '다시 로그인해 주세요', message: e.detail, meta }
    case 403:
      return {
        kind: 'forbidden',
        title: '지금 역할로는 할 수 없는 일입니다',
        message: `서버가 권한을 확인하고 막았습니다.\n이유: ${e.detail}`,
        meta,
      }
    case 404:
      return { kind: 'error', title: '찾는 내용이 없습니다', message: '삭제됐거나 볼 권한이 없는 항목일 수 있습니다.', meta }
    case 409:
      return { kind: 'error', title: '이미 같은 내용이 있습니다', message: e.detail, meta }
    case 422:
      return {
        kind: 'error',
        title: '입력 내용을 확인해 주세요',
        message: `입력값이 업무 규칙(예: 원문 근거가 꼭 있어야 함)에 맞지 않습니다.\n이유: ${reasonOf(e)}`,
        meta,
      }
    default:
      return { kind: 'error', title: '서버에서 문제가 생겼습니다', message: '잠시 뒤 다시 시도해 주세요.', meta }
  }
}

const ICONS: Record<ToastKind, string> = { success: '✅', info: 'ℹ️', error: '⚠️', forbidden: '🔒' }

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const seq = useRef(0)

  const dismiss = useCallback((id: number) => setToasts((ts) => ts.filter((t) => t.id !== id)), [])

  const show = useCallback(
    (t: Omit<Toast, 'id'>) => {
      const id = ++seq.current
      setToasts((ts) => [...ts.slice(-3), { ...t, id }])
      setTimeout(() => dismiss(id), t.kind === 'success' || t.kind === 'info' ? 3500 : 8000)
    },
    [dismiss],
  )

  const success = useCallback((title: string, message?: string) => show({ kind: 'success', title, message }), [show])

  // 모든 API 오류를 전역 토스트로 보여 준다 (silent 호출 제외)
  useEffect(() => onApiError((e) => show(describeApiError(e))), [show])

  return (
    <ToastContext.Provider value={{ show, success }}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`}>
            <span className="toast-icon">{ICONS[t.kind]}</span>
            <div className="toast-body">
              <strong>{t.title}</strong>
              {t.message && <p>{t.message}</p>}
              {t.meta && <small>{t.meta}</small>}
            </div>
            <button className="toast-close" onClick={() => dismiss(t.id)} aria-label="닫기">×</button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast 는 ToastProvider 안에서만 쓸 수 있습니다')
  return ctx
}
