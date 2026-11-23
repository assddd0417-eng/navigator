import { useState } from 'react'
import { listDstateVariables, updateDstateVariable, type DstateVariableDef } from '../../api/navigator'
import { useAuth } from '../../auth/AuthContext'
import { useToast } from '../../components/Toast'
import { Card, Empty, fmtDate, PageHeader, useAction, useAsync } from '../../components/ui'

const AREA_KO: Record<string, string> = {
  TECH: '기술', QUALITY: '품질·인증', PRODUCTION: '생산·공급망', BUSINESS: '사업화·재무', DEFENSE: '방산진입', EXPORT: '수출',
}

const TYPE_LABEL: Record<DstateVariableDef['value_type'], string> = { LEVEL: '단계', INTEGER: '정수', PROFILE: '회사 정보' }

export function VariablesPage() {
  const { role } = useAuth()
  const canEdit = role === 'AX_ADMIN'
  const list = useAsync(listDstateVariables, [])
  const [editing, setEditing] = useState<string | null>(null)
  return (
    <>
      <PageHeader title="진단 변수사전" subtitle="변수 이름과 설명, 보완 질문만 고칩니다. 산정식과 값 유형은 진단 기준을 따릅니다." />
      <Card>
        {list.loading ? <div className="page-loading">불러오는 중…</div> : !list.data?.length ? <Empty>변수가 없습니다.</Empty> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>변수</th><th>정의</th><th>값 유형</th><th>영역</th><th>증빙 원천</th><th>보완 질문</th><th>최근 수정</th>{canEdit && <th />}</tr></thead>
              <tbody>
                {list.data.map((v) => editing === v.code ? (
                  <VariableEditRow key={v.code} v={v} onDone={(changed) => { setEditing(null); if (changed) void list.reload() }} />
                ) : (
                  <tr key={v.code}>
                    <td>{v.name_ko}<div className="small muted">{v.code}</div></td>
                    <td className="small">{v.definition}</td>
                    <td className="small">{TYPE_LABEL[v.value_type]}
                      {v.options.length > 0 && <div className="muted">{v.options.map((o) => o.label).join(', ')}</div>}</td>
                    <td className="small">{v.areas.map((a) => AREA_KO[a] ?? a).join(', ') || '–'}</td>
                    <td className="small">{v.source_desc}</td>
                    <td className="small">{v.value_type === 'PROFILE' ? <span className="muted">회사 정보에서 읽음</span> : v.question || '–'}</td>
                    <td className="small">{v.updated_at ? `${fmtDate(v.updated_at)} ${v.updated_by_name ?? ''}` : '–'}</td>
                    {canEdit && <td><button className="btn btn-sm" onClick={() => setEditing(v.code)}>고치기</button></td>}
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

function VariableEditRow({ v, onDone }: { v: DstateVariableDef; onDone: (changed: boolean) => void }) {
  const [name, setName] = useState(v.name_ko)
  const [def, setDef] = useState(v.definition)
  const [source, setSource] = useState(v.source_desc)
  const [question, setQuestion] = useState(v.question ?? '')
  const [labels, setLabels] = useState<Record<string, string>>(Object.fromEntries(v.options.map((o) => [o.code, o.label])))
  const { busy, run } = useAction()
  const toast = useToast()
  const profile = v.value_type === 'PROFILE'
  const save = () => run(async () => {
    const changedLabels = Object.fromEntries(v.options.filter((o) => labels[o.code].trim() && labels[o.code] !== o.label).map((o) => [o.code, labels[o.code].trim()]))
    await updateDstateVariable(v.code, {
      name_ko: name.trim(), definition: def.trim(), source_desc: source.trim(),
      ...(profile ? {} : { question: question.trim() }),
      ...(Object.keys(changedLabels).length ? { option_labels: changedLabels } : {}),
    })
    toast.show({ kind: 'success', title: '저장했습니다' })
    onDone(true)
  })
  return (
    <tr>
      <td><input value={name} onChange={(e) => setName(e.target.value)} aria-label="변수 이름" maxLength={50} /><div className="small muted">{v.code}</div></td>
      <td><textarea rows={3} value={def} onChange={(e) => setDef(e.target.value)} aria-label="정의" maxLength={500} /></td>
      <td className="small">{TYPE_LABEL[v.value_type]}
        {v.options.map((o) => (
          <input key={o.code} value={labels[o.code]} aria-label={`선택지 ${o.code}`} style={{ display: 'block', marginTop: 4 }}
            onChange={(e) => setLabels({ ...labels, [o.code]: e.target.value })} />
        ))}
      </td>
      <td className="small">{v.areas.map((a) => AREA_KO[a] ?? a).join(', ') || '–'}</td>
      <td><input value={source} onChange={(e) => setSource(e.target.value)} aria-label="증빙 원천" maxLength={200} /></td>
      <td>{profile ? <span className="small muted">회사 정보에서 읽음</span>
        : <textarea rows={3} value={question} onChange={(e) => setQuestion(e.target.value)} aria-label="보완 질문" maxLength={300} />}</td>
      <td className="small">{v.updated_at ? fmtDate(v.updated_at) : '–'}</td>
      <td style={{ whiteSpace: 'nowrap' }}>
        <button className="btn btn-sm btn-primary" disabled={busy || !name.trim() || !def.trim() || !source.trim()} onClick={() => void save()}>저장</button>{' '}
        <button className="btn btn-sm" disabled={busy} onClick={() => onDone(false)}>취소</button>
      </td>
    </tr>
  )
}
