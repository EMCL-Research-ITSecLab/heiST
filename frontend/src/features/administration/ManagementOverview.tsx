import { useI18n } from '../../lib/i18n.tsx';
import { useState } from 'react';
import { Badge, Card, Notice, ResourceState, Stat } from '../../components/ui.tsx';
import { number, payload, row, rows, text, truth, type Row } from '../../lib/data.ts';
import { Link } from '../../lib/router.tsx';
import { PoolEditor } from './PoolEditor.tsx';
import { useAction, useResource } from '../../lib/state.tsx';

export function ManagementOverview({
  view = 'overview',
}: {
  view?: 'overview' | 'capacity' | 'data';
}) {
  const { t } = useI18n();
  const resource = useResource('/api/admin/overview', 30000),
    data = payload(resource.data);
  const counts = row(data.counts),
    host = row(data.host),
    training = row(data.training);
  const action = useAction(),
    [pool, setPool] = useState<Row | null>(null);
  const gib = (value: unknown) => (number(value) / 1024 ** 3).toFixed(1) + ' GiB';
  return (
    <>
      <Notice error={action.error} message={action.message} />
      <ResourceState {...resource}>
        {view === 'overview' && (
          <>
            <div className="stats-grid">
              <Stat label={t('overview.accounts')} value={counts.users} />
              <Stat label={t('overview.assignedStudents')} value={counts.assigned_users} />
              <Stat label={t('overview.publishedExercises')} value={counts.published} />
              <Stat label={t('overview.managedVms')} value={counts.machines} />
            </div>
            <AttentionPanel />
            <Card title={t('overview.exerciseReadiness')}>
              {truth(data.exercises_truncated) && (
                <p className="notice">{t('overview.exerciseLimitHint')}</p>
              )}
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>{t('common.labels.exercise')}</th>
                      <th>{t('common.labels.owner')}</th>
                      <th>{t('common.labels.availability')}</th>
                      <th>{t('overview.import')}</th>
                      <th>{t('overview.vms')}</th>
                      <th>{t('common.labels.instances')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows(data.exercises).map((exercise) => (
                      <tr key={number(exercise.id)}>
                        <td>
                          <Link href={'/manage-ctf?exercise=' + number(exercise.id)}>
                            {text(exercise.name)}
                          </Link>
                        </td>
                        <td>{text(exercise.owner, 'Unavailable')}</td>
                        <td>
                          <Badge>
                            {truth(exercise.marked_for_deletion)
                              ? t('authoring.retired')
                              : truth(exercise.is_active)
                                ? t('common.published')
                                : t('common.draft')}
                          </Badge>
                        </td>
                        <td>
                          <Badge tone={truth(exercise.ready_to_launch) ? 'active' : 'warning'}>
                            {truth(exercise.ready_to_launch)
                              ? t('common.ready')
                              : t('common.notReady')}
                          </Badge>
                        </td>
                        <td>{number(exercise.machines)}</td>
                        <td>
                          <Link href={'/manage-instances?template_id=' + number(exercise.id)}>
                            {number(exercise.instances)}
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </>
        )}
        {view === 'capacity' && (
          <>
            <Card title={t('overview.hostCapacity')}>
              <p>
                {t('overview.proxmoxMeasurements') + ' '}
                <Badge tone={host.status === 'ready' ? 'active' : 'warning'}>
                  {text(host.status, 'unavailable')}
                </Badge>
              </p>
              {host.status === 'ready' ? (
                <div className="stats-grid">
                  <Stat
                    label={t('overview.hostCpu')}
                    value={number(host.cpu_percent).toFixed(1) + '%'}
                  />
                  <Stat label={t('overview.hostCores')} value={host.cores} />
                  <Stat
                    label={t('overview.memoryUsedTotal')}
                    value={gib(host.memory_used_bytes) + ' / ' + gib(host.memory_total_bytes)}
                  />
                  <Stat
                    label={t('overview.rootFilesystemUsedTotal')}
                    value={gib(host.root_used_bytes) + ' / ' + gib(host.root_total_bytes)}
                  />
                </div>
              ) : (
                <p>{t('overview.liveHostMeasurementsCouldNotBeVerified')}</p>
              )}
            </Card>
            <Card title={t('overview.configuredChallengeResources')}>
              <div className="stats-grid">
                <Stat label={t('overview.vms')} value={counts.machines} />
                <Stat label={t('overview.configuredVcpus')} value={counts.allocated_cores} />
                <Stat
                  label={t('overview.configuredRam')}
                  value={text(counts.allocated_ram_gb, 'Unknown') + ' GiB'}
                />
                <Stat label={t('overview.availableImages')} value={counts.available_images} />
              </div>
              <p className="muted">{t('capacity.allocationCaveat')}</p>
              <div className="button-row">
                {Object.entries(row(data.lifecycle)).map(([state, count]) => (
                  <Link key={state} href={'/manage-instances?state=' + encodeURIComponent(state)}>
                    {state}: {number(count)}
                  </Link>
                ))}
              </div>
            </Card>
            <Card title={t('overview.readyInstancePools')}>
              <p>{t('pools.manualTargetExplanation')}</p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>{t('common.labels.exercise')}</th>
                      <th>{t('overview.readyCopies')}</th>
                      <th>{t('overview.policy')}</th>
                      <th>{t('overview.ramPerCopy')}</th>
                      <th>{t('common.labels.action')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows(data.exercises).map((exercise) => (
                      <tr key={number(exercise.id)}>
                        <td>{text(exercise.name)}</td>
                        <td>{number(exercise.ready_pool)}</td>
                        <td>
                          {truth(exercise.pool_override)
                            ? 'Manual: ' + number(exercise.pool_size)
                            : 'Forecast'}
                        </td>
                        <td>
                          {number(exercise.ram_per_instance)}
                          {' ' + t('authoring.gib')}
                        </td>
                        <td>
                          <button
                            className="secondary small"
                            onClick={() => {
                              action.clear();
                              setPool(exercise);
                            }}
                          >
                            {t('authoring.configurePool')}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </>
        )}
        {view === 'data' && (
          <>
            <Card title={t('overview.trainingDataGovernance')}>
              <div className="stats-grid">
                <Stat label={t('overview.accountPreferences')} value={training.accounts} />
                <Stat label={t('overview.optedOut')} value={training.opted_out} />
                <Stat label={t('overview.eligibleByPreference')} value={training.eligible} />
              </div>
              <p>
                {t('overview.trainingCapture') + ' '}
                <Badge tone="warning">{text(training.capture_status, 'unknown')}</Badge>
                {' ' + t('overview.trainingExport') + ' '}
                <Badge tone="warning">{text(training.export_status, 'unknown')}</Badge>
              </p>
              <p>{text(training.reason, 'Capture and export readiness are unverified.')}</p>
              <p className="muted">{t('privacy.captureEligibilityCaveat')}</p>
            </Card>
            <Card title={t('overview.administrativeAccess')}>
              <p>
                {number(counts.administrators)}
                {' ' + t('overview.administratorAccessHint')}
              </p>
              <Link className="button secondary" href="/manage-users">
                {t('overview.manageAccountsAndSessions')}
              </Link>
              <p className="muted">{t('users.authorizationExplanation')}</p>
            </Card>
          </>
        )}
      </ResourceState>
      {pool && (
        <PoolEditor
          identifier={number(pool.id)}
          onClose={() => setPool(null)}
          onSaved={resource.reload}
        />
      )}
    </>
  );
}

function AttentionPanel() {
  const { t } = useI18n();
  const health = useResource('/api/admin/operations', 30000),
    jobs = useResource('/api/admin/jobs?state=NEEDS_REVIEW', 15000);
  const data = payload(health.data),
    monitoring = row(data.monitoring),
    archive = row(data.archive);
  const failed = rows(monitoring.checks).filter((check) => check.state === 'failed');
  const uncertain = rows(monitoring.checks).filter(
    (check) => check.state === 'unknown' || check.state === 'warning',
  );
  return (
    <Card title={t('overview.needsAttention')}>
      <ResourceState {...health}>
        {data.database !== 'ready' && (
          <p className="notice">
            {t('overview.databaseReadinessIsUnverified') + ' '}
            <Link href="/operations?tab=health">{t('overview.inspectHealth')}</Link>
          </p>
        )}
        {truth(data.maintenance) && <p className="notice">{t('overview.maintenanceModeIsOn')}</p>}
        {monitoring.status === 'stale' ||
        !['ok', 'warning', 'failed', 'unknown'].includes(text(monitoring.status)) ? (
          <p className="notice">{t('monitoring.staleEvidenceWarning')}</p>
        ) : (
          <>
            {failed.map((check) => (
              <p key={text(check.id)} className="notice">
                <strong>{text(check.label)}</strong>: {text(check.summary)}{' '}
                <Link href="/operations?tab=health">{t('instances.inspect')}</Link>
              </p>
            ))}
            {!failed.length && <p>{t('monitoring.noFailedChecks')}</p>}
            {uncertain.length > 0 && (
              <p>
                {uncertain.length}
                {' ' + t('overview.checksNeedVerification') + ' '}
                <Link href="/operations?tab=health">{t('overview.reviewEvidence')}</Link>
              </p>
            )}
          </>
        )}
        {archive.status !== 'success' && (
          <p className="notice">
            {archive.status === 'running'
              ? 'Archive transfer in progress. Delivery is confirmed when the job finishes.'
              : 'Archive delivery: ' + text(archive.status, 'unverified') + '.'}{' '}
            <Link href="/operations?tab=health">{t('overview.inspectBackupAndArchiveStatus')}</Link>
          </p>
        )}
      </ResourceState>
      <ResourceState {...jobs}>
        {rows(payload(jobs.data).jobs)
          .filter((job) => job.state === 'NEEDS_REVIEW')
          .map((job) => (
            <p key={text(job.id)} className="notice">
              {t('overview.operation') + ' '}
              {text(job.action)}
              {' ' + t('overview.requiresReconciliation') + ' '}
              <Link
                href={`/operations?tab=jobs&scope=${text(job.scope)}&resource=${number(job.resource)}`}
              >
                {t('instances.inspect') + ' '}
                {text(job.scope)} {number(job.resource)}
              </Link>
            </p>
          ))}
      </ResourceState>
    </Card>
  );
}
