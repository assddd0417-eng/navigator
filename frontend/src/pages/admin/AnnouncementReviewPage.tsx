import { useEffect, useState, type FormEvent } from 'react'
import {
  createAnnouncementFromText, extractRequirements, getAnnouncement, getAnnouncementSource, getRequirementTypes, listAnnouncements, saveReview,
  type AnnDetail, type AnnFields, type EvalItem, type AnnSource, type Extraction, type ReqDraft, type TechDraft,
} from '../../api/navigator'
import { useAuth } from '../../auth/AuthContext'
import { Card, Empty, fmtDate, PageHeader, useAction, useAsync } from '../../components/ui'
import { fmtDay, fmtKrw } from '../navigator/components'

const TABS: ['PENDING' | 'DONE', string][] = [['PENDING', '확인 전'], ['DONE', '확인 완료']]
const KIND_LABELS: Record<string, string> = { EXTERNAL: '홈페이지 수집', PDF: '공고문 업로드', MANUAL: '직접 입력' }

interface Row extends ReqDraft { ruleText: string; ruleError?: string }

const toRow = (r: ReqDraft): Row => ({ ...r, ruleText: JSON.stringify(r.rule ?? {}) })
const fieldsOf = (a: AnnDetail): AnnFields => ({
  receipt_start: a.receipt_start, receipt_end: a.receipt_end, support_amount_krw: a.support_amount_krw,
  support_period_months: a.support_period_months, target_desc: a.target_desc, summary: a.summary,
  company_burden: a.company_burden, submit_documents: a.submit_documents ?? [],
})

const AREAS: [string, string][] = [['TECH', '기술'], ['QUALITY', '품질·인증'], ['PRODUCTION', '생산·공급망'],
  ['BUSINESS', '사업화·재무'], ['DEFENSE', '방산진입'], ['EXPORT', '수출']]
const KINDS: [EvalItem['kind'], string][] = [['CAPABILITY', '역량'], ['PURPOSE', '사업 목적'], ['APPLICATION', '신청서 기반']]
const DISQ: [string, string][] = [['TAX_DELINQUENT', '체납'], ['INSOLVENT', '부도·자본잠식'], ['RND_RESTRICTED', 'R&D 참여제한'],
  ['PROCUREMENT_SANCTIONED', '부정당제재']]
const parseRule = (t: string): Record<string, unknown> => { try { return JSON.parse(t || '{}') } catch { return {} } }


