import { useI18n } from '../../lib/i18n.tsx';
import { useState } from 'react';
import { Badge, ResourceState } from '../../components/ui.tsx';
import { number, payload, row, rows, text, truth } from '../../lib/data.ts';
import { useResource } from '../../lib/state.tsx';

export function ActivityPanel({ instanceId }: { instanceId?: number }) {
  const { t } = useI18n();
  const [visible, setVisible] = useState(false);
  return (
    <section aria-label={t('monitoring.commandAndProcessActivity')}>
      <h3>{t('monitoring.commandAndProcessActivity')}</h3>
      <p className="muted">{t('monitoring.eventWindowCaveat')}</p>
      <button className="secondary" onClick={() => setVisible(!visible)}>
        {visible ? t('common.hideActivity') : t('common.loadActivity')}
      </button>
      {visible && <ActivityResults key={instanceId ?? 'all'} instanceId={instanceId} />}
    </section>
  );
}

function ActivityResults({ instanceId }: { instanceId?: number }) {
  const { t } = useI18n();
  const resource = useResource(
    '/api/admin/monitoring/activity' +
      (instanceId === undefined ? '' : '?instance_id=' + instanceId),
  );
  const data = payload(resource.data),
    counts = row(data.counts);
  return (
    <ResourceState {...resource}>
      <p>
        {t('monitoring.eventSearch') + ' '}
        <Badge tone={data.status === 'ready' ? 'active' : 'warning'}>
          {text(data.status, 'unknown')}
        </Badge>
      </p>
      {data.status === 'ready' ? (
        <>
          <p>
            {number(counts.commands)}
            {' ' + t('monitoring.commandEvents') + ' '}
            {number(counts.processes)}
            {' ' + t('monitoring.processEventsAnEventCanBelongToBothGroups')}
          </p>
          {rows(data.events).length ? (
            <div className="table-wrap">
              <table aria-label={t('monitoring.recentCommandAndProcessEvents')}>
                <thead>
                  <tr>
                    <th>{t('common.labels.time')}</th>
                    <th>{t('monitoring.vm')}</th>
                    <th>{t('common.labels.type')}</th>
                    <th>{t('monitoring.event')}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows(data.events).map((event, index) => (
                    <tr key={index}>
                      <td>{text(event.timestamp)}</td>
                      <td>{number(event.machine_id)}</td>
                      <td>{text(event.kind)}</td>
                      <td>
                        <p>{text(event.description)}</p>
                        <pre className="activity-command">
                          {text(event.command, 'Command text not supplied')}
                        </pre>
                        {truth(event.truncated) && (
                          <small>{t('monitoring.commandTextShortened')}</small>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p>{t('monitoring.emptyEventWindow')}</p>
          )}
          {truth(data.has_more) && <p>{t('monitoring.eventLimitHint')}</p>}
        </>
      ) : (
        <p>{t('monitoring.eventCollectionUnavailable')}</p>
      )}
      <button className="secondary small" onClick={resource.reload}>
        {t('monitoring.refreshActivity')}
      </button>
    </ResourceState>
  );
}
