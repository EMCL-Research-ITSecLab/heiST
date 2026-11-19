import {useI18n} from '../../lib/i18n.tsx';
import { useState } from 'react';
import { Badge, ResourceState } from '../../components/ui.tsx';
import { number, payload, row, rows, text, truth } from '../../lib/data.ts';
import { useResource } from '../../lib/state.tsx';

export function ActivityPanel({ instanceId }: { instanceId?: number }) {
  const {t}=useI18n();
  const [visible, setVisible] = useState(false);
  return <section aria-label={t("Command and process activity")}>
    <h3>{t("Command and process activity")}</h3>
    <p className="muted">{t("Received events from the last 15 minutes. Collection coverage is unverified. VM IDs can be reused; events may precede the current assignment.")}</p>
    <button className="secondary" onClick={() => setVisible(!visible)}>{t(visible ? 'Hide activity' : 'Load activity')}</button>
    {visible && <ActivityResults key={instanceId ?? 'all'} instanceId={instanceId} />}
  </section>;
}

function ActivityResults({ instanceId }: { instanceId?: number }) {
  const {t}=useI18n();
  const resource = useResource('/api/admin/monitoring/activity' + (instanceId === undefined ? '' : '?instance_id=' + instanceId));
  const data = payload(resource.data), counts = row(data.counts);
  return <ResourceState {...resource}>
    <p>{t("Event search ")}<Badge tone={data.status === 'ready' ? 'active' : 'warning'}>{text(data.status, 'unknown')}</Badge></p>
    {data.status === 'ready' ? <>
      <p>{number(counts.commands)}{t(" command events · ")}{number(counts.processes)}{t(" process events. An event can belong to both groups.")}</p>
      {rows(data.events).length ? <div className="table-wrap"><table aria-label={t("Recent command and process events")}>
        <thead><tr><th>{t("Time")}</th><th>{t("VM")}</th><th>{t("Type")}</th><th>{t("Event")}</th></tr></thead>
        <tbody>{rows(data.events).map((event, index) => <tr key={index}>
          <td>{text(event.timestamp)}</td><td>{number(event.machine_id)}</td><td>{text(event.kind)}</td>
          <td><p>{text(event.description)}</p><pre className="activity-command">{text(event.command, 'Command text not supplied')}</pre>
            {truth(event.truncated) && <small>{t("Command text shortened.")}</small>}</td>
        </tr>)}</tbody>
      </table></div> : <p>{t("No events received in this time window. This does not verify that collection works.")}</p>}
      {truth(data.has_more) && <p>{t("Showing the latest 25 events. Use Grafana for a wider investigation.")}</p>}
    </> : <p>{t("Event collection could not be checked. Check indexer access and certificate trust in the monitoring configuration.")}</p>}
    <button className="secondary small" onClick={resource.reload}>{t("Refresh activity")}</button>
  </ResourceState>;
}
