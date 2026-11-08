import { Badge, Card } from '../../components/ui.tsx';
import { date, text, type Row } from '../../lib/data.ts';
import { Link } from '../../lib/router.tsx';

const priority = (item: Row) => item.importance === 'critical' ? 2 : item.importance === 'important' ? 1 : 0;
export function DashboardAnnouncements({ announcements }: { announcements: Row[] }) {
  if (!announcements.length) return null;
  const ordered = [...announcements].sort((a, b) => priority(b) - priority(a));
  return <section aria-label="Dashboard announcements" className="dashboard-announcements">
    <div className="section-heading">
      <h2>Announcements</h2>
      <Link href="/announcements">View all announcements →</Link>
    </div>
    {ordered.map((announcement, index) => <Card key={text(announcement.id, String(index))}
      className={'dashboard-announcement ' + (priority(announcement) === 2 ? 'critical' : priority(announcement) === 1 ? 'important' : 'normal')}>
      <div className="spread">
        <Badge tone={priority(announcement) === 2 ? 'critical' : priority(announcement) === 1 ? 'important' : ''}>
          {priority(announcement) === 2 ? 'Critical' : priority(announcement) === 1 ? 'Important' : 'Announcement'}
        </Badge>
        <small className="muted">{date(announcement.created_at)}</small>
      </div>
      <h3>{text(announcement.title)}</h3>
      {Boolean(announcement.short_description) && <p className="prose">{text(announcement.short_description)}</p>}
      {Boolean(announcement.author) && <small className="muted">{text(announcement.author)}</small>}
    </Card>)}
  </section>;
}
