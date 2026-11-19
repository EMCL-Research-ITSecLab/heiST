import { useI18n } from '../../lib/i18n.tsx';
import { useState } from 'react';
import { Confirm, Field, Notice, ResourceState } from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { number, payload, text, truth, type Row } from '../../lib/data.ts';
import { useAction, useResource } from '../../lib/state.tsx';

type Props = { identifier: number; onClose: () => void; onSaved: () => void };
export function PoolEditor(props: Props) {
  const resource = useResource(`/api/admin/pools/${props.identifier}`);
  return (
    <ResourceState {...resource}>
      {!resource.loading && !resource.error && (
        <PoolForm
          key={`${props.identifier}:${number(payload(resource.data).pool_revision)}`}
          {...props}
          policy={payload(resource.data)}
        />
      )}
    </ResourceState>
  );
}
function PoolForm({ identifier, onClose, onSaved, policy }: Props & { policy: Row }) {
  const { t } = useI18n();
  const action = useAction(),
    [size, setSize] = useState(number(policy.pool_size ?? 6)),
    [manual, setManual] = useState(truth(policy.pool_override));
  const active =
    truth(policy.is_active) && truth(policy.ready_to_launch) && !truth(policy.marked_for_deletion);
  return (
    <Confirm
      title={t('pools.configureReadyInstancePool')}
      confirm={t('pools.savePoolPolicy')}
      busy={action.busy}
      disabled={!Number.isInteger(size) || size < 0 || size > 10}
      onClose={onClose}
      onConfirm={() =>
        void action.run(
          () =>
            request(`/api/admin/pools/${identifier}`, {
              method: 'POST',
              body: { size, enabled: manual, expected_revision: number(policy.pool_revision) },
            }),
          () => {
            onClose();
            onSaved();
          },
        )
      }
    >
      <Notice error={action.error} />
      <p>
        {text(policy.name)} · {number(policy.ready_pool)}
        {' ' + t('pools.readyCopies')}
      </p>
      <label className="check">
        <input
          type="checkbox"
          checked={manual}
          onChange={(event) => setManual(event.target.checked)}
        />
        {t('pools.useAManualPoolTarget')}
      </label>
      <Field
        label={t('overview.readyCopies')}
        type="number"
        min={0}
        max={10}
        value={size}
        disabled={!manual}
        onChange={(event) => setSize(Number(event.target.value))}
      />
      <p>
        {manual
          ? t('pools.manualCapacityEstimate', {
              count: size,
              ram: size * number(policy.ram_per_instance),
            })
          : t('pools.forecastHint')}
      </p>
      {!active && <p className="notice">{t('pools.stagedPolicyExplanation')}</p>}
      <p className="muted">{t('pools.drainHint')}</p>
    </Confirm>
  );
}
