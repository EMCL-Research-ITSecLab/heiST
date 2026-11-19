import { useI18n } from '../lib/i18n.tsx';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Notice } from './ui.tsx';
import { post } from '../lib/api.ts';
import { avatarImage } from '../lib/artwork.ts';
import { Link, useRouter } from '../lib/router.tsx';
import { useAction, useSession } from '../lib/state.tsx';
export function AppShell({ children }: { children: ReactNode }) {
  const { t, language, setLanguage } = useI18n();
  const session = useSession(),
    router = useRouter(),
    action = useAction(),
    [open, setOpen] = useState(false),
    [collapsed, setCollapsed] = useState(
      () => localStorage.getItem('heist-navigation') === 'collapsed',
    ),
    [dark, setDark] = useState(() => localStorage.getItem('heist-theme') !== 'light');
  const menu = useRef<HTMLButtonElement>(null);
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width:850px)').matches);
  useEffect(() => {
    const query = window.matchMedia('(max-width:850px)');
    const change = () => {
      setMobile(query.matches);
      setOpen(false);
    };
    query.addEventListener('change', change);
    return () => query.removeEventListener('change', change);
  }, []);
  useEffect(() => {
    if (open) document.querySelector<HTMLElement>('#workspace-navigation a')?.focus();
  }, [open]);
  useEffect(() => {
    localStorage.setItem('heist-navigation', collapsed ? 'collapsed' : 'expanded');
  }, [collapsed]);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    localStorage.setItem('heist-theme', dark ? 'dark' : 'light');
  }, [dark]);
  useEffect(() => {
    setOpen(false);
    document.getElementById('main-content')?.focus({ preventScroll: true });
  }, [router.location]);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && menu.current?.getAttribute('aria-expanded') === 'true') {
        setOpen(false);
        if (!mobile) setCollapsed(true);
        menu.current?.focus();
      }
    };
    window.addEventListener('keydown', escape);
    return () => window.removeEventListener('keydown', escape);
  }, [mobile]);
  const links = [
    ['/dashboard', 'navigation.overview', '◫'],
    ['/explore', 'navigation.challengeLibrary', '◇'],
    ['/activity', 'common.activity', '⌁'],
    ['/badges', 'navigation.achievements', '✦'],
    ['/announcements', 'navigation.announcements', '◉'],
  ] as const;
  const admin = [
    ['/manage-ctf', 'navigation.challenges', '▦'],
    ['/create-ctf', 'authoring.create.title', '＋'],
    ['/upload-diskfile', 'navigation.artifacts', '▱'],
    ['/manage-users', 'navigation.users', '♙'],
    ['/manage-instances', 'navigation.runningChallenges', '▣'],
    ['/operations', 'navigation.platformStatus', '▤'],
    ['/manage-announcements', 'navigation.communications', '◌'],
  ] as const;
  const nav = (
    items: readonly (readonly [string, import('../lib/messages/en.ts').MessageKey, string])[],
  ) =>
    items.map(([href, label, icon]) => (
      <Link
        key={href}
        href={href}
        className={router.location.split('?')[0] === href ? 'active' : ''}
        aria-current={router.location.split('?')[0] === href ? 'page' : undefined}
      >
        <span aria-hidden>{icon}</span>
        {t(label)}
      </Link>
    ));
  return (
    <div className={'app' + (!mobile && collapsed ? ' navigation-collapsed' : '')}>
      <a href="#main-content" className="skip-link">
        {t('navigation.skipToContent')}
      </a>
      <aside
        className={'sidebar ' + (open ? 'open' : '')}
        id="workspace-navigation"
        inert={mobile ? !open : collapsed}
      >
        <Link
          href={session.user ? '/dashboard' : '/landing'}
          className="brand"
          aria-label={t('navigation.heistHome')}
        >
          <img src="/assets/logo/logo_dark.svg" alt="heiST" width="150" height="48" />
        </Link>
        <nav aria-label={t('navigation.workspace')}>
          <p className="nav-caption">{t('navigation.workspaceLabel')}</p>
          {nav(session.user ? links : links.filter(([path]) => path === '/explore'))}
          {session.user?.admin && (
            <>
              <p className="nav-caption">{t('routing.administration')}</p>
              {nav(admin)}
            </>
          )}
        </nav>
      </aside>
      {mobile && open && (
        <button
          className="nav-overlay"
          aria-label={t('navigation.closeNavigation')}
          onClick={() => {
            setOpen(false);
            menu.current?.focus();
          }}
        />
      )}
      <div className="workspace">
        <header className="topbar">
          <button
            ref={menu}
            className="icon-button menu-button"
            aria-expanded={mobile ? open : !collapsed}
            aria-controls="workspace-navigation"
            aria-label={t('navigation.toggleNavigation')}
            onClick={() => (mobile ? setOpen(!open) : setCollapsed(!collapsed))}
          >
            ☰
          </button>
          <span className="topbar-context">{t('navigation.heist')}</span>
          <div className="topbar-actions">
            <select
              className="language-select"
              aria-label="Language / Sprache"
              value={language}
              onChange={(event) => setLanguage(event.target.value === 'de' ? 'de' : 'en')}
            >
              <option value="en">English</option>
              <option value="de">Deutsch</option>
            </select>
            <button
              className="icon-button"
              onClick={() => setDark(!dark)}
              aria-label={dark ? t('common.useLightTheme') : t('common.useDarkTheme')}
            >
              {dark ? '☀' : '☾'}
            </button>
            {session.user ? (
              <>
                <Link className="user-chip" href="/profile">
                  <img className="avatar" src={avatarImage(session.user.avatar)} alt="" />
                  <span>
                    {session.user.username}
                    <small>
                      {session.user.admin ? t('audit.administrator') : t('authoring.student')}
                    </small>
                  </span>
                </Link>
                <button
                  className="secondary small"
                  disabled={action.busy}
                  onClick={() =>
                    void action.run(
                      () => post('logout', {}),
                      async () => {
                        await session.refresh();
                        router.navigate('/login', true);
                      },
                    )
                  }
                >
                  {t('auth.logout')}
                </button>
              </>
            ) : (
              <>
                <Link href="/login">{t('auth.login.title')}</Link>
                <Link className="button small" href="/signup">
                  {t('auth.signup.title')}
                </Link>
              </>
            )}
          </div>
        </header>
        <main id="main-content" tabIndex={-1}>
          <Notice error={action.error} />
          {children}
        </main>
        <footer className="workspace-footer">
          <span>{t('navigation.heist')}</span>
          <nav aria-label={t('navigation.legal')}>
            {session.legal.imprint_url && (
              <a href={session.legal.imprint_url} target="_blank" rel="noopener noreferrer">
                {t('navigation.impressum')}
              </a>
            )}
            {session.legal.terms_url && (
              <a href={session.legal.terms_url} target="_blank" rel="noopener noreferrer">
                {t('navigation.termsOfService')}
              </a>
            )}
            {session.legal.privacy_url && (
              <a href={session.legal.privacy_url} target="_blank" rel="noopener noreferrer">
                {t('navigation.privacyPolicy')}
              </a>
            )}
          </nav>
        </footer>
      </div>
    </div>
  );
}
