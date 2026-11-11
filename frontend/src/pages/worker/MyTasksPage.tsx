import { Link } from 'react-router-dom'
import { getReviewQueue, listCards, publishCard, type CardRow } from '../../api/endpoints'
import { useAuth } from '../../auth/AuthContext'
import { QueueTable } from '../../components/QueueTable'
import { useToast } from '../../components/Toast'
import { Card, Empty, fmtDate, PageHeader, RoleHint, StatusBadge, Steps, useAction, useAsync } from '../../components/ui'

function DraftCards() {
  const toast = useToast()
  const { busy, run } = useAction()
  const { data, reload } = useAsync(() => listCards({ status: 'DRAFT' }))

  const publish = async (c: CardRow) => {
    // publishCard 는 204(본문 없음)라 성공 표시로 true 를 돌려받는다
    if (await run(() => publishCard(c.id).then(() => true))) {
      toast.success('성과카드를 발행했습니다', `‘${c.title}’이(가) 이제 AI 추천 대상이 됩니다`)
      void reload()
    }
  }

  return (
    <Card title={`발행 전 성과카드 ${data?.length ?? 0}장`} actions={<RoleHint roles={['CURATOR']} />}>
      {data?.length === 0 ? (
        <Empty>발행할 카드가 없습니다. <Link to="/documents/upload">문서 올리기</Link>에서 새 카드를 만들 수 있습니다.</Empty>
      ) : (
        <table className="table">
          <thead><tr><th>성과</th><th>과제</th><th>기술 성숙도</th><th>상태</th><th>고친 날</th><th /></tr></thead>
          <tbody>
            {data?.map((c) => (
              <tr key={c.id}>
                <td>{c.title}<div className="muted small">{c.card_no}</div></td><td>{c.project_title}<div className="muted small">{c.project_no}</div></td><td>{c.trl == null ? '–' : `${c.trl}단계`}</td>
                <td><StatusBadge status={c.status} /></td><td>{fmtDate(c.updated_at)}</td>
                <td><button className="btn btn-sm btn-primary" disabled={busy} onClick={() => void publish(c)} title="내용을 확인했으면 발행합니다. 발행된 카드만 AI 추천에 쓰입니다.">확인 완료 · 발행</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}

/** 작업자(큐레이터·전문가) 내 작업 목록 */
export function MyTasksPage() {
  const { role } = useAuth()
  const queue = useAsync(() => getReviewQueue(true))

  return (
    <>
      <PageHeader title="내 할 일"
        subtitle={role === 'CURATOR'
          ? '올린 보고서로 만든 성과카드를 확인해 발행하고, 나에게 온 검토 요청을 처리합니다.'
          : '나에게 온 추천을 기술 눈으로 검토하고 의견을 남깁니다.'} />
      <Steps items={role === 'CURATOR'
        ? ['‘문서 올리기’에서 결과보고서를 올리고 성과카드 초안을 만듭니다.', '아래 목록에서 내용을 확인하고 ‘확인 완료 · 발행’을 누릅니다.', '나에게 온 검토 요청이 있으면 ‘검토하기’로 처리합니다.']
        : ['아래 목록에서 ‘검토하기’를 누릅니다.', '추천 이유와 근거 문서를 읽고 채택·보류·제외 의견을 남깁니다. (최종 결정은 담당 부서 검수자가 합니다)']} />
      <Card title={`나에게 온 검토 요청 ${queue.data?.length ?? 0}건`}>
        {queue.loading && !queue.data ? <div className="page-loading">불러오는 중…</div>
          : <QueueTable rows={queue.data ?? []} empty="지금 온 검토 요청이 없습니다. 기획자가 요청하면 여기에 나타납니다." />}
      </Card>
      {role === 'CURATOR' && <DraftCards />}
    </>
  )
}
