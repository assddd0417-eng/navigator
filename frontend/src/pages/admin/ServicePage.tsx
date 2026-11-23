import { Card, PageHeader } from '../../components/ui'
import { useServiceInfo } from '../../components/useServiceInfo'

export function ServicePage() {
  const info = useServiceInfo()
  if (!info) return <div className="page-loading">불러오는 중…</div>
  const { service, raci, levels } = info
  return (
    <>
      <PageHeader title="서비스 안내" subtitle="서비스가 하는 일과 부서별 역할, 사람이 확정하는 단계를 정리했습니다." />
      <div className="stack">
        <Card title="서비스 정의">
          <h4>{service.name}</h4>
          <p>{service.summary}</p>
          <div className="small muted">대상</div>
          <div className="chips">{service.targets.map((t) => <span key={t} className="badge badge-info">{t}</span>)}</div>
        </Card>

        <Card title="주요 기능">
          <div className="grid-3">
            {service.functions.map((f) => (
              <div key={f.code} className="card">
                <h4>{f.code}. {f.name}</h4>
                <ul>{f.items.map((i) => <li key={i}>{i}</li>)}</ul>
              </div>
            ))}
          </div>
        </Card>

        <Card title="서비스 목표">
          <ul>{service.goals.map((g) => <li key={g}>{g}</li>)}</ul>
        </Card>

        <Card title="처리 흐름">
          <ol>{service.flow.map((f) => <li key={f}>{f}</li>)}</ol>
        </Card>

        <Card title="주체별 역할">
          <div className="raci-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>기능</th><th>세부 업무</th><th>방산기업</th><th>기업지원 담당자</th><th>지원사업 소관부서</th>
                  <th>AX 주관부서</th><th>시스템 (성장경로 Agent)</th><th>등급</th>
                </tr>
              </thead>
              <tbody>
                {raci.map((r, i) => (
                  <tr key={i}>
                    <td className="small">{r.area}</td><td className="small">{r.task}</td>
                    <td className="small">{r.company}</td><td className="small">{r.staff}</td><td className="small">{r.owner}</td>
                    <td className="small">{r.ax}</td><td className="small">{r.agent}</td>
                    <td><span className="badge badge-info">{r.level}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted">R 실행, A 최종 책임, C 협의, I 통보.</p>
        </Card>

        <Card title="AI 자율성 등급">
          <div className="grid-3">
            {levels.map((l) => (
              <div key={l.code} className="card">
                <h4><span className={`badge badge-${l.code === 'L1' ? 'info' : l.code === 'L2' ? 'warn' : 'ok'}`}>{l.code}</span> {l.label}</h4>
                <p className="small">{l.desc}</p>
              </div>
            ))}
          </div>
        </Card>

        <Card title="연계 시스템">
          <table className="table">
            <tbody>
              {service.integrations.map((s) => (
                <tr key={s.name}>
                  <td>{s.name}</td>
                  <td><span className={`badge badge-${s.status.startsWith('연동 예정') ? 'muted' : 'ok'}`}>{s.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </>
  )
}
