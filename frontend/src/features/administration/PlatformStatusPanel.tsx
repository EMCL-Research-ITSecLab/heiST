import { Badge, Card, ResourceState } from '../../components/ui.tsx';
import { number, payload, row, rows, text, truth } from '../../lib/data.ts';
import { useResource } from '../../lib/state.tsx';

const lifecycleStates = ['PROVISIONING', 'READY', 'ASSIGNED', 'ACTIVE', 'EXPIRED', 'TERMINATING'];
function tone(state: string) {
  if (['ready', 'active', 'success'].includes(state)) return 'active';
  if (['failed', 'stale', 'unavailable'].includes(state)) return 'critical';
  return 'warning';
}
function timestamp(value: unknown) {
  const date = new Date(text(value));
  return Number.isNaN(date.getTime()) ? 'No verified timestamp' : date.toLocaleString();
}
function exportDiagnostics(data: Record<string, unknown>) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'heist-operations.json';
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function PlatformStatusPanel() {
  const resource = useResource('/backend/admin-operations.php', 30000);
  const data = payload(resource.data), archive = row(data.archive), release = row(data.release);
  const storage = row(data.storage), lifecycle = row(data.lifecycle);
  return <Card title="Platform diagnostics" action={<button className="secondary small" onClick={resource.reload}>Refresh diagnostics</button>}>
    <ResourceState {...resource}>
      <p className="muted">Checked {timestamp(data.checked_at)}. Diagnostic data describes this host; exercise availability is listed below.</p>
      <div className="two-columns">
        <section aria-label="Platform health">
          <h3>Platform health</h3>
          <p>Database <Badge tone={tone(text(data.database))}>{text(data.database, 'unknown')}</Badge></p>
          <p>Maintenance <Badge tone={truth(data.maintenance) ? 'warning' : ''}>{truth(data.maintenance) ? 'Enabled' : 'Not enabled'}</Badge></p>
          <p>Running source version: <strong>{text(data.source_version, 'unknown')}</strong></p>
          <p>Last recorded release: <strong>{text(release.version, 'unknown')}</strong></p>
          {text(release.commit) && <p className="muted">Commit <code>{text(release.commit)}</code></p>}
          {text(release.active_transaction) && <p className="notice">Active maintenance transaction: <code>{text(release.active_transaction)}</code>. Inspect it with the release CLI before starting another rollout.</p>}
          <p>Host root filesystem: {storage.used_percent === undefined ? 'Unknown' : `${number(storage.used_percent).toFixed(1)}% used · ${(number(storage.free_bytes) / 1024 ** 3).toFixed(1)} GiB free`}</p>
        </section>
        <section aria-label="Log archive status">
          <h3>Log archive</h3>
          <p>File archive receipt <Badge tone={tone(text(archive.status))}>{text(archive.status, 'unknown')}</Badge></p>
          <p>Last successful run: {timestamp(archive.last_success_at)}</p>
          <p className="muted">{archive.status === 'not configured' ? 'Configure the read-only archive receipt connection on the backend host.' : 'Receipts come from the separate archive VM. A stale or failed receipt requires investigation.'}</p>
          {Object.keys(row(archive.counters)).length > 0 && <dl className="summary-counts">
            <div><dt>Verified files, latest run</dt><dd>{number(row(archive.counters).verified)}</dd></div>
            <div><dt>Copied files, latest run</dt><dd>{number(row(archive.counters).copied)}</dd></div>
          </dl>}
        </section>
      </div>
      <div className="table-wrap">
        <table aria-label="Platform services">
          <thead><tr><th>Service</th><th>State</th><th>Detail</th></tr></thead>
          <tbody>{rows(data.services).map(service => <tr key={text(service.unit)}>
            <td><code>{text(service.unit)}</code></td><td><Badge tone={tone(text(service.state))}>{text(service.state, 'unknown')}</Badge></td><td>{text(service.detail)}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <h3>Challenge instances across the platform</h3>
      <div className="button-row">{lifecycleStates.map(state => <span key={state}><Badge>{state.toLowerCase()}</Badge> {lifecycle[state] === undefined && data.database !== 'ready' ? 'unknown' : number(lifecycle[state])}</span>)}</div>
      <div className="button-row"><button className="secondary small" disabled={resource.loading || Boolean(resource.error)} onClick={() => exportDiagnostics(data)}>Download diagnostics JSON</button></div>
    </ResourceState>
  </Card>;
}
