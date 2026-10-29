import { Link } from 'react-router-dom'
import { getReviewQueue, listCards, publishCard, type CardRow } from '../../api/endpoints'
import { useAuth } from '../../auth/AuthContext'
import { QueueTable } from '../../components/QueueTable'
import { useToast } from '../../components/Toast'
import { Card, Empty, fmtDate, PageHeader, RoleHint, StatusBadge, useAction, useAsync } from '../../components/ui'

function DraftCards() {
  const toast = useToast()
  const { busy, run } = useAction()
  const { data, reload } = useAsync(() => listCards({ status: 'DRAFT' }))

  const publish = async (c: CardRow) => {
    // publishCard 는 204(본문 없음)라 성공 표시로 true 를 돌려받는다
    if (await run(() => publishCard(c.id).then(() => true))) {
      toast.success('성과카드를 발행했습니다', `${c.card_no} 이(가) 매칭 대상이 됩니다`)
      void reload()
    }
  }

  return (
    <Card title="검수 대기 성과카드 (초안)" actions={<RoleHint roles={['CURATOR']} />}>
      {data?.length === 0 ? (
        <Empty>검수할 초안이 없습니다. <Link to="/documents/upload">문서 업로드</Link>에서 새 카드를 만들 수 있습니다.</Empty>
      ) : (
        <table className="table">
          <thead><tr><th>카드번호</th><th>제목</th><th>과제</th><th>TRL</th><th>상태</th><th>수정일</th><th /></tr></thead>
          <tbody>
            {data?.map((c) => (
              <tr key={c.id}>
                <td>{c.card_no}</td><td>{c.title}</td><td>{c.project_no}</td><td>{c.trl ?? '–'}</td>
                <td><StatusBadge status={c.status} /></td><td>{fmtDate(c.updated_at)}</td>
                <td><button className="btn btn-sm btn-primary" disabled={busy} onClick={() => void publish(c)}>검수 완료·발행</button></td>
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
      <PageHeader title="내 작업"
        subtitle={role === 'CURATOR'
          ? '성과카드를 검수해 발행하고, 나에게 온 검토 요청을 처리합니다.'
          : '나에게 배정된 추천을 검토하고 의견을 남깁니다.'} />
      <Card title="나에게 배정된 검토">
        <QueueTable rows={queue.data ?? []} empty="배정된 검토가 없습니다. 기획자가 배정하면 여기에 표시됩니다." />
      </Card>
      {role === 'CURATOR' && <DraftCards />}
    </>
  )
}
