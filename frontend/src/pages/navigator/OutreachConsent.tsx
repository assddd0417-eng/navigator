import { setOutreachConsent, type FullProfile } from '../../api/navigator'
import { useToast } from '../../components/Toast'
import { Card, useAction } from '../../components/ui'

/** 기관 담당자의 참여 권유 메일 받기. 등록 이메일로만 보낸다. */
export function OutreachConsent({ token, profile, onChange }: {
  token: string
  profile: FullProfile
  onChange: (consentAt: string | null) => void
}) {
  const { busy, run } = useAction()
  const toast = useToast()
  const on = !!profile.outreach_consent_at
  const toggle = () => void run(async () => {
    const r = await setOutreachConsent(token, !on)
    onChange(r.outreach_consent_at)
    toast.show({ kind: 'success', title: r.outreach_consent ? '참여 권유 메일을 받습니다' : '참여 권유 메일을 받지 않습니다' })
  })
  return (
    <Card title="기관 담당자 참여 권유">
      <div className="manage-box">
        <div>
          <strong>{on ? '받는 중' : '받지 않음'}</strong>
          <div className="small muted">
            새 공고에 우리 회사가 적합하거나 확인이 필요하면 기관 담당자가 {profile.registered_email ?? '등록 이메일'} 로
            참여를 권하는 메일을 보낼 수 있습니다. 같은 공고로는 한 번만 오고, 메일마다 수신 거부 링크가 있습니다.
          </div>
        </div>
        <button type="button" className={`btn ${on ? '' : 'btn-primary'}`} disabled={busy} onClick={toggle}>
          {on ? '그만 받기' : '받기'}
        </button>
      </div>
    </Card>
  )
}
