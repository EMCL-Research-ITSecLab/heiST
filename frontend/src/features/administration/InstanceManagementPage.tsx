import { useState } from 'react';
import { Badge, Card, Confirm, Empty, Notice, PageTitle, ResourceState } from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { date, number, payload, row, rows, text, truth, type Row } from '../../lib/data.ts';
import { useAction, useResource } from '../../lib/state.tsx';

type InstanceAction = 'release' | 'rebuild' | 'remove';
type Selection = { instance: Row; kind: InstanceAction };
const removableStates = ['READY', 'EXPIRED', 'TERMINATING'];
const descriptions: Record<InstanceAction, string> = {
  release: 'Disconnect the student and expire this instance. Cleanup will remove its resources. Grades are kept.',
  rebuild: 'Remove this instance and start a fresh copy from the exercise template. All guest changes are lost. Grades are kept.',
  remove: 'Remove this unassigned instance, its virtual machines, networks and monitoring registrations. Grades are kept.',
};

export function ManageInstances() {
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<number | null>(null);
  const [pending, setPending] = useState<Selection | null>(null);
  const resource = useResource('/api/admin/instances?page=' + page, 15000);
  const data = payload(resource.data);
  const action = useAction();

  function choose(instance: Row, kind: InstanceAction) {
    action.clear();
    setPending({ instance, kind });
  }
  async function apply() {
    if (!pending) return;
    await action.run(
      () => request('/api/admin/instances/' + number(pending.instance.id), { method: 'POST', body: { action: pending.kind } }),
      () => { setPending(null); setSelected(null); resource.reload(); },
    );
  }

  return <>
    <PageTitle title="Running challenges" eyebrow="ADMINISTRATION" description="Assignments, virtual machines and recovery status."
      action={<button className="secondary" onClick={resource.reload}>Refresh</button>} />
    <Notice error={action.error} message={action.message} />
    <ResourceState {...resource}>
      <Card title="Instances">
        {rows(data.instances).length ? <div className="table-wrap">
          <table>
            <thead><tr><th>Instance</th><th>Challenge</th><th>Student</th><th>State</th><th>Expires</th><th>Actions</th></tr></thead>
            <tbody>
              {rows(data.instances).map(instance => <tr key={number(instance.id)}>
                <td>{number(instance.id)}</td><td>{text(instance.name)}</td><td>{text(instance.username, 'Unassigned')}</td>
                <td><Badge>{text(instance.state)}</Badge></td><td>{date(instance.expires_at)}</td>
                <td><div className="button-row">
                  <button className="secondary small" onClick={() => setSelected(number(instance.id))}>Inspect</button>
                  {instance.user_id ? <>
                    <button className="secondary small" onClick={() => choose(instance, 'release')}>Release</button>
                    <button className="secondary small" onClick={() => choose(instance, 'rebuild')}>Rebuild</button>
                  </> : <button className="danger small"
                    disabled={(instance.state === 'READY' && Boolean(instance.pre_assigned_user_id)) || !removableStates.includes(text(instance.state))}
                    onClick={() => choose(instance, 'remove')}>Remove</button>}
                </div></td>
              </tr>)}
            </tbody>
          </table>
        </div> : <Empty title="No challenge instances" />}
        <div className="button-row">
          <button className="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span>Page {page}</span>
          <button className="secondary" disabled={!truth(data.has_more)} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      </Card>
    </ResourceState>
    {selected !== null && <InstanceDetails key={selected} identifier={selected} onClose={() => setSelected(null)} />}
    {pending && <Confirm
      title={pending.kind === 'rebuild' ? 'Rebuild instance' : pending.kind === 'release' ? 'Release assignment' : 'Remove instance'}
      confirm={pending.kind === 'rebuild' ? 'Rebuild' : pending.kind === 'release' ? 'Release' : 'Remove'}
      busy={action.busy} onClose={() => setPending(null)} onConfirm={() => void apply()}>
      <Notice error={action.error} />
      <p>Instance {number(pending.instance.id)} · {text(pending.instance.name)}</p>
      <p>{descriptions[pending.kind]}</p>
      <p className="muted">If the operation fails, inspect its recorded status before retrying.</p>
    </Confirm>}
  </>;
}

function InstanceDetails({ identifier, onClose }: { identifier: number; onClose: () => void }) {
  const resource = useResource('/api/admin/instances/' + identifier);
  const data = payload(resource.data);
  const operation = row(data.operation);
  return <Card title={`Instance ${identifier}`} action={<div className="button-row">
    <button className="secondary small" onClick={resource.reload}>Refresh details</button>
    <button className="secondary small" onClick={onClose}>Close details</button>
  </div>}>
    <ResourceState {...resource}>
      <p>{text(data.name)} · {text(data.state)} · {text(data.username, 'Unassigned')}</p>
      <h3>Virtual machines</h3>
      <ul>{rows(data.machines).map(vm => <li key={number(vm.id)}>
        {number(vm.id)} · {text(vm.name)} · <Badge>{text(vm.status)}</Badge>
      </li>)}</ul>
      <h3>Networks</h3>
      <ul>{rows(data.networks).map(network => <li key={number(network.id)}>
        {text(network.name)} · {text(network.subnet)}{truth(network.accessible) ? ' · Student access' : ''}{truth(network.is_dmz) ? ' · DMZ' : ''}
      </li>)}</ul>
      <h3>Connections</h3>
      <ul>{rows(data.connections).map((connection, index) => <li key={index}>
        VM {number(connection.machine_id)} → Network {number(connection.network_id)} · {text(connection.address)} · {text(connection.mac)}
      </li>)}</ul>
      <h3>Latest operation</h3>
      {operation.id ? <dl className="diagnostic-grid">
        <dt>Operation</dt><dd>{text(operation.id)}</dd>
        <dt>Scope</dt><dd>{text(operation.scope)}</dd>
        <dt>Resource</dt><dd>{number(operation.resource)}</dd>
        <dt>Action</dt><dd>{text(operation.action)}</dd>
        <dt>State</dt><dd>{text(operation.state)}</dd>
        <dt>Started</dt><dd>{date(operation.started)}</dd>
      </dl> : <p className="muted">No operation recorded for this resource.</p>}
    </ResourceState>
  </Card>;
}
