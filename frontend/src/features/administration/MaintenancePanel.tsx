import {useI18n} from '../../lib/i18n.tsx';
import { Badge, Card, ResourceState } from '../../components/ui.tsx';
import { number, payload, row, rows, text, truth } from '../../lib/data.ts';
import { Link } from '../../lib/router.tsx';
import { useResource } from '../../lib/state.tsx';

export function MaintenancePanel() {
  const {t}=useI18n();
  const resource=useResource('/api/admin/maintenance',15000),data=payload(resource.data),release=row(data.release),acceptance=row(data.acceptance);
  return <ResourceState {...resource}>
    <Card title={t("Maintenance and release recovery")} action={<button className="secondary small" onClick={resource.reload}>{t("Refresh release status")}</button>}>
      <p>{t("Maintenance mode ")}<Badge tone={truth(data.maintenance)?'warning':''}>{t(truth(data.maintenance)?'On':'Off')}</Badge></p>
      <p>{t("Recorded release ")}{text(release.version,'Unknown')} · <code>{text(release.commit,'No recorded commit')}</code></p>
      <p>{number(data.pending_requests)}{t(" administrator requests must finish, be cancelled or be reconciled before rollout. ")}<Link href="/operations?tab=jobs">{t("Inspect jobs")}</Link></p>
      <p>{t("Upgrade/recovery acceptance receipt: ")}<Badge tone={acceptance.status==='verified receipt'?'active':'warning'}>{text(acceptance.status,'not configured')}</Badge></p>
      {Boolean(acceptance.target_commit)&&<p>{t("Evidence target: ")}<code>{text(acceptance.target_commit)}</code>. {t(truth(acceptance.installed_match)?'Matches the recorded installed release.':'Does not certify the recorded installed release.')}</p>}
      <p className="muted">{t("Updates and rollback run through the reviewed maintenance CLI with verified backups. This view does not deploy code or claim that a recorded checkpoint has passed a restore test.")}</p>
      <Link href="/operations?tab=health">{t("Inspect backup, archive and service evidence")}</Link>
    </Card>
    <Card title={t("Recorded release transactions")}>
      {truth(data.unavailable)&&<p className="notice">{t("Release transaction history could not be read.")}</p>}
      {truth(data.truncated)&&<p className="notice">{t("The transaction history scan is bounded; older transactions remain on the host.")}</p>}
      {rows(data.transactions).length?<div className="table-wrap"><table><thead><tr><th>{t("Transaction")}</th><th>{t("Version")}</th><th>{t("Phase")}</th><th>{t("Checkpoint recorded")}</th><th>{t("Committed")}</th></tr></thead>
        <tbody>{rows(data.transactions).map(transaction=><tr key={text(transaction.id)}><td><code>{text(transaction.id)}</code></td><td>{text(transaction.version)}</td>
          <td><Badge tone={transaction.phase==='RECOVERY_REQUIRED'?'critical':''}>{text(transaction.phase)}</Badge></td><td>{t(truth(transaction.checkpoint_recorded)?'Yes':'No')}</td><td>{t(truth(transaction.committed)?'Yes':'No')}</td></tr>)}</tbody></table></div>:<p>{t("No readable release transactions recorded.")}</p>}
    </Card>
  </ResourceState>;
}
