import { useState, type FormEvent } from 'react'
import {
  REGULATION_CHECKS, confirmRegulation, createRegulation, deleteRegulation, getRegulation, listRegulations,
  previewRegulation, routeRules, searchRegulations, updateRegulation,
  type Regulation, type RegulationArticleIn, type RegulationCheck, type RegulationHit,
} from '../../api/navigator'
import { useAuth } from '../../auth/AuthContext'
import { Card, Empty, PageHeader, useAction, useAsync } from '../../components/ui'
import { fmtDay } from '../navigator/components'

export function RegulationsPage() {
  const { role } = useAuth()
  const canEdit = role === 'PROGRAM_OWNER' || role === 'AX_ADMIN'
  const list = useAsync(listRegulations, [])
  const [selected, setSelected] = useState<number | null>(null)
  const [adding, setAdding] = useState(false)
  return (
    <>
      <PageHeader title="운영규정·지침"
        subtitle="공통운영규정과 사업별 운영지침을 조문 단위로 등록합니다. 참여제한 조문은 모든 공고 자격검토에 더해집니다." />
      <SearchBox onPick={(id) => { setAdding(false); setSelected(id) }} />
      <div className="grid-side">
        <Card title="규정 목록" actions={canEdit && (
          <button className="btn btn-sm" onClick={() => { setAdding(true); setSelected(null) }}>새 규정 등록</button>
        )}>
          {list.loading ? <div className="page-loading">불러오는 중…</div> : !list.data?.length ? <Empty>등록된 규정이 없습니다.</Empty> : (
            <ul className="select-list">
              {list.data.map((g) => (
                <li key={g.id}>
                  <button className={g.id === selected ? 'on' : ''} onClick={() => { setAdding(false); setSelected(g.id) }}>
                    <strong>{g.title}</strong>
                    <span className="small muted">
                      {g.kind_label}{g.program_name ? ` · ${g.program_name}` : ''} · 조문 {g.article_count} · 참여제한 {g.limit_count}
                    </span>
                    <span>
                      {g.confirmed_at
                        ? <span className="badge badge-ok">확인 {fmtDay(g.confirmed_at)}</span>
                        : <span className="badge badge-warn">확인 전</span>}
                      {!g.is_active && <> <span className="badge badge-muted">사용 안 함</span></>}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <div className="stack">
          {adding && <NewRegulation onCancel={() => setAdding(false)}
            onCreated={(id) => { setAdding(false); setSelected(id); void list.reload() }} />}
          {!adding && selected != null && (
            <Detail key={selected} id={selected} canEdit={canEdit} onChanged={() => void list.reload()}
              onDeleted={() => { setSelected(null); void list.reload() }} />
          )}
          {!adding && selected == null && <Card><Empty>왼쪽에서 규정을 고르세요.</Empty></Card>}
        </div>
      </div>
    </>
  )
}

function SearchBox({ onPick }: { onPick: (id: number) => void }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<RegulationHit[] | null>(null)
  const { busy, run } = useAction()
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!q.trim()) return
    void run(async () => setHits(await searchRegulations(q.trim())))
  }
  return (
    <Card title="조문 검색">
      <form className="form-row" onSubmit={submit}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="예: 체납 중인 기업의 참여" aria-label="조문 검색" />
        <button className="btn" disabled={busy}>{busy ? '찾는 중…' : '검색'}</button>
      </form>
      {hits && (!hits.length ? <p className="small muted">맞는 조문이 없습니다.</p> : (
        <ul className="small" style={{ marginTop: 10 }}>
          {hits.map((h) => (
            <li key={h.id}>
              <button className="btn btn-sm btn-ghost" onClick={() => onPick(h.regulation_id)}>{h.ref}</button>
              <span className="muted"> 관련도 {h.score.toFixed(2)}</span>
              <div className="muted">{h.body.length > 140 ? `${h.body.slice(0, 140)}…` : h.body}</div>
            </li>
          ))}
        </ul>
      ))}
    </Card>
  )
}

function CheckChips({ a, onChange, disabled }:
  { a: RegulationArticleIn; onChange: (a: RegulationArticleIn) => void; disabled?: boolean }) {
  const toggle = (code: RegulationCheck) => {
    const on = a.checks.includes(code)
    const checks = on ? a.checks.filter((c) => c !== code) : [...a.checks, code]
    onChange({ ...a, checks, within_years: checks.includes('DUPLICATE') ? (a.within_years ?? 1) : null })
  }
  return (
    <div>
      <div className="chips" style={{ marginTop: 0 }}>
        {REGULATION_CHECKS.map((c) => (
          <button key={c.code} type="button" disabled={disabled}
            className={`chip ${a.checks.includes(c.code) ? 'chip-on' : ''}`} onClick={() => toggle(c.code)}>{c.label}</button>
        ))}
      </div>
      {a.checks.includes('DUPLICATE') && (
        <label className="small">제한 기간(년){' '}
          <input type="number" min={1} max={10} style={{ width: 70 }} disabled={disabled} value={a.within_years ?? 1}
            onChange={(e) => onChange({ ...a, within_years: Math.min(10, Math.max(1, Number(e.target.value) || 1)) })} />
        </label>
      )}
    </div>
  )
}

const toIn = (a: RegulationArticleIn): RegulationArticleIn =>
  ({ article_no: a.article_no, title: a.title, body: a.body, checks: a.checks, within_years: a.within_years })

function NewRegulation({ onCreated, onCancel }: { onCreated: (id: number) => void; onCancel: () => void }) {
  const programs = useAsync(routeRules, [])
  const [f, setF] = useState({
    title: '', kind: 'COMMON' as 'COMMON' | 'PROGRAM', program_id: '', version_label: '', effective_on: '', source_url: '', text: '',
  })
  const [arts, setArts] = useState<RegulationArticleIn[] | null>(null)
  const { busy, run } = useAction()
  const split = () => void run(async () => setArts((await previewRegulation(f.text)).map(toIn)))
  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      const r = await createRegulation({
        title: f.title.trim(), kind: f.kind,
        program_id: f.kind === 'PROGRAM' && f.program_id ? Number(f.program_id) : null,
        version_label: f.version_label.trim() || undefined, effective_on: f.effective_on || undefined,
        source_url: f.source_url.trim() || undefined,
        ...(arts ? { articles: arts } : { text: f.text }),
      })
      onCreated(r.id)
    })
  }
  return (
    <Card title="새 규정 등록">
      <p className="small muted">전문을 붙여 넣고 조문 나누기로 나눈 결과를 확인하세요. 고친 조문이 그대로 저장됩니다.</p>
      <form className="form" onSubmit={submit}>
        <label>제목<input required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></label>
        <div className="form-row">
          <label>구분
            <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as 'COMMON' | 'PROGRAM' })}>
              <option value="COMMON">공통운영규정</option>
              <option value="PROGRAM">사업별 운영규정·지침</option>
            </select>
          </label>
          {f.kind === 'PROGRAM' && (
            <label>지원사업
              <select required value={f.program_id} onChange={(e) => setF({ ...f, program_id: e.target.value })}>
                <option value="">선택</option>
                {programs.data?.programs.map((p) => <option key={p.program_id} value={p.program_id}>{p.name}</option>)}
              </select>
            </label>
          )}
          <label>판 표시<input value={f.version_label} placeholder="예: 2026년 개정" onChange={(e) => setF({ ...f, version_label: e.target.value })} /></label>
          <label>시행일<input type="date" value={f.effective_on} onChange={(e) => setF({ ...f, effective_on: e.target.value })} /></label>
        </div>
        <label>원문 주소<input value={f.source_url} placeholder="https://" onChange={(e) => setF({ ...f, source_url: e.target.value })} /></label>
        <label>규정 전문<textarea required rows={12} value={f.text}
          placeholder="제1조(목적) 형식으로 된 전문을 붙여 넣으세요"
          onChange={(e) => { setF({ ...f, text: e.target.value }); setArts(null) }} /></label>
        <div>
          <button type="button" className="btn" disabled={busy || !f.text.trim()} onClick={split}>조문 나누기</button>
        </div>
        {arts && (
          <>
            <p className="small muted">조문 {arts.length}개. 참여제한에 해당하는 항목을 켜고 끄세요.</p>
            <ArticleTable arts={arts} onChange={setArts} />
          </>
        )}
        <div className="form-foot">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>취소</button>
          <button className="btn btn-primary" disabled={busy}>{busy ? '저장 중…' : '저장'}</button>
        </div>
      </form>
    </Card>
  )
}

