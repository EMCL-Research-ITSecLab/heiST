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
  ResourceState,
} from '../../components/ui.tsx';
import { Link } from '../../lib/router.tsx';
import { request } from '../../lib/api.ts';
import { date, number, payload, row, rows, text, truth, type Row } from '../../lib/data.ts';
import { useAction, useResource, useSession } from '../../lib/state.tsx';

type UserAction = 'role' | 'password' | 'revoke_sessions';
type Selection = { user: Row; kind: UserAction };

export function ManageUsers() {
  const { t } = useI18n();
  const session = useSession();
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [confirmation, setConfirmation] = useState('');
  const [password, setPassword] = useState('');
  const resource = useResource(
    '/api/admin/users?' + new URLSearchParams({ search, page: String(page) }),
  );
  const data = payload(resource.data);
  const action = useAction();

  function choose(user: Row, kind: UserAction) {
    action.clear();
    setSelected({ user, kind });
    setConfirmation('');
    setPassword('');
  }
  function close() {
    setSelected(null);
    setPassword('');
    setConfirmation('');
  }
  async function apply() {
    if (!selected) return;
    const { user, kind } = selected;
    const body: Row = { action: kind, confirmation };
    if (kind === 'role') body.administrator = !truth(user.is_admin);
    if (kind === 'password') body.password = password;
    await action.run(
      () => request('/api/admin/users/' + number(user.id), { method: 'POST', body }),
      () => {
        close();
        resource.reload();
      },
    );
  }

  return (
    <>
      <PageTitle
        title={t('navigation.users')}
        eyebrow={t('routing.administration')}
        description={t('users.accountsRolesAndActiveSessions')}
        action={
          <button className="secondary" onClick={resource.reload}>
            {t('common.actions.refresh')}
          </button>
        }
      />
      <Notice error={action.error} message={action.message} />
      <Card>
        <Field
          label={t('users.findAUser')}
          value={search}
          maxLength={100}
          placeholder={t('users.usernameOrEmail')}
          onChange={(event) => {
            setSearch(event.target.value);
            setPage(1);
          }}
        />
      </Card>
      <ResourceState {...resource}>
        <Card title={t('overview.accounts')}>
          {rows(data.users).length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t('common.labels.user')}</th>
                    <th>{t('common.labels.role')}</th>
                    <th>{t('users.sessions')}</th>
                    <th>{t('instances.instance')}</th>
                    <th>{t('users.lastSignIn')}</th>
                    <th>{t('common.labels.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows(data.users).map((user) => {
                    const operation = row(user.operation);
                    const ownAccount = user.username === session.user?.username;
                    return (
                      <tr key={number(user.id)}>
                        <td>
                          <Link href={'/profile/' + encodeURIComponent(text(user.username))}>
                            <strong>{text(user.username)}</strong>
                          </Link>
                          <small className="muted account-email">{text(user.email)}</small>
                          <small className="muted account-email">
                            {t('common.labels.id') + ' '}
                            {number(user.id)}
                            {user.vpn_ip ? ` · VPN ${text(user.vpn_ip)}` : ''}
                          </small>
                        </td>
                        <td>
                          <Badge>
                            {truth(user.is_admin)
                              ? t('audit.administrator')
                              : t('authoring.student')}
                          </Badge>
                          {truth(user.password_reset) && (
                            <small className="account-email">
                              {t('users.passwordChangeRequired')}
                            </small>
                          )}
                        </td>
                        <td>
                          {number(user.sessions)}
                          {Boolean(operation.state) && (
                            <details>
                              <summary>
                                {t('users.operation') + ' '}
                                {text(operation.state)}
                              </summary>
                              <p className="prose">
                                {text(operation.action)} · {text(operation.id)}
                                <br />
                                {t('users.scope') + ' '}
                                {text(operation.scope)}
                                {' ' + t('users.resource') + ' '}
                                {number(operation.resource)}
                              </p>
                            </details>
                          )}
                        </td>
                        <td>{user.running_challenge ? number(user.running_challenge) : '—'}</td>
                        <td>{date(user.last_login)}</td>
                        <td>
                          <div className="button-row">
                            <button
                              className="secondary small"
                              disabled={ownAccount}
                              onClick={() => choose(user, 'role')}
                            >
                              {t('users.changeRole')}
                            </button>
                            <button
                              className="secondary small"
                              disabled={ownAccount}
                              onClick={() => choose(user, 'password')}
                            >
                              {t('users.resetPassword')}
                            </button>
                            <button
                              className="secondary small"
                              disabled={ownAccount}
                              onClick={() => choose(user, 'revoke_sessions')}
                            >
                              {t('users.signOutSessions')}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title={t('users.noMatchingUsers')} />
          )}
          <div className="button-row">
            <button className="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>
              {t('common.pagination.previous')}
            </button>
            <span>
              {t('common.page') + ' '}
              {page}
            </span>
            <button
              className="secondary"
              disabled={!truth(data.has_more)}
              onClick={() => setPage(page + 1)}
            >
              {t('common.pagination.next')}
            </button>
          </div>
        </Card>
      </ResourceState>
      {selected && (
        <Confirm
          title={
            selected.kind === 'role'
              ? t('users.changeRole')
              : selected.kind === 'password'
                ? t('users.resetPassword')
                : t('users.signOutSessions')
          }
          confirm={t('common.actions.apply')}
          busy={action.busy}
          onClose={close}
          onConfirm={() => void apply()}
        >
          <Notice error={action.error} />
          <p>
            {selected.kind === 'role'
              ? t('users.confirmRoleChange', {
                  username: text(selected.user.username),
                  role: truth(selected.user.is_admin)
                    ? t('common.aStudent')
                    : t('common.anAdministrator'),
                })
              : selected.kind === 'password'
                ? t('users.passwordResetHint')
                : t('users.revokeSessionsHint')}{' '}
            {t('users.sessionRevocationHint')}
          </p>
          {selected.kind === 'password' && (
            <Field
              label={t('users.temporaryPassword')}
              type="password"
              autoComplete="new-password"
              minLength={8}
              maxLength={72}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          )}
          <Field
            label={t('users.confirmUsername', { username: text(selected.user.username) })}
            value={confirmation}
            autoComplete="off"
            onChange={(event) => setConfirmation(event.target.value)}
          />
        </Confirm>
      )}
    </>
  );
}
