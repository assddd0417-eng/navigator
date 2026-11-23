import { useEffect, useState } from 'react'
import { activateCriteria, getCriteria, saveCriteria, type CheckItem, type CheckKind, type CriteriaView, type FitRule } from '../../api/navigator'
import { useAuth } from '../../auth/AuthContext'
import { useToast } from '../../components/Toast'
import { Card, Empty, fmtDate, PageHeader, useAction, useAsync } from '../../components/ui'

const KINDS: { code: CheckKind; label: string }[] = [
  { code: 'MANDATORY', label: '필수요건' },
  { code: 'FIT', label: '적합도' },
  { code: 'GUIDE', label: '안내' },
]

type Nums = Omit<FitRule, 'version'>
const FIELDS: { key: keyof Nums; label: string }[] = [
  { key: 'capability_full', label: '역량 충분 경계' },
  { key: 'capability_partial', label: '역량 부분 경계' },
  { key: 'grade_high', label: '적합도 상 경계' },
  { key: 'grade_mid', label: '적합도 중 경계' },
  { key: 'partial_ratio', label: '부분 충족 비율(%)' },
]

export function ruleText(n: Nums): string {
  return `역량: ${n.capability_full}점 이상 충분, ${n.capability_partial}~${n.capability_full - 1}점 부분, ${n.capability_partial}점 미만 미흡`
    + ` · 등급: 상 ${n.grade_high}점 이상, 중 ${n.grade_mid}~${n.grade_high - 1}점, 하 ${n.grade_mid}점 미만`
    + ` · 부분 충족 ${n.partial_ratio}%`
}

export function CriteriaPage() {
  const { role } = useAuth()
  const canEdit = role === 'PROGRAM_OWNER' || role === 'AX_ADMIN'
  const view = useAsync(getCriteria, [])
  return (
    <>
      <PageHeader title="판정기준" subtitle="공고문 점검 항목과 적합도 판정 기준입니다. 소관부서 협의로 정하고 모든 공고에 공통 적용합니다." />
      {view.loading ? <div className="page-loading">불러오는 중…</div> : !view.data ? <Card><Empty>불러오지 못했습니다.</Empty></Card> : (
        <CriteriaEditor key={view.data.active.version ?? 0} view={view.data} canEdit={canEdit} onChanged={() => void view.reload()} />
      )}
    </>
  )
}

function CriteriaEditor({ view, canEdit, onChanged }: { view: CriteriaView; canEdit: boolean; onChanged: () => void }) {
  const a = view.active
  const [nums, setNums] = useState<Nums>({
    capability_full: a.capability_full, capability_partial: a.capability_partial,
    grade_high: a.grade_high, grade_mid: a.grade_mid, partial_ratio: a.partial_ratio,
  })
  const [items, setItems] = useState<CheckItem[]>(a.check_items.map((x) => ({ item: x.item, content: x.content, kind: x.kind })))
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const { busy, run } = useAction()
  const toast = useToast()
  useEffect(() => setError(null), [nums, items])

  const setItem = (i: number, patch: Partial<CheckItem>) => setItems(items.map((x, j) => (j === i ? { ...x, ...patch } : x)))
  const save = () => run(async () => {
    try {
      await saveCriteria({ ...nums, check_items: items.map(({ item, content, kind }) => ({ item: item.trim(), content: content.trim(), kind })), note: note.trim() || undefined })
      toast.show({ kind: 'success', title: '새 버전으로 저장했습니다' })
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장하지 못했습니다')
      throw e
    }
  })
  const activate = (v: number) => run(async () => {
    await activateCriteria(v)
    toast.show({ kind: 'success', title: `v${v}을 사용합니다` })
    onChanged()
  })

  return (
    <>
      <Card title="공고문 점검 항목" actions={<span className="badge badge-ok">사용 중 v{a.version ?? '–'}</span>}>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>공고 항목</th><th>점검 내용</th><th>판정 구분</th>{canEdit && <th />}</tr></thead>
            <tbody>
              {items.map((x, i) => (
                <tr key={i}>
                  <td>{canEdit ? <input value={x.item} onChange={(e) => setItem(i, { item: e.target.value })} aria-label="공고 항목" /> : x.item}</td>
                  <td>{canEdit ? <input value={x.content} onChange={(e) => setItem(i, { content: e.target.value })} aria-label="점검 내용" /> : x.content}</td>
                  <td>
                    {canEdit ? (
                      <select value={x.kind} onChange={(e) => setItem(i, { kind: e.target.value as CheckKind })} aria-label="판정 구분">
                        {KINDS.map((k) => <option key={k.code} value={k.code}>{k.label}</option>)}
                      </select>
                    ) : KINDS.find((k) => k.code === x.kind)?.label ?? x.kind}
                  </td>
                  {canEdit && <td><button className="btn btn-sm" onClick={() => setItems(items.filter((_, j) => j !== i))}>삭제</button></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {canEdit && <div style={{ marginTop: 8 }}>
          <button className="btn btn-sm" onClick={() => setItems([...items, { item: '', content: '', kind: 'FIT' }])}>항목 추가</button>
        </div>}
      </Card>

      <Card title="판정 경계">
        <div className="form">
          <div className="grid-2">
            {FIELDS.map((f) => (
              <label key={f.key}>
                {f.label}
                <input type="number" min={1} max={f.key === 'partial_ratio' ? 99 : 100} value={nums[f.key]} readOnly={!canEdit}
                  onChange={(e) => setNums({ ...nums, [f.key]: Number(e.target.value) })} />
              </label>
            ))}
          </div>
          <p className="small">{ruleText(nums)}</p>
          {canEdit ? (
            <>
              <label>
                바꾼 이유 (협의 내용)
                <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="예: 방산사업팀 협의에 따라 상 경계를 70점으로 조정" />
              </label>
              {error && <div className="notice notice-warn">{error}</div>}
              <div>
                <button className="btn btn-primary" disabled={busy || items.length === 0} onClick={() => void save()}>
                  {busy ? '저장 중…' : '새 버전으로 저장'}
                </button>
              </div>
            </>
          ) : <p className="small muted">수정은 소관부서와 AX 주관부서만 할 수 있습니다.</p>}
        </div>
      </Card>

      <Card title="버전 기록">
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>버전</th><th>바꾼 이유</th><th>기준</th><th>작성자</th><th>시각</th><th /></tr></thead>
            <tbody>
              {view.history.map((h) => {
                const s = h.settings as Partial<Nums>
                const ok = [s.capability_full, s.capability_partial, s.grade_high, s.grade_mid, s.partial_ratio].every((n) => typeof n === 'number')
                return (
                  <tr key={h.id}>
                    <td>v{h.version} {h.is_active && <span className="badge badge-ok">사용 중</span>}</td>
                    <td>{h.note || '–'}</td>
                    <td className="small">{ok ? ruleText(s as Nums) : '–'}</td>
                    <td>{h.created_by_name ?? '–'}</td>
                    <td>{fmtDate(h.created_at)}</td>
                    <td>{canEdit && !h.is_active && <button className="btn btn-sm" disabled={busy} onClick={() => void activate(h.version)}>이 버전 사용</button>}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}
