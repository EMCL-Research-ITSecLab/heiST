import { Component,type ErrorInfo,type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import './styles.css';
class ErrorBoundary extends Component<{
    children: ReactNode;
}, {
    failed: boolean;
}> {
    state = { failed: false };
    static getDerivedStateFromError() { return { failed: true }; }
    componentDidCatch(_error: Error, _info: ErrorInfo) { }
    render() { return this.state.failed ? <main className="empty">
    <h1>Something interrupted your workspace.</h1>
    <p>Reload the page to try again. Your submitted progress is stored on the server.</p>
    <button onClick={() => window.location.reload()}>Reload workspace</button>
  </main> : this.props.children; }
}
createRoot(document.getElementById('root')!).render(<ErrorBoundary>
    <App />
  </ErrorBoundary>);
