import type { ServiceGate } from '../api/navigator'
import { useServiceInfo } from './useServiceInfo'

/** 결과 화면 위에 붙이는 AI 자율성 등급 한 줄: 등급 배지, 관문 이름, 설명 */
export function GateLine({ gate }: { gate: 'dstate' | 'eligibility' | 'route' }) {
  const info = useServiceInfo()
  const g: ServiceGate | undefined = info?.gates[gate]
  if (!g) return null
  const lv = info?.levels.find((l) => l.code === g.level)
  return (
    <div className="gate-line small">
      <span className={`badge badge-${g.level === 'L1' ? 'info' : g.level === 'L2' ? 'warn' : 'ok'}`}>
        {g.level}{lv ? ` ${lv.label}` : ''}
      </span>
      <strong>{g.gate}</strong>
      <span className="muted">{g.text}</span>
    </div>
  )
}
