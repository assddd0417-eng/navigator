import { useState, type ChangeEvent, type FormEvent } from 'react'
import {
  createCard, createDocument, listDocuments, parseDocumentFile, uploadDocumentFile,
  type DocumentCreated, type ParsePreview,
} from '../../api/endpoints'
import { useAuth } from '../../auth/AuthContext'
import { useToast } from '../../components/Toast'
import { Link } from 'react-router-dom'
import { Card, Empty, fmtDate, More, PageHeader, RoleHint, StatusBadge, Steps, useAction, useAsync } from '../../components/ui'

const DOC_TYPES = [
  ['FINAL_REPORT', '결과보고서'], ['RND_PLAN', '연구개발계획서'], ['TEST_REPORT', '시험성적서'],
  ['PAPER', '논문'], ['PATENT', '특허·지재권'], ['EVALUATION', '평가자료'], ['OTHER', '기타'],
] as const

/** 시드 과제·부서 (seeds/init_test_data.sql). 과제의 소관부서가 문서 열람 권한을 정한다. */
const PROJECTS = [
  { id: 1, label: 'PRJ-2022-001 소형 무인기용 항재밍 데이터링크 개발', dept: 3 },
  { id: 2, label: 'PRJ-2021-007 전술 배터리 열관리 기술', dept: 2 },
  { id: 3, label: 'PRJ-2023-004 EO/IR 영상 기반 표적 자동탐지', dept: 2 },
]

/** 붙여넣은 텍스트는 빈 줄 기준으로 문단을 나눠 RAG 청크로 만든다. PDF 는 서버가 쪽 단위로 추출·청킹한다. */
const toChunks = (text: string) => text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean)

const isPdf = (file: File) => file.type === 'application/pdf' || /\.pdf$/i.test(file.name)

/** PDF 추출 미리보기: 쪽 수·청크 수·제외된 쪽 경고와 앞부분 청크 몇 개 */
function PdfPreview({ preview, onClear }: { preview: ParsePreview; onClear: () => void }) {
  return (
    <div className="pdf-preview">
      <div className="pdf-preview-head">
        <strong>📕 {preview.filename}</strong>
        <span className="muted small">
          {preview.page_count}쪽 · 글자 {preview.char_count.toLocaleString()}자 · 검색 단위 {preview.chunks.length}개
        </span>
        <button type="button" className="btn btn-ghost" onClick={onClear}>파일 빼기</button>
      </div>
      {preview.warnings.map((w) => <div key={w} className="notice small">{w}</div>)}
      <ul className="evidence">
        {preview.chunks.slice(0, 3).map((c, i) => (
          <li key={i}>
            <span className="evidence-src">{c.page_start}쪽</span>
            <blockquote>{c.content.length > 220 ? `${c.content.slice(0, 220)}…` : c.content}</blockquote>
          </li>
        ))}
      </ul>
      {preview.chunks.length > 3 && <p className="muted small">앞부분만 보여 줍니다 (외 {preview.chunks.length - 3}개 문단)</p>}
    </div>
  )
}

