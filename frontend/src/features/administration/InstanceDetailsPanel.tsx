import { Badge, Card, ResourceState } from '../../components/ui.tsx';
import { NetworkPreview } from '../../components/NetworkPreview.tsx';
import { timestamp, number, payload, row, rows, text, truth } from '../../lib/data.ts';
import { Link } from '../../lib/router.tsx';
import { useResource } from '../../lib/state.tsx';
import { InstanceMonitoringPanel } from './InstanceMonitoringPanel.tsx';
import { ActivityPanel } from './ActivityPanel.tsx';
import { OperationHistoryPanel } from './OperationHistoryPanel.tsx';
import type { ActionSelection } from './InstanceActionDialog.tsx';

export function InstanceDetailsPanel({ identifier, onClose, onAction }: { identifier: number; onClose: () => void; onAction: (action: ActionSelection) => void }) {
  const resource = useResource('/api/admin/instances/' + identifier, 30000), data = payload(resource.data);
  const machines = rows(data.machines), networks = rows(data.networks), connections = rows(data.connections);
  const controlsAllowed = ['READY', 'ASSIGNED', 'ACTIVE'].includes(text(data.state));
  const operation=row(data.operation);
  return <Card title={`Instance ${identifier}`} action={<div className="button-row">
    <button className="secondary small" onClick={resource.reload}>Refresh details</button>
    <button className="secondary small" onClick={onClose}>Close details</button>
  </div>}>
    <ResourceState {...resource}>
      <p>{text(data.name)} · <Badge>{text(data.state)}</Badge> · {text(data.username, 'Unassigned')}</p>
      <dl className="diagnostic-grid"><dt>Exercise</dt><dd><Link href={'/manage-ctf?exercise=' + number(data.challenge_template_id)}>#{number(data.challenge_template_id)}</Link></dd>
        <dt>Subnet</dt><dd>{text(data.subnet, 'Unavailable')}</dd><dt>Activated</dt><dd>{timestamp(data.activated_at)}</dd><dt>Expires</dt><dd>{timestamp(data.expires_at)}</dd></dl>
      <h3>Virtual machines</h3>
      <div className="table-wrap"><table aria-label="Instance virtual machines"><thead><tr><th>VM</th><th>State</th><th>Resources</th><th>Actions</th></tr></thead>
        <tbody>{machines.map(vm => <tr key={number(vm.id)}><td>{text(vm.name)} <small>#{number(vm.id)} · {text(vm.ad_role)}</small></td>
          <td><Badge>{text(vm.status)}</Badge></td><td>{number(vm.cores)} vCPU · {number(vm.ram_gb)} GiB RAM</td>
          <td><div className="button-row">{(['start', 'shutdown', 'reboot'] as const).map(kind => <button key={kind} className="secondary small"
            disabled={!controlsAllowed || (kind === 'start' ? vm.status !== 'stopped' : vm.status !== 'running')}
            onClick={() => onAction({ instance: identifier, kind, machineId: number(vm.id) })}>{kind === 'shutdown' ? 'Shut down' : kind.charAt(0).toUpperCase() + kind.slice(1)}</button>)}</div></td></tr>)}</tbody>
      </table></div>
      <NetworkPreview machines={machines.map(vm => ({ key: String(vm.id), name: text(vm.name) }))}
        networks={networks.map(network => ({ key: String(network.id), name: text(network.name), accessible: truth(network.accessible), dmz: truth(network.is_dmz),
          machines: connections.filter(connection => connection.network_id === network.id).map(connection => String(connection.machine_id)) }))} />
      <details><summary>Network addresses</summary><div className="table-wrap"><table><thead><tr><th>VM</th><th>Network</th><th>Address</th><th>MAC</th></tr></thead>
        <tbody>{connections.map((connection, index) => <tr key={index}><td>{number(connection.machine_id)}</td><td>{number(connection.network_id)}</td><td>{text(connection.address)}</td><td>{text(connection.mac)}</td></tr>)}</tbody></table></div></details>
      <InstanceMonitoringPanel value={data.monitoring} />
      <ActivityPanel instanceId={identifier} />
      <h3>Latest operation</h3>
      {Boolean(operation.state)&&<section aria-label="Latest instance operation"><dl className="diagnostic-grid">
        <dt>Scope</dt><dd>{text(operation.scope)}</dd><dt>Resource</dt><dd>{number(operation.resource)}</dd>
        <dt>State</dt><dd>{text(operation.state)}</dd><dt>Action</dt><dd>{text(operation.action)}</dd>
      </dl></section>}
      <OperationHistoryPanel scope={data.user_id ? 'user' : 'instance'} identifier={data.user_id ? number(data.user_id) : identifier} />
    </ResourceState>
  </Card>;
}
