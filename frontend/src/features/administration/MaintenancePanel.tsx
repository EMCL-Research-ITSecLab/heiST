import { Badge, Card, ResourceState } from '../../components/ui.tsx';
import { number, payload, row, rows, text, truth } from '../../lib/data.ts';
import { Link } from '../../lib/router.tsx';
import { useResource } from '../../lib/state.tsx';

export function MaintenancePanel() {
  const resource=useResource('/api/admin/maintenance',15000),data=payload(resource.data),release=row(data.release),acceptance=row(data.acceptance);
  return <ResourceState {...resource}>
    <Card title="Maintenance and release recovery" action={<button className="secondary small" onClick={resource.reload}>Refresh release status</button>}>
      <p>Maintenance mode <Badge tone={truth(data.maintenance)?'warning':''}>{truth(data.maintenance)?'On':'Off'}</Badge></p>
      <p>Recorded release {text(release.version,'Unknown')} · <code>{text(release.commit,'No recorded commit')}</code></p>
      <p>{number(data.pending_requests)} administrator requests must finish, be cancelled or be reconciled before rollout. <Link href="/operations?tab=jobs">Inspect jobs</Link></p>
      <p>Upgrade/recovery acceptance receipt: <Badge tone={acceptance.status==='verified receipt'?'active':'warning'}>{text(acceptance.status,'not configured')}</Badge></p>
      {Boolean(acceptance.target_commit)&&<p>Evidence target: <code>{text(acceptance.target_commit)}</code>. {truth(acceptance.installed_match)?'Matches the recorded installed release.':'Does not certify the recorded installed release.'}</p>}
      <p className="muted">Updates and rollback run through the reviewed maintenance CLI with verified backups. This view does not deploy code or claim that a recorded checkpoint has passed a restore test.</p>
      <Link href="/operations?tab=health">Inspect backup, archive and service evidence</Link>
    </Card>
    <Card title="Recorded release transactions">
      {truth(data.unavailable)&&<p className="notice">Release transaction history could not be read.</p>}
      {truth(data.truncated)&&<p className="notice">The transaction history scan is bounded; older transactions remain on the host.</p>}
      {rows(data.transactions).length?<div className="table-wrap"><table><thead><tr><th>Transaction</th><th>Version</th><th>Phase</th><th>Checkpoint recorded</th><th>Committed</th></tr></thead>
        <tbody>{rows(data.transactions).map(transaction=><tr key={text(transaction.id)}><td><code>{text(transaction.id)}</code></td><td>{text(transaction.version)}</td>
          <td><Badge tone={transaction.phase==='RECOVERY_REQUIRED'?'critical':''}>{text(transaction.phase)}</Badge></td><td>{truth(transaction.checkpoint_recorded)?'Yes':'No'}</td><td>{truth(transaction.committed)?'Yes':'No'}</td></tr>)}</tbody></table></div>:<p>No readable release transactions recorded.</p>}
    </Card>
  </ResourceState>;
}
