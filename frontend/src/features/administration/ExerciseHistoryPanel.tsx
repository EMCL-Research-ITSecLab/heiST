import {useI18n} from '../../lib/i18n.tsx';
import { useState } from 'react';
import { Badge, Card, Confirm, Field, Notice, ResourceState } from '../../components/ui.tsx';
import { NetworkPreview } from '../../components/NetworkPreview.tsx';
import { request } from '../../lib/api.ts';
import { date, number, payload, row, rows, text, truth } from '../../lib/data.ts';
import { Link, useRouter } from '../../lib/router.tsx';
import { useAction, useResource } from '../../lib/state.tsx';

export function ExerciseHistoryPanel({ identifier, name, onClose }: { identifier:number;name:string;onClose:()=>void }) {
  const {t}=useI18n();
  const resource=useResource('/api/admin/challenges/'+identifier+'/revisions'),data=payload(resource.data),action=useAction(),router=useRouter();
  const [selected,setSelected]=useState<number|null>(null),[clone,setClone]=useState<number|null>(null),[draftName,setDraftName]=useState('');
  return <Card title={t('{name} · configuration history',{name})} action={<button className="secondary small" onClick={onClose}>{t("Close history")}</button>}>
    <Notice error={action.error} message={action.message}/>
    <p>{t("Snapshots preserve exercise definitions and image identities. They do not copy OVA files or snapshot student VMs. Cloning creates a separate inactive exercise.")}</p>
    <button className="secondary" disabled={action.busy} onClick={()=>void action.run(()=>request('/api/admin/challenges/'+identifier+'/revisions',{method:'POST',body:{}}),resource.reload)}>{t("Record current revision")}</button>
    <ResourceState {...resource}>
      {truth(data.has_more)&&<p className="notice">{t("Showing the latest 50 configurations.")}</p>}
      {rows(data.revisions).length?<div className="table-wrap"><table aria-label={t("Exercise configuration history")}><thead><tr><th>{t("Revision")}</th><th>{t("Recorded")}</th><th>{t("Administrator")}</th><th>{t("State")}</th><th>{t("Definition")}</th><th>{t("Actions")}</th></tr></thead>
        <tbody>{rows(data.revisions).map(revision=><tr key={number(revision.id)}><td>#{number(revision.id)}</td><td>{date(revision.recorded_at)}</td><td>{text(revision.actor,'Deleted account')}</td>
          <td><Badge>{t(truth(revision.is_active)?'Published':'Inactive')}</Badge></td><td>{number(revision.machines)}{t(" VMs · ")}{number(revision.networks)}{t(" networks")}<small>{t("SHA256 ")}<code>{text(revision.fingerprint)}</code></small></td>
          <td><div className="button-row"><button className="secondary small" onClick={()=>setSelected(number(revision.id))}>{t("Inspect revision")}</button>
            <button className="secondary small" onClick={()=>{action.clear();setClone(number(revision.id));setDraftName((name+' copy').slice(0,100));}}>{t("Clone as draft")}</button></div></td></tr>)}</tbody></table></div>
        :<p>{t("No configurations recorded yet. Recording starts history from the current definition.")}</p>}
    </ResourceState>
    {selected&&<RevisionDetails key={selected} identifier={identifier} revision={selected}/>}
    {clone&&<Confirm title={t("Clone configuration as draft")} confirm={t("Clone draft")} busy={action.busy} disabled={!draftName.trim()} onClose={()=>setClone(null)} onConfirm={()=>void action.run(
      ()=>request(`/api/admin/challenges/${identifier}/revisions/${clone}/clone`,{method:'POST',body:{name:draftName}}),result=>{setClone(null);router.navigate('/manage-ctf?exercise='+number(result.id));resource.reload();})}>
      <Notice error={action.error}/><p>{t("Create a new inactive exercise and import its machine templates. Current running instances are unchanged. Referenced VM images must still be available with the same identities.")}</p>
      <Field label={t("New draft name")} value={draftName} maxLength={100} onChange={event=>setDraftName(event.target.value)}/>
    </Confirm>}
  </Card>;
}

function RevisionDetails({identifier,revision}:{identifier:number;revision:number}) {
  const {t}=useI18n();
  const resource=useResource(`/api/admin/challenges/${identifier}/revisions/${revision}`),definition=row(payload(resource.data).definition);
  const machines=rows(definition.vms),networks=rows(definition.subnets);
  return <ResourceState {...resource}><Card title={t('Revision {id}',{id:revision})}>
    <p>{text(definition.name)} · {text(definition.category)} · {text(definition.difficulty)}</p><p>{text(definition.description)}</p>
    <div className="table-wrap"><table><thead><tr><th>{t("VM")}</th><th>{t("Image")}</th><th>{t("Resources")}</th><th>{t("Domain")}</th></tr></thead><tbody>{machines.map(vm=><tr key={text(vm.name)}>
      <td>{text(vm.name)}</td><td>{text(vm.ova_name)} · #{number(vm.artifact_id)}</td><td>{number(vm.cores)}{t(" vCPU · ")}{number(vm.ram_gb)}{t(" GiB")}</td><td>{text(vm.domain_name,'None')}</td>
    </tr>)}</tbody></table></div>
    <NetworkPreview machines={machines.map(vm=>({key:text(vm.name),name:text(vm.name)}))} networks={networks.map(network=>({key:text(network.name),name:text(network.name),
      accessible:truth(network.accessible),dmz:truth(network.dmz),machines:Array.isArray(network.attached_vms)?network.attached_vms.map(value=>text(value)):[]}))}/>
    <p>{rows(definition.flags).length}{t(" flags · ")}{rows(definition.hints).length}{t(" hints. Flag values are not displayed in this history view.")}</p>
    <Link href={'/manage-instances?template_id='+identifier}>{t("Inspect current instances")}</Link>
  </Card></ResourceState>;
}
