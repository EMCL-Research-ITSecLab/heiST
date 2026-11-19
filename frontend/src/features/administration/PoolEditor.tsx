import { useState } from 'react';
import { Confirm, Field, Notice, ResourceState } from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { number, payload, text, truth, type Row } from '../../lib/data.ts';
import { useAction, useResource } from '../../lib/state.tsx';

type Props = {identifier: number; onClose: () => void; onSaved: () => void};
export function PoolEditor(props: Props) {
  const resource = useResource(`/api/admin/pools/${props.identifier}`);
  return <ResourceState {...resource}>{!resource.loading && !resource.error &&
    <PoolForm key={`${props.identifier}:${number(payload(resource.data).pool_revision)}`} {...props} policy={payload(resource.data)}/>
  }</ResourceState>;
}
function PoolForm({identifier,onClose,onSaved,policy}: Props & {policy: Row}) {
  const action = useAction(), [size,setSize] = useState(number(policy.pool_size ?? 6)), [manual,setManual] = useState(truth(policy.pool_override));
  const active = truth(policy.is_active) && truth(policy.ready_to_launch) && !truth(policy.marked_for_deletion);
  return <Confirm title="Configure ready-instance pool" confirm="Save pool policy" busy={action.busy}
    disabled={!Number.isInteger(size) || size<0 || size>10} onClose={onClose}
    onConfirm={()=>void action.run(()=>request(`/api/admin/pools/${identifier}`, {method:'POST',body:{size,enabled:manual,expected_revision:number(policy.pool_revision)}}),()=>{onClose();onSaved();})}>
    <Notice error={action.error}/><p>{text(policy.name)} · {number(policy.ready_pool)} ready copies</p>
    <label className="check"><input type="checkbox" checked={manual} onChange={event=>setManual(event.target.checked)}/>Use a manual pool target</label>
    <Field label="Ready copies" type="number" min={0} max={10} value={size} disabled={!manual} onChange={event=>setSize(Number(event.target.value))}/>
    <p>{manual ? `${size} copies require about ${size*number(policy.ram_per_instance)} GiB of configured guest RAM.` : 'Use forecasting with a minimum of six ready copies.'}</p>
    {!active && <p className="notice">The policy is saved now. Preparation starts when the exercise is published and import-ready.</p>}
    <p className="muted">Assigned labs stay in place. Set a manual target of zero to drain unused copies.</p>
  </Confirm>;
}
