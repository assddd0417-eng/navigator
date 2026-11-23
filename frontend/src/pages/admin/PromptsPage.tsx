import { useEffect, useState } from 'react'
import { activateAiPrompt, listAiPrompts, saveAiPrompt, type AiPrompt, type PromptCode } from '../../api/navigator'
import { useAuth } from '../../auth/AuthContext'
import { useToast } from '../../components/Toast'
import { Card, Empty, fmtDate, PageHeader, useAction, useAsync } from '../../components/ui'

const CODES: { code: PromptCode; label: string }[] = [
  { code: 'ELIGIBILITY_JUDGE', label: '자격 판단 지침' },
  { code: 'REPORT_DRAFT', label: '상담결과서 템플릿' },
]

export function PromptsPage() {
  const { role } = useAuth()
  const canEdit = role === 'AX_ADMIN'
  const list = useAsync(listAiPrompts, [])
  const [code, setCode] = useState<PromptCode>('ELIGIBILITY_JUDGE')
  const llm = list.data?.mode === 'llm'
  return (
    <>
      <PageHeader title="프롬프트 관리" subtitle="AI가 따르는 지침을 확인하고, 바꾸면 새 버전으로 남깁니다."
        actions={list.data && <span className={`badge badge-${llm ? 'ok' : 'muted'}`}>
          {llm ? 'AI 판단 켜짐' : 'AI 판단 꺼짐 (규칙으로 판정)'}</span>} />
      <div className="form-row" style={{ marginBottom: 12, gap: 8 }}>
        {CODES.map((c) => (
          <button key={c.code} className={`btn ${c.code === code ? 'btn-primary' : ''}`} onClick={() => setCode(c.code)}>{c.label}</button>
        ))}
      </div>
      {list.loading ? <div className="page-loading">불러오는 중…</div> : !list.data ? <Card><Empty>불러오지 못했습니다.</Empty></Card> : (
        <PromptEditor key={code} code={code} items={list.data.items.filter((p) => p.code === code)} canEdit={canEdit} reload={() => void list.reload()} />
      )}
    </>
  )
}

function PromptEditor({ code, items, canEdit, reload }: { code: PromptCode; items: AiPrompt[]; canEdit: boolean; reload: () => void }) {
  const active = items.find((p) => p.is_active) ?? items[0]
  const [showSystem, setShowSystem] = useState(false)
  const [system, setSystem] = useState('')
  const [guide, setGuide] = useState('')
  const [note, setNote] = useState('')
  const { busy, run } = useAction()
  const toast = useToast()
  useEffect(() => {
    setSystem(active?.system_text ?? '')
    setGuide(active?.guide_text ?? '')
    setNote('')
  }, [active?.id])

  if (!active) return <Card><Empty>등록된 지침이 없습니다.</Empty></Card>
  const changed = system !== active.system_text || guide !== active.guide_text

  const save = () => run(async () => {
    await saveAiPrompt(code, { title: active.title, system_text: system, guide_text: guide, note: note.trim() || undefined })
    toast.show({ kind: 'success', title: '새 버전으로 저장했습니다' })
    reload()
  })
  const activate = (p: AiPrompt) => run(async () => {
    await activateAiPrompt(code, p.id)
    toast.show({ kind: 'success', title: `v${p.version}을 사용합니다` })
    reload()
  })

  return (
    <>
      <Card title={`${active.title} v${active.version}`} actions={<span className="badge badge-ok">사용 중</span>}>
        <div className="form">
          <label>
            지침 (이 내용이 AI에게 전달됩니다)
            <textarea rows={10} value={guide} readOnly={!canEdit} onChange={(e) => setGuide(e.target.value)} />
          </label>
          <div>
            <button className="btn btn-sm" onClick={() => setShowSystem(!showSystem)}>형식 고치기</button>
            <span className="small muted"> 출력 형식과 규칙입니다. 보통은 건드리지 않습니다.</span>
          </div>
          {showSystem && (
            <label>
              형식
              <textarea rows={10} value={system} readOnly={!canEdit} onChange={(e) => setSystem(e.target.value)} />
            </label>
          )}
          {!showSystem && <textarea rows={4} value={system} readOnly aria-label="형식" />}
          {canEdit ? (
            <>
              <label>
                바꾼 이유
                <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="예: 인용 없는 판단은 확인 필요로 두도록 보강" />
              </label>
              <div>
                <button className="btn btn-primary" disabled={busy || !changed} onClick={() => void save()}>
                  {busy ? '저장 중…' : '새 버전으로 저장'}
                </button>
              </div>
            </>
          ) : <p className="small muted">수정은 AX 주관부서만 할 수 있습니다.</p>}
        </div>
      </Card>
      <Card title="버전 기록">
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>버전</th><th>바꾼 이유</th><th>작성자</th><th>시각</th><th /></tr></thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id}>
                  <td>v{p.version} {p.is_active && <span className="badge badge-ok">사용 중</span>}</td>
                  <td>{p.note || '–'}</td>
                  <td>{p.created_by_name ?? '–'}</td>
                  <td>{fmtDate(p.created_at)}</td>
                  <td>{canEdit && !p.is_active && <button className="btn btn-sm" disabled={busy} onClick={() => void activate(p)}>이 버전 사용</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}
