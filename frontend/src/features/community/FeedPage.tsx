import { useState } from 'react';
import { ActivityList,Badge,Card,Empty,PageTitle,Pager,ResourceState,Select,Stat } from '../../components/ui.tsx';
import { date,number,payload,row,rows,text,truth } from '../../lib/data.ts';
import { useResource } from '../../lib/state.tsx';
export function Feed({ kind }: {
    kind: 'announcements' | 'activity' | 'badges';
}) {
    const [page, setPage] = useState(1), [range, setRange] = useState('all'), [filter, setFilter] = useState('all');
    const resource = useResource(`/backend/${kind}.php?` + new URLSearchParams({ page: String(page), range, importance: filter, type: filter, category: 'all' }));
    const data = payload(resource.data), badges = rows(data.badges), stats = row(data.stats), items = rows(data.announcements ?? data.activities);
    return <>
    <PageTitle eyebrow={kind === 'badges' ? 'YOUR ACHIEVEMENTS' : 'STAY IN THE LOOP'} title={kind === 'badges' ? 'Milestones worth remembering.' : kind === 'activity' ? 'Your investigation journal.' : 'From the heiST team.'} description={kind === 'badges' ? 'Every achievement is a reminder of what you’ve learned.' : kind === 'activity' ? 'Challenges, discoveries and progress in one place.' : 'Platform news, upcoming events and maintenance notices.'}/>
    {kind !== 'badges' && <div className="filter-bar">
      <Select 
        label="Time period" 
        value={range} 
        options={['all', 'week', 'month', 'year']} 
        onChange={e => { setRange(e.target.value); setPage(1); }}/>
      <Select 
        label={kind === 'activity' ? 'Activity type' : 'Importance'} 
        value={filter} 
        options={kind === 'activity' ? ['all', 'challenge', 'badge'] : ['all', 'normal', 'important', 'critical']} 
        onChange={e => { setFilter(e.target.value); setPage(1); }}/>
    </div>}
    <ResourceState {...resource}>
      {kind === 'badges' ? <>
        <div className="stats-grid">
          <Stat label="Badges earned" value={stats.earned ?? stats.earned_badges}/>
          <Stat label="Available achievements" value={stats.total ?? badges.length}/>
        </div>
        <div className="feature-grid">
          {badges.map((badge, i) => <Card key={text(badge.id, String(i))} className={truth(badge.earned ?? badge.is_earned) ? 'earned' : ''}>
            <span className="achievement-glyph" aria-hidden>✦</span>
            <h2>
              {text(badge.name)}
            </h2>
            <p className="muted">
              {text(badge.description)}
            </p>
            <Badge tone={truth(badge.earned ?? badge.is_earned) ? 'active' : ''}>
              {truth(badge.earned ?? badge.is_earned) ? 'Earned' : 'In progress'}
            </Badge>
          </Card>)}
        </div>
      </> : kind === 'activity' ? <Card>
        <ActivityList items={items}/>
      </Card> : items.length ? <div className="news-list">
        {items.map((item, i) => <Card key={text(item.id, String(i))}>
          <div className="spread">
            <Badge tone={text(item.importance)}>
              {text(item.category, 'general')}
            </Badge>
            <small className="muted">
              {date(item.created_at)}
            </small>
          </div>
          <h2>
            {text(item.title)}
          </h2>
          <p className="lede">
            {text(item.short_description)}
          </p>
          <p className="prose">
            {text(item.content)}
          </p>
        </Card>)}
      </div> : <Empty title="You’re all caught up">There are no announcements matching these filters.</Empty>}
      {kind !== 'badges' && <Pager page={page} totalPages={number(data.total_pages) || Math.ceil(number(data.total) / (number(data.per_page) || 10)) || 1} onPage={setPage}/>}
    </ResourceState>
  </>;
}
