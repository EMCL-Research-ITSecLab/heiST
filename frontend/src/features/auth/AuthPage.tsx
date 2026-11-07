import { useState, type FormEvent } from 'react';
import { Field, Notice } from '../../components/ui.tsx';
import { post } from '../../lib/api.ts';
import { safeNext, text } from '../../lib/data.ts';
import { Link, useRouter } from '../../lib/router.tsx';
import { useAction, useSession } from '../../lib/state.tsx';
export function AuthPage({ mode }: {
  mode: 'login' | 'signup' | 'reset-password';
}) {
  const session = useSession(), action = useAction(), router = useRouter();
  const [visible, setVisible] = useState(false);
  const signup = mode === 'signup', reset = mode === 'reset-password';
  const title = signup ? 'Create account' : reset ? 'Change password' : 'Sign in';
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = new FormData(event.currentTarget);
    if (signup && body.get('password') !== body.get('confirm-password') || reset && body.get('new-password') !== body.get('confirm-password'))
      return void action.run(async () => { throw new Error('The passwords do not match.'); });
    if (reset) {
      body.set('current_password', String(body.get('current-password') ?? ''));
      body.set('new_password', String(body.get('new-password') ?? ''));
      body.set('confirm_password', String(body.get('confirm-password') ?? ''));
    }
    await action.run(() => post(mode, body), async (data) => { await session.refresh(); router.navigate(reset || signup ? '/dashboard' : safeNext(new URLSearchParams(window.location.search).get('next') ?? text(data.redirect, '/dashboard')), true); });
  }
  return <div className="auth-layout">
    <section className="auth-form card">
      <h1>{title}</h1>
      {reset && <p className="muted">Change your password to continue.</p>}
      <Notice error={action.error} message={action.message} />
      <form onSubmit={submit}>
        {!reset && <Field label="Username" name="username" autoComplete="username" required maxLength={50} />}
        {signup && <Field
          label="Email address"
          name="email"
          type="email"
          autoComplete="email"
          required
          maxLength={254} />}
        {reset && <Field
          label="Current password"
          name="current-password"
          type={visible ? 'text' : 'password'}
          autoComplete="current-password"
          required />}
        <Field
          label={reset ? 'New password' : 'Password'}
          name={reset ? 'new-password' : 'password'}
          type={visible ? 'text' : 'password'}
          autoComplete={signup || reset ? 'new-password' : 'current-password'}
          required
          minLength={signup || reset ? 8 : undefined} />
        {(signup || reset) && <Field
          label="Confirm password"
          name="confirm-password"
          type={visible ? 'text' : 'password'}
          autoComplete="new-password"
          required />}
        <label className="check">
          <input type="checkbox" checked={visible} onChange={e => setVisible(e.target.checked)} />Show passwords</label>
        <button className="full" disabled={action.busy}>
          {action.busy ? 'Please wait…' : signup ? 'Create account' : reset ? 'Save new password' : 'Sign in'}
          <span aria-hidden>→</span>
        </button>
      </form>
      {!reset && <p className="auth-alternative">
        {signup ? 'Have an account?' : 'No account?'} <Link href={signup ? '/login' : '/signup'}>
          {signup ? 'Sign in' : 'Create an account'}
        </Link>
      </p>}
    </section>
  </div>;
}
