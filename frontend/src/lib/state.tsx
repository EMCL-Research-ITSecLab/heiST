import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { ApiError, request, setCsrf } from './api.ts';
import { payload, row, text, truth, type Row } from './data.ts';
export type User = {
  username: string;
  admin: boolean;
  avatar: string;
  passwordChange: boolean;
};
const Session = createContext({ user: null as User | null, loading: true, error: '', refresh: async () => { } });
export function SessionProvider({ children }: {
  children: ReactNode;
}) {
  const [user, setUser] = useState<User | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState('');
  const refresh = useCallback(async () => {
    try {
      const data = payload(await request('/backend/session.php'));
      const record = row(data.user);
      setCsrf(text(data.csrf_token));
      setUser(truth(data.is_logged_in) ? { username: text(record.username), admin: truth(record.is_admin), avatar: text(record.avatar_url), passwordChange: truth(data.requires_password_change) } : null);
      setError('');
    }
    catch (error) {
      setError(error instanceof Error ? error.message : 'Cannot load your session.');
    }
    finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void refresh(); const expired = () => void refresh(); window.addEventListener('heist:session-expired', expired); return () => window.removeEventListener('heist:session-expired', expired); }, [refresh]);
  return <Session.Provider value={{ user, loading, error, refresh }}>
    {children}
  </Session.Provider>;
}
export const useSession = () => useContext(Session);
export function useResource(path: string, poll = 0) {
  const [data, setData] = useState<Row>({}), [loading, setLoading] = useState(true), [error, setError] = useState('');
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let pending = false;
    setLoading(true);
    setError('');
    async function load() {
      if (pending || controller.signal.aborted)
        return;
      pending = true;
      try {
        const next = await request(path, { signal: controller.signal });
        if (!controller.signal.aborted) {
          setData(next);
          setError('');
        }
      }
      catch (error) {
        if (!controller.signal.aborted)
          setError(error instanceof Error ? error.message : 'Could not load this page.');
      }
      finally {
        pending = false;
        if (!controller.signal.aborted)
          setLoading(false);
      }
    }
    void load();
    const interval = poll ? window.setInterval(() => {
      if (!document.hidden)
        void load();
    }, poll) : undefined;
    return () => {
      controller.abort(); if (interval)
        clearInterval(interval);
    };
  }, [path, version, poll]);
  return { data, loading, error, reload: () => setVersion(v => v + 1) };
}
export function useAction() {
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [message, setMessage] = useState('');
  const running = useRef(false);
  async function run(action: () => Promise<Row>, done?: (data: Row) => void | Promise<void>) {
    if (running.current)
      return;
    running.current = true;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const data = await action();
      setMessage(text(data.message, 'Changes saved.'));
      await done?.(data);
    }
    catch (error) {
      setError(error instanceof ApiError || error instanceof Error ? error.message : 'This action could not be completed.');
    }
    finally {
      running.current = false;
      setBusy(false);
    }
  }
  return { busy, error, message, run, clear: () => { setError(''); setMessage(''); } };
}
