import { ActivityList,Card,ChallengeCard,Empty,PageTitle,ResourceState,Stat } from '../../components/ui.tsx';
import { number,payload,row,rows,text } from '../../lib/data.ts';
import { Link } from '../../lib/router.tsx';
import { useResource,useSession } from '../../lib/state.tsx';
export function Dashboard() {
    const resource = useResource('/backend/dashboard.php', 30000), data = payload(resource.data), user = row(data.user), progress = row(data.progress), active = row(data.active_challenge), timeline = row(data.timeline);
    const session = useSession();
    return <>
    <PageTitle 
      eyebrow="YOUR LEARNING WORKSPACE" 
      title={`Ready for your next discovery${text(user.username ?? session.user?.username) ? ', ' + text(user.username ?? session.user?.username) : ''}?`} 
      description="Pick up an investigation or find something new to explore." 
      action={<Link className="button" href="/explore">Explore challenges ↗</Link>}/>
    <ResourceState {...resource}>
      <div className="stats-grid">
        <Stat label="Total points" value={user.points}/>
        <Stat label="Challenges solved" value={progress.solved}/>
        <Stat label="Success rate" value={`${number(progress.success_rate)}%`}/>
        <Stat label="Your rank" value={number(user.rank) ? '#' + text(user.rank) : '—'}/>
      </div>
      {Object.keys(active).length > 0 && number(active.id ?? active.challenge_template_id) > 0 && <div className="active-banner">
        <span className="status-dot"/>
        <div>
          <strong>Your lab is ready when you are</strong>
          <p>
            {text(active.name ?? active.challenge_name)}
          </p>
        </div>
        <Link className="button secondary" href={`/challenge?id=${number(active.challenge_template_id ?? active.id)}`}>Continue investigation →</Link>
      </div>}
      <div className="section-heading">
        <div>
          <p className="eyebrow">KEEP YOUR CURIOSITY MOVING</p>
          <h2>Your next challenge</h2>
        </div>
        <Link href="/explore">View library →</Link>
      </div>
      <div className="challenge-grid">
        {rows(data.challenges).map(c => <ChallengeCard key={text(c.id)} challenge={c}/>)}
      </div>
      {rows(data.challenges).length === 0 && <Empty title="A fresh start">Browse the library to find your first investigation.</Empty>}
      <div className="two-columns">
        <Card title="Recent activity" action={<Link href="/activity">View all →</Link>}>
          <ActivityList items={rows(data.activity)}/>
        </Card>
        <Card title="Your learning rhythm">
          <div className="bar-chart" aria-label="Points earned over time">
            {Array.isArray(timeline.points) && timeline.points.length ? timeline.points.map((point, i) => <div key={i}>
              <span style={{ height: `${Math.max(3, number(point) / Math.max(1, ...timeline.points as number[]) * 120)}px` }} title={`${text((timeline.labels as unknown[])?.[i])}: ${number(point)} points`}/>
              <small>
                {text((timeline.labels as unknown[])?.[i])}
              </small>
            </div>) : <Empty title="Progress starts with practice">Your points will appear here as you solve challenges.</Empty>}
          </div>
          <Link href="/badges">Explore your achievements →</Link>
        </Card>
      </div>
    </ResourceState>
  </>;
}
