import { ManageUsers } from './features/administration/UserManagementPage.tsx';
import { ManageInstances } from './features/administration/InstanceManagementPage.tsx';
import { useEffect } from 'react';
import { AppShell } from './components/AppShell.tsx';
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
import { Link, RouterProvider, useRouter } from './lib/router.tsx';
import { SessionProvider, useSession } from './lib/state.tsx';
export const routes = [
  ['/impressum', 'public'], ['/privacy-policy', 'public'], ['/', 'public'], ['/landing', 'public'], ['/login', 'public'], ['/signup', 'public'],
  ['/explore', 'public'], ['/challenge', 'student'], ['/dashboard', 'student'],
  ['/profile', 'student'], ['/profile/:username', 'student'], ['/profile_public', 'student'],
  ['/reset-password', 'student'], ['/activity', 'student'], ['/badges', 'student'],
  ['/announcements', 'student'], ['/create-ctf', 'admin'], ['/manage-ctf', 'admin'],
  ['/manage-users','admin'], ['/manage-instances','admin'], ['/upload-diskfile', 'admin'], ['/manage-announcements', 'admin'], ['/operations', 'admin'], ['/404', 'public'],
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
    case '/manage-users': return <ManageUsers />;
    case '/manage-instances': return <ManageInstances />;
    case '/operations': return <Operations />;
    default: return <div className="empty">
      <p className="eyebrow">404</p>
      <h1>Page not found</h1>
      <p>This page does not exist.</p>
      <Link className="button" href="/explore">Challenges</Link>
    </div>;
  }
}
export default function App() {
  return <RouterProvider>
    <SessionProvider>
      <AppShell>
        <RouteContent />
      </AppShell>
    </SessionProvider>
  </RouterProvider>;
}
