import { useState } from 'react';
import { Badge, Card, Empty, ResourceState, Select } from '../../components/ui.tsx';
import { date, number, payload, rows, text, truth } from '../../lib/data.ts';
import { useResource } from '../../lib/state.tsx';

export function OperationJournalPanel() {
  const [state, setState] = useState('all');
  const [page, setPage] = useState(1);
  const resource = useResource('/api/admin/jobs?' + new URLSearchParams({ state, page: String(page) }), 15000);
  const data = payload(resource.data);
  return <Card title="Recorded operations" action={<button className="secondary small" onClick={resource.reload}>Refresh operations</button>}>
    <Select label="Operation state" value={state}
      options={['all', 'RUNNING', 'NEEDS_REVIEW', 'SUCCEEDED', 'REJECTED', 'RESOLVED', 'UNAVAILABLE']}
      onChange={event => { setState(event.target.value); setPage(1); }} />
    <ResourceState {...resource}>
      {truth(data.truncated) && <p className="notice">The registry scan is limited to 5,000 resources. Inspect older operations on the host.</p>}
      {rows(data.jobs).length ? <div className="table-wrap">
        <table>
          <thead><tr><th>Scope</th><th>Resource</th><th>Action</th><th>State</th><th>Started</th><th>Operation ID</th></tr></thead>
          <tbody>{rows(data.jobs).map(job => <tr key={text(job.scope) + ':' + number(job.resource)}>
            <td>{text(job.scope)}</td><td>{number(job.resource)}</td><td>{text(job.action)}</td>
            <td><Badge tone={job.state === 'NEEDS_REVIEW' ? 'warning' : ''}>{text(job.state)}</Badge></td>
            <td>{date(job.started)}</td><td><code>{text(job.id)}</code></td>
          </tr>)}</tbody>
        </table>
      </div> : <Empty title="No matching operations" />}
      <div className="button-row">
        <button className="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous operations</button>
        <span>Page {page}</span>
        <button className="secondary" disabled={!truth(data.has_more)} onClick={() => setPage(page + 1)}>Next operations</button>
      </div>
    </ResourceState>
  </Card>;
}
