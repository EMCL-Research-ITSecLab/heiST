import { Badge, Card, Empty, PageTitle, ResourceState, Stat } from '../../components/ui.tsx';
import { number, payload, row, rows, text, truth } from '../../lib/data.ts';
import { Link } from '../../lib/router.tsx';
import { useResource } from '../../lib/state.tsx';
export function Operations() {
  const resource = useResource('/backend/manage-ctf.php?action=get_challenges', 15000), data = payload(resource.data), stats = row(data.stats), challenges = rows(data.challenges);
  return <>
    <PageTitle
      eyebrow="ADMINISTRATION / LAB OVERVIEW"
      title="Keep the whole picture in view."
      description="Availability and deployment activity for the exercises you manage."
      action={<button className="secondary" onClick={resource.reload}>Refresh ↻</button>} />
    <ResourceState {...resource}>
      <div className="stats-grid">
        <Stat label="Managed challenges" value={stats.total_challenges ?? challenges.length} />
        <Stat label="Active deployments" value={stats.active_deployments} />
        <Stat label="Total deployments" value={stats.total_deployments} />
        <Stat label="Average completion" value={number(stats.avg_completion_minutes) ? number(stats.avg_completion_minutes).toFixed(1) + ' min' : '—'} />
      </div>
      <Card title="Exercise availability" action={<Link href="/manage-ctf">Manage challenges →</Link>}>
        {challenges.length ? <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Exercise</th>
                <th>Availability</th>
                <th>Active deployments</th>
                <th>Total deployments</th>
                <th>Solves</th>
              </tr>
            </thead>
            <tbody>
              {challenges.map(c => <tr key={text(c.id)}>
                <td>
                  <Link href={`/challenge?id=${number(c.id)}`}>
                    {text(c.name)}
                  </Link>
                </td>
                <td>
                  <Badge tone={truth(c.marked_for_deletion) ? 'warning' : truth(c.is_active) ? 'active' : ''}>
                    {truth(c.marked_for_deletion) ? 'Retiring' : truth(c.is_active) ? 'Available' : 'Inactive'}
                  </Badge>
                </td>
                <td>
                  {number(c.active_deployments)}
                </td>
                <td>
                  {number(c.total_deployments)}
                </td>
                <td>
                  {number(c.solve_count)}
                </td>
              </tr>)}
            </tbody>
          </table>
        </div> : <Empty title="No exercises to monitor yet" />}
      </Card>
    </ResourceState>
  </>;
}
