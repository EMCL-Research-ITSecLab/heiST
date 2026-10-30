import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Card, Confirm, Empty, Field, Notice, PageTitle, ResourceState, Select } from '../../components/ui.tsx';
import { post, request } from '../../lib/api.ts';
import { number, payload, row, rows, text, type Row } from '../../lib/data.ts';
import { useAction, useResource } from '../../lib/state.tsx';
export function Artifacts() {
  const resource = useResource('/backend/upload-diskfile.php?action=list'), config = useResource('/config/general.config.json'), limits = row(config.data.upload), action = useAction();
  const [file, setFile] = useState<File | null>(null), [guest, setGuest] = useState('linux'), [busy, setBusy] = useState(false), [progress, setProgress] = useState(0), [phase, setPhase] = useState(''), [error, setError] = useState(''), [message, setMessage] = useState(''), [deleting, setDeleting] = useState<Row | null>(null);
  const controller = useRef<AbortController | null>(null), uploadId = useRef(''), finalizing = useRef(false);
  useEffect(() => () => {
    if (!finalizing.current) {
      controller.current?.abort();
      if (uploadId.current)
        void post('upload-diskfile', { phase: 'cancel', uploadId: uploadId.current }).catch(() => { });
    }
  }, []);
  useEffect(() => {
    if (!busy)
      return; const leave = (event: BeforeUnloadEvent) => event.preventDefault(); window.addEventListener('beforeunload', leave); return () => window.removeEventListener('beforeunload', leave);
  }, [busy]);
  async function cancel() {
    controller.current?.abort(); if (uploadId.current)
      await post('upload-diskfile', { phase: 'cancel', uploadId: uploadId.current });
  }
  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file || busy)
      return;
    setError('');
    setMessage('');
    if (!/\.(ova|ovf)$/i.test(file.name) || file.size <= 0 || file.size > number(limits.MAX_FILE_SIZE)) {
      setError(`Choose an OVA/OVF smaller than ${(number(limits.MAX_FILE_SIZE) / 1024 ** 3).toFixed(0)} GiB.`);
      return;
    }
    const abort = new AbortController();
    controller.current = abort;
    uploadId.current = '';
    finalizing.current = false;
    setBusy(true);
    setProgress(0);
    setPhase('Uploading artifact');
    try {
      if (file.size < number(limits.CHUNK_UPLOAD_THRESHOLD)) {
        const form = new FormData();
        form.set('ova_file', file);
        form.set('guest_os', guest);
        setPhase('Uploading and validating artifact');
        await post('upload-diskfile', form, abort.signal);
        setProgress(100);
      }
      else {
        const size = number(limits.CHUNK_SIZE);
        if (size <= 0)
          throw new Error('The server supplied an invalid chunk size.');
        const total = Math.ceil(file.size / size);
        const initialized = await post('upload-diskfile', { phase: 'init', uploadId: 'ui_' + crypto.randomUUID(), fileName: file.name, fileSize: file.size, totalChunks: total, guest_os: guest }, abort.signal);
        uploadId.current = text(initialized.uploadId);
        if (!uploadId.current)
          throw new Error('The server did not return an upload identity.');
        for (let index = 0; index < total; index++) {
          const form = new FormData();
          form.set('chunk', file.slice(index * size, Math.min(file.size, (index + 1) * size)), file.name + '.part');
          form.set('uploadId', uploadId.current);
          form.set('chunkIndex', String(index));
          form.set('phase', 'chunk');
          await post('upload-diskfile', form, abort.signal);
          setProgress(Math.round(Math.min(file.size, (index + 1) * size) / file.size * 100));
        }
        finalizing.current = true;
        setPhase('Transfer complete. Server is validating the artifact…');
        await post('upload-diskfile', { phase: 'finalize', uploadId: uploadId.current });
      }
      uploadId.current = '';
      setMessage('Artifact uploaded and validated. It is ready for challenge creation.');
      setFile(null);
      resource.reload();
      setPhase('Complete');
    }
    catch (error) {
      if (abort.signal.aborted) {
        setPhase('Upload cancelled');
        setMessage('Upload cancelled.');
      }
      else {
        setError(error instanceof Error ? error.message : 'Upload failed.');
        if (uploadId.current && !finalizing.current)
          await post('upload-diskfile', { phase: 'cancel', uploadId: uploadId.current }).catch(() => { });
      }
    }
    finally {
      setBusy(false);
      controller.current = null;
      finalizing.current = false;
    }
  }
  const items = rows(payload(resource.data).ovas);
  return <>
    <PageTitle eyebrow="ADMINISTRATION / ARTIFACT LIBRARY" title="The building blocks of your labs." description="Upload VM artifacts once, then use them in your exercises." />
    <Notice error={error || action.error} message={message || action.message} />
    <Card title="Upload an artifact">
      <p className="muted">Large uploads use the server’s chunked upload protocol. Validation must finish before the artifact is available.</p>
      <ResourceState {...config}>
        <form onSubmit={upload}>
          <div className="form-grid">
            <Field
              label="OVA or OVF file"
              type="file"
              accept=".ova,.ovf"
              required
              disabled={busy}
              onChange={e => setFile(e.target.files?.[0] ?? null)} />
            <Select
              label="Guest operating system"
              options={['linux', 'windows']}
              value={guest}
              disabled={busy}
              onChange={e => setGuest(e.target.value)} />
          </div>
          {file && <p className="mono muted">
            {file.name} · {(file.size / 1024 ** 2).toFixed(1)} MiB</p>}
          <div className="button-row">
            <button disabled={!file || busy || config.loading}>
              {busy ? 'Uploading…' : 'Upload artifact ↑'}
            </button>
            {busy && !finalizing.current && <button type="button" className="secondary" onClick={() => void cancel().catch(error => setError(error.message))}>Cancel upload</button>}
          </div>
          {busy && <div className="upload-progress" role="status">
            <progress max={100} value={progress} />
            <p>
              {phase}
              {progress > 0 ? ` · ${progress}% transferred` : ''}
            </p>
          </div>}
        </form>
      </ResourceState>
    </Card>
    <ResourceState {...resource}>
      <Card title="Your artifact library" action={<button className="secondary small" onClick={resource.reload}>Refresh ↻</button>}>
        {items.length ? <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Artifact</th>
                <th>Operating system</th>
                <th>Size</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map(item => <tr key={text(item.id)}>
                <td>
                  <strong>
                    {text(item.original_filename ?? item.filename ?? item.name)}
                  </strong>
                  <small>#{text(item.id)}
                  </small>
                </td>
                <td>
                  {text(item.guest_os)}
                </td>
                <td>
                  {number(item.file_size ?? item.size) ? (number(item.file_size ?? item.size) / 1024 ** 2).toFixed(1) + ' MiB' : '—'}
                </td>
                <td>
                  <button className="danger subtle small" onClick={() => setDeleting(item)}>Delete</button>
                </td>
              </tr>)}
            </tbody>
          </table>
        </div> : <Empty title="Your artifact library is empty">Upload a VM artifact to start building an exercise.</Empty>}
      </Card>
    </ResourceState>
    {deleting && <Confirm
      title="Delete this artifact?"
      confirm="Delete artifact"
      busy={action.busy}
      onClose={() => setDeleting(null)}
      onConfirm={() => void action.run(() => request('/backend/upload-diskfile.php?action=delete', { method: 'DELETE', body: { ova_id: number(deleting.id) } }), () => { setDeleting(null); resource.reload(); })}>
      <p>The server will refuse deletion if this artifact is still required by a challenge.</p>
      <Notice error={action.error} />
    </Confirm>}
  </>;
}
