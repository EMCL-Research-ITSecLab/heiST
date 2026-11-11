import { useState } from 'react';
import { Badge, Card, Empty, Field, PageTitle, ResourceState, Select } from '../../components/ui.tsx';
import { number, payload, rows, text, truth } from '../../lib/data.ts';
import { Link, useRouter } from '../../lib/router.tsx';
import { useResource } from '../../lib/state.tsx';
import { InstanceActionDialog, type ActionSelection } from './InstanceActionDialog.tsx';
import { InstanceDetailsPanel } from './InstanceDetailsPanel.tsx';

export function ManageInstances() {
  const router = useRouter(), query = new URLSearchParams(router.location.split('?')[1]);
  const page = Math.max(1, number(query.get('page')) || 1), selected = number(query.get('instance')) || null;
  const search = query.get('search') ?? '', state = query.get('state') ?? 'all';
  const parameters = new URLSearchParams({ page: String(page), search, state });
  if (query.has('template_id')) parameters.set('template_id', query.get('template_id')!);
  const resource = useResource('/api/admin/instances?' + parameters, 15000), data = payload(resource.data);
  const [pending, setPending] = useState<ActionSelection | null>(null);
  const [queued,setQueued]=useState('');
  function update(key: string, value: string, replace = false) {
    const next = new URLSearchParams(query);
    if (value) next.set(key, value); else next.delete(key);
    if (['search', 'state', 'template_id'].includes(key)) { next.delete('page'); next.delete('instance'); }
    router.navigate('/manage-instances' + (next.size ? '?' + next : ''), replace);
  }
  return <>
    <PageTitle title="Running challenges" eyebrow="ADMINISTRATION" description="Assignments, virtual machines, networks and recovery."
      action={<button className="secondary" onClick={resource.reload}>Refresh</button>} />
    {queued&&<p className="notice">Operation queued. <Link href={queued}>View progress</Link></p>}
    <Card title="Instances">
      <div className="filter-bar"><Field label="Find an instance" value={search} maxLength={100} placeholder="Exercise, student or ID" onChange={event => update('search', event.target.value, true)} />
        <Select label="Instance state" value={state} options={['all', 'PROVISIONING', 'READY', 'ASSIGNED', 'ACTIVE', 'EXPIRED', 'TERMINATING']} onChange={event => update('state', event.target.value)} />
        {query.has('template_id') && <button className="secondary" onClick={() => update('template_id', '')}>Clear exercise filter</button>}</div>
      <ResourceState {...resource}>
        {rows(data.instances).length ? <div className="table-wrap"><table><thead><tr><th>Instance</th><th>Challenge</th><th>Student</th><th>State</th><th>Expires</th><th>Actions</th></tr></thead>
          <tbody>{rows(data.instances).map(instance => <tr key={number(instance.id)}><td>{number(instance.id)}</td><td>{text(instance.name)}</td><td>{text(instance.username, 'Unassigned')}</td>
            <td><Badge>{text(instance.state)}</Badge></td><td>{text(instance.expires_at, 'Unavailable')}</td><td><div className="button-row">
              <button className="secondary small" onClick={() => update('instance', String(instance.id))}>Inspect</button>
              {instance.user_id ? <>{(['release', 'rebuild'] as const).map(kind => <button key={kind} className="secondary small" onClick={() => setPending({ instance: number(instance.id), kind })}>{kind === 'release' ? 'Release' : 'Rebuild'}</button>)}</>
                : <button className="danger small" disabled={(instance.state === 'READY' && Boolean(instance.pre_assigned_user_id)) || !['READY', 'EXPIRED', 'TERMINATING'].includes(text(instance.state))}
                  onClick={() => setPending({ instance: number(instance.id), kind: 'remove' })}>Remove</button>}
            </div></td></tr>)}</tbody></table></div> : <Empty title="No matching instances" />}
        <div className="button-row"><button className="secondary" disabled={page <= 1} onClick={() => update('page', String(page - 1))}>Previous</button><span>Page {page}</span>
          <button className="secondary" disabled={!truth(data.has_more)} onClick={() => update('page', String(page + 1))}>Next</button></div>
      </ResourceState>
    </Card>
    {selected !== null && <InstanceDetailsPanel key={selected} identifier={selected} onClose={() => update('instance', '')} onAction={setPending} />}
    {pending && <InstanceActionDialog selection={pending} onClose={() => setPending(null)} onComplete={result => {
      const job=payload(result);setQueued('/operations?tab=jobs&scope='+text(job.scope)+'&resource='+number(job.resource));setPending(null);resource.reload();
    }} />}
  </>;
}
