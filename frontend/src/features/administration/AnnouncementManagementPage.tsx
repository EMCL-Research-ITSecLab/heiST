import { useState,type FormEvent } from 'react';
import { Area,Badge,Card,Confirm,Empty,Field,Notice,PageTitle,Pager,ResourceState,Select } from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { date,number,payload,rows,text,type Row } from '../../lib/data.ts';
import { useAction,useResource } from '../../lib/state.tsx';
export function ManageAnnouncements() {
    const [page, setPage] = useState(1), [editing, setEditing] = useState<Row | null>(null), [deleting, setDeleting] = useState<Row | null>(null);
    const resource = useResource(`/backend/manage-announcements.php?action=list&page=${page}`), data = payload(resource.data), action = useAction();
    async function save(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const body = Object.fromEntries(new FormData(event.currentTarget)); await action.run(() => request('/backend/manage-announcements.php?action=' + (editing?.id ? 'update' : 'create'), { method: 'POST', body: { ...body, ...(editing?.id ? { id: editing.id } : {}) } }), () => { setEditing(null); resource.reload(); }); }
    return <>
    <PageTitle 
      eyebrow="ADMINISTRATION / COMMUNICATION" 
      title="Keep everyone in the loop." 
      description="Share updates, events and maintenance notices with your students." 
      action={<button onClick={() => setEditing({})}>＋ New announcement</button>}/>
    <Notice error={action.error} message={action.message}/>
    <ResourceState {...resource}>
      <div className="news-list">
        {rows(data.announcements).map(item => <Card key={text(item.id)}>
          <div className="spread">
            <Badge>
              {text(item.category)}
            </Badge>
            <small>
              {date(item.created_at)}
            </small>
          </div>
          <h2>
            {text(item.title)}
          </h2>
          <p>
            {text(item.short_description)}
          </p>
          <div className="button-row">
            <button className="secondary" onClick={() => setEditing(item)}>Edit</button>
            <button className="danger subtle" onClick={() => setDeleting(item)}>Delete</button>
          </div>
        </Card>)}
      </div>
      {!rows(data.announcements).length && <Empty title="No announcements yet"/>}
      <Pager page={page} totalPages={Math.ceil(number(data.total) / 10) || 1} onPage={setPage}/>
    </ResourceState>
    {editing && <Card title={editing.id ? 'Edit announcement' : 'New announcement'} className="editor-panel">
      <form onSubmit={save}>
        <Field label="Title" name="title" defaultValue={text(editing.title)} maxLength={100} required/>
        <Area 
          label="Short description" 
          name="short_description" 
          defaultValue={text(editing.short_description)} 
          maxLength={255}/>
        <Area 
          label="Announcement" 
          name="content" 
          defaultValue={text(editing.content)} 
          maxLength={5000} 
          required/>
        <div className="form-grid">
          <Select 
            label="Category" 
            name="category" 
            defaultValue={text(editing.category, 'general')} 
            options={['general', 'updates', 'maintenance', 'events', 'security']}/>
          <Select 
            label="Importance" 
            name="importance" 
            defaultValue={text(editing.importance, 'normal')} 
            options={['normal', 'important', 'critical']}/>
        </div>
        <div className="button-row">
          <button disabled={action.busy}>Publish announcement</button>
          <button type="button" className="secondary" onClick={() => setEditing(null)}>Cancel</button>
        </div>
      </form>
    </Card>}
    {deleting && <Confirm 
        title="Delete this announcement?" 
        confirm="Delete announcement" 
        busy={action.busy} 
        onClose={() => setDeleting(null)} 
        onConfirm={() => void action.run(() => request('/backend/manage-announcements.php?action=delete', { method: 'POST', body: { id: deleting.id } }), () => { setDeleting(null); resource.reload(); })}>
      <p>
        {text(deleting.title)}
      </p>
      <Notice error={action.error}/>
    </Confirm>}
  </>;
}
