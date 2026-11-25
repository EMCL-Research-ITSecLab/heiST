import { useI18n } from '../../lib/i18n.tsx';
import { useState } from 'react';
import { Badge, Card, Empty, ResourceState, Select } from '../../components/ui.tsx';
import { timestamp, number, payload, rows, text, truth } from '../../lib/data.ts';
import { useResource } from '../../lib/state.tsx';
import { Link, useRouter } from '../../lib/router.tsx';
import { OperationHistoryPanel } from './OperationHistoryPanel.tsx';
import { useTableView } from '../../lib/useTableView.tsx';
import { SortableHeader } from '../../components/SortableHeader.tsx';

export function OperationJournalPanel() {
  const { t } = useI18n();
  const router = useRouter(),
    query = new URLSearchParams(router.location.split('?')[1]);
  const scope = query.get('scope') ?? '',
    identifier = number(query.get('resource'));
  const [state, setState] = useState('all');
  const [page, setPage] = useState(1);
  const resource = useResource(
    '/api/admin/jobs?' + new URLSearchParams({ state, page: String(page) }),
    15000,
  );
  const data = payload(resource.data);
  const jobs = useTableView(
    rows(data.jobs),
    [
      { key: 'scope', label: t('common.labels.scope'), value: (item) => text(item.scope) },
      { key: 'resource', label: t('instances.resource'), value: (item) => number(item.resource) },
      { key: 'action', label: t('common.labels.action'), value: (item) => text(item.action) },
      { key: 'state', label: t('common.labels.state'), value: (item) => text(item.state) },
      { key: 'stage', label: t('operations.stage'), value: (item) => text(item.stage) },
      { key: 'started', label: t('operations.started'), value: (item) => text(item.started) },
    ],
    '',
    { loadedRowsOnly: true },
  );
  return (
    <>
      <Card
        title={t('operations.recordedOperations')}
        action={
          <button className="secondary small" onClick={resource.reload}>
            {t('operations.refreshOperations')}
          </button>
        }
      >
        <Select
          label={t('operations.operationState')}
          value={state}
          options={[
            'all',
            'QUEUED',
            'RUNNING',
            'NEEDS_REVIEW',
            'SUCCEEDED',
            'REJECTED',
            'RESOLVED',
            'UNAVAILABLE',
            'CANCELLED',
          ]}
          onChange={(event) => {
            setState(event.target.value);
            setPage(1);
          }}
        />
        <ResourceState {...resource}>
          {truth(data.truncated) && <p className="notice">{t('operations.registryScanLimit')}</p>}
          {jobs.controls}
          {rows(data.jobs).length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {['scope', 'resource', 'action', 'state', 'stage', 'started'].map((key) => (
                      <SortableHeader key={key} {...jobs.header(key)} />
                    ))}
                    <th>{t('authoring.history')}</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.items.map((job) => (
                    <tr key={text(job.id) || text(job.scope) + ':' + number(job.resource)}>
                      <td>{text(job.scope)}</td>
                      <td>{number(job.resource)}</td>
                      <td>{text(job.action)}</td>
                      <td>
                        <Badge tone={job.state === 'NEEDS_REVIEW' ? 'warning' : ''}>
                          {text(job.state)}
                        </Badge>
                      </td>
                      <td>{text(job.stage, 'Not recorded').replaceAll('_', ' ')}</td>
                      <td>{timestamp(job.started)}</td>
                      <td>
                        <Link
                          href={`/operations?tab=jobs&scope=${text(job.scope)}&resource=${number(job.resource)}`}
                        >
                          {t('instances.inspect')}
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title={t('operations.noMatchingOperations')} />
          )}
          <div className="button-row">
            <button className="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>
              {t('operations.previousOperations')}
            </button>
            <span>
              {t('common.page') + ' '}
              {page}
            </span>
            <button
              className="secondary"
              disabled={!truth(data.has_more)}
              onClick={() => setPage(page + 1)}
            >
              {t('operations.nextOperations')}
            </button>
          </div>
        </ResourceState>
      </Card>
      {['user', 'template', 'pool', 'artifact', 'instance'].includes(scope) && identifier > 0 && (
        <OperationHistoryPanel key={scope + identifier} scope={scope} identifier={identifier} />
      )}
    </>
  );
}
