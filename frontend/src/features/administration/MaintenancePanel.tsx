import { useI18n } from '../../lib/i18n.tsx';
import { Badge, Card, ResourceState } from '../../components/ui.tsx';
import { number, payload, row, rows, text, truth } from '../../lib/data.ts';
import { Link } from '../../lib/router.tsx';
import { useResource } from '../../lib/state.tsx';
import { useTableView } from '../../lib/useTableView.tsx';
import { SortableHeader } from '../../components/SortableHeader.tsx';

export function MaintenancePanel() {
  const { t } = useI18n();
  const resource = useResource('/api/admin/maintenance', 15000),
    data = payload(resource.data),
    release = row(data.release),
    acceptance = row(data.acceptance);
  const transactions = useTableView(rows(data.transactions), [
    { key: 'id', label: t('maintenance.transaction'), value: (item) => text(item.id) },
    { key: 'version', label: t('common.labels.version'), value: (item) => text(item.version) },
    { key: 'phase', label: t('maintenance.phase'), value: (item) => text(item.phase) },
    {
      key: 'checkpoint',
      label: t('maintenance.checkpointRecorded'),
      value: (item) => (truth(item.checkpoint_recorded) ? t('common.yes') : t('common.no')),
    },
    {
      key: 'committed',
      label: t('maintenance.committed'),
      value: (item) => (truth(item.committed) ? t('common.yes') : t('common.no')),
    },
  ]);
  return (
    <ResourceState {...resource}>
      <Card
        title={t('maintenance.maintenanceAndReleaseRecovery')}
        action={
          <button className="secondary small" onClick={resource.reload}>
            {t('maintenance.refreshReleaseStatus')}
          </button>
        }
      >
        <p>
          {t('maintenance.maintenanceMode') + ' '}
          <Badge tone={truth(data.maintenance) ? 'warning' : ''}>
            {truth(data.maintenance) ? t('common.on') : t('common.off')}
          </Badge>
        </p>
        <p>
          {t('maintenance.recordedRelease') + ' '}
          {text(release.version, 'Unknown')} ·{' '}
          <code>{text(release.commit, 'No recorded commit')}</code>
        </p>
        <p>
          {number(data.pending_requests)}
          {' ' + t('maintenance.pendingRequestsHint') + ' '}
          <Link href="/operations?tab=jobs">{t('maintenance.inspectJobs')}</Link>
        </p>
        <p>
          {t('maintenance.upgradeRecoveryAcceptanceReceipt') + ' '}
          <Badge tone={acceptance.status === 'verified receipt' ? 'active' : 'warning'}>
            {text(acceptance.status, 'not configured')}
          </Badge>
        </p>
        {Boolean(acceptance.target_commit) && (
          <p>
            {t('maintenance.evidenceTarget') + ' '}
            <code>{text(acceptance.target_commit)}</code>.{' '}
            {truth(acceptance.installed_match)
              ? t('common.matchesTheRecordedInstalledRelease')
              : t('common.doesNotCertifyTheRecordedInstalledRelease')}
          </p>
        )}
        <p className="muted">{t('maintenance.rolloutExplanation')}</p>
        <Link href="/operations?tab=health">
          {t('maintenance.inspectBackupArchiveAndServiceEvidence')}
        </Link>
      </Card>
      <Card title={t('maintenance.recordedReleaseTransactions')}>
        {truth(data.unavailable) && (
          <p className="notice">{t('maintenance.releaseTransactionHistoryCouldNotBeRead')}</p>
        )}
        {truth(data.truncated) && <p className="notice">{t('maintenance.historyLimitHint')}</p>}
        {transactions.controls}
        {rows(data.transactions).length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {['id', 'version', 'phase', 'checkpoint', 'committed'].map((key) => (
                    <SortableHeader key={key} {...transactions.header(key)} />
                  ))}
                </tr>
              </thead>
              <tbody>
                {transactions.items.map((transaction) => (
                  <tr key={text(transaction.id)}>
                    <td>
                      <code>{text(transaction.id)}</code>
                    </td>
                    <td>{text(transaction.version)}</td>
                    <td>
                      <Badge tone={transaction.phase === 'RECOVERY_REQUIRED' ? 'critical' : ''}>
                        {text(transaction.phase)}
                      </Badge>
                    </td>
                    <td>
                      {truth(transaction.checkpoint_recorded) ? t('common.yes') : t('common.no')}
                    </td>
                    <td>{truth(transaction.committed) ? t('common.yes') : t('common.no')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>{t('maintenance.emptyTransactions')}</p>
        )}
      </Card>
    </ResourceState>
  );
}
