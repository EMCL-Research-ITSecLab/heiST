import { Badge } from '../../components/ui.tsx';
import { text } from '../../lib/data.ts';
import { healthTone, monitoringView } from '../../lib/monitoring.ts';

export function MonitoringPanel({ value }: { value: unknown }) {
  const health = monitoringView(value);
  const at = new Date(text(health.checkedAt));
  return <section aria-label="Platform monitoring">
    <h3>Platform monitoring <Badge tone={healthTone(health.status)}>{health.status}</Badge></h3>
    {health.status === 'not configured' ? <p>Configure the scheduled health collector to monitor infrastructure, sensors and log shippers.</p>
      : <p>{Number.isNaN(at.getTime()) ? 'No verified collection timestamp.' : `Collected ${at.toLocaleString()}.`} Failed checks: {health.failed} · Unverified checks: {health.unverified}.</p>}
    {health.historical && <p role="alert" className="notice">Current health is unavailable. Any checks below describe an earlier collection.</p>}
    <p className="muted">Active services do not prove that commands, events or packets reach storage. End-to-end checks remain unverified until delivery is tested.</p>
    {health.checks.length > 0 && <details open={health.failed > 0 || health.historical}>
      <summary>Monitoring checks ({health.checks.length})</summary>
      <div className="table-wrap"><table aria-label="Platform monitoring checks">
        <thead><tr><th>Check</th><th>State{health.historical ? ' (previous collection)' : ''}</th><th>Evidence</th></tr></thead>
        <tbody>{health.checks.map(check => <tr key={text(check.id)}>
          <td>{text(check.label)}</td><td><Badge tone={health.historical ? 'warning' : healthTone(text(check.state))}>{text(check.state, 'unknown')}</Badge></td><td>{text(check.summary)}</td>
        </tr>)}</tbody>
      </table></div>
    </details>}
  </section>;
}
