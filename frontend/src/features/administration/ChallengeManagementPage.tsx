import { useI18n } from '../../lib/i18n.tsx';
import { useState } from 'react';
import {
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
  Stat,
} from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { categories, number, payload, row, rows, text, truth, type Row } from '../../lib/data.ts';
import { Link, useRouter } from '../../lib/router.tsx';
import { useAction, useResource } from '../../lib/state.tsx';
import { PoolEditor } from './PoolEditor.tsx';
import { ExerciseHistoryPanel } from './ExerciseHistoryPanel.tsx';
import { SortableHeader } from '../../components/SortableHeader.tsx';
import { useTableSort } from '../../lib/useTableSort.ts';
import { Overlay } from '../../components/Overlay.tsx';
import { CreateChallenge } from './ChallengeEditorPage.tsx';
export function ManageChallenges() {
  const { t } = useI18n();
  const router = useRouter(),
    query = new URLSearchParams(router.location.split('?')[1]),
    selected = number(query.get('exercise')),
    editing = number(query.get('edit'));
  const resource = useResource('/api/admin/challenges', 30000),
    data = payload(resource.data),
    stats = row(data.stats),
    action = useAction();
  const [search, setSearch] = useState(''),
    [state, setState] = useState('all'),
    [deleting, setDeleting] = useState<Row | null>(null),
    [force, setForce] = useState(false),
    [leader, setLeader] = useState<Row | null>(null);
  const [poolId, setPoolId] = useState(0);
  const [category, setCategory] = useState('all'),
    [page, setPage] = useState(1);
  const sorting = useTableSort<Row>(
    {
      name: (c) => text(c.name),
      category: (c) => text(c.category),
      availability: (c) =>
        truth(c.marked_for_deletion) ? 'Retired' : truth(c.is_active) ? 'Available' : 'Inactive',
      instances: (c) => number(c.active_deployments),
    },
    'name',
  );
  const filtered = rows(data.challenges).filter(
    (c) =>
      text(c.name).toLowerCase().includes(search.toLowerCase()) &&
      (state === 'all' ||
        (state === 'active'
          ? truth(c.is_active) && !truth(c.marked_for_deletion)
          : state === 'retired'
            ? truth(c.marked_for_deletion)
            : !truth(c.is_active))),
  );
  const matching = sorting.apply(
    filtered.filter((c) => category === 'all' || text(c.category) === category),
  );
  const totalPages = Math.max(1, Math.ceil(matching.length / 20)),
    currentPage = Math.min(page, totalPages);
  const challenges = matching.slice((currentPage - 1) * 20, currentPage * 20);
  return (
    <>
      <PageTitle
        eyebrow={t('authoring.administrationChallenges')}
        title={t('authoring.manageChallenges')}
        description={t('authoring.management.description')}
        action={
          <Link className="button" href="/create-ctf">
            {t('authoring.createChallenge')}
          </Link>
        }
      />
      <Notice error={action.error} message={action.message} />
      <ResourceState {...resource}>
        <div className="stats-grid">
          <Stat
            label={t('navigation.challenges')}
            value={stats.total_challenges ?? rows(data.challenges).length}
          />
          <Stat
            label={t('authoring.available')}
            value={
              stats.active_challenges ??
              rows(data.challenges).filter((c) => truth(c.is_active)).length
            }
          />
          <Stat
            label={t('authoring.retired')}
            value={rows(data.challenges).filter((c) => truth(c.marked_for_deletion)).length}
          />
          <Stat label={t('authoring.runningInstances')} value={stats.active_deployments} />
        </div>
        <Card>
          <div className="filter-bar">
            <Field
              label={t('authoring.findAChallenge')}
              placeholder={t('authoring.searchByName')}
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
            <Select
              label={t('common.labels.availability')}
              value={state}
              options={['all', 'active', 'inactive', 'retired']}
              onChange={(e) => {
                setState(e.target.value);
                setPage(1);
              }}
            />
            <Select
              label={t('common.labels.category')}
              value={category}
              options={['all', ...categories]}
              onChange={(e) => {
                setCategory(e.target.value);
                setPage(1);
              }}
            />
            <button className="secondary" onClick={resource.reload}>
              {t('artifacts.refresh')}
            </button>
          </div>
          <p className="muted">
            {matching.length}
            {' ' + t('authoring.matchingExercises')}
          </p>
          {challenges.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {(['name', 'category', 'availability', 'instances'] as const).map(
                      (key, index) => (
                        <SortableHeader
                          key={key}
                          {...sorting.header(
                            key,
                            [
                              t('common.labels.challenge'),
                              t('common.labels.category'),
                              t('common.labels.availability'),
                              t('common.labels.instances'),
                            ][index],
                          )}
                          onSort={() => {
                            sorting.header(key, '').onSort();
                            setPage(1);
                          }}
                        />
                      ),
                    )}
                    <th>{t('common.labels.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {challenges.map((c) => (
                    <tr key={text(c.id)}>
                      <td>
                        <Link href={`/challenge?id=${number(c.id)}`}>
                          <strong>{text(c.name)}</strong>
                        </Link>
                        <small>
                          {text(c.difficulty)} · #{text(c.id)}
                        </small>
                      </td>
                      <td>
                        <Badge>{text(c.category)}</Badge>
                      </td>
                      <td>
                        <Badge
                          tone={
                            truth(c.marked_for_deletion)
                              ? 'warning'
                              : truth(c.is_active)
                                ? 'active'
                                : ''
                          }
                        >
                          {truth(c.marked_for_deletion)
                            ? t('authoring.retired')
                            : truth(c.is_active)
                              ? t('authoring.available')
                              : t('common.inactive')}
                        </Badge>
                      </td>
                      <td>{number(c.active_deployments)}</td>
                      <td>
                        <div className="table-actions">
                          {truth(c.marked_for_deletion) ? (
                            <button className="secondary small" disabled>
                              {t('common.actions.edit')}
                            </button>
                          ) : (
                            <Link
                              className="button secondary small"
                              href={`/manage-ctf?edit=${number(c.id)}`}
                            >
                              {t('common.actions.edit')}
                            </Link>
                          )}
                          <button
                            className="secondary small"
                            onClick={() => setPoolId(number(c.id))}
                          >
                            {t('authoring.configurePool')}
                          </button>
                          <button className="secondary small" onClick={() => setLeader(c)}>
                            {t('authoring.leaderboard')}
                          </button>
                          <button
                            className="secondary small"
                            onClick={() => router.navigate('/manage-ctf?exercise=' + number(c.id))}
                          >
                            {t('authoring.history')}
                          </button>
                          {truth(c.marked_for_deletion) ? (
                            <button
                              className="secondary small"
                              disabled={action.busy}
                              onClick={() =>
                                void action.run(
                                  () =>
                                    request('/api/admin/challenges/' + text(c.id) + '/restore', {
                                      method: 'POST',
                                      body: {},
                                    }),
                                  resource.reload,
                                )
                              }
                            >
                              {t('common.actions.restore')}
                            </button>
                          ) : (
                            <button
                              className="danger subtle small"
                              onClick={() => {
                                setForce(false);
                                setDeleting(c);
                              }}
                            >
                              {t('authoring.retire')}
                            </button>
                          )}
                          <button
                            className="danger subtle small"
                            onClick={() => {
                              setForce(true);
                              setDeleting(c);
                            }}
                          >
                            {t('common.actions.delete')}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title={t('authoring.noMatchingChallenges')} />
          )}
          <Pager page={currentPage} totalPages={totalPages} onPage={setPage} />
        </Card>
      </ResourceState>
      {poolId > 0 && (
        <PoolEditor identifier={poolId} onClose={() => setPoolId(0)} onSaved={resource.reload} />
      )}
      {selected > 0 && (
        <ExerciseHistoryPanel
          key={selected}
          identifier={selected}
          name={text(
            rows(data.challenges).find((item) => number(item.id) === selected)?.name,
            'Exercise #' + selected,
          )}
          onClose={() => router.navigate('/manage-ctf')}
        />
      )}
      {editing > 0 && (
        <Overlay title={t('authoring.edit.title')} onClose={() => router.navigate('/manage-ctf')}>
          <CreateChallenge />
        </Overlay>
      )}
      {leader && (
        <Overlay title={t('authoring.leaderboard')} onClose={() => setLeader(null)}>
          <Leaderboard challenge={leader} onClose={() => setLeader(null)} />
        </Overlay>
      )}
      {deleting && (
        <Confirm
          title={
            force ? t('common.permanentlyDeleteThisChallenge') : t('common.retireThisChallenge')
          }
          confirm={force ? t('common.deleteChallengeAndInstances') : t('common.retireChallenge')}
          busy={action.busy}
          onClose={() => setDeleting(null)}
          onConfirm={() =>
            void action.run(
              () =>
                request('/api/admin/challenges/' + text(deleting.id), {
                  method: 'DELETE',
                  body: { force },
                }),
              () => {
                setDeleting(null);
                resource.reload();
              },
            )
          }
        >
          <p>{force ? t('authoring.delete.warning') : t('authoring.retire.explanation')}</p>
          <strong>{text(deleting.name)}</strong>
          <Notice error={action.error} />
        </Confirm>
      )}
    </>
  );
}
function Leaderboard({ challenge, onClose }: { challenge: Row; onClose: () => void }) {
  const { t } = useI18n();
  const [page, setPage] = useState(1),
    resource = useResource(
      `/api/admin/challenges/${number(challenge.id)}/leaderboard?page=${page}`,
    ),
    data = payload(resource.data);
  return (
    <Card
      title={t('authoring.leaderboard.title', { name: text(challenge.name) })}
      action={
        <button className="secondary" onClick={onClose}>
          {t('common.actions.close')}
        </button>
      }
    >
      <ResourceState {...resource}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('authoring.rank')}</th>
                <th>{t('authoring.student')}</th>
                <th>{t('common.labels.points')}</th>
              </tr>
            </thead>
            <tbody>
              {rows(data.leaderboard).map((entry, i) => (
                <tr key={i}>
                  <td>{text(entry.rank)}</td>
                  <td>
                    <Link href={'/profile/' + encodeURIComponent(text(entry.username))}>
                      {text(entry.username)}
                    </Link>
                  </td>
                  <td>{text(entry.total_points ?? entry.points)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pager
          page={page}
          totalPages={Math.ceil(number(data.total_entries) / 10) || 1}
          onPage={setPage}
        />
      </ResourceState>
    </Card>
  );
}
