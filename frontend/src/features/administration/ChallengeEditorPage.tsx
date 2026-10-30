import { useState, type FormEvent } from 'react';
import { Area, Card, Empty, Field, Notice, PageTitle, ResourceState, Select, Stat } from '../../components/ui.tsx';
import { post } from '../../lib/api.ts';
import { categories, difficulties, number, rows, text } from '../../lib/data.ts';
import { Link, useRouter } from '../../lib/router.tsx';
import { useAction, useResource } from '../../lib/state.tsx';
type Machine = {
  key: string;
  name: string;
  ova_name: string;
  cores: number;
  ram_gb: number;
  domain_name: string;
  ad_role: string;
};
type Network = {
  key: string;
  name: string;
  dmz: boolean;
  accessible: boolean;
  machines: string[];
};
type Flag = {
  key: string;
  flag: string;
  description: string;
  points: number;
  user_specific: boolean;
  machine: string;
};
type Hint = {
  key: string;
  hint_text: string;
  unlock_points: number;
};
const key = () => crypto.randomUUID();
export function CreateChallenge() {
  const resource = useResource('/backend/create-ctf.php'), action = useAction(), router = useRouter();
  const [machines, setMachines] = useState<Machine[]>([]), [networks, setNetworks] = useState<Network[]>([]), [flags, setFlags] = useState<Flag[]>([]), [hints, setHints] = useState<Hint[]>([]);
  const ovaOptions: [
    string,
    string
  ][] = [['', 'Select an artifact'], ...rows(resource.data.ovas).map(ova => [text(ova.filename ?? ova.name ?? ova.ova_name), text(ova.filename ?? ova.name ?? ova.ova_name)] as [
    string,
    string
  ])];
  function updateMachine(id: string, change: Partial<Machine>) { setMachines(items => items.map(item => item.key === id ? { ...item, ...change } : item)); }
  function updateNetwork(id: string, change: Partial<Network>) { setNetworks(items => items.map(item => item.key === id ? { ...item, ...change } : item)); }
  function updateFlag(id: string, change: Partial<Flag>) { setFlags(items => items.map(item => item.key === id ? { ...item, ...change } : item)); }
  function updateHint(id: string, change: Partial<Hint>) { setHints(items => items.map(item => item.key === id ? { ...item, ...change } : item)); }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const names = machines.map(vm => vm.name);
    if (!flags.length || !machines.length || !networks.length || new Set(names).size !== names.length || names.some(name => !name))
      return void action.run(async () => { throw new Error('Add at least one machine, network and flag. Every machine needs a unique name.'); });
    if (networks.some(network => !network.machines.length))
      return void action.run(async () => { throw new Error('Attach at least one machine to every network.'); });
    form.set('isActive', form.has('isActive') ? 'true' : 'false');
    form.set('vms', JSON.stringify(machines.map(({ key: _, ...vm }) => vm)));
    form.set('subnets', JSON.stringify(networks.map(network => ({ name: network.name, dmz: network.dmz, accessible: network.accessible, attached_vms: network.machines.map(id => machines.find(vm => vm.key === id)?.name).filter(Boolean) }))));
    form.set('flags', JSON.stringify(flags.map((flag, index) => ({ flag: flag.flag, description: flag.description, points: flag.points, order_index: index, user_specific: flag.user_specific, vm_name: machines.find(vm => vm.key === flag.machine)?.name ?? null }))));
    form.set('hints', JSON.stringify(hints.map((hint, index) => ({ hint_text: hint.hint_text, unlock_points: hint.unlock_points, order_index: index }))));
    await action.run(() => post('create-ctf', form), () => router.navigate('/manage-ctf'));
  }
  return <>
    <PageTitle
      eyebrow="ADMINISTRATION / NEW CHALLENGE"
      title="Build a new investigation."
      description="Define the learning experience, connect its machines and decide what discovery looks like."
      action={<Link href="/manage-ctf">← Back to challenges</Link>} />
    <Notice error={action.error} message={action.message} />
    <ResourceState {...resource}>
      <form onSubmit={submit}>
        <fieldset disabled={action.busy} className="editor-fieldset">
          <div className="editor-layout">
            <div>
              <Card title="01 / The exercise">
                <Field
                  label="Challenge name"
                  name="name"
                  required
                  maxLength={100}
                  placeholder="An investigation worth starting"
                  pattern="[a-zA-Z0-9_\- ]+" />
                <Area
                  label="Description"
                  name="description"
                  required
                  maxLength={2000}
                  placeholder="Give students context, objectives and a starting point." />
                <div className="form-grid">
                  <Select label="Category" name="category" options={categories} />
                  <Select label="Difficulty" name="difficulty" options={difficulties} />
                </div>
                <Field
                  label="Cover image (optional, up to 2 MiB)"
                  name="image"
                  type="file"
                  accept="image/png,image/jpeg,image/gif" />
                <Area label="General hint (optional)" name="hint" maxLength={500} />
                <Area
                  label="Tutor solution"
                  name="solution"
                  maxLength={2000}
                  placeholder="The explanation shown by the server once the exercise is solved." />
              </Card>
              <Card title="02 / Machines" action={<button
                className="secondary small"
                type="button"
                disabled={machines.length >= 20}
                onClick={() => setMachines(items => [...items, { key: key(), name: '', ova_name: '', cores: 1, ram_gb: 1, domain_name: '', ad_role: 'none' }])}>＋ Add machine</button>}>
                {!ovaOptions.slice(1).length && <p className="notice">Upload an artifact in <Link href="/upload-diskfile">Artifacts</Link> before adding a machine.</p>}
                {machines.map((vm, index) => <fieldset className="repeat-row" key={vm.key}>
                  <legend>Machine {index + 1}
                  </legend>
                  <div className="form-grid">
                    <Field
                      label="Machine name"
                      value={vm.name}
                      pattern="[a-zA-Z0-9_\-]+"
                      required
                      maxLength={50}
                      onChange={e => updateMachine(vm.key, { name: e.target.value })} />
                    <Select
                      label="OVA artifact"
                      required
                      value={vm.ova_name}
                      options={ovaOptions}
                      onChange={e => updateMachine(vm.key, { ova_name: e.target.value })} />
                    <Field
                      label="CPU cores"
                      type="number"
                      min={1}
                      max={16}
                      value={vm.cores}
                      onChange={e => updateMachine(vm.key, { cores: number(e.target.value) })} />
                    <Field
                      label="Memory (GiB)"
                      type="number"
                      min={1}
                      max={32}
                      value={vm.ram_gb}
                      onChange={e => updateMachine(vm.key, { ram_gb: number(e.target.value) })} />
                    <Field
                      label="Domain name"
                      required
                      value={vm.domain_name}
                      placeholder="portal.lab"
                      maxLength={255}
                      onChange={e => updateMachine(vm.key, { domain_name: e.target.value })} />
                    <Select
                      label="Directory role"
                      value={vm.ad_role}
                      options={['none', 'dc', 'member']}
                      onChange={e => updateMachine(vm.key, { ad_role: e.target.value })} />
                  </div>
                  <button className="danger subtle small" type="button" onClick={() => { setMachines(items => items.filter(item => item.key !== vm.key)); setNetworks(items => items.map(n => ({ ...n, machines: n.machines.filter(id => id !== vm.key) }))); setFlags(items => items.map(f => f.machine === vm.key ? { ...f, machine: '', user_specific: false } : f)); }}>Remove machine</button>
                </fieldset>)}
                {!machines.length && <Empty title="Give your investigation a home">Add machines from your artifact library.</Empty>}
              </Card>
              <Card title="03 / Networks" action={<button
                className="secondary small"
                type="button"
                disabled={networks.length >= 10}
                onClick={() => setNetworks(items => [...items, { key: key(), name: '', dmz: false, accessible: true, machines: [] }])}>＋ Add network</button>}>
                {networks.map((network, index) => <fieldset className="repeat-row" key={network.key}>
                  <legend>Network {index + 1}
                  </legend>
                  <Field
                    label="Network name"
                    value={network.name}
                    required
                    pattern="[a-zA-Z0-9_\-]+"
                    maxLength={50}
                    onChange={e => updateNetwork(network.key, { name: e.target.value })} />
                  <div className="button-row">
                    <label className="check">
                      <input type="checkbox" checked={network.accessible} onChange={e => updateNetwork(network.key, { accessible: e.target.checked })} />Student accessible</label>
                    <label className="check">
                      <input type="checkbox" checked={network.dmz} onChange={e => updateNetwork(network.key, { dmz: e.target.checked })} />DMZ</label>
                  </div>
                  <p className="muted">Attach machines</p>
                  <div className="checkbox-grid">
                    {machines.map(vm => <label className="check" key={vm.key}>
                      <input type="checkbox" checked={network.machines.includes(vm.key)} onChange={e => updateNetwork(network.key, { machines: e.target.checked ? [...network.machines, vm.key] : network.machines.filter(id => id !== vm.key) })} />
                      {vm.name || 'Unnamed machine'}
                    </label>)}
                  </div>
                  <button type="button" className="danger subtle small" onClick={() => setNetworks(items => items.filter(item => item.key !== network.key))}>Remove network</button>
                </fieldset>)}
                {!networks.length && <Empty title="Connect the pieces">Add a network and choose which machines belong to it.</Empty>}
              </Card>
              <Card title="04 / Flags" action={<button
                className="secondary small"
                type="button"
                disabled={flags.length >= 20}
                onClick={() => setFlags(items => [...items, { key: key(), flag: '', description: '', points: 100, user_specific: false, machine: '' }])}>＋ Add flag</button>}>
                {flags.map((flag, index) => <fieldset className="repeat-row" key={flag.key}>
                  <legend>Flag {index + 1}
                  </legend>
                  <Field
                    label="Flag value"
                    type="password"
                    autoComplete="new-password"
                    value={flag.flag}
                    required
                    maxLength={255}
                    onChange={e => updateFlag(flag.key, { flag: e.target.value })} />
                  <Field
                    label="Flag description"
                    value={flag.description}
                    maxLength={500}
                    onChange={e => updateFlag(flag.key, { description: e.target.value })} />
                  <div className="form-grid">
                    <Field
                      label="Points"
                      type="number"
                      value={flag.points}
                      min={1}
                      max={1000}
                      required
                      onChange={e => updateFlag(flag.key, { points: number(e.target.value) })} />
                    <Select
                      label="Machine"
                      value={flag.machine}
                      required={flag.user_specific}
                      options={[['', 'No linked machine'], ...machines.map(vm => [vm.key, vm.name || 'Unnamed machine'] as [
                        string,
                        string
                      ])]}
                      onChange={e => updateFlag(flag.key, { machine: e.target.value })} />
                  </div>
                  <label className="check">
                    <input type="checkbox" checked={flag.user_specific} onChange={e => updateFlag(flag.key, { user_specific: e.target.checked })} />Generate a student-specific flag</label>
                  <button type="button" className="danger subtle small" onClick={() => setFlags(items => items.filter(item => item.key !== flag.key))}>Remove flag</button>
                </fieldset>)}
                {!flags.length && <Empty title="Define a discovery">Flags mark the important milestones in an investigation.</Empty>}
              </Card>
              <Card title="05 / Progressive hints" action={<button
                className="secondary small"
                type="button"
                disabled={hints.length >= 10}
                onClick={() => setHints(items => [...items, { key: key(), hint_text: '', unlock_points: 0 }])}>＋ Add hint</button>}>
                {hints.map((hint, index) => <fieldset className="repeat-row" key={hint.key}>
                  <legend>Hint {index + 1}
                  </legend>
                  <Area
                    label="Hint text"
                    value={hint.hint_text}
                    required
                    maxLength={500}
                    onChange={e => updateHint(hint.key, { hint_text: e.target.value })} />
                  <Field
                    label="Unlock after points earned"
                    type="number"
                    min={0}
                    max={500}
                    value={hint.unlock_points}
                    onChange={e => updateHint(hint.key, { unlock_points: number(e.target.value) })} />
                  <button type="button" className="danger subtle small" onClick={() => setHints(items => items.filter(item => item.key !== hint.key))}>Remove hint</button>
                </fieldset>)}
                {!hints.length && <p className="muted">Optional hints can unlock as students earn points.</p>}
              </Card>
            </div>
            <aside>
              <Card title="Ready to share?">
                <div className="summary-counts">
                  <Stat label="Machines" value={machines.length} />
                  <Stat label="Networks" value={networks.length} />
                  <Stat label="Flags" value={flags.length} />
                  <Stat label="Total points" value={flags.reduce((total, flag) => total + flag.points, 0)} />
                </div>
                <label className="check">
                  <input type="checkbox" name="isActive" />Make available to students</label>
                <p className="muted">Leave this unchecked to create an inactive exercise for review.</p>
                <button className="full" type="submit" disabled={action.busy}>
                  {action.busy ? 'Creating the environment…' : 'Create challenge →'}
                </button>
                {action.busy && <p role="status">The server is creating templates. This can take several minutes; the request will not be retried automatically.</p>}
                <Notice error={action.error} />
              </Card>
            </aside>
          </div>
        </fieldset>
      </form>
    </ResourceState>
  </>;
}
