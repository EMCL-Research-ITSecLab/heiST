import { useI18n } from '../../lib/i18n.tsx';
import { useState, type FormEvent } from 'react';
import {
  Area,
  Badge,
  Card,
  Confirm,
  Empty,
  Field,
  Notice,
  PageTitle,
  Pager,
  ResourceState,
  Select,
} from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { date, number, payload, rows, text, type Row } from '../../lib/data.ts';
import { useAction, useResource } from '../../lib/state.tsx';
export function ManageAnnouncements() {
  const { t } = useI18n();
  const [page, setPage] = useState(1),
    [editing, setEditing] = useState<Row | null>(null),
    [deleting, setDeleting] = useState<Row | null>(null);
  const resource = useResource(`/api/admin/announcements?page=${page}`),
    data = payload(resource.data),
    action = useAction();
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = Object.fromEntries(new FormData(event.currentTarget));
    await action.run(
      () =>
        request('/api/admin/announcements' + (editing?.id ? '/' + text(editing.id) : ''), {
          method: editing?.id ? 'PUT' : 'POST',
          body,
        }),
      () => {
        setEditing(null);
        resource.reload();
      },
    );
  }
  return (
    <>
      <PageTitle
        eyebrow={t('announcements.administrationCommunication')}
        title={t('announcements.manageAnnouncements')}
        description={t('announcements.page.description')}
        action={
          <button onClick={() => setEditing({})}>{t('announcements.newAnnouncement')}</button>
        }
      />
      <Notice error={action.error} message={action.message} />
      <ResourceState {...resource}>
        <div className="news-list">
          {rows(data.announcements).map((item) => (
            <Card key={text(item.id)}>
              <div className="spread">
                <Badge>{text(item.category)}</Badge>
                <small>{date(item.created_at)}</small>
              </div>
              <h2>{text(item.title)}</h2>
              <p>{text(item.short_description)}</p>
              <div className="button-row">
                <button className="secondary" onClick={() => setEditing(item)}>
                  {t('common.actions.edit')}
                </button>
                <button className="danger subtle" onClick={() => setDeleting(item)}>
                  {t('common.actions.delete')}
                </button>
              </div>
            </Card>
          ))}
        </div>
        {!rows(data.announcements).length && (
          <Empty title={t('announcements.noAnnouncementsYet')} />
        )}
        <Pager page={page} totalPages={Math.ceil(number(data.total) / 10) || 1} onPage={setPage} />
      </ResourceState>
      {editing && (
        <Card
          title={editing.id ? t('common.editAnnouncement') : t('common.newAnnouncement')}
          className="editor-panel"
        >
          <form onSubmit={save}>
            <Field
              label={t('common.labels.title')}
              name="title"
              defaultValue={text(editing.title)}
              maxLength={100}
              required
            />
            <Area
              label={t('announcements.shortDescription')}
              name="short_description"
              defaultValue={text(editing.short_description)}
              maxLength={255}
            />
            <Area
              label={t('announcements.announcement')}
              name="content"
              defaultValue={text(editing.content)}
              maxLength={5000}
              required
            />
            <div className="form-grid">
              <Select
                label={t('common.labels.category')}
                name="category"
                defaultValue={text(editing.category, 'general')}
                options={['general', 'updates', 'maintenance', 'events', 'security']}
              />
              <Select
                label={t('announcements.importance')}
                name="importance"
                defaultValue={text(editing.importance, 'normal')}
                options={['normal', 'important', 'critical']}
              />
            </div>
            <div className="button-row">
              <button disabled={action.busy}>{t('announcements.publishAnnouncement')}</button>
              <button type="button" className="secondary" onClick={() => setEditing(null)}>
                {t('common.actions.cancel')}
              </button>
            </div>
          </form>
        </Card>
      )}
      {deleting && (
        <Confirm
          title={t('announcements.deleteThisAnnouncement')}
          confirm={t('announcements.deleteAnnouncement')}
          busy={action.busy}
          onClose={() => setDeleting(null)}
          onConfirm={() =>
            void action.run(
              () => request('/api/admin/announcements/' + text(deleting.id), { method: 'DELETE' }),
              () => {
                setDeleting(null);
                resource.reload();
              },
            )
          }
        >
          <p>{text(deleting.title)}</p>
          <Notice error={action.error} />
        </Confirm>
      )}
    </>
  );
}
