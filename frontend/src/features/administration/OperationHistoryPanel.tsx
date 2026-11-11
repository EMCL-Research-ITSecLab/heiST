import { useState } from 'react';
import { Badge, Card, Confirm, Field, Notice, ResourceState } from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { timestamp, number, payload, row, rows, text, truth } from '../../lib/data.ts';
import { useAction, useResource } from '../../lib/state.tsx';
import { Link } from '../../lib/router.tsx';

export function OperationHistoryPanel({ scope, identifier }: { scope: string; identifier: number }) {
  const resource = useResource('/api/admin/jobs/' + encodeURIComponent(scope) + '/' + identifier, 10000);
  const data = payload(resource.data);
  const action=useAction(),[pending,setPending]=useState<{id:string;kind:'cancel'|'resolve'}|null>(null);
  const [reason,setReason]=useState(''),[confirmation,setConfirmation]=useState('');
  return <><Card title={`${scope} ${identifier} · operation history`} action={<button className="secondary small" onClick={resource.reload}>Refresh history</button>}>
    <Notice error={action.error} message={action.message}/>
    <ResourceState {...resource}>
      {row(data.current).state==='UNAVAILABLE'&&<p className="notice">The current operation receipt could not be read. Historical entries do not confirm the current resource state.</p>}
      {truth(data.truncated) && <p className="notice">Only the latest 50 readable operations from the bounded registry scan are shown.</p>}
      {rows(data.operations).length ? rows(data.operations).map(operation => <details key={text(operation.id)}>
        <summary><Badge tone={operation.state === 'NEEDS_REVIEW' ? 'warning' : ''}>{text(operation.state)}</Badge> {text(operation.action)} · {timestamp(operation.started)}</summary>
        <dl className="diagnostic-grid">
          <dt>Operation</dt><dd><code>{text(operation.id)}</code></dd>
          <dt>Administrator</dt><dd>{operation.actor ? '#' + number(operation.actor) : 'Not recorded'}</dd>
          <dt>Stage</dt><dd>{text(operation.stage, 'Not recorded').replaceAll('_', ' ')}</dd>
          <dt>Finished</dt><dd>{timestamp(operation.finished)}</dd>
          {number(operation.instance_id)>0&&<><dt>Instance</dt><dd><Link href={'/manage-instances?instance='+number(operation.instance_id)}>#{number(operation.instance_id)}</Link></dd></>}
          {number(operation.cancelled_by)>0&&<><dt>Cancelled by</dt><dd>#{number(operation.cancelled_by)}</dd></>}
          {number(operation.resolved_by)>0&&<><dt>Reconciled by</dt><dd>#{number(operation.resolved_by)}</dd></>}
        </dl>
        <ol>{rows(operation.events).map((event, index) => <li key={index}>{timestamp(event.at)} · {text(event.stage).replaceAll('_', ' ')}</li>)}</ol>
        {operation.state === 'NEEDS_REVIEW' && <p className="notice">Check the actual resources before reconciliation. Retrying an uncertain operation can repeat infrastructure changes.</p>}
        {truth(operation.managed_queue)&&['QUEUED','NEEDS_REVIEW'].includes(text(operation.state))&&<button className="secondary small" onClick={()=>{
          action.clear();setReason('');setConfirmation('');setPending({id:text(operation.id),kind:operation.state==='QUEUED'?'cancel':'resolve'});
        }}>{operation.state==='QUEUED'?'Cancel queued operation':'Record reconciliation'}</button>}
      </details>) : <p>No operation history recorded.</p>}
    </ResourceState>
  </Card>{pending&&<Confirm title={pending.kind==='cancel'?'Cancel queued operation':'Record reconciliation'} confirm={pending.kind==='cancel'?'Cancel operation':'Mark reconciled'} busy={action.busy}
    disabled={pending.kind==='resolve'&&(reason.trim().length<10||confirmation!==pending.id)} onClose={()=>setPending(null)} onConfirm={()=>void action.run(()=>request('/api/admin/jobs/'+pending.id+'/'+pending.kind,
      {method:'POST',body:pending.kind==='resolve'?{reason,confirmation}:{}}),()=>{setPending(null);resource.reload();})}>
    <Notice error={action.error}/><p><code>{pending.id}</code></p>
    {pending.kind==='cancel'?<p>Cancel only if this operation has not started. The server rejects cancellation after execution begins.</p>:<>
      <p>Independently inspect assignment, VM, network and monitoring state first. This records your recovery checks and permits future operations; it does not repeat or undo the failed action.</p>
      <Field label="Recovery checks" value={reason} minLength={10} maxLength={500} onChange={event=>setReason(event.target.value)}/>
      <Field label="Type operation ID" value={confirmation} onChange={event=>setConfirmation(event.target.value)}/>
      <p className="muted">Do not include credentials in the recovery notes.</p>
    </>}
  </Confirm>}</>;
}
