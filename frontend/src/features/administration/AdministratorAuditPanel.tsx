import { useI18n } from '../../lib/i18n.tsx';
import { useState } from 'react';
import { Card, ResourceState } from '../../components/ui.tsx';
import { timestamp, number, payload, rows, text, truth } from '../../lib/data.ts';
import { Link } from '../../lib/router.tsx';
import { useResource } from '../../lib/state.tsx';
import { useTableView } from '../../lib/useTableView.tsx';
import { SortableHeader } from '../../components/SortableHeader.tsx';

export function AdministratorAuditPanel() {
  const { t } = useI18n();
  const [page, setPage] = useState(1),
    resource = useResource('/api/admin/audit?page=' + page, 15000),
    data = payload(resource.data);
  const events = useTableView(
    rows(data.events),
    [
      { key: 'time', label: t('common.labels.time'), value: (item) => text(item.recorded_at) },
      { key: 'actor', label: t('audit.administrator'), value: (item) => text(item.actor) },
      { key: 'action', label: t('common.labels.action'), value: (item) => text(item.action) },
      {
        key: 'exercise',
        label: t('common.labels.exercise'),
        value: (item) => number(item.resource_id),
      },
      {
        key: 'revision',
        label: t('audit.revision'),
        value: (item) => (item.revision_id == null ? null : number(item.revision_id)),
      },
    ],
    '',
    { loadedRowsOnly: true },
  );
  return (
    <Card
      title={t('audit.exerciseAdministrationAudit')}
      action={
        <button className="secondary small" onClick={resource.reload}>
          {t('audit.refreshAudit')}
        </button>
      }
    >
      <p className="muted">{t('audit.retentionExplanation')}</p>
      <ResourceState {...resource}>
        {events.controls}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {['time', 'actor', 'action', 'exercise', 'revision'].map((key) => (
                  <SortableHeader key={key} {...events.header(key)} />
                ))}
              </tr>
            </thead>
            <tbody>
              {events.items.map((event) => (
                <tr key={number(event.id)}>
                  <td>{timestamp(event.recorded_at)}</td>
                  <td>{text(event.actor, 'Deleted account')}</td>
                  <td>{text(event.action)}</td>
                  <td>
                    <Link href={'/manage-ctf?exercise=' + number(event.resource_id)}>
                      #{number(event.resource_id)}
                    </Link>
                  </td>
                  <td>{event.revision_id ? '#' + number(event.revision_id) : 'None'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!rows(data.events).length && <p>{t('audit.emptyEvents')}</p>}
        <div className="button-row">
          <button className="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            {t('audit.previousAuditPage')}
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
            {t('audit.nextAuditPage')}
          </button>
        </div>
      </ResourceState>
    </Card>
  );
}