function UploadForm({ onUploaded }: { onUploaded: (doc: DocumentCreated, projectId: number, title: string) => void }) {
  const toast = useToast()
  const { busy, run } = useAction()
  const [f, setF] = useState({ title: '', doc_type: 'FINAL_REPORT', project: '1', section_no: '', heading: '', page: '', text: '' })
  const [pdf, setPdf] = useState<{ file: File; preview: ParsePreview } | null>(null)
  const [parsing, setParsing] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  const chunks = toChunks(f.text)
  const chunkCount = pdf ? pdf.preview.chunks.length : chunks.length

  const readFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const input = e.target
    const file = input.files?.[0]
    input.value = '' // 같은 파일을 다시 골라도 change 가 일어나도록
    if (!file) return
    const stem = file.name.replace(/\.[^.]+$/, '')
    if (!isPdf(file)) {
      const text = await file.text()
      setPdf(null)
      setF((prev) => ({ ...prev, text, title: prev.title || stem }))
      return
    }
    // PDF: 서버에서 텍스트 추출 → 미리보기 (스캔본·암호·손상 파일은 오류 토스트로 사유 표시)
    setParsing(true)
    try {
      const preview = await parseDocumentFile(file)
      setPdf({ file, preview })
      setF((prev) => ({ ...prev, text: '', title: prev.title || stem }))
    } catch {
      setPdf(null)
    } finally {
      setParsing(false)
    }
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const project = PROJECTS.find((p) => p.id === Number(f.project))!
    if (pdf) {
      const res = await run(() => uploadDocumentFile(pdf.file, {
        doc_type_code: f.doc_type, title: f.title, project_id: project.id, owner_dept_id: project.dept,
      }))
      if (res) {
        toast.success('PDF 문서를 올렸습니다', `${res.page_count}쪽을 읽어 검색할 수 있게 했습니다. 이어서 성과카드를 만들어 보세요.`)
        onUploaded(res, project.id, f.title)
        setPdf(null)
        setF({ ...f, title: '', text: '' })
      }
      return
    }
    const page = f.page ? Number(f.page) : null
    const hasSection = Boolean(f.section_no || f.heading)
    const res = await run(() => createDocument({
      doc_type_code: f.doc_type, title: f.title, project_id: project.id, owner_dept_id: project.dept,
      sections: hasSection ? [{ key: 's1', section_no: f.section_no || undefined, heading: f.heading || undefined,
        page_start: page ?? undefined, page_end: page ?? undefined }] : [],
      chunks: chunks.map((content) => ({ content, section_key: hasSection ? 's1' : undefined, page_start: page, page_end: page })),
    }))
    if (res) {
      toast.success('문서를 올렸습니다', `문단 ${res.chunk_ids.length}개를 검색할 수 있게 했습니다. 이어서 성과카드를 만들어 보세요.`)
      onUploaded(res, project.id, f.title)
      setF({ ...f, title: '', text: '' })
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <label className="file-drop">
        <input type="file" accept=".pdf,application/pdf,.txt,.md,text/plain" onChange={(e) => void readFile(e)} />
        <span>{parsing
          ? '⏳ PDF에서 글자를 읽는 중…'
          : '📄 여기를 눌러 PDF나 텍스트 파일을 고르세요 (또는 아래에 본문 붙여넣기)'}</span>
        <span className="muted small">스캔한 그림 PDF, 암호 걸린 PDF는 글자를 읽을 수 없습니다</span>
      </label>
      <div className="form-row">
        <label className="grow">문서 제목<input value={f.title} onChange={set('title')} required /></label>
        <label>문서 유형<select value={f.doc_type} onChange={set('doc_type')}>
          {DOC_TYPES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
        </select></label>
      </div>
      <label>어느 과제의 문서인가요? (과제 담당 부서가 이 문서를 볼 수 있게 됩니다)<select value={f.project} onChange={set('project')}>
        {PROJECTS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
      </select></label>
      {pdf ? <PdfPreview preview={pdf.preview} onClear={() => setPdf(null)} /> : (
        <>
          <label>본문 (문단 사이에 빈 줄을 넣으면 문단마다 따로 검색됩니다)
            <textarea rows={8} value={f.text} onChange={set('text')} required /></label>
          <More label="어느 장·쪽의 내용인지 적기 (선택 · 근거로 보여 줄 때 쓰임)">
            <div className="form-row">
              <label>장 번호<input value={f.section_no} onChange={set('section_no')} placeholder="4.3" /></label>
              <label className="grow">장 제목<input value={f.heading} onChange={set('heading')} placeholder="미해결 기술 및 후속 연구 필요사항" /></label>
              <label>쪽<input type="number" min={1} value={f.page} onChange={set('page')} placeholder="88" /></label>
            </div>
          </More>
        </>
      )}
      <div className="form-foot">
        <span className="muted small">{chunkCount ? `문단 ${chunkCount}개${pdf ? ' (쪽 번호 자동 기록)' : ''}` : '내용을 넣으면 올릴 수 있습니다'}</span>
        <RoleHint roles={['CURATOR', 'PLANNER']} />
        <button className="btn btn-primary" disabled={busy || parsing || chunkCount === 0}>
          {busy ? '올리는 중…' : '문서 올리기'}</button>
      </div>
    </form>
  )
}

function CardDraftForm({ doc, projectId, docTitle, onDone }:
  { doc: DocumentCreated; projectId: number; docTitle: string; onDone: (saved: boolean) => void }) {
  const toast = useToast()
  const { busy, run } = useAction()
  const [f, setF] = useState({
    card_no: `AC-${String(Date.now()).slice(-5)}`, title: docTitle, core: '', tech: '', trl: '5',
  })
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  const evidence = doc.chunk_ids.map((chunk_id) => ({ chunk_id }))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const res = await run(() => createCard({
      card_no: f.card_no, project_id: projectId, title: f.title, core_achievement: f.core,
      trl: f.trl ? Number(f.trl) : null,
      technologies: f.tech ? [{ tech_name: f.tech, is_primary: true, evidence }] : [],
      evidence,
    }))
    if (res) {
      toast.success('성과카드 초안을 만들었습니다', '‘내 할 일’에서 확인 후 발행하세요')
      onDone(true)
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <p className="muted small">방금 올린 문서가 이 카드의 근거로 자동 연결됩니다.</p>
      <div className="form-row">
        <label className="grow">성과 이름<input value={f.title} onChange={set('title')} required /></label>
        <label>기술 성숙도(TRL)<input type="number" min={1} max={9} value={f.trl} onChange={set('trl')} />
          <span className="hint">1 아이디어 ~ 9 실전 배치</span></label>
      </div>
      <label>무엇을 이뤘나요? (핵심 성과)<textarea rows={2} value={f.core} onChange={set('core')} required
        placeholder="예: 재밍 환경에서 데이터링크 동기 유지 시간 3배 향상" /></label>
      <label>핵심 기술<input value={f.tech} onChange={set('tech')} placeholder="주파수 도약 항재밍 데이터링크" /></label>
      <More label="관리 번호 (자동으로 만들어짐)">
        <label>카드 번호<input value={f.card_no} onChange={set('card_no')} required /></label>
      </More>
      <div className="form-foot">
        <RoleHint roles={['CURATOR', 'PLANNER']} />
        <button type="button" className="btn btn-ghost" onClick={() => onDone(false)}>나중에 만들기</button>
        <button className="btn btn-primary" disabled={busy}>{busy ? '저장 중…' : '성과카드 초안 저장'}</button>
      </div>
    </form>
  )
}

/** 작업자: 결과보고서 올리기 → 성과카드 초안 만들기 */
export function DocumentUploadPage() {
  const { role } = useAuth()
  const docs = useAsync(() => listDocuments())
  const [uploaded, setUploaded] = useState<{ doc: DocumentCreated; projectId: number; title: string } | null>(null)
  const [saved, setSaved] = useState(false)

  return (
    <>
      <PageHeader title="문서 올리기" subtitle="과제 결과보고서 같은 원문을 올리면 AI가 내용을 검색할 수 있게 정리하고, 성과카드의 근거로 씁니다." />
      {role === 'EXPERT' && (
        <div className="notice">🔒 전문가는 문서를 올릴 수 없습니다. 눌러 보면 서버가 막는 것을 확인할 수 있습니다.</div>
      )}
      <Steps items={['① 문서를 올립니다.', '② 그 문서로 성과카드 초안을 만듭니다.', <>③ <Link to="/my-tasks">내 할 일</Link>에서 확인 후 발행하면 AI 추천에 쓰입니다.</>]} />
      {saved && (
        <div className="notice notice-ok">✅ 성과카드 초안을 만들었습니다. <Link to="/my-tasks">내 할 일에서 발행하기 →</Link></div>
      )}
      <div className="grid-2">
        <Card title="① 문서 올리기">
          <UploadForm onUploaded={(doc, projectId, title) => { setUploaded({ doc, projectId, title }); setSaved(false); void docs.reload() }} />
        </Card>
        <Card title="② 성과카드 초안 만들기">
          {uploaded
            ? <CardDraftForm key={uploaded.doc.id} doc={uploaded.doc} projectId={uploaded.projectId} docTitle={uploaded.title}
                onDone={(ok) => { setUploaded(null); setSaved(ok) }} />
            : <Empty>왼쪽에서 문서를 올리면 그 내용을 근거로 성과카드 초안을 만들 수 있습니다.</Empty>}
        </Card>
      </div>
      <Card title="올린 문서">
        {docs.loading && !docs.data ? <div className="page-loading">불러오는 중…</div> : docs.data?.length === 0 ? <Empty>볼 수 있는 문서가 없습니다.</Empty> : (
          <table className="table">
            <thead><tr><th>제목</th><th>종류</th><th>문단 수</th><th>처리 상태</th><th>올린 날</th></tr></thead>
            <tbody>
              {docs.data?.map((d) => (
                <tr key={d.id}>
                  <td>{d.title}</td><td>{d.doc_type_name}</td><td>{d.chunk_count}</td>
                  <td><StatusBadge status={d.parse_status} /></td><td>{fmtDate(d.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted small">내 부서·보안등급으로 볼 수 있는 문서만 보입니다. ‘검색 가능’이 되면 AI 추천의 근거로 쓰입니다.</p>
      </Card>
    </>
  )
}
