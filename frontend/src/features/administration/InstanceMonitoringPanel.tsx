import { Badge } from '../../components/ui.tsx';
import { number, row, rows, text } from '../../lib/data.ts';
import { healthTone } from '../../lib/monitoring.ts';

function timestamp(value: unknown) {
  const date = new Date(text(value));
  return Number.isNaN(date.getTime()) ? 'Unknown' : date.toLocaleString();
}

export function InstanceMonitoringPanel({ value }: { value: unknown }) {
  const data = row(value);
  return <section aria-label="Challenge monitoring">
    <h3>Challenge monitoring <Badge>{text(data.status, 'unknown')}</Badge></h3>
    <p className="muted">Collected {timestamp(data.checked_at)}. Agent state is matched by VM ID. Command delivery and this instance's network coverage remain unverified.</p>
    {rows(data.machines).length > 0 && <div className="table-wrap"><table aria-label="Challenge monitoring agents">
      <thead><tr><th>VM</th><th>VM state</th><th>Agent</th><th>Last seen</th></tr></thead>
      <tbody>{rows(data.machines).map(machine => {
        const state = text(machine.agent_status, 'unknown');
        const tone = machine.vm_status !== 'running' ? 'warning' : state === 'active' ? 'active' : ['missing', 'disconnected', 'stale'].includes(state) ? 'critical' : 'warning';
        return <tr key={number(machine.machine_id)}><td>{number(machine.machine_id)}</td><td>{text(machine.vm_status)}</td>
          <td><Badge tone={tone}>{state}</Badge></td><td>{timestamp(machine.last_keepalive)}</td></tr>;
      })}</tbody>
    </table></div>}
    {rows(data.sensors).length > 0 && <><h4>Shared platform sensors</h4><div className="button-row">
      {rows(data.sensors).map(sensor => <span key={text(sensor.id)}>{text(sensor.label)} <Badge tone={healthTone(text(sensor.state))}>{text(sensor.state)}</Badge></span>)}
    </div></>}
  </section>;
}
