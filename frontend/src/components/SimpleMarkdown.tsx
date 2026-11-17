import type { ReactNode } from 'react'

/** 우리 서버가 만든 문서(제목·목록·표·문단)만 보여 주는 작은 Markdown 표시기. HTML 은 그대로 글자로 둔다. */
export function SimpleMarkdown({ text }: { text: string }) {
  const lines = text.split('\n')
  const out: ReactNode[] = []
  let i = 0
  const cells = (l: string) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
  while (i < lines.length) {
    const l = lines[i]
    if (l.startsWith('|')) {
      const rows: string[][] = []
      while (i < lines.length && lines[i].startsWith('|')) {
        if (!/^\|[\s|:-]+\|$/.test(lines[i].trim())) rows.push(cells(lines[i]))
        i++
      }
      const [head, ...body] = rows
      out.push(
        <div className="table-scroll" key={`t${i}`}><table className="table">
          <thead><tr>{head.map((c, k) => <th key={k}>{c}</th>)}</tr></thead>
          <tbody>{body.map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
        </table></div>)
      continue
    }
    if (l.startsWith('- ')) {
      const items: string[] = []
      while (i < lines.length && lines[i].startsWith('- ')) items.push(lines[i++].slice(2))
      out.push(<ul key={`u${i}`}>{items.map((t, k) => <li key={k}>{t}</li>)}</ul>)
      continue
    }
    const h = /^(#{1,3}) (.*)$/.exec(l)
    if (h) out.push(h[1].length === 1 ? <h2 key={i}>{h[2]}</h2> : h[1].length === 2 ? <h3 key={i}>{h[2]}</h3> : <h4 key={i}>{h[2]}</h4>)
    else if (l.trim()) out.push(<p key={i}>{l}</p>)
    i++
  }
  return <div className="md-doc">{out}</div>
}
