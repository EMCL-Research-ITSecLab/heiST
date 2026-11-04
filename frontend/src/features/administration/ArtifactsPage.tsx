import { useState, type FormEvent } from 'react';
import { Badge, Card, Confirm, Empty, Field, Notice, PageTitle, ResourceState, Select } from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { number, payload, row, rows, text, type Row } from '../../lib/data.ts';
import { useAction, useResource, useSession } from '../../lib/state.tsx';
import { useArtifactUpload } from './useArtifactUpload.ts';
export function Artifacts() {
  const resource = useResource('/api/admin/artifacts', 10000), data = payload(resource.data), limits = row(data.limits), action = useAction();
  const session = useSession();
  const transfer = useArtifactUpload(session.user?.username ?? '', resource.reload);
  const [file, setFile] = useState<File | null>(null), [guest, setGuest] = useState('linux'), [deleting, setDeleting] = useState<Row | null>(null);
  const items = rows(data.ovas), pending = rows(data.uploads);
  const {busy, progress, phase} = transfer;
  function upload(event: FormEvent) {
    event.preventDefault();
    if (file) void transfer.upload(file, guest, limits);
  }
  return <>
    <PageTitle eyebrow="ADMINISTRATION / ARTIFACT LIBRARY" title="The building blocks of your labs." description="Upload VM artifacts once, then use them in your exercises." />
    <Notice error={transfer.error || action.error} message={transfer.message || action.message} />
    <Card title="Upload an artifact">
      <p className="muted">Large uploads use the server’s chunked upload protocol. Validation must finish before the artifact is available.</p>
      <ResourceState {...resource}>
        <form onSubmit={upload}>
          <div className="form-grid">
            <Field
              label="OVA file"
              type="file"
              accept=".ova"
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
            <button disabled={!file || busy || resource.loading}>
              {busy ? 'Uploading…' : 'Upload artifact ↑'}
            </button>
            {busy && transfer.canCancel && <button type="button" className="secondary" onClick={() => void action.run(() => transfer.cancel().then(() => ({success: true})))}>Cancel upload</button>}
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
    {pending.length > 0 && <Card title="Transfers and validation">
      <div className="table-wrap"><table><thead><tr><th>Artifact</th><th>Status</th><th>Action</th></tr></thead><tbody>
        {pending.map(item => <tr key={text(item.id)}><td>{text(item.name)}</td><td><Badge>{text(item.state).toLowerCase()}</Badge></td><td>
          {['RECEIVING','FAILED','READY'].includes(text(item.state)) ? <button className="secondary small" disabled={busy || action.busy} onClick={() => void action.run(() => transfer.cancel(text(item.id)).then(() => ({success:true})))}>{item.state==='RECEIVING' ? 'Cancel transfer' : 'Dismiss receipt'}</button> : item.state==='NEEDS_REVIEW' ? <button className="secondary small" disabled={busy || action.busy} onClick={() => void action.run(() => request('/api/admin/artifact-uploads/'+text(item.id)+'/retry',{method:'POST',body:{}}),resource.reload)}>Retry validation</button> : <span className="muted">Validation is pending.</span>}
        </td></tr>)}
      </tbody></table></div>
      <p className="muted">To resume a transfer, select its original file. Completed transfers remain unavailable until validation succeeds.</p>
    </Card>}
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
                    {text(item.display_name ?? item.filename)}
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
      onConfirm={() => void action.run(() => request('/api/admin/artifacts/'+text(deleting.id), { method: 'DELETE' }), () => { setDeleting(null); resource.reload(); })}>
      <p>The server will refuse deletion if this artifact is still required by a challenge.</p>
      <Notice error={action.error} />
    </Confirm>}
  </>;
}
