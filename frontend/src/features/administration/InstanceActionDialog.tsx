import { useI18n } from '../../lib/i18n.tsx';
import { Confirm, Notice, ResourceState } from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { number, payload, text, truth, type Row } from '../../lib/data.ts';
import { useAction, useResource } from '../../lib/state.tsx';

export type ManagedAction = 'release' | 'rebuild' | 'remove' | 'start' | 'shutdown' | 'reboot';
export type ActionSelection = { instance: number; kind: ManagedAction; machineId?: number };
export const managedActionLabels = {
  release: 'common.release',
  rebuild: 'common.rebuild',
  remove: 'common.actions.remove',
  start: 'common.start',
  shutdown: 'common.shutDown',
  reboot: 'common.reboot',
} as const;
const descriptions = {
  release: 'instances.actions.releaseDescription',
  rebuild: 'instances.actions.rebuildDescription',
  remove: 'instances.actions.removeDescription',
  start: 'instances.actions.startDescription',
  shutdown: 'instances.actions.shutdownDescription',
  reboot: 'instances.actions.rebootDescription',
} as const;

export function InstanceActionDialog({
  selection,
  onClose,
  onComplete,
}: {
  selection: ActionSelection;
  onClose: () => void;
  onComplete: (result: Row) => void;
}) {
  const { t } = useI18n();
  const query = new URLSearchParams({ action: selection.kind });
  if (selection.machineId) query.set('machine_id', String(selection.machineId));
  const resource = useResource(`/api/admin/instances/${selection.instance}/preview?${query}`),
    action = useAction();
  const data = payload(resource.data),
    fingerprint = text(data.fingerprint);
  const ready = !resource.loading && !resource.error && /^[a-f0-9]{64}$/.test(fingerprint);
  async function confirm() {
    if (!ready) return;
    const endpoint =
      '/api/admin/instances/' +
      selection.instance +
      (selection.machineId ? '/machines/' + selection.machineId : '');
    await action.run(async () => {
      const result = await request(endpoint, {
          method: 'POST',
          body: { action: selection.kind, expected: fingerprint },
        }),
        job = payload(result);
      if (
        !/^[a-f0-9]{32}$/.test(text(job.job_id)) ||
        !['user', 'instance'].includes(text(job.scope)) ||
        number(job.resource) <= 0
      )
        throw new Error(
          'Operation acknowledgement was not confirmed. Inspect Jobs before retrying.',
        );
      return result;
    }, onComplete);
  }
  return (
    <Confirm
      title={t('instances.reviewAction', { action: t(managedActionLabels[selection.kind]) })}
      confirm={t(managedActionLabels[selection.kind])}
      busy={action.busy}
      disabled={!ready}
      onClose={onClose}
      onConfirm={() => void confirm()}
    >
      <Notice error={action.error} />
      <p>{t(descriptions[selection.kind])}</p>
      <ResourceState {...resource}>
        <p>
          {t('instances.instance') + ' '}
          {selection.instance} · {text(data.name)} · {text(data.state)}
        </p>
        <p>
          {t('instances.affectedVms') + ' '}
          {Array.isArray(data.machines)
            ? data.machines.map(number).join(', ') || 'None'
            : 'Unavailable'}
        </p>
        <p>
          {t('instances.affectedNetworks') + ' '}
          {Array.isArray(data.networks)
            ? data.networks.map(number).join(', ') || 'None'
            : 'Unavailable'}
        </p>
        {truth(data.guest_changes_lost) && (
          <p className="notice">{t('instances.guestChangesWillBeLost')}</p>
        )}
        <p className="muted">{t('instances.assignmentRecheckExplanation')}</p>
        <p className="muted">{t('instances.actions.queueExplanation')}</p>
      </ResourceState>
    </Confirm>
  );
}
