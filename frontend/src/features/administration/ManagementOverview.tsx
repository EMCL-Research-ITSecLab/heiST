import {useI18n} from '../../lib/i18n.tsx';
import { useState } from 'react';
import { Badge, Card, Notice, ResourceState, Stat } from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { number, payload, row, rows, text, truth, type Row } from '../../lib/data.ts';
import { Link } from '../../lib/router.tsx';
import { PoolEditor } from './PoolEditor.tsx';
import { useAction, useResource } from '../../lib/state.tsx';

export function ManagementOverview({ view = 'overview' }: { view?: 'overview' | 'capacity' | 'data' }) {
  const {t}=useI18n();
  const resource = useResource('/api/admin/overview', 30000), data = payload(resource.data);
  const counts = row(data.counts), host = row(data.host), training = row(data.training);
  const action=useAction(),[pool,setPool]=useState<Row|null>(null);
  const gib = (value: unknown) => (number(value) / 1024 ** 3).toFixed(1) + ' GiB';
  return <><Notice error={action.error} message={action.message}/><ResourceState {...resource}>
    {view === 'overview' && <>
      <div className="stats-grid"><Stat label={t("Accounts")} value={counts.users} /><Stat label={t("Assigned students")} value={counts.assigned_users} />
        <Stat label={t("Published exercises")} value={counts.published} /><Stat label={t("Managed VMs")} value={counts.machines} /></div>
      <AttentionPanel />
      <Card title={t("Exercise readiness")}>
        {truth(data.exercises_truncated) && <p className="notice">{t("Showing the first 100 exercises. Use challenge management for the complete list.")}</p>}
        <div className="table-wrap"><table><thead><tr><th>{t("Exercise")}</th><th>{t("Owner")}</th><th>{t("Availability")}</th><th>{t("Import")}</th><th>{t("VMs")}</th><th>{t("Instances")}</th></tr></thead>
          <tbody>{rows(data.exercises).map(exercise => <tr key={number(exercise.id)}>
            <td><Link href={'/manage-ctf?exercise=' + number(exercise.id)}>{text(exercise.name)}</Link></td><td>{text(exercise.owner, 'Unavailable')}</td>
            <td><Badge>{t(truth(exercise.marked_for_deletion) ? 'Retired' : truth(exercise.is_active) ? 'Published' : 'Draft')}</Badge></td>
            <td><Badge tone={truth(exercise.ready_to_launch) ? 'active' : 'warning'}>{t(truth(exercise.ready_to_launch) ? 'Ready' : 'Not ready')}</Badge></td>
            <td>{number(exercise.machines)}</td><td><Link href={'/manage-instances?template_id=' + number(exercise.id)}>{number(exercise.instances)}</Link></td>
          </tr>)}</tbody></table></div>
      </Card>
    </>}
    {view === 'capacity' && <>
      <Card title={t("Host capacity")}>
        <p>{t("Proxmox measurements ")}<Badge tone={host.status === 'ready' ? 'active' : 'warning'}>{text(host.status, 'unavailable')}</Badge></p>
        {host.status === 'ready' ? <div className="stats-grid"><Stat label={t("Host CPU")} value={number(host.cpu_percent).toFixed(1) + '%'} />
          <Stat label={t("Host cores")} value={host.cores} /><Stat label={t("Memory used / total")} value={gib(host.memory_used_bytes) + ' / ' + gib(host.memory_total_bytes)} />
          <Stat label={t("Root filesystem used / total")} value={gib(host.root_used_bytes) + ' / ' + gib(host.root_total_bytes)} /></div> : <p>{t("Live host measurements could not be verified.")}</p>}
      </Card>
      <Card title={t("Configured challenge resources")}><div className="stats-grid"><Stat label={t("VMs")} value={counts.machines} /><Stat label={t("Configured vCPUs")} value={counts.allocated_cores} />
        <Stat label={t("Configured RAM")} value={text(counts.allocated_ram_gb, 'Unknown') + ' GiB'} /><Stat label={t("Available images")} value={counts.available_images} /></div>
        <p className="muted">{t("Configured totals include stopped VMs. They are allocations, not live utilization or a guarantee that another challenge fits.")}</p>
        <div className="button-row">{Object.entries(row(data.lifecycle)).map(([state, count]) => <Link key={state} href={'/manage-instances?state=' + encodeURIComponent(state)}>{state}: {number(count)}</Link>)}</div>
      </Card>
      <Card title={t("Ready-instance pools")}><p>{t("Manual targets override forecasting. The pool manager applies changes asynchronously; assigned instances are not reset. Resource estimates are not reservations.")}</p>
        <div className="table-wrap"><table><thead><tr><th>{t("Exercise")}</th><th>{t("Ready copies")}</th><th>{t("Policy")}</th><th>{t("RAM per copy")}</th><th>{t("Action")}</th></tr></thead>
          <tbody>{rows(data.exercises).map(exercise=><tr key={number(exercise.id)}><td>{text(exercise.name)}</td><td>{number(exercise.ready_pool)}</td>
            <td>{truth(exercise.pool_override)?'Manual: '+number(exercise.pool_size):'Forecast'}</td><td>{number(exercise.ram_per_instance)}{t(" GiB")}</td>
            <td><button className="secondary small" onClick={()=>{action.clear();setPool(exercise);}}>{t("Configure pool")}</button></td></tr>)}</tbody></table></div>
      </Card>
    </>}
    {view === 'data' && <>
      <Card title={t("Training-data governance")}><div className="stats-grid"><Stat label={t("Account preferences")} value={training.accounts} />
        <Stat label={t("Opted out")} value={training.opted_out} /><Stat label={t("Eligible by preference")} value={training.eligible} /></div>
        <p>{t("Training capture ")}<Badge tone="warning">{text(training.capture_status, 'unknown')}</Badge>{t(" · Training export ")}<Badge tone="warning">{text(training.export_status, 'unknown')}</Badge></p>
        <p>{text(training.reason, 'Capture and export readiness are unverified.')}</p>
        <p className="muted">{t("Preference eligibility does not authorize capture or export. Shared security captures and incomplete participant attribution are excluded. Dataset lineage and removal acceptance remain required.")}</p>
      </Card>
      <Card title={t("Administrative access")}><p>{number(counts.administrators)}{t(" administrator accounts have platform-wide management access.")}</p>
        <Link className="button secondary" href="/manage-users">{t("Manage accounts and sessions")}</Link>
        <p className="muted">{t("Account changes recheck administrator authority and are journalled. Student access to administrator routes remains denied.")}</p>
      </Card>
    </>}
  </ResourceState>{pool&&<PoolEditor identifier={number(pool.id)} onClose={()=>setPool(null)} onSaved={resource.reload}/>}</>;
}

