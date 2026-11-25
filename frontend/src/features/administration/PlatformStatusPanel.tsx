import { useI18n } from '../../lib/i18n.tsx';
import { Badge, Card, ResourceState } from '../../components/ui.tsx';
import { number, payload, row, rows, text, truth } from '../../lib/data.ts';
import { useResource } from '../../lib/state.tsx';
import { MonitoringPanel } from './MonitoringPanel.tsx';
import { ActivityPanel } from './ActivityPanel.tsx';
import { useTableView } from '../../lib/useTableView.tsx';
import { SortableHeader } from '../../components/SortableHeader.tsx';

const lifecycleStates = ['PROVISIONING', 'READY', 'ASSIGNED', 'ACTIVE', 'EXPIRED', 'TERMINATING'];
function tone(state: string) {
  if (['ready', 'active', 'success'].includes(state)) return 'active';
  if (['failed', 'stale', 'unavailable'].includes(state)) return 'critical';
  return 'warning';
}
function timestamp(value: unknown) {
  const date = new Date(text(value));
  return Number.isNaN(date.getTime()) ? 'No verified timestamp' : date.toLocaleString();
}
function exportDiagnostics(data: Record<string, unknown>) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }),
  );
  const link = document.createElement('a');
  link.href = url;
  link.download = 'heist-operations.json';
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function PlatformStatusPanel() {
  const { t } = useI18n();
  const resource = useResource('/api/admin/operations', 30000);
  const data = payload(resource.data),
    archive = row(data.archive),
    release = row(data.release);
  const storage = row(data.storage),
    lifecycle = row(data.lifecycle);
  const services = useTableView(rows(data.services), [
    { key: 'service', label: t('common.labels.service'), value: (item) => text(item.unit) },
    { key: 'state', label: t('common.labels.state'), value: (item) => text(item.state) },
    { key: 'detail', label: t('platform.detail'), value: (item) => text(item.detail) },
  ]);
  return (
    <Card
      title={t('platform.platformDiagnostics')}
      action={
        <button className="secondary small" onClick={resource.reload}>
          {t('platform.refreshDiagnostics')}
        </button>
      }
    >
      <ResourceState {...resource}>
        <p className="muted">
          {t('platform.checked') + ' '}
          {timestamp(data.checked_at)}
          {t('platform.diagnosticsScopeHint')}
        </p>
        <div className="two-columns">
          <section aria-label={t('platform.platformHealth')}>
            <h3>{t('platform.platformHealth')}</h3>
            <p>
              {t('platform.database') + ' '}
              <Badge tone={tone(text(data.database))}>{text(data.database, 'unknown')}</Badge>
            </p>
            <p>
              {t('maintenance.maintenanceMode') + ' '}
              <Badge tone={truth(data.maintenance) ? 'warning' : ''}>
                {truth(data.maintenance) ? t('common.on') : t('common.off')}
              </Badge>
            </p>
            <p>
              {t('platform.runningSourceVersion') + ' '}
              <strong>{text(data.source_version, 'unknown')}</strong>
            </p>
            <p>
              {t('platform.lastRecordedRelease') + ' '}
              <strong>{text(release.version, 'unknown')}</strong>
            </p>
            {text(release.commit) && (
              <p className="muted">
                {t('platform.commit') + ' '}
                <code>{text(release.commit)}</code>
              </p>
            )}
            {text(release.active_transaction) && (
              <p className="notice">
                {t('platform.activeMaintenanceTransaction') + ' '}
                <code>{text(release.active_transaction)}</code>
                {t('platform.inspectItWithTheReleaseCliBeforeStartingAnother')}
              </p>
            )}
            <p>
              {t('platform.hostRootFilesystem') + ' '}
              {storage.used_percent === undefined
                ? t('common.unknown')
                : `${number(storage.used_percent).toFixed(1)}% used · ${(number(storage.free_bytes) / 1024 ** 3).toFixed(1)} GiB free`}
            </p>
          </section>
          <section aria-label={t('platform.logArchiveStatus')}>
            <h3>{t('platform.logArchive')}</h3>
            <p>
              {t('platform.fileArchiveReceipt') + ' '}
              <Badge tone={tone(text(archive.status))}>{text(archive.status, 'unknown')}</Badge>
            </p>
            <p>
              {t('platform.lastSuccessfulRun') + ' '}
              {timestamp(archive.last_success_at)}
            </p>
            <p className="muted">
              {archive.status === 'not configured'
                ? t('common.configureTheReadOnlyArchiveReceiptConnectionOnThe')
                : t('archive.receiptExplanation')}
            </p>
            {Object.keys(row(archive.counters)).length > 0 && (
              <dl className="summary-counts">
                <div>
                  <dt>{t('platform.verifiedFilesLatestRun')}</dt>
                  <dd>{number(row(archive.counters).verified)}</dd>
                </div>
                <div>
                  <dt>{t('platform.copiedFilesLatestRun')}</dt>
                  <dd>{number(row(archive.counters).copied)}</dd>
                </div>
              </dl>
            )}
          </section>
        </div>
        <MonitoringPanel value={data.monitoring} />
        <ActivityPanel />
        {services.controls}
        <div className="table-wrap">
          <table aria-label={t('platform.platformServices')}>
            <thead>
              <tr>
                {['service', 'state', 'detail'].map((key) => (
                  <SortableHeader key={key} {...services.header(key)} />
                ))}
              </tr>
            </thead>
            <tbody>
              {services.items.map((service) => (
                <tr key={text(service.unit)}>
                  <td>
                    <code>{text(service.unit)}</code>
                  </td>
                  <td>
                    <Badge tone={tone(text(service.state))}>{text(service.state, 'unknown')}</Badge>
                  </td>
                  <td>{text(service.detail)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3>{t('platform.challengeInstancesAcrossThePlatform')}</h3>
        <div className="button-row">
          {lifecycleStates.map((state) => (
            <span key={state}>
              <Badge>{state.toLowerCase()}</Badge>{' '}
              {lifecycle[state] === undefined && data.database !== 'ready'
                ? 'unknown'
                : number(lifecycle[state])}
            </span>
          ))}
        </div>
        <div className="button-row">
          <button
            className="secondary small"
            disabled={resource.loading || Boolean(resource.error)}
            onClick={() => exportDiagnostics(data)}
          >
            {t('platform.downloadDiagnosticsJson')}
          </button>
        </div>
      </ResourceState>
    </Card>
  );
}
