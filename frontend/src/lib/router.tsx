import { createContext,useContext,useEffect,useState,type AnchorHTMLAttributes,type ReactNode } from 'react';
const Router = createContext({ location: window.location.pathname + window.location.search, navigate: (_: string, _replace = false) => { } });
export function RouterProvider({ children }: {
    children: ReactNode;
}) {
    const [location, setLocation] = useState(window.location.pathname + window.location.search);
    useEffect(() => { const pop = () => setLocation(window.location.pathname + window.location.search); window.addEventListener('popstate', pop); return () => window.removeEventListener('popstate', pop); }, []);
    function navigate(path: string, replace = false) {
        const url = new URL(path, window.location.origin);
        if (url.origin !== window.location.origin)
            throw new Error('Navigation must stay on this origin');
        window.history[replace ? 'replaceState' : 'pushState']({}, '', url.pathname + url.search);
        setLocation(url.pathname + url.search);
        window.scrollTo(0, 0);
    }
    return <Router.Provider value={{ location, navigate }}>
    {children}
  </Router.Provider>;
}
export const useRouter = () => useContext(Router);
export function Link({ href = '/', children, onClick, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) {
    const { navigate } = useRouter();
    return <a {...props} href={href} onClick={event => {
            onClick?.(event);
            if (!event.defaultPrevented && event.button === 0 && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey && !props.target && !props.download && new URL(href, window.location.origin).origin === window.location.origin) {
                event.preventDefault();
                navigate(href);
            }
        }}>
    {children}
  </a>;
}
