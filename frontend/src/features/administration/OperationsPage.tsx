import { useI18n } from '../../lib/i18n.tsx';
import { OperationJournalPanel } from './OperationJournalPanel.tsx';
import { PlatformStatusPanel } from './PlatformStatusPanel.tsx';
import { Badge, Card, Empty, PageTitle, ResourceState, Stat } from '../../components/ui.tsx';
import { number, payload, row, rows, text, truth, type Row } from '../../lib/data.ts';
import { SortableHeader } from '../../components/SortableHeader.tsx';
import { useTableSort } from '../../lib/useTableSort.ts';
import { Link, useRouter } from '../../lib/router.tsx';
import { useResource } from '../../lib/state.tsx';
import { ManagementOverview } from './ManagementOverview.tsx';
import { AdministratorAuditPanel } from './AdministratorAuditPanel.tsx';
import { MaintenancePanel } from './MaintenancePanel.tsx';
import { GradingPanel } from './GradingPanel.tsx';
const managementTabs = [
  ['overview', 'navigation.overview'],
  ['health', 'common.health'],
  ['jobs', 'common.jobs'],
  ['capacity', 'common.capacity'],
  ['data', 'common.data'],
  ['grading', 'common.grading'],
  ['audit', 'common.audit'],
  ['maintenance', 'common.maintenance'],
] as const;
export function Operations() {
  const { t } = useI18n();
  const sorting = useTableSort<Row>(
    {
      name: (c) => text(c.name),
      availability: (c) =>
        truth(c.marked_for_deletion) ? 'Retiring' : truth(c.is_active) ? 'Available' : 'Inactive',
      active: (c) => number(c.active_deployments),
      total: (c) => number(c.total_deployments),
      solves: (c) => number(c.solve_count),
    },
    'name',
  );
  const router = useRouter(),
    query = new URLSearchParams(router.location.split('?')[1]);
  const selected = query.get('tab') ?? 'overview';
  const tab = [
    'overview',
    'health',
    'jobs',
    'capacity',
    'data',
    'grading',
    'audit',
    'maintenance',
  ].includes(selected)
    ? selected
    : 'overview';
  const resource = useResource('/api/admin/challenges', 15000),
    data = payload(resource.data),
    stats = row(data.stats),
    challenges = rows(data.challenges);
  return (
    <>
      <PageTitle
        eyebrow={t('operations.administrationLabOverview')}
        title={t('navigation.platformStatus')}
        description={t('operations.page.description')}
        action={
          <button className="secondary" onClick={resource.reload}>
            {t('artifacts.refresh')}
          </button>
        }
      />
      <nav aria-label={t('operations.managementViews')} className="button-row">
        {managementTabs.map(([name, label]) => (
          <Link
            key={name}
            className={'button ' + (tab === name ? '' : 'secondary')}
            aria-current={tab === name ? 'page' : undefined}
            href={'/operations?tab=' + name}
          >
            {t(label)}
          </Link>
        ))}
      </nav>
      {tab === 'overview' && <ManagementOverview />}
      {tab === 'health' && <PlatformStatusPanel />}
      {tab === 'jobs' && <OperationJournalPanel />}
      {tab === 'capacity' && <ManagementOverview view="capacity" />}
      {tab === 'data' && <ManagementOverview view="data" />}
      {tab === 'audit' && <AdministratorAuditPanel />}
      {tab === 'maintenance' && <MaintenancePanel />}
      {tab === 'grading' && <GradingPanel />}
      {tab === 'overview' && (
        <ResourceState {...resource}>
          <div className="stats-grid">
            <Stat
              label={t('operations.managedChallenges')}
              value={stats.total_challenges ?? challenges.length}
            />
            <Stat label={t('operations.activeDeployments')} value={stats.active_deployments} />
            <Stat label={t('operations.totalDeployments')} value={stats.total_deployments} />
            <Stat
              label={t('operations.averageCompletion')}
              value={
                number(stats.avg_completion_minutes)
                  ? number(stats.avg_completion_minutes).toFixed(1) + ' min'
                  : '—'
              }
            />
          </div>
          <Card
            title={t('operations.exerciseAvailability')}
            action={<Link href="/manage-ctf">{t('operations.manageChallenges')}</Link>}
          >
            {challenges.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      {['name', 'availability', 'active', 'total', 'solves'].map((key, index) => (
                        <SortableHeader
                          key={key}
                          {...sorting.header(
                            key,
                            [
                              t('common.labels.exercise'),
                              t('common.labels.availability'),
                              t('operations.activeDeployments'),
                              t('operations.totalDeployments'),
                              t('operations.solves'),
                            ][index],
                          )}
                        />
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sorting.apply(challenges).map((c) => (
                      <tr key={text(c.id)}>
                        <td>
                          <Link href={`/challenge?id=${number(c.id)}`}>{text(c.name)}</Link>
                        </td>
                        <td>
                          <Badge
                            tone={
                              truth(c.marked_for_deletion)
                                ? 'warning'
                                : truth(c.is_active)
                                  ? 'active'
                                  : ''
                            }
                          >
                            {truth(c.marked_for_deletion)
                              ? t('common.retiring')
                              : truth(c.is_active)
                                ? t('authoring.available')
                                : t('common.inactive')}
                          </Badge>
                        </td>
                        <td>{number(c.active_deployments)}</td>
                        <td>{number(c.total_deployments)}</td>
                        <td>{number(c.solve_count)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty title={t('operations.noExercisesToMonitorYet')} />
            )}
          </Card>
        </ResourceState>
      )}
    </>
  );
}
