import { useEffect, useRef, useState } from 'react';
import { request } from '../../lib/api.ts';
import { number, payload, text, type Row } from '../../lib/data.ts';

/** Keep the server identity across navigation; replay every chunk to verify the selected file matches. */
export function useArtifactUpload(username: string, completed: () => void) {
  const [busy, setBusy] = useState(false), [progress, setProgress] = useState(0), [phase, setPhase] = useState('');
  const [error, setError] = useState(''), [message, setMessage] = useState('');
  const controller = useRef<AbortController | null>(null), current = useRef(''), sealed = useRef(false);
  const cancelled = useRef(false);
  const storageKey = 'heist:artifact-upload:'+username;
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (!busy) return;
    const leave = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener('beforeunload', leave);
    return () => window.removeEventListener('beforeunload', leave);
  }, [busy]);

  async function cancel(identifier = current.current) {
    if (!identifier) return;
    cancelled.current = true;
    controller.current?.abort();
    const result=await request('/api/admin/artifact-uploads/'+identifier, {method: 'DELETE'});
    if (sessionStorage.getItem(storageKey) === identifier) sessionStorage.removeItem(storageKey);
    setMessage(text(result.message,'Transfer closed.'));
    completed();
  }

  async function upload(file: File, guest: string, limits: Row) {
    if (controller.current) return;
    setError(''); setMessage('');
    if (!/\.ova$/i.test(file.name) || file.size <= 0 || file.size > number(limits.MAX_FILE_SIZE)) {
      setError(`Choose an OVA smaller than ${(number(limits.MAX_FILE_SIZE)/1024**3).toFixed(0)} GiB.`);
      return;
    }
    const abort = new AbortController();
    controller.current = abort;
    sealed.current = false;
    cancelled.current = false;
    setBusy(true); setProgress(0); setPhase('Preparing transfer');
    try {
      const saved = sessionStorage.getItem(storageKey);
      let transfer: Row;
      if (saved) {
        transfer = payload(await request('/api/admin/artifact-uploads/'+saved, {signal: abort.signal}));
        if (transfer.state !== 'RECEIVING') {
          sessionStorage.removeItem(storageKey);
          throw new Error('The previous transfer is already sealed. Check its validation status below before starting another.');
        }
        if (transfer.name !== file.name || number(transfer.size) !== file.size || transfer.guest_os !== guest)
          throw new Error('An earlier transfer is saved. Finish it with the original file, or cancel it below before starting another.');
      } else {
        transfer = payload(await request('/api/admin/artifact-uploads', {method: 'POST', body: {name: file.name, size: file.size, guest_os: guest}, signal: abort.signal}));
      }
      const identifier = text(transfer.id), size = number(transfer.chunk_bytes);
      if (!/^[a-f0-9]{32}$/.test(identifier) || !Number.isSafeInteger(size) || size <= 0 || size > 16*1024**2)
        throw new Error('The server returned invalid transfer parameters.');
      current.current = identifier;
      sessionStorage.setItem(storageKey, identifier);
      for (let index = 0; index < Math.ceil(file.size/size); index++) {
        setPhase('Transferring artifact');
        await request(`/api/admin/artifact-uploads/${identifier}/chunks/${index}`, {method: 'PUT', body: file.slice(index*size, Math.min(file.size, (index+1)*size)), signal: abort.signal});
        setProgress(Math.round(Math.min(file.size, (index+1)*size)/file.size*100));
      }
      sealed.current = true;
      setPhase('Sealing transfer');
      const result = await request('/api/admin/artifact-uploads/'+identifier+'/seal', {method: 'POST', body: {}});
      sessionStorage.removeItem(storageKey);
      current.current = '';
      setPhase('Transfer complete');
      setMessage(text(result.message, 'Transfer complete. Validation is pending.'));
      completed();
    } catch (value) {
      setError(cancelled.current ? '' : abort.signal.aborted ? 'Transfer paused. Select the same file to resume, or cancel it below.' : value instanceof Error ? value.message : 'Transfer failed.');
      completed();
    } finally {
      controller.current = null;
      sealed.current = false;
      setBusy(false);
    }
  }
  return {upload, cancel, busy, progress, phase, error, message, canCancel: !sealed.current};
}
