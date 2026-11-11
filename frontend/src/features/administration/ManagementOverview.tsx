import { useState } from 'react';
import { Badge, Card, Confirm, Field, Notice, ResourceState, Stat } from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { number, payload, row, rows, text, truth, type Row } from '../../lib/data.ts';
import { Link } from '../../lib/router.tsx';
import { useAction, useResource } from '../../lib/state.tsx';

export function ManagementOverview({ view = 'overview' }: { view?: 'overview' | 'capacity' | 'data' }) {
  const resource = useResource('/api/admin/overview', 30000), data = payload(resource.data);
  const counts = row(data.counts), host = row(data.host), training = row(data.training);
  const action=useAction(),[pool,setPool]=useState<Row|null>(null),[poolSize,setPoolSize]=useState(0),[manual,setManual]=useState(false);
  const gib = (value: unknown) => (number(value) / 1024 ** 3).toFixed(1) + ' GiB';
  return <><Notice error={action.error} message={action.message}/><ResourceState {...resource}>
    {view === 'overview' && <>
      <div className="stats-grid"><Stat label="Accounts" value={counts.users} /><Stat label="Assigned students" value={counts.assigned_users} />
        <Stat label="Published exercises" value={counts.published} /><Stat label="Managed VMs" value={counts.machines} /></div>
      <AttentionPanel />
      <Card title="Exercise readiness">
        {truth(data.exercises_truncated) && <p className="notice">Showing the first 100 exercises. Use challenge management for the complete list.</p>}
        <div className="table-wrap"><table><thead><tr><th>Exercise</th><th>Owner</th><th>Availability</th><th>Import</th><th>VMs</th><th>Instances</th></tr></thead>
          <tbody>{rows(data.exercises).map(exercise => <tr key={number(exercise.id)}>
            <td><Link href={'/manage-ctf?exercise=' + number(exercise.id)}>{text(exercise.name)}</Link></td><td>{text(exercise.owner, 'Unavailable')}</td>
            <td><Badge>{truth(exercise.marked_for_deletion) ? 'Retired' : truth(exercise.is_active) ? 'Published' : 'Draft'}</Badge></td>
            <td><Badge tone={truth(exercise.ready_to_launch) ? 'active' : 'warning'}>{truth(exercise.ready_to_launch) ? 'Ready' : 'Not ready'}</Badge></td>
            <td>{number(exercise.machines)}</td><td><Link href={'/manage-instances?template_id=' + number(exercise.id)}>{number(exercise.instances)}</Link></td>
          </tr>)}</tbody></table></div>
      </Card>
    </>}
    {view === 'capacity' && <>
      <Card title="Host capacity">
        <p>Proxmox measurements <Badge tone={host.status === 'ready' ? 'active' : 'warning'}>{text(host.status, 'unavailable')}</Badge></p>
        {host.status === 'ready' ? <div className="stats-grid"><Stat label="Host CPU" value={number(host.cpu_percent).toFixed(1) + '%'} />
          <Stat label="Host cores" value={host.cores} /><Stat label="Memory used / total" value={gib(host.memory_used_bytes) + ' / ' + gib(host.memory_total_bytes)} />
          <Stat label="Root filesystem used / total" value={gib(host.root_used_bytes) + ' / ' + gib(host.root_total_bytes)} /></div> : <p>Live host measurements could not be verified.</p>}
      </Card>
      <Card title="Configured challenge resources"><div className="stats-grid"><Stat label="VMs" value={counts.machines} /><Stat label="Configured vCPUs" value={counts.allocated_cores} />
        <Stat label="Configured RAM" value={text(counts.allocated_ram_gb, 'Unknown') + ' GiB'} /><Stat label="Available images" value={counts.available_images} /></div>
        <p className="muted">Configured totals include stopped VMs. They are allocations, not live utilization or a guarantee that another challenge fits.</p>
        <div className="button-row">{Object.entries(row(data.lifecycle)).map(([state, count]) => <Link key={state} href={'/manage-instances?state=' + encodeURIComponent(state)}>{state}: {number(count)}</Link>)}</div>
      </Card>
      <Card title="Ready-instance pools"><p>Manual targets override forecasting. The pool manager applies changes asynchronously; assigned instances are not reset. Resource estimates are not reservations.</p>
        <div className="table-wrap"><table><thead><tr><th>Exercise</th><th>Ready copies</th><th>Policy</th><th>RAM per copy</th><th>Action</th></tr></thead>
          <tbody>{rows(data.exercises).map(exercise=><tr key={number(exercise.id)}><td>{text(exercise.name)}</td><td>{number(exercise.ready_pool)}</td>
            <td>{truth(exercise.pool_override)?'Manual: '+number(exercise.pool_size):'Forecast'}</td><td>{number(exercise.ram_per_instance)} GiB</td>
            <td><button className="secondary small" onClick={()=>{action.clear();setPool(exercise);setPoolSize(number(exercise.pool_size));setManual(truth(exercise.pool_override));}}>Configure pool</button></td></tr>)}</tbody></table></div>
      </Card>
    </>}
    {view === 'data' && <>
      <Card title="Training-data governance"><div className="stats-grid"><Stat label="Account preferences" value={training.accounts} />
        <Stat label="Opted out" value={training.opted_out} /><Stat label="Eligible by preference" value={training.eligible} /></div>
        <p>Training capture <Badge tone="warning">{text(training.capture_status, 'unknown')}</Badge> · Training export <Badge tone="warning">{text(training.export_status, 'unknown')}</Badge></p>
        <p>{text(training.reason, 'Capture and export readiness are unverified.')}</p>
        <p className="muted">Preference eligibility does not authorize capture or export. Shared security captures and incomplete participant attribution are excluded. Dataset lineage and removal acceptance remain required.</p>
      </Card>
      <Card title="Administrative access"><p>{number(counts.administrators)} administrator accounts have platform-wide management access.</p>
        <Link className="button secondary" href="/manage-users">Manage accounts and sessions</Link>
        <p className="muted">Account changes recheck administrator authority and are journalled. Student access to administrator routes remains denied.</p>
      </Card>
    </>}
  </ResourceState>{pool&&<Confirm title="Configure ready-instance pool" confirm="Save pool policy" busy={action.busy}
    disabled={!Number.isInteger(poolSize)||poolSize<0||poolSize>10} onClose={()=>setPool(null)} onConfirm={()=>void action.run(()=>request('/api/admin/pools/'+number(pool.id),
      {method:'POST',body:{size:poolSize,enabled:manual,expected_revision:number(pool.pool_revision)}}),()=>{setPool(null);resource.reload();})}>
    <Notice error={action.error}/><p>{text(pool.name)}</p>
    <label className="check"><input type="checkbox" checked={manual} onChange={event=>setManual(event.target.checked)}/>Use a manual pool target</label>
    <Field label="Ready copies" type="number" min={0} max={10} value={poolSize} disabled={!manual} onChange={event=>setPoolSize(Number(event.target.value))}/>
    <p>{manual?`${poolSize} copies require about ${poolSize*number(pool.ram_per_instance)} GiB of configured guest RAM.`:'Resume the existing forecast policy.'}</p>
    <p className="muted">Only published, import-ready exercises can prepare a nonzero manual pool. The target does not guarantee host capacity or immediate availability.</p>
  </Confirm>}</>;
}

