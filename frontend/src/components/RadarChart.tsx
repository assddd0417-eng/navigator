import type { Radar } from '../api/navigator'

const SIZE = 260
const C = SIZE / 2
const R = 92

function point(i: number, n: number, v: number): [number, number] {
  const a = -Math.PI / 2 + (2 * Math.PI * i) / n
  return [C + Math.cos(a) * R * (v / 100), C + Math.sin(a) * R * (v / 100)]
}

const path = (vals: number[]) => vals.map((v, i) => point(i, vals.length, v).map((x) => x.toFixed(1)).join(',')).join(' ')

/** 역량 6축 레이더. 값이 없는 축(신용등급 미입력)은 0으로 그리고 표에 ‘미입력’으로 적는다. */
export function RadarChart({ radar, compact = false, who = '우리 회사' }: { radar: Radar; compact?: boolean; who?: string }) {
  const axes = radar.axes
  const n = axes.length
  const mine = axes.map((a) => a.value ?? 0)
  const avg = axes.map((a) => a.average ?? 0)
  return (
    <div className={`radar${compact ? ' radar-compact' : ''}`}>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label="역량 레이더">
        {[25, 50, 75, 100].map((g) => (
          <polygon key={g} points={path(axes.map(() => g))} className="radar-grid" />
        ))}
        {axes.map((_, i) => {
          const [x, y] = point(i, n, 100)
          return <line key={i} x1={C} y1={C} x2={x} y2={y} className="radar-grid" />
        })}
        <polygon points={path(avg)} className="radar-avg" />
        <polygon points={path(mine)} className="radar-mine" />
        {mine.map((v, i) => {
          const [x, y] = point(i, n, v)
          return <circle key={i} cx={x} cy={y} r={3} className="radar-dot"><title>{`${axes[i].label} ${axes[i].value ?? '미입력'}`}</title></circle>
        })}
        {axes.map((a, i) => {
          const [x, y] = point(i, n, 122)
          return (
            <text key={a.code} x={x} y={y} className="radar-label" textAnchor={Math.abs(x - C) < 4 ? 'middle' : x > C ? 'start' : 'end'}
              dominantBaseline="middle">{a.label}</text>
          )
        })}
      </svg>
      <div className="radar-side">
        <div className="radar-legend small">
          <span><i className="sw sw-mine" />{who}</span>
          <span><i className="sw sw-avg" />등록 기업 평균 ({radar.company_count}곳)</span>
        </div>
        <table className="radar-table small">
          <thead><tr><th /><td className="num muted">점수</td><td className="num muted">평균</td></tr></thead>
          <tbody>
            {axes.map((a) => (
              <tr key={a.code} title={a.note}>
                <th>{a.label}</th>
                <td className="num">{a.value ?? <span className="muted">미입력</span>}</td>
                <td className="num muted">{a.average ?? '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!compact && <div className="small muted">입력한 회사 정보로 계산한 0~100 점수입니다. 항목에 마우스를 올리면 계산 기준이 보입니다.</div>}
      </div>
    </div>
  )
}