function ArticleTable({ arts, onChange }: { arts: RegulationArticleIn[]; onChange: (a: RegulationArticleIn[]) => void }) {
  return (
    <table className="table">
      <thead><tr><th>조문</th><th>본문</th><th>참여제한 항목</th></tr></thead>
      <tbody>
        {arts.map((a, i) => (
          <tr key={i}>
            <td>{a.article_no}{a.title ? `(${a.title})` : ''}</td>
            <td className="small">{a.body.length > 160 ? `${a.body.slice(0, 160)}…` : a.body}</td>
            <td><CheckChips a={a} onChange={(n) => onChange(arts.map((x, j) => (j === i ? n : x)))} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Detail({ id, canEdit, onChanged, onDeleted }:
  { id: number; canEdit: boolean; onChanged: () => void; onDeleted: () => void }) {
  const reg = useAsync(() => getRegulation(id), [id])
  const { busy, run } = useAction()
  const [confirmDel, setConfirmDel] = useState(false)
  const g = reg.data
  if (reg.loading && !g) return <Card><div className="page-loading">불러오는 중…</div></Card>
  if (!g) return <Card><Empty>규정을 불러오지 못했습니다.</Empty></Card>
  const done = () => { void reg.reload(); onChanged() }
  return (
    <>
      <Card title={g.title} actions={g.source_url && <a className="btn btn-sm" href={g.source_url} target="_blank" rel="noreferrer">원문</a>}>
        <div className="small muted">
          {g.kind_label}{g.program_name ? ` · ${g.program_name}` : ''}
          {' · '}판 {g.version_label ?? '–'} · 시행일 {fmtDay(g.effective_on)} · 소관부서 {g.owner_dept_name ?? '–'}
        </div>
        <div style={{ margin: '8px 0' }}>
          {g.confirmed_at
            ? <span className="badge badge-ok">확인 {fmtDay(g.confirmed_at)}{g.confirmed_by_name ? ` · ${g.confirmed_by_name}` : ''}</span>
            : <span className="badge badge-warn">확인 전</span>}
          {!g.is_active && <> <span className="badge badge-muted">사용 안 함</span></>}
        </div>
        {canEdit && (
          <div className="form-foot" style={{ justifyContent: 'flex-start' }}>
            <button className="btn btn-primary" disabled={busy} onClick={() => void run(async () => { await confirmRegulation(id); done() })}>내용 확인</button>
            <button className="btn" disabled={busy}
              onClick={() => void run(async () => { await updateRegulation(id, { is_active: !g.is_active }); done() })}>
              {g.is_active ? '사용 안 함' : '다시 사용'}
            </button>
            {!confirmDel
              ? <button className="btn btn-ghost" onClick={() => setConfirmDel(true)}>삭제</button>
              : (
                <span className="small">
                  이 규정과 조문을 모두 지울까요?{' '}
                  <button className="btn btn-sm" disabled={busy}
                    onClick={() => void run(async () => { await deleteRegulation(id); onDeleted() })}>삭제 확인</button>{' '}
                  <button className="btn btn-sm btn-ghost" onClick={() => setConfirmDel(false)}>취소</button>
                </span>
              )}
          </div>
        )}
      </Card>
      <Articles reg={g} canEdit={canEdit} onSaved={done} />
    </>
  )
}

function Articles({ reg, canEdit, onSaved }: { reg: Regulation; canEdit: boolean; onSaved: () => void }) {
  const [arts, setArts] = useState<RegulationArticleIn[]>(() => reg.articles.map(toIn))
  const [dirty, setDirty] = useState(false)
  const { busy, run } = useAction()
  const set = (i: number, a: RegulationArticleIn) => { setArts(arts.map((x, j) => (j === i ? a : x))); setDirty(true) }
  return (
    <Card title={`조문 ${arts.length}개`} actions={canEdit && (
      <button className="btn btn-primary btn-sm" disabled={busy || !dirty}
        onClick={() => void run(async () => { await updateRegulation(reg.id, { articles: arts }); setDirty(false); onSaved() })}>
        {busy ? '저장 중…' : '조문 저장'}
      </button>
    )}>
      {canEdit && <p className="small muted">조문을 고치면 확인일이 지워져 다시 확인해야 합니다.</p>}
      {arts.map((a, i) => (
        <div key={reg.articles[i]?.id ?? i} style={{ borderTop: '1px solid var(--border)', padding: '10px 0' }}>
          <strong>{a.article_no}{a.title ? `(${a.title})` : ''}</strong>
          {canEdit
            ? <textarea rows={4} style={{ width: '100%', margin: '6px 0' }} value={a.body} aria-label={`${a.article_no} 본문`}
                onChange={(e) => set(i, { ...a, body: e.target.value })} />
            : <p className="small" style={{ whiteSpace: 'pre-wrap' }}>{a.body}</p>}
          {canEdit
            ? <CheckChips a={a} onChange={(n) => set(i, n)} />
            : a.checks.length > 0 && (
              <div className="chips" style={{ marginTop: 0 }}>
                {REGULATION_CHECKS.filter((c) => a.checks.includes(c.code)).map((c) => (
                  <span key={c.code} className="badge badge-info">
                    {c.label}{c.code === 'DUPLICATE' && a.within_years ? ` ${a.within_years}년` : ''}
                  </span>
                ))}
              </div>
            )}
        </div>
      ))}
    </Card>
  )
}
