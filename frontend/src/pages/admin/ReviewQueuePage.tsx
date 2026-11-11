import { useSearchParams } from 'react-router-dom'
import { getReviewQueue } from '../../api/endpoints'
import { QueueTable } from '../../components/QueueTable'
import { Card, PageHeader, Steps, useAsync } from '../../components/ui'

/** 검토할 추천: 나·우리 부서 몫 또는 전체. 보기 선택은 주소(?view=all)에 남긴다. */
export function ReviewQueuePage() {
  const [params, setParams] = useSearchParams()
  const mine = params.get('view') !== 'all'
  const { data, loading } = useAsync(() => getReviewQueue(mine), [mine])
  const setMine = (v: boolean) => setParams(v ? {} : { view: 'all' }, { replace: true })

  return (
    <>
      <PageHeader title="검토할 추천" subtitle="AI가 찾은 연계 후보는 사람이 확인해야 확정됩니다. 맡은 건을 열어 채택·보류·제외를 정해 주세요." />
      <Steps items={['‘검토하기’를 눌러 추천 이유와 근거 문서를 읽습니다.', '채택·보류·제외 중 하나를 고르고 의견을 남깁니다.', '담당 부서 검수자가 ‘최종 결정’으로 등록하면 끝납니다.']} />
      <Card
        title={mine ? '나·우리 부서에 온 검토' : '전체 검토 대기'}
        actions={
          <div className="seg">
            <button className={mine ? 'on' : ''} onClick={() => setMine(true)}>내 몫</button>
            <button className={!mine ? 'on' : ''} onClick={() => setMine(false)}>전체</button>
          </div>
        }>
        {loading && !data ? <div className="page-loading">불러오는 중…</div> : (
          <QueueTable rows={data ?? []}
            empty={mine ? '지금 맡은 검토가 없습니다. ‘전체’를 누르면 다른 부서 몫도 볼 수 있습니다.' : '검토를 기다리는 추천이 없습니다.'} />
        )}
      </Card>
    </>
  )
}
