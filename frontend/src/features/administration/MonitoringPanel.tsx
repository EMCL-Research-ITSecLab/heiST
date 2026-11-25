import { useI18n } from '../../lib/i18n.tsx';
import { Badge } from '../../components/ui.tsx';
import { text } from '../../lib/data.ts';
import { healthTone, monitoringView } from '../../lib/monitoring.ts';
import { useTableView } from '../../lib/useTableView.tsx';
import { SortableHeader } from '../../components/SortableHeader.tsx';

export function MonitoringPanel({ value }: { value: unknown }) {
  const { t } = useI18n();
  const health = monitoringView(value);
  const checks = useTableView(health.checks, [
    { key: 'check', label: t('monitoring.check'), value: (item) => text(item.label) },
    { key: 'state', label: t('common.labels.state'), value: (item) => text(item.state) },
    { key: 'evidence', label: t('monitoring.evidence'), value: (item) => text(item.summary) },
  ]);
  const at = new Date(text(health.checkedAt));
  return (
    <section aria-label={t('monitoring.platformMonitoring')}>
      <h3>
        {t('monitoring.platformMonitoring') + ' '}
        <Badge tone={healthTone(health.status)}>{health.status}</Badge>
      </h3>
      {health.status === 'not configured' ? (
        <p>{t('monitoring.collectorSetupHint')}</p>
      ) : (
        <p>
          {Number.isNaN(at.getTime())
            ? t('common.noVerifiedCollectionTimestamp')
            : `Collected ${at.toLocaleString()}.`}
          {' ' + t('monitoring.failedChecks') + ' '}
          {health.failed}
          {' ' + t('monitoring.unverifiedChecks') + ' '}
          {health.unverified}.
        </p>
      )}
      {health.historical && (
        <p role="alert" className="notice">
          {t('monitoring.historicalEvidenceWarning')}
        </p>
      )}
      <p className="muted">{t('monitoring.deliveryProofExplanation')}</p>
      {health.checks.length > 0 && (
        <details open={health.failed > 0 || health.historical}>
          <summary>
            {t('monitoring.monitoringChecks')}
            {health.checks.length})
          </summary>
          {checks.controls}
          <div className="table-wrap">
            <table aria-label={t('monitoring.platformMonitoringChecks')}>
              <thead>
                <tr>
                  {['check', 'state', 'evidence'].map((key) => (
                    <SortableHeader key={key} {...checks.header(key)} />
                  ))}
                </tr>
              </thead>
              <tbody>
                {checks.items.map((check) => (
                  <tr key={text(check.id)}>
                    <td>{text(check.label)}</td>
                    <td>
                      <Badge tone={health.historical ? 'warning' : healthTone(text(check.state))}>
                        {text(check.state, 'unknown')}
                      </Badge>
                    </td>
                    <td>{text(check.summary)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  );
}
