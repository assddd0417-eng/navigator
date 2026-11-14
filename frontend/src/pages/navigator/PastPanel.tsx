import { useEffect, useState } from 'react'
import { getMyPastMatches, type PastMatchRec, type PastMatchRun } from '../../api/navigator'
import { Card, useAction } from '../../components/ui'
import { Deadline, fmtDay, GroupedMatches, MatchCard, PAST_VERDICT_TEXT } from './components'

/** 참여할 수 있었던 사업: 최근 마감 공고를 지금 회사 정보로 다시 판정한 결과 */
export function PastPanel({ token, onOpenCurrent, onEditProfile }: {
  token: string
  onOpenCurrent: () => void
  onEditProfile: () => void
}) {
  const [res, setRes] = useState<PastMatchRun | null>(null)
  const { run } = useAction()
  useEffect(() => { void run(async () => setRes(await getMyPastMatches(token))) }, [run, token])

  return (
    <Card title="참여할 수 있었던 사업" actions={
      res && <span className="small muted">{fmtDay(res.closed_since)} 이후 마감된 공고</span>
    }>
      <div className="notice small">
        지금 입력된 회사 정보로 마감된 공고를 다시 판정한 결과입니다. 마감 당시 회사 상황과 다를 수 있으니
        다음 회차를 준비하는 참고로 봐 주세요.
      </div>
      {!res ? <div className="page-loading">불러오는 중…</div> : res.recommendations.length === 0 ? (
        <div className="empty">최근 마감된 공고 중 조건이 맞는 사업이 없습니다.</div>
      ) : (
        <GroupedMatches run={res} audience="company" verdictText={PAST_VERDICT_TEXT}
          hints={{ ELIGIBLE: '필수 조건을 모두 충족했던 공고', NEEDS_INFO: '회사 정보를 더 채우면 판정할 수 있는 공고' }}
          renderCard={(r) => {
            const p = r as PastMatchRec
            return (
              <MatchCard rec={p} audience="company" verdictText={PAST_VERDICT_TEXT}
                title={<strong>{p.announcement_title}</strong>}
                meta={<>
                  {p.agency_name} · 마감 {fmtDay(p.receipt_end)}
                  {p.participated && <span className="badge badge-muted past-tag">참여함</span>}
                  {p.next_round && (
                    <span className="past-next">
                      <span className="badge badge-ok">다음 회차 {p.next_round.receipt_state === 'OPEN' ? '접수중' : '접수 예정'}</span>{' '}
                      <button className="link-btn" onClick={onOpenCurrent}>{p.next_round.title}</button>{' '}
                      <Deadline end={p.next_round.receipt_end} state={p.next_round.receipt_state} />
                    </span>
                  )}
                </>}
                onEditProfile={onEditProfile} />
            )
          }} />
      )}
    </Card>
  )
}
