import { useState } from 'react'
import { getReviewQueue } from '../../api/endpoints'
import { QueueTable } from '../../components/QueueTable'
import { Card, PageHeader, useAsync } from '../../components/ui'

/** 관리자 검토 큐: 본인·본인 부서 배정분 또는 전체 */
export function ReviewQueuePage() {
  const [mine, setMine] = useState(true)
  const { data, loading } = useAsync(() => getReviewQueue(mine), [mine])

  return (
    <>
      <PageHeader title="검토 큐" subtitle="AI 추천 중 사람의 검토(Human-in-the-Loop)를 기다리는 건입니다." />
      <Card
        title={mine ? '내·우리 부서에 배정된 검토' : '전체 검토 대기'}
        actions={
          <div className="seg">
            <button className={mine ? 'on' : ''} onClick={() => setMine(true)}>내 배정</button>
            <button className={!mine ? 'on' : ''} onClick={() => setMine(false)}>전체</button>
          </div>
        }>
        {loading && !data ? <div className="page-loading">불러오는 중…</div> : (
          <QueueTable rows={data ?? []}
            empty={mine ? '배정된 검토가 없습니다. 전체 보기로 다른 부서 배정분을 확인할 수 있습니다.' : '검토 대기 중인 추천이 없습니다.'} />
        )}
      </Card>
    </>
  )
}
