import { useI18n } from '../../lib/i18n.tsx';
import { Badge } from '../../components/ui.tsx';
import { number, row, rows, text } from '../../lib/data.ts';
import { healthTone } from '../../lib/monitoring.ts';

function timestamp(value: unknown) {
  const date = new Date(text(value));
  return Number.isNaN(date.getTime()) ? 'Unknown' : date.toLocaleString();
}

export function InstanceMonitoringPanel({ value }: { value: unknown }) {
  const { t } = useI18n();
  const data = row(value);
  return (
    <section aria-label={t('monitoring.challengeMonitoring')}>
      <h3>
        {t('monitoring.challengeMonitoring') + ' '}
        <Badge>{text(data.status, 'unknown')}</Badge>
      </h3>
      <p className="muted">
        {t('monitoring.collected') + ' '}
        {timestamp(data.checked_at)}
        {t('monitoring.agentCoverageCaveat')}
      </p>
      {rows(data.machines).length > 0 && (
        <div className="table-wrap">
          <table aria-label={t('monitoring.challengeMonitoringAgents')}>
            <thead>
              <tr>
                <th>{t('monitoring.vm')}</th>
                <th>{t('monitoring.vmState')}</th>
                <th>{t('monitoring.agent')}</th>
                <th>{t('monitoring.lastSeen')}</th>
              </tr>
            </thead>
            <tbody>
              {rows(data.machines).map((machine) => {
                const state = text(machine.agent_status, 'unknown');
                const tone =
                  machine.vm_status !== 'running'
                    ? 'warning'
                    : state === 'active'
                      ? 'active'
                      : ['missing', 'disconnected', 'stale'].includes(state)
                        ? 'critical'
                        : 'warning';
                return (
                  <tr key={number(machine.machine_id)}>
                    <td>{number(machine.machine_id)}</td>
                    <td>{text(machine.vm_status)}</td>
                    <td>
                      <Badge tone={tone}>{state}</Badge>
                    </td>
                    <td>{timestamp(machine.last_keepalive)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {rows(data.sensors).length > 0 && (
        <>
          <h4>{t('monitoring.sharedPlatformSensors')}</h4>
          <div className="button-row">
            {rows(data.sensors).map((sensor) => (
              <span key={text(sensor.id)}>
                {text(sensor.label)}{' '}
                <Badge tone={healthTone(text(sensor.state))}>{text(sensor.state)}</Badge>
              </span>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
