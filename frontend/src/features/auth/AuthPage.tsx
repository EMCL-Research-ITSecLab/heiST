import { useI18n } from '../../lib/i18n.tsx';
import { useState, type FormEvent } from 'react';
import { Field, Notice } from '../../components/ui.tsx';
import { post } from '../../lib/api.ts';
import { safeNext, text } from '../../lib/data.ts';
import { Link, useRouter } from '../../lib/router.tsx';
import { useAction, useSession } from '../../lib/state.tsx';
export function AuthPage({ mode }: { mode: 'login' | 'signup' | 'reset-password' }) {
  const { t } = useI18n();
  const session = useSession(),
    action = useAction(),
    router = useRouter();
  const [visible, setVisible] = useState(false);
  const signup = mode === 'signup',
    reset = mode === 'reset-password';
  const title = signup
    ? 'auth.signup.title'
    : reset
      ? 'profile.changePassword'
      : 'auth.login.title';
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = new FormData(event.currentTarget);
    if (
      (signup && body.get('password') !== body.get('confirm-password')) ||
      (reset && body.get('new-password') !== body.get('confirm-password'))
    )
      return void action.run(async () => {
        throw new Error('The passwords do not match.');
      });
    if (signup) body.set('legal_version', session.legal.version);
    if (reset) {
      body.set('current_password', String(body.get('current-password') ?? ''));
      body.set('new_password', String(body.get('new-password') ?? ''));
      body.set('confirm_password', String(body.get('confirm-password') ?? ''));
    }
    await action.run(
      () => post(mode, body),
      async (data) => {
        await session.refresh();
        router.navigate(
          reset || signup
            ? '/dashboard'
            : safeNext(
                new URLSearchParams(window.location.search).get('next') ??
                  text(data.redirect, '/dashboard'),
              ),
          true,
        );
      },
    );
  }
  return (
    <div className="auth-layout">
      <section className="auth-form card">
        <h1>{t(title)}</h1>
        {reset && <p className="muted">{t('auth.changeYourPasswordToContinue')}</p>}
        <Notice error={action.error} message={action.message} />
        {signup && !session.registrationEnabled ? (
          <p role="status">{t('auth.registrationIsCurrentlyClosed')}</p>
        ) : (
          <form onSubmit={submit}>
            {!reset && (
              <Field
                label={t('common.labels.username')}
                name="username"
                autoComplete="username"
                required
                maxLength={50}
              />
            )}
            {signup && (
              <Field
                label={t('common.labels.emailAddress')}
                name="email"
                type="email"
                autoComplete="email"
                required
                maxLength={254}
              />
            )}
            {reset && (
              <Field
                label={t('profile.currentPassword')}
                name="current-password"
                type={visible ? 'text' : 'password'}
                autoComplete="current-password"
                required
              />
            )}
            <Field
              label={reset ? t('profile.newPassword') : t('common.password')}
              name={reset ? 'new-password' : 'password'}
              type={visible ? 'text' : 'password'}
              autoComplete={signup || reset ? 'new-password' : 'current-password'}
              required
              minLength={signup || reset ? 8 : undefined}
            />
            {(signup || reset) && (
              <Field
                label={t('auth.confirmPassword')}
                name="confirm-password"
                type={visible ? 'text' : 'password'}
                autoComplete="new-password"
                required
              />
            )}
            {signup && (
              <>
                <Field
                  label={t('auth.lectureCode')}
                  name="lecture_token"
                  type="password"
                  autoComplete="off"
                  required
                  maxLength={256}
                />
                <label className="check legal-acceptance">
                  <input type="checkbox" name="accept_legal" value="true" required />
                  <span>
                    {t('auth.iAcceptThe') + ' '}
                    <a href={session.legal.terms_url} target="_blank" rel="noopener noreferrer">
                      {t('navigation.termsOfService')}
                    </a>
                    {' ' + t('auth.and') + ' '}
                    <a href={session.legal.privacy_url} target="_blank" rel="noopener noreferrer">
                      {t('auth.privacyPolicy')}
                    </a>
                    .
                  </span>
                </label>
              </>
            )}
            <label className="check">
              <input
                type="checkbox"
                checked={visible}
                onChange={(e) => setVisible(e.target.checked)}
              />
              {t('auth.showPasswords')}
            </label>
            <button className="full" disabled={action.busy}>
              {action.busy
                ? t('common.pleaseWait')
                : signup
                  ? t('auth.signup.title')
                  : reset
                    ? t('common.saveNewPassword')
                    : t('auth.login.title')}
              <span aria-hidden>→</span>
            </button>
          </form>
        )}
        {!reset && (
          <p className="auth-alternative">
            {signup ? t('common.haveAnAccount') : t('common.noAccount')}{' '}
            <Link href={signup ? '/login' : '/signup'}>
              {signup ? t('auth.login.title') : t('common.createAnAccount')}
            </Link>
          </p>
        )}
      </section>
    </div>
  );
}
