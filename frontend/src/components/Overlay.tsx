import {useEffect, useId, useRef, type ReactNode} from 'react';

export function Overlay({title, onClose, children}: {title: string; onClose: () => void; children: ReactNode}) {
  const ref = useRef<HTMLDialogElement>(null), id = useId();
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    ref.current?.showModal();
    return () => { ref.current?.close(); if (opener?.isConnected) opener.focus(); };
  }, []);
  return <dialog ref={ref} className="management-overlay" aria-labelledby={id} onCancel={onClose}>
    <div className="overlay-heading"><h2 id={id}>{title}</h2><button type="button" className="secondary" onClick={onClose}>Close</button></div>
    {children}
  </dialog>;
}
