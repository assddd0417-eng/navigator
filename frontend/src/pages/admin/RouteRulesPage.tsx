import { PageHeader } from '../../components/ui'
import { RouteRulesCard } from './RouteRulesCard'

export function RouteRulesPage() {
  return (
    <>
      <PageHeader title="성장경로 기준" subtitle="단계별 사업, 진입조건, 다음 연계사업을 한곳에서 봅니다. 상담의 성장경로 추천이 이 기준을 따릅니다." />
      <RouteRulesCard />
    </>
  )
}
