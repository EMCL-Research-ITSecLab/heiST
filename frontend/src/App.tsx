import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Notice } from './components/ui.tsx';
import { Profile } from './features/account/ProfilePage.tsx';
import { ManageAnnouncements } from './features/administration/AnnouncementManagementPage.tsx';
import { Artifacts } from './features/administration/ArtifactsPage.tsx';
import { CreateChallenge } from './features/administration/ChallengeEditorPage.tsx';
import { ManageChallenges } from './features/administration/ChallengeManagementPage.tsx';
import { Operations } from './features/administration/OperationsPage.tsx';
import { AuthPage } from './features/auth/AuthPage.tsx';
import { Challenge } from './features/challenges/ChallengePage.tsx';
import { Explore } from './features/challenges/ExplorePage.tsx';
import { Feed } from './features/community/FeedPage.tsx';
import { Dashboard } from './features/dashboard/DashboardPage.tsx';
import { LegalPage } from './features/legal/LegalPage.tsx';
import { Landing } from './features/welcome/LandingPage.tsx';
import { post } from './lib/api.ts';
import { image } from './lib/data.ts';
import { Link, RouterProvider, useRouter } from './lib/router.tsx';
import { SessionProvider, useAction, useSession } from './lib/state.tsx';
export const routes = [
  ['/impressum', 'public'], ['/privacy-policy', 'public'], ['/', 'public'], ['/landing', 'public'], ['/login', 'public'], ['/signup', 'public'],
  ['/explore', 'public'], ['/challenge', 'student'], ['/dashboard', 'student'],
  ['/profile', 'student'], ['/profile/:username', 'student'], ['/profile_public', 'student'],
  ['/reset-password', 'student'], ['/activity', 'student'], ['/badges', 'student'],
  ['/announcements', 'student'], ['/create-ctf', 'admin'], ['/manage-ctf', 'admin'],
  ['/upload-diskfile', 'admin'], ['/manage-announcements', 'admin'], ['/operations', 'admin'], ['/404', 'public'],
] as const;
function Redirect({ to }: {
  to: string;
}) { const router = useRouter(); useEffect(() => router.navigate(to, true), [to]); return <div className="loading" role="status">Loading…</div>; }
function RouteContent() {
  const { location } = useRouter(), session = useSession(), path = location.split('?')[0].replace(/\/$/, '') || '/';
  let publicProfile: string | undefined;
  try {
    publicProfile = path.startsWith('/profile/') ? decodeURIComponent(path.slice(9)) : path === '/profile_public' ? new URLSearchParams(location.split('?')[1]).get('username') ?? '' : undefined;
  } catch {
    publicProfile = undefined;
  }
  const route = routes.find(([p]) => p === path || p === '/profile/:username' && publicProfile);
  if (path === '/impressum' || path === '/privacy-policy') return <LegalPage kind={path.slice(1) as 'impressum' | 'privacy-policy'} />;
  if (session.loading)
    return <div className="loading" role="status">
      <span className="spinner" />Loading…</div>;
  if (session.error)
    return <div className="empty" role="alert">
      <h1>Connection failed</h1>
      <p>
        {session.error}
      </p>
      <button onClick={() => void session.refresh()}>Try again</button>
    </div>;
  if (session.user?.passwordChange && path !== '/reset-password')
    return <Redirect to="/reset-password" />;
  if (route && route[1] !== 'public' && !session.user)
    return <Redirect to={'/login?next=' + encodeURIComponent(location)} />;
  if (route?.[1] === 'admin' && !session.user?.admin)
    return <div className="empty">
      <p className="eyebrow">ADMINISTRATION</p>
      <h1>Administrator access required</h1>
      <p>Your account does not have permission to manage the platform.</p>
      <Link className="button" href="/dashboard">Dashboard</Link>
    </div>;
  if (publicProfile)
    return <Profile key={path} username={publicProfile} />;
  switch (path) {
    case '/':
    case '/landing': return <Landing />;
    case '/login':
    case '/signup': return session.user ? <Redirect to="/dashboard" /> : <AuthPage key={path} mode={path === '/signup' ? 'signup' : 'login'} />;
    case '/reset-password': return <AuthPage mode="reset-password" />;
    case '/dashboard': return <Dashboard />;
    case '/explore': return <Explore />;
    case '/challenge': return <Challenge key={location} />;
    case '/profile': return <Profile />;
    case '/activity':
    case '/announcements':
    case '/badges': return <Feed key={path} kind={path.slice(1) as 'activity' | 'announcements' | 'badges'} />;
    case '/manage-ctf': return <ManageChallenges />;
    case '/create-ctf': return <CreateChallenge />;
    case '/upload-diskfile': return <Artifacts />;
    case '/manage-announcements': return <ManageAnnouncements />;
    case '/operations': return <Operations />;
    default: return <div className="empty">
      <p className="eyebrow">404</p>
      <h1>Page not found</h1>
      <p>This page does not exist.</p>
      <Link className="button" href="/explore">Challenges</Link>
    </div>;
  }
}
function Shell({ children }: {
  children: ReactNode;
}) {
  const session = useSession(), router = useRouter(), action = useAction(), [open, setOpen] = useState(false), [dark, setDark] = useState(() => localStorage.getItem('heist-theme') !== 'light');
  const menu = useRef<HTMLButtonElement>(null);
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width:850px)').matches);
  useEffect(() => {
    const query = window.matchMedia('(max-width:850px)');
    const change = () => { setMobile(query.matches); setOpen(false); };
    query.addEventListener('change', change);
    return () => query.removeEventListener('change', change);
  }, []);
  useEffect(() => {
    if (open) document.querySelector<HTMLElement>('#workspace-navigation a')?.focus();
  }, [open]);
  useEffect(() => { document.documentElement.dataset.theme = dark ? 'dark' : 'light'; localStorage.setItem('heist-theme', dark ? 'dark' : 'light'); }, [dark]);
  useEffect(() => { setOpen(false); document.getElementById('main-content')?.focus({preventScroll: true}); }, [router.location]);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && menu.current?.getAttribute('aria-expanded') === 'true') {
        setOpen(false);
        menu.current?.focus();
      }
    }; window.addEventListener('keydown', escape); return () => window.removeEventListener('keydown', escape);
  }, []);
  const links = [['/dashboard', 'Overview', '◫'], ['/explore', 'Challenge library', '◇'], ['/activity', 'Activity', '⌁'], ['/badges', 'Achievements', '✦'], ['/announcements', 'Announcements', '◉']];
  const admin = [['/manage-ctf', 'Challenges', '▦'], ['/create-ctf', 'Create challenge', '＋'], ['/upload-diskfile', 'Artifacts', '▱'], ['/operations', 'Lab overview', '▤'], ['/manage-announcements', 'Communications', '◌']];
  const nav = (items: string[][]) => items.map(([href, label, icon]) => <Link
    key={href}
    href={href}
    className={router.location.split('?')[0] === href ? 'active' : ''}
    aria-current={router.location.split('?')[0] === href ? 'page' : undefined}>
    <span aria-hidden>
      {icon}
    </span>
    {label}
  </Link>);
  return <div className="app">
    <a href="#main-content" className="skip-link">Skip to content</a>
    <aside className={'sidebar ' + (open ? 'open' : '')} id="workspace-navigation" inert={mobile && !open}>
      <Link href={session.user ? '/dashboard' : '/landing'} className="brand" aria-label="heiST home"><img src="/assets/logo/logo_dark.svg" alt="heiST" width="150" height="48" /></Link>
      <div className="workspace-label">
        <span className="status-dot" />SECURITY TRAINING</div>
      <nav aria-label="Workspace">
        <p className="nav-caption">WORKSPACE</p>
        {nav(session.user ? links : links.filter(([path]) => path === '/explore'))}
        {session.user?.admin && <>
          <p className="nav-caption">ADMINISTRATION</p>
          {nav(admin)}
        </>}
      </nav>
      <div className="sidebar-bottom">
        <p>Heidelberg Security Training</p>
      </div>
    </aside>
    {open && <button className="nav-overlay" aria-label="Close navigation" onClick={() => { setOpen(false); menu.current?.focus(); }} />}
    <div className="workspace">
      <header className="topbar">
        <button
          ref={menu}
          className="icon-button menu-button"
          aria-expanded={open}
          aria-controls="workspace-navigation"
          aria-label="Toggle navigation"
          onClick={() => setOpen(!open)}>☰</button>
        <span className="topbar-context">heiST
        </span>
        <div className="topbar-actions">
          <button className="icon-button" onClick={() => setDark(!dark)} aria-label={dark ? 'Use light theme' : 'Use dark theme'}>
            {dark ? '☀' : '☾'}
          </button>
          {session.user ? <>
            <Link className="user-chip" href="/profile">
              <img className="avatar" src={image(session.user.avatar || '/assets/avatars/default-avatar.png')} alt="" />
              <span>
                {session.user.username}
                <small>
                  {session.user.admin ? 'Administrator' : 'Student'}
                </small>
              </span>
            </Link>
            <button className="secondary small" disabled={action.busy} onClick={() => void action.run(() => post('logout', {}), async () => { await session.refresh(); router.navigate('/login', true); })}>Sign out</button>
          </> : <>
            <Link href="/login">Sign in</Link>
            <Link className="button small" href="/signup">Create account</Link>
          </>}
        </div>
      </header>
      <main id="main-content" tabIndex={-1}>
        <Notice error={action.error} />
        {children}
      </main>
      <footer className="workspace-footer">
        <span>heiST</span>
        <nav aria-label="Legal">
          {session.legal.imprint_url && <a href={session.legal.imprint_url} target="_blank" rel="noopener noreferrer">Impressum</a>}
          {session.legal.privacy_url && <a href={session.legal.privacy_url} target="_blank" rel="noopener noreferrer">Privacy policy</a>}
        </nav>
      </footer>
    </div>
  </div>;
}
export default function App() {
  return <RouterProvider>
    <SessionProvider>
      <Shell>
        <RouteContent />
      </Shell>
    </SessionProvider>
  </RouterProvider>;
}
