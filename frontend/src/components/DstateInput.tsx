import type { DstateValues, DstateVariable } from '../api/navigator'

/** 진단 변수 입력칸. draft 는 입력 문자열이고 빈 문자열은 값 지우기. */
export function DstateInput({ v, draft, onChange, disabled }:
  { v: DstateVariable; draft: string | undefined; onChange: (d: string) => void; disabled?: boolean }) {
  const cur = draft ?? (v.value == null ? '' : String(v.value))
  if (v.value_type === 'LEVEL') {
    return (
      <select value={cur} disabled={disabled} onChange={(e) => onChange(e.target.value)} aria-label={v.name}>
        <option value="">미확보</option>
        {v.options.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
      </select>
    )
  }
  return (
    <input type="number" min={0} step={1} value={cur} disabled={disabled} aria-label={v.name}
      onChange={(e) => onChange(e.target.value)} />
  )
}

/** 바뀐 변수만 API 값으로 만든다. 지운 값은 null. */
export function changedValues(vars: DstateVariable[], drafts: Record<string, string>): DstateValues {
  const out: DstateValues = {}
  for (const v of vars) {
    const d = drafts[v.code]
    if (d === undefined || v.value_type === 'PROFILE') continue
    const prev = v.value == null ? '' : String(v.value)
    if (d === prev) continue
    out[v.code] = d === '' ? null : v.value_type === 'INTEGER' ? Number(d) : d
  }
  return out
}
