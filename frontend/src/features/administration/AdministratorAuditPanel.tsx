import { useState } from 'react';
import { Card, ResourceState } from '../../components/ui.tsx';
import { timestamp, number, payload, rows, text, truth } from '../../lib/data.ts';
import { Link } from '../../lib/router.tsx';
import { useResource } from '../../lib/state.tsx';

export function AdministratorAuditPanel() {
  const [page,setPage]=useState(1),resource=useResource('/api/admin/audit?page='+page,15000),data=payload(resource.data);
  return <Card title="Exercise administration audit" action={<button className="secondary small" onClick={resource.reload}>Refresh audit</button>}>
    <p className="muted">Recorded metadata changes survive exercise deletion. Instance and account operations have their own job histories. Sensitive configuration and flag values are excluded.</p>
    <ResourceState {...resource}><div className="table-wrap"><table><thead><tr><th>Time</th><th>Administrator</th><th>Action</th><th>Exercise</th><th>Revision</th></tr></thead>
      <tbody>{rows(data.events).map(event=><tr key={number(event.id)}><td>{timestamp(event.recorded_at)}</td><td>{text(event.actor,'Deleted account')}</td><td>{text(event.action)}</td>
        <td><Link href={'/manage-ctf?exercise='+number(event.resource_id)}>#{number(event.resource_id)}</Link></td><td>{event.revision_id?'#'+number(event.revision_id):'None'}</td></tr>)}</tbody></table></div>
      {!rows(data.events).length&&<p>No exercise administration events recorded.</p>}
      <div className="button-row"><button className="secondary" disabled={page<=1} onClick={()=>setPage(page-1)}>Previous audit page</button><span>Page {page}</span>
        <button className="secondary" disabled={!truth(data.has_more)} onClick={()=>setPage(page+1)}>Next audit page</button></div>
    </ResourceState>
  </Card>;
}