function AttentionPanel() {
  const {t}=useI18n();
  const health = useResource('/api/admin/operations', 30000), jobs = useResource('/api/admin/jobs?state=NEEDS_REVIEW', 15000);
  const data = payload(health.data), monitoring = row(data.monitoring), archive = row(data.archive);
  const failed = rows(monitoring.checks).filter(check => check.state === 'failed');
  const uncertain = rows(monitoring.checks).filter(check => check.state === 'unknown' || check.state === 'warning');
  return <Card title={t("Needs attention")}>
    <ResourceState {...health}>
      {data.database !== 'ready' && <p className="notice">{t("Database readiness is unverified. ")}<Link href="/operations?tab=health">{t("Inspect health")}</Link></p>}
      {truth(data.maintenance) && <p className="notice">{t("Maintenance mode is on.")}</p>}
      {monitoring.status === 'stale' || !['ok', 'warning', 'failed', 'unknown'].includes(text(monitoring.status)) ? <p className="notice">{t("Current monitoring evidence is unavailable or stale.")}</p> : <>
        {failed.map(check => <p key={text(check.id)} className="notice"><strong>{text(check.label)}</strong>: {text(check.summary)} <Link href="/operations?tab=health">{t("Inspect")}</Link></p>)}
        {!failed.length && <p>{t("No failed checks in the current monitoring receipt.")}</p>}
        {uncertain.length > 0 && <p>{uncertain.length}{t(" checks need verification. ")}<Link href="/operations?tab=health">{t("Review evidence")}</Link></p>}
      </>}
      {archive.status !== 'success' && <p className="notice">{archive.status==='running'?'Archive transfer in progress. Delivery is confirmed when the job finishes.':'Archive delivery: '+text(archive.status, 'unverified')+'.'} <Link href="/operations?tab=health">{t("Inspect backup and archive status")}</Link></p>}
    </ResourceState>
    <ResourceState {...jobs}>{rows(payload(jobs.data).jobs).filter(job=>job.state==='NEEDS_REVIEW').map(job => <p key={text(job.id)} className="notice">{t("Operation ")}{text(job.action)}{t(" requires reconciliation. ")}<Link href={`/operations?tab=jobs&scope=${text(job.scope)}&resource=${number(job.resource)}`}>{t("Inspect ")}{text(job.scope)} {number(job.resource)}</Link></p>)}</ResourceState>
  </Card>;
}