export function AnnouncementReviewPage() {
  const { role } = useAuth()
  const canEdit = role === 'STAFF'
  const [tab, setTab] = useState<'PENDING' | 'DONE'>('PENDING')
  const anns = useAsync(() => listAnnouncements({ review: tab }), [tab])
  const [selected, setSelected] = useState<number | null>(null)
  const [adding, setAdding] = useState(false)

  useEffect(() => {
    if (selected == null && anns.data?.length && !adding) setSelected(anns.data[0].id)
  }, [anns.data, selected, adding])

  const created = (id: number) => { setAdding(false); setTab('PENDING'); setSelected(id); anns.reload() }

  return (
    <>
      <PageHeader title="공고 등록·조건 확인"
        subtitle="수집하거나 붙여 넣은 공고문에서 지원 조건을 뽑고, 원문과 대조해 확인한 뒤 공개합니다. 공개한 공고만 기업 추천에 쓰입니다." />
      <div className="grid-side">
        <Card title="공고" actions={canEdit && (
          <button className="btn btn-sm" onClick={() => { setAdding(true); setSelected(null) }}>직접 등록</button>
        )}>
          <div className="chips" style={{ marginTop: 0, marginBottom: 10 }}>
            {TABS.map(([v, l]) => (
              <button key={v} className={`chip ${tab === v ? 'chip-on' : ''}`} onClick={() => { setTab(v); setSelected(null) }}>{l}</button>
            ))}
          </div>
          {anns.loading ? <div className="page-loading">불러오는 중…</div> : !anns.data?.length ? (
            <Empty>{tab === 'PENDING' ? '확인할 공고가 없습니다.' : '확인한 공고가 없습니다.'}</Empty>
          ) : (
            <ul className="select-list">
              {anns.data.map((a) => (
                <li key={a.id}>
                  <button className={a.id === selected ? 'on' : ''} onClick={() => { setAdding(false); setSelected(a.id) }}>
                    <strong>{a.title}</strong>
                    <span className="small muted">
                      {a.posted_on ? `게시 ${fmtDay(a.posted_on)}` : a.announcement_no} · {KIND_LABELS[a.source_kind ?? ''] ?? '직접 입력'}
                      {a.status === 'PUBLISHED' ? ' · 공개' : ' · 작성 중'}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="stack">
          {adding && <NewAnnouncement onCreated={created} onCancel={() => setAdding(false)} />}
          {!adding && selected != null && (
            <Review key={selected} annId={selected} canEdit={canEdit} onSaved={() => anns.reload()} />
          )}
        </div>
      </div>
    </>
  )
}

function NewAnnouncement({ onCreated, onCancel }: { onCreated: (id: number) => void; onCancel: () => void }) {
  const [f, setF] = useState({ title: '', agency_name: '국방기술진흥연구소', announcement_no: '', source_url: '', posted_on: '', body_text: '' })
  const { busy, run } = useAction()
  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      const r = await createAnnouncementFromText({
        title: f.title.trim(), agency_name: f.agency_name.trim(), body_text: f.body_text,
        announcement_no: f.announcement_no.trim() || undefined, source_url: f.source_url.trim() || undefined,
        posted_on: f.posted_on || undefined,
      })
      onCreated(r.id)
    })
  }
  return (
    <Card title="공고 직접 등록">
      <p className="small muted">홈페이지에 없는 공고나 미리 받은 공고문을 붙여 넣습니다. 작성 중으로 저장되고, 조건은 다음 화면에서 뽑습니다.</p>
      <form className="form" onSubmit={submit}>
        <label>제목<input required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></label>
        <div className="form-row">
          <label>기관<input required value={f.agency_name} onChange={(e) => setF({ ...f, agency_name: e.target.value })} /></label>
          <label>공고 번호<input value={f.announcement_no} placeholder="비우면 자동" onChange={(e) => setF({ ...f, announcement_no: e.target.value })} /></label>
          <label>게시일<input type="date" value={f.posted_on} onChange={(e) => setF({ ...f, posted_on: e.target.value })} /></label>
        </div>
        <label>원문 주소<input value={f.source_url} placeholder="https://" onChange={(e) => setF({ ...f, source_url: e.target.value })} /></label>
        <label>공고문 본문<textarea required minLength={20} rows={14} value={f.body_text}
          placeholder="한글 파일에서 전체 선택해 복사한 내용을 붙여 넣으세요"
          onChange={(e) => setF({ ...f, body_text: e.target.value })} /></label>
        <div className="form-foot">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>취소</button>
          <button className="btn btn-primary" disabled={busy}>{busy ? '저장 중…' : '작성 중으로 저장'}</button>
        </div>
      </form>
    </Card>
  )
}

function Review({ annId, canEdit, onSaved }: { annId: number; canEdit: boolean; onSaved: () => void }) {
  const ann = useAsync(() => getAnnouncement(annId), [annId])
  const src = useAsync(() => getAnnouncementSource(annId), [annId])
  const types = useAsync(getRequirementTypes, [])
  const [fields, setFields] = useState<AnnFields>({})
  const [rows, setRows] = useState<Row[]>([])
  const [evals, setEvals] = useState<EvalItem[] | null>(null)
  const [techs, setTechs] = useState<TechDraft[]>([])
  const [ex, setEx] = useState<Extraction | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const { busy, run } = useAction()

  useEffect(() => {
    if (!ann.data) return
    setFields(fieldsOf(ann.data))
    setEvals(ann.data.eval_items ?? [])
    setRows(ann.data.requirements.map((r) => toRow({ ...r, quote_found: true })))
    setTechs(ann.data.tech_needs.map(({ tech_name, description, is_core }) => ({ tech_name, description, is_core })))
  }, [ann.data])

  if (ann.loading || !ann.data) return <Card title="불러오는 중…"><div className="page-loading">불러오는 중…</div></Card>
  const a = ann.data
  const typeName = (c: string) => types.data?.types.find((t) => t.code === c)?.name_ko ?? c

  const doExtract = () => run(async () => {
    const r = await extractRequirements(annId)
    setEx(r); setMsg(null)
    setFields((f) => ({ ...f, ...r.fields }))
    setRows(r.requirements.map((x) => toRow({ ...x, origin: 'AI_EXTRACTED' })))
    if (r.tech_needs.length) setTechs(r.tech_needs)
  })

  const setRow = (i: number, patch: Partial<Row>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const addRow = () => setRows((rs) => [...rs, toRow({ req_type_code: 'OTHER', rule: {}, is_mandatory: true, description: '', source_quote: null, origin: 'MANUAL' })])

  const save = (publish: boolean) => {
    let bad = false
    const reqs: ReqDraft[] = rows.map((r, i) => {
      try {
        const rule = JSON.parse(r.ruleText || '{}') as Record<string, unknown>
        setRow(i, { ruleError: undefined })
        return { req_type_code: r.req_type_code, rule, is_mandatory: r.is_mandatory, description: r.description.trim(),
          source_quote: r.source_quote, origin: r.origin ?? 'MANUAL',
          bonus_points: r.is_mandatory ? null : r.bonus_points ?? null }
      } catch {
        bad = true; setRow(i, { ruleError: '규칙 형식이 JSON 이 아닙니다' })
        return r
      }
    })
    if (bad) return
    if (reqs.some((r) => !r.description)) { setMsg('조건 문장이 빈 줄이 있습니다.'); return }
    if (evals?.some((e) => !e.name.trim() || (e.kind === 'CAPABILITY' && !e.areas.length))) {
      setMsg('평가항목의 이름을 쓰고, 역량 항목은 영역을 하나 이상 고르세요.'); return
    }
    void run(async () => {
      await saveReview(annId, { fields: clean({ ...fields, submit_documents: (fields.submit_documents ?? []).filter((d) => d.name.trim()) }),
        requirements: reqs, eval_items: evals ?? undefined, tech_needs: techs.filter((t) => t.tech_name.trim()), confirm: true, publish })
      setMsg(publish ? '확인하고 공개했습니다. 이제 기업 추천과 알림에 쓰입니다.' : '확인 완료로 저장했습니다.')
      ann.reload(); onSaved()
    })
  }

  return (
    <>
      <Card title={a.title} actions={a.source_url && <a className="btn btn-sm" href={a.source_url} target="_blank" rel="noreferrer">원문 게시글</a>}>
        <div className="profile-line small">
          <span>{a.announcement_no}</span>
          <span>{a.agency_name}</span>
          {a.posted_on && <span>게시 {fmtDay(a.posted_on)}</span>}
          <span>{KIND_LABELS[a.source_kind ?? ''] ?? '직접 입력'}</span>
          <span className={`badge ${a.status === 'PUBLISHED' ? 'badge-ok' : 'badge-warn'}`}>{a.status === 'PUBLISHED' ? '공개' : '작성 중'}</span>
          {a.requirements_confirmed_at && <span>조건 확인 {fmtDate(a.requirements_confirmed_at)}</span>}
        </div>
      </Card>

      <div className="grid-2">
        <Card title="원문">
          <SourceView src={src.data} loading={src.loading} />
        </Card>

        <Card title="확인할 내용" actions={canEdit && (
          <button className="btn btn-sm" disabled={busy} onClick={() => void doExtract()}>
            {busy ? '뽑는 중…' : rows.length ? '조건 다시 뽑기' : '조건 뽑기'}
          </button>
        )}>
          {ex && (
            <p className="small muted">
              {ex.extractor === 'rules' ? '규칙으로 뽑은 후보입니다.' : 'AI 가 뽑은 후보입니다.'} 원문과 대조해 고치고 저장하세요.
            </p>
          )}
          {ex?.warnings.map((w) => <div key={w} className="notice small" style={{ marginBottom: 6 }}>{w}</div>)}
          {msg && <div className="notice notice-ok small" style={{ marginBottom: 6 }}>{msg}</div>}

          <div className="form">
            <div className="form-row">
              <label>접수 시작<input type="date" value={fields.receipt_start ?? ''} onChange={(e) => setFields({ ...fields, receipt_start: e.target.value || null })} /></label>
              <label>접수 마감<input type="date" value={fields.receipt_end ?? ''} onChange={(e) => setFields({ ...fields, receipt_end: e.target.value || null })} /></label>
            </div>
            <div className="form-row">
              <label>지원 한도 (원){fields.support_amount_krw ? ` · ${fmtKrw(fields.support_amount_krw)}` : ''}
                <input type="number" min={0} value={fields.support_amount_krw ?? ''} onChange={(e) => setFields({ ...fields, support_amount_krw: e.target.value ? Number(e.target.value) : null })} /></label>
              <label>지원 기간 (개월)<input type="number" min={1} value={fields.support_period_months ?? ''} onChange={(e) => setFields({ ...fields, support_period_months: e.target.value ? Number(e.target.value) : null })} /></label>
            </div>
            <label>지원 대상<textarea rows={2} value={fields.target_desc ?? ''} onChange={(e) => setFields({ ...fields, target_desc: e.target.value || null })} /></label>
            <label>사업 목적<textarea rows={2} value={fields.summary ?? ''} onChange={(e) => setFields({ ...fields, summary: e.target.value || null })} /></label>
            <label>기업부담<input value={fields.company_burden ?? ''} placeholder="예: 총사업비의 25%"
              onChange={(e) => setFields({ ...fields, company_burden: e.target.value || null })} /></label>
          </div>

          <h4 style={{ margin: '16px 0 6px' }}>제출서류</h4>
          <div className="stack" style={{ gap: 6 }}>
            {(fields.submit_documents ?? []).map((d, i) => {
              const setDoc = (patch: Partial<typeof d>) => setFields({ ...fields,
                submit_documents: (fields.submit_documents ?? []).map((x, j) => (j === i ? { ...x, ...patch } : x)) })
              return (
                <div key={i} className="form-row">
                  <input value={d.name} placeholder="서류 이름" onChange={(e) => setDoc({ name: e.target.value })} />
                  <select value={d.required ? '1' : '0'} style={{ flex: '0 0 90px' }} onChange={(e) => setDoc({ required: e.target.value === '1' })}>
                    <option value="1">필수</option><option value="0">해당 시</option>
                  </select>
                  <button className="btn btn-sm btn-ghost"
                    onClick={() => setFields({ ...fields, submit_documents: (fields.submit_documents ?? []).filter((_, j) => j !== i) })}>삭제</button>
                </div>
              )
            })}
          </div>
          <button className="btn btn-sm" style={{ marginTop: 8 }}
            onClick={() => setFields({ ...fields, submit_documents: [...(fields.submit_documents ?? []), { name: '', required: true }] })}>서류 추가</button>

          <h4 style={{ margin: '16px 0 6px' }}>평가항목·배점 (합계 {(evals ?? []).reduce((n, e) => n + (Number(e.points) || 0), 0)}점)</h4>
          <p className="small muted">평가항목은 기업 상담의 적합도(상·중·하) 계산에 씁니다.</p>
          <div className="stack" style={{ gap: 10 }}>
            {(evals ?? []).map((e, i) => {
              const setEv = (patch: Partial<EvalItem>) => setEvals((xs) => (xs ?? []).map((x, j) => (j === i ? { ...x, ...patch } : x)))
              return (
                <div key={i} className="req-edit">
                  <div className="form-row">
                    <input value={e.name} placeholder="평가항목 이름" onChange={(ev) => setEv({ name: ev.target.value })} />
                    <input type="number" min={0} step={0.5} style={{ flex: '0 0 80px' }} value={e.points} title="배점"
                      onChange={(ev) => setEv({ points: Number(ev.target.value) })} />
                    <select value={e.kind} style={{ flex: '0 0 120px' }} onChange={(ev) => setEv({ kind: ev.target.value as EvalItem['kind'] })}>
                      {KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                    <button className="btn btn-sm btn-ghost" onClick={() => setEvals((xs) => (xs ?? []).filter((_, j) => j !== i))}>삭제</button>
                  </div>
                  {e.kind === 'CAPABILITY' && (
                    <div className="chips" style={{ marginTop: 0 }}>
                      {AREAS.map(([code, label]) => {
                        const on = e.areas.includes(code)
                        return <button key={code} type="button" className={`chip ${on ? 'chip-on' : ''}`}
                          onClick={() => setEv({ areas: on ? e.areas.filter((a) => a !== code) : [...e.areas, code] })}>{label}</button>
                      })}
                    </div>
                  )}
                  <input value={e.source_quote ?? ''} placeholder="근거 조항 (공고문 인용)" onChange={(ev) => setEv({ source_quote: ev.target.value || null })} />
                </div>
              )
            })}
          </div>
          {canEdit && <button className="btn btn-sm" style={{ marginTop: 8 }}
            onClick={() => setEvals((xs) => [...(xs ?? []), { name: '', points: 10, kind: 'CAPABILITY', areas: [] }])}>평가항목 추가</button>}

          <h4 style={{ margin: '16px 0 6px' }}>지원 조건 {rows.length}개 (필수 {rows.filter((r) => r.is_mandatory).length})</h4>
          {!rows.length && <Empty>아직 조건이 없습니다. ‘조건 뽑기’를 누르거나 직접 추가하세요.</Empty>}
          <div className="stack" style={{ gap: 10 }}>
            {rows.map((r, i) => (
              <div key={i} className="req-edit">
                <div className="form-row">
                  <select value={r.req_type_code} onChange={(e) => {
                    const t = types.data?.types.find((x) => x.code === e.target.value)
                    setRow(i, { req_type_code: e.target.value, ruleText: JSON.stringify(t?.rule_example ?? {}) })
                  }}>
                    {(types.data?.types ?? [{ code: r.req_type_code, name_ko: typeName(r.req_type_code) }]).map((t) => (
                      <option key={t.code} value={t.code}>{t.name_ko}</option>
                    ))}
                  </select>
                  <select value={r.is_mandatory ? '1' : '0'} onChange={(e) => setRow(i, { is_mandatory: e.target.value === '1' })}>
                    <option value="1">필수</option><option value="0">우대</option>
                  </select>
                  <button className="btn btn-sm btn-ghost" onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>삭제</button>
                </div>
                <input value={r.description} placeholder="조건 문장 (기업에게 보이는 문장)" onChange={(e) => setRow(i, { description: e.target.value })} />
                {!r.is_mandatory && (
                  <label className="small">우대 가점
                    <input type="number" min={0} max={100} step={0.5} style={{ width: 90, marginLeft: 6 }} value={r.bonus_points ?? ''}
                      onChange={(e) => setRow(i, { bonus_points: e.target.value ? Number(e.target.value) : null })} /> 점
                  </label>
                )}
                {r.req_type_code === 'DUPLICATE_SUPPORT' && (
                  <label className="small">최근
                    <input type="number" min={1} style={{ width: 70, margin: '0 6px' }}
                      value={Number(parseRule(r.ruleText).within_years ?? 1)}
                      onChange={(e) => setRow(i, { ruleText: JSON.stringify({ within_years: Number(e.target.value) || 1 }), ruleError: undefined })} />
                    년 내 같은 사업 수혜 제한
                  </label>
                )}
                {r.req_type_code === 'NO_DISQUALIFICATION' && (
                  <div className="chips" style={{ marginTop: 0 }}>
                    {DISQ.map(([code, label]) => {
                      const cur = (parseRule(r.ruleText).checks as string[] | undefined) ?? []
                      const on = cur.includes(code)
                      return (
                        <button key={code} type="button" className={`chip ${on ? 'chip-on' : ''}`}
                          onClick={() => {
                            const next = on ? cur.filter((x) => x !== code) : [...cur, code]
                            if (next.length) setRow(i, { ruleText: JSON.stringify({ ...parseRule(r.ruleText), checks: next }), ruleError: undefined })
                          }}>{label}</button>
                      )
                    })}
                  </div>
                )}
                {r.req_type_code !== 'OTHER' && (
                  <input className="mono small" value={r.ruleText} title="판정에 쓰는 규칙"
                    onChange={(e) => setRow(i, { ruleText: e.target.value, ruleError: undefined })} />
                )}
                {r.ruleError && <span className="small" style={{ color: 'var(--bad)' }}>{r.ruleError}</span>}
                {r.source_quote && (
                  <div className="small muted">
                    근거: “{r.source_quote}” {r.quote_found === false && <span className="badge badge-warn">원문에서 못 찾음</span>}
                  </div>
                )}
              </div>
            ))}
          </div>
          {canEdit && <button className="btn btn-sm" style={{ marginTop: 8 }} onClick={addRow}>조건 추가</button>}

          <h4 style={{ margin: '16px 0 6px' }}>요구 기술</h4>
          <div className="stack" style={{ gap: 6 }}>
            {techs.map((t, i) => (
              <div key={i} className="form-row">
                <input value={t.tech_name} placeholder="예: 데이터링크 모뎀" onChange={(e) => setTechs((ts) => ts.map((x, j) => (j === i ? { ...x, tech_name: e.target.value } : x)))} />
                <label className="check" style={{ flex: '0 0 auto', flexDirection: 'row' }}>
                  <input type="checkbox" checked={t.is_core} onChange={(e) => setTechs((ts) => ts.map((x, j) => (j === i ? { ...x, is_core: e.target.checked } : x)))} /> 핵심
                </label>
                <button className="btn btn-sm btn-ghost" onClick={() => setTechs((ts) => ts.filter((_, j) => j !== i))}>삭제</button>
              </div>
            ))}
          </div>
          {canEdit && <button className="btn btn-sm" style={{ marginTop: 8 }} onClick={() => setTechs((ts) => [...ts, { tech_name: '', is_core: true }])}>기술 추가</button>}

          {canEdit && (
            <div className="form-foot" style={{ marginTop: 16 }}>
              <button className="btn" disabled={busy} onClick={() => save(false)}>확인 완료로 저장</button>
              <button className="btn btn-primary" disabled={busy || !rows.length}
                title={rows.length ? '저장하고 공개합니다. 알림을 신청한 기업에 알립니다.' : '조건이 있어야 공개할 수 있습니다'}
                onClick={() => save(true)}>
                {a.status === 'PUBLISHED' ? '저장 (공개 중)' : '확인하고 공개'}
              </button>
            </div>
          )}
        </Card>
      </div>
    </>
  )
}

function SourceView({ src, loading }: { src: AnnSource | null; loading: boolean }) {
  if (loading) return <div className="page-loading">불러오는 중…</div>
  if (!src) return <Empty>원문을 불러오지 못했습니다.</Empty>
  return (
    <div className="stack" style={{ gap: 10 }}>
      {src.body_text && (
        <details open>
          <summary><strong>게시글 본문</strong></summary>
          <pre className="source-text">{src.body_text}</pre>
        </details>
      )}
      {src.attachments.map((t, i) => (
        <details key={t.id ?? `doc-${i}`} open={!src.body_text && i === 0}>
          <summary>
            <strong>{t.file_name}</strong>{' '}
            {t.parse_status === 'PARSED'
              ? <span className="badge badge-ok">글자 추출</span>
              : <span className="badge badge-muted" title={t.parse_note ?? ''}>{t.parse_note ?? '읽지 않음'}</span>}
          </summary>
          {t.text_content ? <pre className="source-text">{t.text_content}</pre>
            : t.source_url && <a className="small" href={t.source_url} target="_blank" rel="noreferrer">파일 받기</a>}
        </details>
      ))}
      {!src.body_text && !src.attachments.length && <Empty>공고문 글자가 없습니다.</Empty>}
    </div>
  )
}

function clean(f: AnnFields): AnnFields {
  return Object.fromEntries(Object.entries(f).filter(([, v]) => v !== undefined)) as AnnFields
}
