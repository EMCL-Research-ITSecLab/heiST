import { useState } from 'react';
import { Badge, Card, Confirm, Empty, Field, Notice, PageTitle, ResourceState } from '../../components/ui.tsx';
import { Link } from '../../lib/router.tsx';
import { request } from '../../lib/api.ts';
import { date, number, payload, row, rows, text, truth, type Row } from '../../lib/data.ts';
import { useAction, useResource, useSession } from '../../lib/state.tsx';

type UserAction = 'role' | 'password' | 'revoke_sessions';
type Selection = { user: Row; kind: UserAction };

export function ManageUsers() {
  const session = useSession();
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [confirmation, setConfirmation] = useState('');
  const [password, setPassword] = useState('');
  const resource = useResource('/api/admin/users?' + new URLSearchParams({ search, page: String(page) }));
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
      () => { close(); resource.reload(); },
    );
  }

  return <>
    <PageTitle title="Users" eyebrow="ADMINISTRATION" description="Accounts, roles and active sessions."
      action={<button className="secondary" onClick={resource.reload}>Refresh</button>} />
    <Notice error={action.error} message={action.message} />
    <Card>
      <Field label="Find a user" value={search} maxLength={100} placeholder="Username or email"
        onChange={event => { setSearch(event.target.value); setPage(1); }} />
    </Card>
    <ResourceState {...resource}>
      <Card title="Accounts">
        {rows(data.users).length ? <div className="table-wrap">
          <table>
            <thead><tr><th>User</th><th>Role</th><th>Sessions</th><th>Instance</th><th>Last sign in</th><th>Actions</th></tr></thead>
            <tbody>
              {rows(data.users).map(user => {
                const operation = row(user.operation);
                const ownAccount = user.username === session.user?.username;
                return <tr key={number(user.id)}>
                  <td>
                    <Link href={'/profile/' + encodeURIComponent(text(user.username))}><strong>{text(user.username)}</strong></Link>
                    <small className="muted account-email">{text(user.email)}</small>
                    <small className="muted account-email">ID {number(user.id)}{user.vpn_ip ? ` · VPN ${text(user.vpn_ip)}` : ''}</small>
                  </td>
                  <td>
                    <Badge>{truth(user.is_admin) ? 'Administrator' : 'Student'}</Badge>
                    {truth(user.password_reset) && <small className="account-email">Password change required</small>}
                  </td>
                  <td>
                    {number(user.sessions)}
                    {Boolean(operation.state) && <details>
                      <summary>Operation: {text(operation.state)}</summary>
                      <p className="prose">{text(operation.action)} · {text(operation.id)}<br />Scope: {text(operation.scope)} · Resource: {number(operation.resource)}</p>
                    </details>}
                  </td>
                  <td>{user.running_challenge ? number(user.running_challenge) : '—'}</td>
                  <td>{date(user.last_login)}</td>
                  <td><div className="button-row">
                    <button className="secondary small" disabled={ownAccount} onClick={() => choose(user, 'role')}>Change role</button>
                    <button className="secondary small" disabled={ownAccount} onClick={() => choose(user, 'password')}>Reset password</button>
                    <button className="secondary small" disabled={ownAccount} onClick={() => choose(user, 'revoke_sessions')}>Sign out sessions</button>
                  </div></td>
                </tr>;
              })}
            </tbody>
          </table>
        </div> : <Empty title="No matching users" />}
        <div className="button-row">
          <button className="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span>Page {page}</span>
          <button className="secondary" disabled={!truth(data.has_more)} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      </Card>
    </ResourceState>
    {selected && <Confirm
      title={selected.kind === 'role' ? 'Change role' : selected.kind === 'password' ? 'Reset password' : 'Sign out sessions'}
      confirm="Apply" busy={action.busy} onClose={close} onConfirm={() => void apply()}>
      <Notice error={action.error} />
      <p>
        {selected.kind === 'role'
          ? `Make ${text(selected.user.username)} ${truth(selected.user.is_admin) ? 'a student' : 'an administrator'}?`
          : selected.kind === 'password'
            ? 'Set a temporary password. The user must change it after signing in.'
            : 'Revoke all browser sessions for this user.'}
        {' '}Existing sessions will be signed out. Grades are kept.
      </p>
      {selected.kind === 'password' && <Field label="Temporary password" type="password" autoComplete="new-password"
        minLength={8} maxLength={72} value={password} onChange={event => setPassword(event.target.value)} />}
      <Field label={`Type ${text(selected.user.username)} to confirm`} value={confirmation}
        autoComplete="off" onChange={event => setConfirmation(event.target.value)} />
    </Confirm>}
  </>;
}