function AttentionPanel() {
  const health = useResource('/api/admin/operations', 30000), jobs = useResource('/api/admin/jobs?state=NEEDS_REVIEW', 15000);
  const data = payload(health.data), monitoring = row(data.monitoring), archive = row(data.archive);
  const failed = rows(monitoring.checks).filter(check => check.state === 'failed');
  const uncertain = rows(monitoring.checks).filter(check => check.state === 'unknown' || check.state === 'warning');
  return <Card title="Needs attention">
    <ResourceState {...health}>
      {data.database !== 'ready' && <p className="notice">Database readiness is unverified. <Link href="/operations?tab=health">Inspect health</Link></p>}
      {truth(data.maintenance) && <p className="notice">Maintenance mode is on.</p>}
      {monitoring.status === 'stale' || !['ok', 'warning', 'failed'].includes(text(monitoring.status)) ? <p className="notice">Current monitoring evidence is unavailable or stale.</p> : <>
        {failed.map(check => <p key={text(check.id)} className="notice"><strong>{text(check.label)}</strong>: {text(check.summary)} <Link href="/operations?tab=health">Inspect</Link></p>)}
        {!failed.length && <p>No failed checks in the current monitoring receipt.</p>}
        {uncertain.length > 0 && <p>{uncertain.length} checks need verification. <Link href="/operations?tab=health">Review evidence</Link></p>}
      </>}
      {archive.status !== 'success' && <p className="notice">Archive delivery: {text(archive.status, 'unverified')}. <Link href="/operations?tab=health">Inspect backup and archive status</Link></p>}
    </ResourceState>
    <ResourceState {...jobs}>{rows(payload(jobs.data).jobs).filter(job=>job.state==='NEEDS_REVIEW').map(job => <p key={text(job.id)} className="notice">Operation {text(job.action)} requires reconciliation. <Link href={`/operations?tab=jobs&scope=${text(job.scope)}&resource=${number(job.resource)}`}>Inspect {text(job.scope)} {number(job.resource)}</Link></p>)}</ResourceState>
  </Card>;
}
