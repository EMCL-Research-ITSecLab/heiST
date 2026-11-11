import { useState } from 'react';
import { Badge, Card, Confirm, Field, Notice, ResourceState } from '../../components/ui.tsx';
import { NetworkPreview } from '../../components/NetworkPreview.tsx';
import { request } from '../../lib/api.ts';
import { date, number, payload, row, rows, text, truth } from '../../lib/data.ts';
import { Link, useRouter } from '../../lib/router.tsx';
import { useAction, useResource } from '../../lib/state.tsx';

export function ExerciseHistoryPanel({ identifier, name, onClose }: { identifier:number;name:string;onClose:()=>void }) {
  const resource=useResource('/api/admin/challenges/'+identifier+'/revisions'),data=payload(resource.data),action=useAction(),router=useRouter();
  const [selected,setSelected]=useState<number|null>(null),[clone,setClone]=useState<number|null>(null),[draftName,setDraftName]=useState('');
  return <Card title={`${name} · configuration history`} action={<button className="secondary small" onClick={onClose}>Close history</button>}>
    <Notice error={action.error} message={action.message}/>
    <p>Snapshots preserve exercise definitions and image identities. They do not copy OVA files or snapshot student VMs. Cloning creates a separate inactive exercise.</p>
    <button className="secondary" disabled={action.busy} onClick={()=>void action.run(()=>request('/api/admin/challenges/'+identifier+'/revisions',{method:'POST',body:{}}),resource.reload)}>Record current revision</button>
    <ResourceState {...resource}>
      {truth(data.has_more)&&<p className="notice">Showing the latest 50 configurations.</p>}
      {rows(data.revisions).length?<div className="table-wrap"><table aria-label="Exercise configuration history"><thead><tr><th>Revision</th><th>Recorded</th><th>Administrator</th><th>State</th><th>Definition</th><th>Actions</th></tr></thead>
        <tbody>{rows(data.revisions).map(revision=><tr key={number(revision.id)}><td>#{number(revision.id)}</td><td>{date(revision.recorded_at)}</td><td>{text(revision.actor,'Deleted account')}</td>
          <td><Badge>{truth(revision.is_active)?'Published':'Inactive'}</Badge></td><td>{number(revision.machines)} VMs · {number(revision.networks)} networks<small>SHA256 <code>{text(revision.fingerprint)}</code></small></td>
          <td><div className="button-row"><button className="secondary small" onClick={()=>setSelected(number(revision.id))}>Inspect revision</button>
            <button className="secondary small" onClick={()=>{action.clear();setClone(number(revision.id));setDraftName((name+' copy').slice(0,100));}}>Clone as draft</button></div></td></tr>)}</tbody></table></div>
        :<p>No configurations recorded yet. Recording starts history from the current definition.</p>}
    </ResourceState>
    {selected&&<RevisionDetails key={selected} identifier={identifier} revision={selected}/>}
    {clone&&<Confirm title="Clone configuration as draft" confirm="Clone draft" busy={action.busy} disabled={!draftName.trim()} onClose={()=>setClone(null)} onConfirm={()=>void action.run(
      ()=>request(`/api/admin/challenges/${identifier}/revisions/${clone}/clone`,{method:'POST',body:{name:draftName}}),result=>{setClone(null);router.navigate('/manage-ctf?exercise='+number(result.id));resource.reload();})}>
      <Notice error={action.error}/><p>Create a new inactive exercise and import its machine templates. Current running instances are unchanged. Referenced VM images must still be available with the same identities.</p>
      <Field label="New draft name" value={draftName} maxLength={100} onChange={event=>setDraftName(event.target.value)}/>
    </Confirm>}
  </Card>;
}

function RevisionDetails({identifier,revision}:{identifier:number;revision:number}) {
  const resource=useResource(`/api/admin/challenges/${identifier}/revisions/${revision}`),definition=row(payload(resource.data).definition);
  const machines=rows(definition.vms),networks=rows(definition.subnets);
  return <ResourceState {...resource}><Card title={`Revision ${revision}`}>
    <p>{text(definition.name)} · {text(definition.category)} · {text(definition.difficulty)}</p><p>{text(definition.description)}</p>
    <div className="table-wrap"><table><thead><tr><th>VM</th><th>Image</th><th>Resources</th><th>Domain</th></tr></thead><tbody>{machines.map(vm=><tr key={text(vm.name)}>
      <td>{text(vm.name)}</td><td>{text(vm.ova_name)} · #{number(vm.artifact_id)}</td><td>{number(vm.cores)} vCPU · {number(vm.ram_gb)} GiB</td><td>{text(vm.domain_name,'None')}</td>
    </tr>)}</tbody></table></div>
    <NetworkPreview machines={machines.map(vm=>({key:text(vm.name),name:text(vm.name)}))} networks={networks.map(network=>({key:text(network.name),name:text(network.name),
      accessible:truth(network.accessible),dmz:truth(network.dmz),machines:Array.isArray(network.attached_vms)?network.attached_vms.map(value=>text(value)):[]}))}/>
    <p>{rows(definition.flags).length} flags · {rows(definition.hints).length} hints. Flag values are not displayed in this history view.</p>
    <Link href={'/manage-instances?template_id='+identifier}>Inspect current instances</Link>
  </Card></ResourceState>;
}
