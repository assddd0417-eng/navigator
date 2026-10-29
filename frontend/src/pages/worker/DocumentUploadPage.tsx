import { useState, type ChangeEvent, type FormEvent } from 'react'
import { createCard, createDocument, listDocuments, type DocumentCreated } from '../../api/endpoints'
import { useAuth } from '../../auth/AuthContext'
import { useToast } from '../../components/Toast'
import { Card, Empty, fmtDate, PageHeader, RoleHint, StatusBadge, useAction, useAsync } from '../../components/ui'

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

/** 빈 줄 기준으로 문단을 나눠 RAG 청크로 만든다 (실제 PDF 파싱·청킹은 별도 파이프라인). */
const toChunks = (text: string) => text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean)

function UploadForm({ onUploaded }: { onUploaded: (doc: DocumentCreated, projectId: number, title: string) => void }) {
  const toast = useToast()
  const { busy, run } = useAction()
  const [f, setF] = useState({ title: '', doc_type: 'FINAL_REPORT', project: '1', section_no: '', heading: '', page: '', text: '' })
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  const chunks = toChunks(f.text)

  const readFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const text = await file.text()
    setF((prev) => ({ ...prev, text, title: prev.title || file.name.replace(/\.[^.]+$/, '') }))
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const project = PROJECTS.find((p) => p.id === Number(f.project))!
    const page = f.page ? Number(f.page) : null
    const hasSection = Boolean(f.section_no || f.heading)
    const res = await run(() => createDocument({
      doc_type_code: f.doc_type, title: f.title, project_id: project.id, owner_dept_id: project.dept,
      sections: hasSection ? [{ key: 's1', section_no: f.section_no || undefined, heading: f.heading || undefined,
        page_start: page ?? undefined, page_end: page ?? undefined }] : [],
      chunks: chunks.map((content) => ({ content, section_key: hasSection ? 's1' : undefined, page_start: page, page_end: page })),
    }))
    if (res) {
      toast.success('문서를 등록했습니다', `청크 ${res.chunk_ids.length}개 · 임베딩 ${res.embedded}개`)
      onUploaded(res, project.id, f.title)
      setF({ ...f, title: '', text: '' })
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <label className="file-drop">
        <input type="file" accept=".txt,.md,text/plain" onChange={(e) => void readFile(e)} />
        <span>📄 텍스트 파일(.txt, .md)을 선택하거나 아래에 본문을 붙여넣으세요</span>
      </label>
      <div className="form-row">
        <label className="grow">문서 제목<input value={f.title} onChange={set('title')} required /></label>
        <label>문서 유형<select value={f.doc_type} onChange={set('doc_type')}>
          {DOC_TYPES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
        </select></label>
      </div>
      <label>과제<select value={f.project} onChange={set('project')}>
        {PROJECTS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
      </select></label>
      <div className="form-row">
        <label>조항 번호<input value={f.section_no} onChange={set('section_no')} placeholder="4.3" /></label>
        <label className="grow">조항 제목<input value={f.heading} onChange={set('heading')} placeholder="미해결 기술 및 후속 연구 필요사항" /></label>
        <label>쪽<input type="number" min={1} value={f.page} onChange={set('page')} placeholder="88" /></label>
      </div>
      <label>본문 (빈 줄로 문단 구분 → 문단마다 검색용 청크 1개)
        <textarea rows={8} value={f.text} onChange={set('text')} required /></label>
      <div className="form-foot">
        <span className="muted small">청크 {chunks.length}개 예정</span>
        <RoleHint roles={['CURATOR', 'PLANNER']} />
        <button className="btn btn-primary" disabled={busy || chunks.length === 0}>{busy ? '등록 중…' : '문서 등록'}</button>
      </div>
    </form>
  )
}

function CardDraftForm({ doc, projectId, docTitle, onDone }:
  { doc: DocumentCreated; projectId: number; docTitle: string; onDone: () => void }) {
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
      toast.success('성과카드 초안을 만들었습니다', '내 작업에서 검수 후 발행하세요')
      onDone()
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <p className="muted small">방금 등록한 문서의 청크 {doc.chunk_ids.length}개가 원문 근거로 자동 연결됩니다.</p>
      <div className="form-row">
        <label>카드번호<input value={f.card_no} onChange={set('card_no')} required /></label>
        <label className="grow">제목<input value={f.title} onChange={set('title')} required /></label>
        <label>TRL<input type="number" min={1} max={9} value={f.trl} onChange={set('trl')} /></label>
      </div>
      <label>핵심 성과<textarea rows={2} value={f.core} onChange={set('core')} required /></label>
      <label>핵심 기술<input value={f.tech} onChange={set('tech')} placeholder="주파수 도약 항재밍 데이터링크" /></label>
      <div className="form-foot">
        <RoleHint roles={['CURATOR', 'PLANNER']} />
        <button type="button" className="btn btn-ghost" onClick={onDone}>건너뛰기</button>
        <button className="btn btn-primary" disabled={busy}>{busy ? '저장 중…' : '성과카드 초안 저장'}</button>
      </div>
    </form>
  )
}

/** 작업자: 원문 문서 업로드 → 성과카드 초안 작성 */
export function DocumentUploadPage() {
  const { role } = useAuth()
  const docs = useAsync(() => listDocuments())
  const [uploaded, setUploaded] = useState<{ doc: DocumentCreated; projectId: number; title: string } | null>(null)

  return (
    <>
      <PageHeader title="문서 업로드" subtitle="과제 결과보고서 등 원문을 올리면 AI 검색용으로 나뉘어 저장되고, 성과카드의 근거가 됩니다." />
      {role === 'EXPERT' && (
        <div className="notice">전문가 역할은 문서 등록 권한이 없습니다. 등록을 시도하면 서버가 거부(403)하는 것을 확인할 수 있습니다.</div>
      )}
      <div className="grid-2">
        <Card title="① 원문 문서 등록">
          <UploadForm onUploaded={(doc, projectId, title) => { setUploaded({ doc, projectId, title }); void docs.reload() }} />
        </Card>
        <Card title="② 성과카드 초안 작성">
          {uploaded
            ? <CardDraftForm key={uploaded.doc.id} doc={uploaded.doc} projectId={uploaded.projectId} docTitle={uploaded.title}
                onDone={() => setUploaded(null)} />
            : <Empty>문서를 등록하면 그 내용을 근거로 성과카드 초안을 만들 수 있습니다.</Empty>}
        </Card>
      </div>
      <Card title="문서 처리 현황">
        {docs.data?.length === 0 ? <Empty>열람할 수 있는 문서가 없습니다.</Empty> : (
          <table className="table">
            <thead><tr><th>ID</th><th>제목</th><th>유형</th><th>청크</th><th>처리 상태</th><th>등록일</th></tr></thead>
            <tbody>
              {docs.data?.map((d) => (
                <tr key={d.id}>
                  <td>{d.id}</td><td>{d.title}</td><td>{d.doc_type_name}</td><td>{d.chunk_count}</td>
                  <td><StatusBadge status={d.parse_status} /></td><td>{fmtDate(d.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted small">보안등급·소관부서 열람권한에 따라 볼 수 있는 문서만 표시됩니다.</p>
      </Card>
    </>
  )
}
