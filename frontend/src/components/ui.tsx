import { useEffect,useRef,type InputHTMLAttributes,type ReactNode,type SelectHTMLAttributes,type TextareaHTMLAttributes } from 'react';
import { date,image,number,text,type Row } from '../lib/data.ts';
import { Link } from '../lib/router.tsx';
export function PageTitle({ eyebrow = 'Your workspace', title, description, action }: {
    eyebrow?: string;
    title: string;
    description?: string;
    action?: ReactNode;
}) {
    useEffect(() => { document.title = `${title} · heiST`; }, [title]);
    return <header className="page-title">
    <div>
      <p className="eyebrow">
        {eyebrow}
      </p>
      <h1>
        {title}
      </h1>
      {description && <p className="lede">
        {description}
      </p>}
    </div>
    {action}
  </header>;
}
export function Notice({ error, message }: {
    error?: string;
    message?: string;
}) {
    return <>
    {error && <div className="notice error" role="alert">
      {error}
    </div>}
    {message && <div className="notice success" role="status">
      {message}
    </div>}
  </>;
}
export function ResourceState({ loading, error, reload, children }: {
    loading: boolean;
    error: string;
    reload: () => void;
    children: ReactNode;
}) {
    if (loading)
        return <div className="loading" role="status">
    <span className="spinner"/>Loading your workspace…</div>;
    if (error)
        return <div className="empty" role="alert">
    <h2>We couldn’t load this page</h2>
    <p>
      {error}
    </p>
    <button onClick={reload}>Try again</button>
  </div>;
    return <>
    {children}
  </>;
}
export function Empty({ title = 'Nothing here yet', children }: {
    title?: string;
    children?: ReactNode;
}) { return <div className="empty">
    <span className="empty-icon" aria-hidden>◇</span>
    <h2>
      {title}
    </h2>
    {children && <p>
      {children}
    </p>}
  </div>; }
export function Card({ title, children, action, className = '' }: {
    title?: string;
    children: ReactNode;
    action?: ReactNode;
    className?: string;
}) { return <section className={`card ${className}`}>
    {title && <div className="card-heading">
      <h2>
        {title}
      </h2>
      {action}
    </div>}
    {children}
  </section>; }
export function Stat({ label, value, detail }: {
    label: string;
    value: unknown;
    detail?: string;
}) { return <div className="stat">
    <span>
      {label}
    </span>
    <strong>
      {text(value, '—')}
    </strong>
    {detail && <small>
      {detail}
    </small>}
  </div>; }
export function Badge({ children, tone = '' }: {
    children: ReactNode;
    tone?: string;
}) { return <span className={`badge ${tone}`}>
    {children}
  </span>; }
export function Field({ label, ...props }: InputHTMLAttributes<HTMLInputElement> & {
    label: string;
}) { return <label className="field">
    <span>
      {label}
      {props.required && <span aria-hidden> *</span>}
    </span>
    <input {...props}/>
  </label>; }
export function Area({ label, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & {
    label: string;
}) { return <label className="field">
    <span>
      {label}
    </span>
    <textarea rows={4} {...props}/>
  </label>; }
export function Select({ label, options, ...props }: SelectHTMLAttributes<HTMLSelectElement> & {
    label: string;
    options: (string | [
        string,
        string
    ])[];
}) { return <label className="field">
    <span>
      {label}
    </span>
    <select {...props}>
      {options.map(option => { const [value, name] = Array.isArray(option) ? option : [option, option]; return <option key={value} value={value}>
        {name}
      </option>; })}
    </select>
  </label>; }
export function Pager({ page, totalPages, onPage }: {
    page: number;
    totalPages: number;
    onPage: (page: number) => void;
}) { return <nav className="pager" aria-label="Pagination">
    <button className="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>← Previous</button>
    <span>Page {page} of {Math.max(1, totalPages)}
    </span>
    <button className="secondary" disabled={page >= totalPages} onClick={() => onPage(page + 1)}>Next →</button>
  </nav>; }
export function Confirm({ title, children, confirm, onClose, onConfirm, busy = false }: {
    title: string;
    children: ReactNode;
    confirm: string;
    onClose: () => void;
    onConfirm: () => void;
    busy?: boolean;
}) {
    const ref = useRef<HTMLDialogElement>(null);
    useEffect(() => { const dialog = ref.current; dialog?.showModal(); return () => dialog?.close(); }, []);
    return <dialog ref={ref} onCancel={event => { if (busy)
        event.preventDefault();
    else
        onClose(); }} aria-labelledby="confirmation-title">
    <h2 id="confirmation-title">
      {title}
    </h2>
    {children}
    <div className="button-row">
      <button className="secondary" disabled={busy} onClick={onClose}>Cancel</button>
      <button className="danger" disabled={busy} onClick={onConfirm}>
        {busy ? 'Working…' : confirm}
      </button>
    </div>
  </dialog>;
}
export function ChallengeCard({ challenge }: {
    challenge: Row;
}) {
    return <Link className="challenge-card" href={`/challenge?id=${number(challenge.id)}`}>
    <div className="challenge-image">
      <img 
        src={image(challenge.image_path)} 
        alt="" 
        loading="lazy" 
        onError={e => { e.currentTarget.style.display = 'none'; }}/>
      <span>
        {text(challenge.category, 'LAB').slice(0, 3).toUpperCase()}
      </span>
    </div>
    <div className="challenge-card-body">
      <div className="spread">
        <Badge>
          {text(challenge.category, 'misc')}
        </Badge>
        <Badge tone={text(challenge.difficulty)}>
          {text(challenge.difficulty)}
        </Badge>
      </div>
      <h3>
        {text(challenge.name)}
      </h3>
      <p>
        {text(challenge.description)}
      </p>
      <div className="challenge-footer">
        <span>
          {number(challenge.solved_count ?? challenge.solve_count)} solves</span>
        <strong>Open lab ↗</strong>
      </div>
    </div>
  </Link>;
}
export function ActivityList({ items }: {
    items: Row[];
}) { return items.length ? <div className="list">
    {items.map((item, index) => <div className="list-item" key={text(item.id, String(index))}>
      <span className="activity-dot"/>
      <div>
        <strong>
          {text(item.title ?? item.challenge ?? item.item_name ?? item.name)}
        </strong>
        <p>
          {text(item.description ?? item.category ?? item.status)}
        </p>
      </div>
      <small>
        {text(item.time_ago) || date(item.created_at ?? item.started_at)}
      </small>
    </div>)}
  </div> : <Empty title="Your next investigation starts here">Explore a challenge to begin building your activity history.</Empty>; }
