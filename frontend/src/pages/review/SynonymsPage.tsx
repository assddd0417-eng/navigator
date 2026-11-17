import { useState, type ChangeEvent, type FormEvent } from 'react'
import {
  addSynonym, applySynonyms, importSynonyms, listSynonyms, patchSynonym, previewExpand, RELATIONS,
  type ExpandPreview, type ImportResult, type Relation,
} from '../../api/synonyms'
import { useAuth } from '../../auth/AuthContext'
import { useToast } from '../../components/Toast'
import { Card, Empty, PageHeader, RoleHint, Steps, useAction, useAsync } from '../../components/ui'

/**
 * 국방기술 용어 사전: 부서·시스템마다 다르게 쓰는 말(AESA ↔ 능동위상배열 레이더 등)을 묶어
 * 추천 매칭과 문서 검색이 같은 기술을 같은 것으로 보게 한다. 보기는 누구나, 고치기는 기획자·자료 담당.
 */
export function SynonymsPage() {
  const toast = useToast()
  const { role } = useAuth()
  const canEdit = role === 'PLANNER' || role === 'CURATOR'
  const { busy, run } = useAction()
  const [q, setQ] = useState('')
  const [showOff, setShowOff] = useState(false)
  const list = useAsync(() => listSynonyms(q, showOff), [q, showOff])
  const [dirty, setDirty] = useState(false)

  const [f, setF] = useState({ canonical_term: '', synonym: '', relation: 'SYNONYM' as Relation, domain: '', source_note: '' })
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const ok = await run(() => addSynonym({ ...f, domain: f.domain || null, source_note: f.source_note || null }))
    if (!ok) return
    toast.success('사전에 넣었습니다', '‘적용’을 눌러야 추천 매칭에 반영됩니다.')
    setF({ ...f, synonym: '' })
    setDirty(true)
    void list.reload()
  }

  const toggle = async (id: number, active: boolean) => {
    if (await run(() => patchSynonym(id, { is_active: active }))) {
      setDirty(true)
      void list.reload()
    }
  }

  const [file, setFile] = useState<File | null>(null)
  const [imp, setImp] = useState<ImportResult | null>(null)
  const pick = async (e: ChangeEvent<HTMLInputElement>) => {
    const x = e.target.files?.[0] ?? null
    setFile(x)
    setImp(x ? await run(() => importSynonyms(x, true)) ?? null : null)
  }
  const doImport = async () => {
    if (!file) return
    const res = await run(() => importSynonyms(file, false))
    if (!res) return
    toast.success(`${res.added}건을 넣었습니다`, res.skipped ? `이미 있는 ${res.skipped}건은 건너뛰었습니다.` : undefined)
    setFile(null)
    setImp(null)
    setDirty(true)
    void list.reload()
  }

  const apply = async () => {
    const res = await run(applySynonyms)
    if (!res) return
    const r = res.re_embedded
    toast.success('추천 매칭에 반영했습니다', `다시 계산: 성과카드 ${r.cards} · 기획수요 ${r.demands} · 해외 수요 ${r.overseas_demands}건`)
    setDirty(false)
  }

  const [text, setText] = useState('함정용 AESA 레이더 송수신 모듈 국산화')
  const [pv, setPv] = useState<ExpandPreview | null>(null)
  const preview = async (e: FormEvent) => {
    e.preventDefault()
    setPv(await run(() => previewExpand(text)) ?? null)
  }

  const rows = list.data ?? []
  return (
    <>
      <PageHeader title="국방기술 용어 사전"
        subtitle="부서·시스템마다 다르게 쓰는 말을 한 묶음으로 둡니다. 성과와 수요가 다른 말로 적혀 있어도 같은 기술로 보고 후보를 찾습니다."
        actions={canEdit ? <button className="btn btn-primary" disabled={busy} onClick={() => void apply()}>
          {dirty ? '바뀐 내용 적용' : '추천 매칭에 적용'}</button> : undefined} />
      <Steps items={[
        '표준 용어와 같은 뜻의 다른 말(동의어·약어·영문·한글)을 넣습니다. 엑셀로 한꺼번에 올릴 수도 있습니다.',
        '‘적용’을 누르면 글이 바뀐 성과카드·기획수요·해외 수요만 다시 계산합니다.',
        '넓은 말·좁은 말·관련어는 참고로만 남기고 매칭에는 쓰지 않습니다. 엉뚱한 후보가 끌려오지 않게 하기 위해서입니다.',
      ]} />
      {dirty && <p className="notice">사전을 바꿨습니다. 위의 ‘바뀐 내용 적용’을 눌러야 추천 매칭에 반영됩니다.</p>}

      <Card title="이 글은 어떻게 읽히나요" actions={<span className="muted small">검색·매칭에 실제로 쓰는 글</span>}>
        <form className="form-row" onSubmit={(e) => void preview(e)}>
          <label className="grow">글<input value={text} onChange={(e) => setText(e.target.value)} /></label>
          <div><button className="btn" disabled={busy || !text.trim()}>미리 보기</button></div>
        </form>
        {pv && (pv.matched.length === 0 ? <Empty>사전에 있는 말이 없어 글을 그대로 씁니다.</Empty> : (
          <div className="stack">
            <pre className="syn-preview">{pv.expanded}</pre>
            <div className="small">{pv.matched.map((m) => (
              <div key={m.canonical_term}><strong>{m.found}</strong> → {m.terms.filter((t) => t !== m.found).join(', ')}</div>
            ))}</div>
          </div>
        ))}
      </Card>

      {canEdit && (
        <Card title="용어 넣기" actions={<RoleHint roles={['PLANNER', 'CURATOR']} />}>
          <form className="stack" onSubmit={(e) => void submit(e)}>
            <div className="form-row">
              <label className="grow">표준 용어<input required value={f.canonical_term} placeholder="예: 능동위상배열 레이더"
                onChange={(e) => setF({ ...f, canonical_term: e.target.value })} /></label>
              <label className="grow">다른 말<input required value={f.synonym} placeholder="예: AESA"
                onChange={(e) => setF({ ...f, synonym: e.target.value })} /></label>
              <label>관계<select value={f.relation} onChange={(e) => setF({ ...f, relation: e.target.value as Relation })}>
                {Object.entries(RELATIONS).map(([c, r]) => <option key={c} value={c}>{r.name}</option>)}
              </select></label>
            </div>
            <p className="muted small">{RELATIONS[f.relation].help}</p>
            <div className="form-row">
              <label>분야<input value={f.domain} placeholder="예: 레이더" onChange={(e) => setF({ ...f, domain: e.target.value })} /></label>
              <label className="grow">출처<input value={f.source_note} placeholder="예: 지휘정찰기술팀 용어집"
                onChange={(e) => setF({ ...f, source_note: e.target.value })} /></label>
            </div>
            <div><button className="btn btn-primary" disabled={busy}>넣기</button></div>
          </form>
          <hr />
          <div className="stack">
            <label>엑셀로 한꺼번에 올리기 <span className="muted small">(첫 시트, 머리글: 표준 용어 | 동의어 | 관계 | 분야 | 출처)</span>
              <input type="file" accept=".xlsx" onChange={(e) => void pick(e)} /></label>
            {imp && (
              <div className="small">
                <p>{imp.rows}줄 중 새로 들어갈 말 <strong>{imp.would_add}건</strong>, 이미 있는 말 {imp.skipped}건
                  {imp.errors.length > 0 && <>, 넣을 수 없는 줄 {imp.errors.length}건</>}</p>
                {imp.errors.length > 0 && <ul>{imp.errors.slice(0, 10).map((x) => <li key={x.row}>{x.row}번째 줄: {x.reason}</li>)}</ul>}
                <button className="btn" disabled={busy || !imp.would_add} onClick={() => void doImport()}>올리기</button>
              </div>
            )}
          </div>
        </Card>
      )}

      <Card title={`사전 (${rows.length}건)`} actions={
        <div className="syn-filter">
          <input placeholder="용어 찾기" value={q} onChange={(e) => setQ(e.target.value)} />
          <label><input type="checkbox" checked={showOff} onChange={(e) => setShowOff(e.target.checked)} /> 끈 것도 보기</label>
        </div>}>
        {rows.length === 0 ? <Empty>{q ? '찾는 용어가 없습니다.' : '아직 넣은 용어가 없습니다.'}</Empty> : (
          <div className="table-scroll">
            <table className="table">
              <thead><tr><th>표준 용어</th><th>다른 말</th><th>관계</th><th>분야</th><th>출처</th><th>매칭</th>{canEdit && <th />}</tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className={r.is_active ? '' : 'muted'}>
                    <td><strong>{r.canonical_term}</strong></td>
                    <td>{r.synonym}</td>
                    <td>{r.relation_name}</td>
                    <td>{r.domain ?? '–'}</td>
                    <td className="small">{r.source_note ?? '–'}</td>
                    <td>{!r.is_active ? <span className="badge badge-muted">끔</span>
                      : r.used_in_matching ? <span className="badge badge-ok">씀</span> : <span className="badge badge-muted">참고</span>}</td>
                    {canEdit && <td><button className="btn btn-sm" disabled={busy} onClick={() => void toggle(r.id, !r.is_active)}>
                      {r.is_active ? '끄기' : '켜기'}</button></td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}
