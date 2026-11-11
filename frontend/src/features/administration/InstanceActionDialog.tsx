import { Confirm, Notice, ResourceState } from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { number, payload, text, truth, type Row } from '../../lib/data.ts';
import { useAction, useResource } from '../../lib/state.tsx';

export type ManagedAction = 'release' | 'rebuild' | 'remove' | 'start' | 'shutdown' | 'reboot';
export type ActionSelection = { instance: number; kind: ManagedAction; machineId?: number };
const descriptions: Record<ManagedAction, string> = {
  release: 'Disconnect the student and expire this instance. Cleanup will remove its resources. Grades are kept.',
  rebuild: 'Remove this instance and launch a fresh copy from the exercise template. All guest changes are lost. Grades are kept.',
  remove: 'Remove the unassigned instance, its virtual machines, networks and monitoring registrations. Grades are kept.',
  start: 'Start the selected virtual machine. Guest service readiness must be checked separately.',
  shutdown: 'Request a graceful shutdown of the selected virtual machine. This does not force power off.',
  reboot: 'Reboot the selected virtual machine. Connections to it will be interrupted.',
};

export function InstanceActionDialog({ selection, onClose, onComplete }: { selection: ActionSelection; onClose: () => void; onComplete: (result:Row) => void }) {
  const query = new URLSearchParams({ action: selection.kind });
  if (selection.machineId) query.set('machine_id', String(selection.machineId));
  const resource = useResource(`/api/admin/instances/${selection.instance}/preview?${query}`), action = useAction();
  const data = payload(resource.data), fingerprint = text(data.fingerprint);
  const ready = !resource.loading && !resource.error && /^[a-f0-9]{64}$/.test(fingerprint);
  async function confirm() {
    if (!ready) return;
    const endpoint = '/api/admin/instances/' + selection.instance + (selection.machineId ? '/machines/' + selection.machineId : '');
    await action.run(async () => {
      const result=await request(endpoint,{method:'POST',body:{action:selection.kind,expected:fingerprint}}),job=payload(result);
      if (!/^[a-f0-9]{32}$/.test(text(job.job_id)) || !['user','instance'].includes(text(job.scope)) || number(job.resource)<=0)
        throw new Error('Operation acknowledgement was not confirmed. Inspect Jobs before retrying.');
      return result;
    }, onComplete);
  }
  return <Confirm title={`Review ${selection.kind}`} confirm={selection.kind === 'shutdown' ? 'Shut down' : selection.kind.charAt(0).toUpperCase() + selection.kind.slice(1)}
    busy={action.busy} disabled={!ready} onClose={onClose} onConfirm={() => void confirm()}>
    <Notice error={action.error} />
    <p>{descriptions[selection.kind]}</p>
    <ResourceState {...resource}>
      <p>Instance {selection.instance} · {text(data.name)} · {text(data.state)}</p>
      <p>Affected VMs: {Array.isArray(data.machines) ? data.machines.map(number).join(', ') || 'None' : 'Unavailable'}</p>
      <p>Affected networks: {Array.isArray(data.networks) ? data.networks.map(number).join(', ') || 'None' : 'Unavailable'}</p>
      {truth(data.guest_changes_lost) && <p className="notice">Guest changes will be lost.</p>}
      <p className="muted">The server rechecks this assignment before making changes. If it changed, refresh this preview.</p>
      <p className="muted">Confirmation queues the operation. Progress and recovery are recorded in Jobs.</p>
    </ResourceState>
  </Confirm>;
}
