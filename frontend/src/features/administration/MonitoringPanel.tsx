import {useI18n} from '../../lib/i18n.tsx';
import { Badge } from '../../components/ui.tsx';
import { text } from '../../lib/data.ts';
import { healthTone, monitoringView } from '../../lib/monitoring.ts';

export function MonitoringPanel({ value }: { value: unknown }) {
  const {t}=useI18n();
  const health = monitoringView(value);
  const at = new Date(text(health.checkedAt));
  return <section aria-label={t("Platform monitoring")}>
    <h3>{t("Platform monitoring ")}<Badge tone={healthTone(health.status)}>{health.status}</Badge></h3>
    {health.status === 'not configured' ? <p>{t("Configure the scheduled health collector to monitor infrastructure, sensors and log shippers.")}</p>
      : <p>{t(Number.isNaN(at.getTime()) ? 'No verified collection timestamp.' : `Collected ${at.toLocaleString()}.`)}{t(" Failed checks: ")}{health.failed}{t(" · Unverified checks: ")}{health.unverified}.</p>}
    {health.historical && <p role="alert" className="notice">{t("Current health is unavailable. Any checks below describe an earlier collection.")}</p>}
    <p className="muted">{t("Active services do not prove that commands, events or packets reach storage. End-to-end checks remain unverified until delivery is tested.")}</p>
    {health.checks.length > 0 && <details open={health.failed > 0 || health.historical}>
      <summary>{t("Monitoring checks (")}{health.checks.length})</summary>
      <div className="table-wrap"><table aria-label={t("Platform monitoring checks")}>
        <thead><tr><th>{t("Check")}</th><th>{t("State")}{t(health.historical ? ' (previous collection)' : '')}</th><th>{t("Evidence")}</th></tr></thead>
        <tbody>{health.checks.map(check => <tr key={text(check.id)}>
          <td>{text(check.label)}</td><td><Badge tone={health.historical ? 'warning' : healthTone(text(check.state))}>{text(check.state, 'unknown')}</Badge></td><td>{text(check.summary)}</td>
        </tr>)}</tbody>
      </table></div>
    </details>}
  </section>;
}
