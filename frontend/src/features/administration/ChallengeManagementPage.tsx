import { useState, type FormEvent } from 'react';
import { Area, Badge, Card, Confirm, Empty, Field, Notice, PageTitle, Pager, ResourceState, Select, Stat } from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { categories, difficulties, number, payload, row, rows, text, truth, type Row } from '../../lib/data.ts';
import { Link, useRouter } from '../../lib/router.tsx';
import { useAction, useResource } from '../../lib/state.tsx';
import { ExerciseHistoryPanel } from './ExerciseHistoryPanel.tsx';
export function ManageChallenges() {
  const router=useRouter(), selected=number(new URLSearchParams(router.location.split('?')[1]).get('exercise'));
  const resource = useResource('/api/admin/challenges', 30000), data = payload(resource.data), stats = row(data.stats), action = useAction();
  const [search, setSearch] = useState(''), [state, setState] = useState('all'), [editing, setEditing] = useState<Row | null>(null), [deleting, setDeleting] = useState<Row | null>(null), [force, setForce] = useState(false), [leader, setLeader] = useState<Row | null>(null);
  const [category, setCategory] = useState('all'), [sort, setSort] = useState('name'), [page, setPage] = useState(1);
  const filtered = rows(data.challenges).filter(c => text(c.name).toLowerCase().includes(search.toLowerCase()) && (state === 'all' || (state === 'active' ? truth(c.is_active) && !truth(c.marked_for_deletion) : state === 'retired' ? truth(c.marked_for_deletion) : !truth(c.is_active))));
  const matching = filtered.filter(c => category === 'all' || text(c.category) === category)
    .sort((a, b) => (sort === 'deployments' ? number(b.active_deployments) - number(a.active_deployments) : text(a.name).localeCompare(text(b.name))) || number(a.id) - number(b.id));
  const totalPages = Math.max(1, Math.ceil(matching.length / 20)), currentPage = Math.min(page, totalPages);
  const challenges = matching.slice((currentPage - 1) * 20, currentPage * 20);
  async function edit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = new FormData(event.currentTarget); form.set('isActive', form.has('isActive') ? 'true' : 'false'); await action.run(() => request('/api/admin/challenges/'+text(editing?.id), {method: 'PUT', body: Object.fromEntries(form)}), () => { setEditing(null); resource.reload(); }); }
  return <>
    <PageTitle
      eyebrow="ADMINISTRATION / CHALLENGES"
      title="Manage challenges"
      description="Manage availability, content and the lifecycle of your exercises."
      action={<Link className="button" href="/create-ctf">＋ Create challenge</Link>} />
    <Notice error={action.error} message={action.message} />
    <ResourceState {...resource}>
      <div className="stats-grid">
        <Stat label="Challenges" value={stats.total_challenges ?? rows(data.challenges).length} />
        <Stat label="Available" value={stats.active_challenges ?? rows(data.challenges).filter(c => truth(c.is_active)).length} />
        <Stat label="Retired" value={rows(data.challenges).filter(c => truth(c.marked_for_deletion)).length} />
        <Stat label="Running instances" value={stats.active_deployments} />
      </div>
      <Card>
        <div className="filter-bar">
          <Field
            label="Find a challenge"
            placeholder="Search by name…"
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }} />
          <Select
            label="Availability"
            value={state}
            options={['all', 'active', 'inactive', 'retired']}
            onChange={e => { setState(e.target.value); setPage(1); }} />
          <Select label="Category" value={category} options={['all', ...categories]} onChange={e => { setCategory(e.target.value); setPage(1); }} />
          <Select label="Sort challenges" value={sort} options={['name', 'deployments']} onChange={e => { setSort(e.target.value); setPage(1); }} />
          <button className="secondary" onClick={resource.reload}>Refresh ↻</button>
        </div>
        <p className="muted">{matching.length} matching exercises</p>
        {challenges.length ? <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Challenge</th>
                <th>Category</th>
                <th>Availability</th>
                <th>Instances</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {challenges.map(c => <tr key={text(c.id)}>
                <td>
                  <Link href={`/challenge?id=${number(c.id)}`}>
                    <strong>
                      {text(c.name)}
                    </strong>
                  </Link>
                  <small>
                    {text(c.difficulty)} · #{text(c.id)}
                  </small>
                </td>
                <td>
                  <Badge>
                    {text(c.category)}
                  </Badge>
                </td>
                <td>
                  <Badge tone={truth(c.marked_for_deletion) ? 'warning' : truth(c.is_active) ? 'active' : ''}>
                    {truth(c.marked_for_deletion) ? 'Retired' : truth(c.is_active) ? 'Available' : 'Inactive'}
                  </Badge>
                </td>
                <td>
                  {number(c.active_deployments)}
                </td>
                <td>
                  <div className="table-actions">
                    <button className="secondary small" disabled={truth(c.marked_for_deletion)} onClick={() => setEditing(c)}>Edit</button>
                    <button className="secondary small" onClick={() => setLeader(c)}>Leaderboard</button>
                    <button className="secondary small" onClick={()=>router.navigate('/manage-ctf?exercise='+number(c.id))}>History</button>
                    {truth(c.marked_for_deletion) ? <button className="secondary small" disabled={action.busy} onClick={() => void action.run(() => request('/api/admin/challenges/'+text(c.id)+'/restore', {method: 'POST', body: {}}), resource.reload)}>Restore</button> : <button className="danger subtle small" onClick={() => { setForce(false); setDeleting(c); }}>Retire</button>}
                    <button className="danger subtle small" onClick={() => { setForce(true); setDeleting(c); }}>Delete</button>
                  </div>
                </td>
              </tr>)}
            </tbody>
          </table>
        </div> : <Empty title="No matching challenges" />}
        <Pager page={currentPage} totalPages={totalPages} onPage={setPage} />
      </Card>
    </ResourceState>
    {selected>0&&<ExerciseHistoryPanel key={selected} identifier={selected} name={text(rows(data.challenges).find(item=>number(item.id)===selected)?.name,'Exercise #'+selected)} onClose={()=>router.navigate('/manage-ctf')}/>}
    {editing && <Card title={`Edit ${text(editing.name)}`} className="editor-panel">
      <form onSubmit={edit}>
        <Field
          label="Challenge name"
          name="name"
          defaultValue={text(editing.name)}
          required
          maxLength={100} />
        <Area
          label="Description"
          name="description"
          defaultValue={text(editing.description)}
          maxLength={2000}
          required />
        <div className="form-grid">
          <Select
            label="Category"
            name="category"
            defaultValue={text(editing.category)}
            options={categories} />
          <Select
            label="Difficulty"
            name="difficulty"
            defaultValue={text(editing.difficulty)}
            options={difficulties} />
        </div>
        <Area label="General hint" name="hint" defaultValue={text(editing.hint)} />
        <Area label="Tutor solution" name="solution" defaultValue={text(editing.solution)} />
        <label className="check">
          <input type="checkbox" name="isActive" defaultChecked={truth(editing.is_active)} />Available to students</label>
        <div className="button-row">
          <button disabled={action.busy}>Save changes</button>
          <button type="button" className="secondary" onClick={() => setEditing(null)}>Cancel</button>
        </div>
      </form>
    </Card>}
    {leader && <Leaderboard challenge={leader} onClose={() => setLeader(null)} />}
    {deleting && <Confirm
      title={force ? 'Permanently delete this challenge?' : 'Retire this challenge?'}
      confirm={force ? 'Delete challenge and instances' : 'Retire challenge'}
      busy={action.busy}
      onClose={() => setDeleting(null)}
      onConfirm={() => void action.run(() => request('/api/admin/challenges/'+text(deleting.id), { method: 'DELETE', body: { force } }), () => { setDeleting(null); resource.reload(); })}>
      <p>
        {force ? 'This removes the challenge and its instances. Exercise and grading data may be removed under the server’s retention rules. This cannot be undone from the console.' : 'The challenge will be marked for removal. The server will preserve or retire existing instances according to its lifecycle rules.'}
      </p>
      <strong>
        {text(deleting.name)}
      </strong>
      <Notice error={action.error} />
    </Confirm>}
  </>;
}
function Leaderboard({ challenge, onClose }: {
  challenge: Row;
  onClose: () => void;
}) {
  const [page, setPage] = useState(1), resource = useResource(`/api/admin/challenges/${number(challenge.id)}/leaderboard?page=${page}`), data = payload(resource.data);
  return <Card title={`Leaderboard · ${text(challenge.name)}`} action={<button className="secondary" onClick={onClose}>Close</button>}>
    <ResourceState {...resource}>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Rank</th>
              <th>Student</th>
              <th>Points</th>
            </tr>
          </thead>
          <tbody>
            {rows(data.leaderboard).map((entry, i) => <tr key={i}>
              <td>
                {text(entry.rank)}
              </td>
              <td>
                <Link href={'/profile/' + encodeURIComponent(text(entry.username))}>
                  {text(entry.username)}
                </Link>
              </td>
              <td>
                {text(entry.total_points ?? entry.points)}
              </td>
            </tr>)}
          </tbody>
        </table>
      </div>
      <Pager page={page} totalPages={Math.ceil(number(data.total_entries) / 10) || 1} onPage={setPage} />
    </ResourceState>
  </Card>;
}
