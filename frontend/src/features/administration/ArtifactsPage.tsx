import { useI18n } from '../../lib/i18n.tsx';
import { useState, type FormEvent } from 'react';
import {
  Badge,
  Card,
  Confirm,
  Empty,
  Field,
  Notice,
  PageTitle,
  ResourceState,
  Select,
} from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { number, payload, row, rows, text, type Row } from '../../lib/data.ts';
import { useAction, useResource, useSession } from '../../lib/state.tsx';
import { useArtifactUpload } from './useArtifactUpload.ts';
import { SortableHeader } from '../../components/SortableHeader.tsx';
import { useTableView } from '../../lib/useTableView.tsx';
export function Artifacts() {
  const { t } = useI18n();
  const resource = useResource('/api/admin/artifacts', 10000),
    data = payload(resource.data),
    limits = row(data.limits),
    action = useAction();
  const session = useSession();
  const transfer = useArtifactUpload(session.user?.username ?? '', resource.reload);
  const [file, setFile] = useState<File | null>(null),
    [guest, setGuest] = useState('linux'),
    [deleting, setDeleting] = useState<Row | null>(null);
  const items = rows(data.ovas),
    pending = rows(data.uploads);
  const library = useTableView<Row>(
    items,
    [
      {
        key: 'name',
        label: t('artifacts.artifact'),
        value: (item) => text(item.display_name ?? item.filename),
      },
      {
        key: 'os',
        label: t('artifacts.guestOperatingSystem'),
        value: (item) => text(item.guest_os),
      },
      {
        key: 'size',
        label: t('tables.size'),
        value: (item) =>
          item.file_size == null && item.size == null ? null : number(item.file_size ?? item.size),
      },
    ],
    'name',
  );
  const transfers = useTableView<Row>(pending, [
    { key: 'name', label: t('artifacts.artifact'), value: (item) => text(item.name) },
    { key: 'status', label: t('common.labels.status'), value: (item) => text(item.state) },
  ]);
  const { busy, progress, phase } = transfer;
  function upload(event: FormEvent) {
    event.preventDefault();
    if (file) void transfer.upload(file, guest, limits);
  }
  return (
    <>
      <PageTitle
        eyebrow={t('artifacts.administrationArtifactLibrary')}
        title={t('artifacts.vmArtifacts')}
        description={t('artifacts.uploadVmArtifactsOnceThenUseThemInYour')}
      />
      <Notice error={transfer.error || action.error} message={transfer.message || action.message} />
      <Card title={t('artifacts.uploadAnArtifact')}>
        <p className="muted">{t('artifacts.chunkedUploadExplanation')}</p>
        <ResourceState {...resource}>
          <form onSubmit={upload}>
            <div className="form-grid">
              <Field
                label={t('artifacts.ovaFile')}
                type="file"
                accept=".ova"
                required
                disabled={busy}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              <Select
                label={t('artifacts.guestOperatingSystem')}
                options={['linux', 'windows']}
                value={guest}
                disabled={busy}
                onChange={(e) => setGuest(e.target.value)}
              />
            </div>
            {file && (
              <p className="mono muted">
                {file.name} · {(file.size / 1024 ** 2).toFixed(1)}
                {' ' + t('artifacts.mib')}
              </p>
            )}
            <div className="button-row">
              <button disabled={!file || busy || resource.loading}>
                {busy ? t('common.uploading') : t('common.uploadArtifact')}
              </button>
              {busy && transfer.canCancel && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() =>
                    void action.run(() => transfer.cancel().then(() => ({ success: true })))
                  }
                >
                  {t('artifacts.cancelUpload')}
                </button>
              )}
            </div>
            {busy && (
              <div className="upload-progress" role="status">
                <progress max={100} value={progress} />
                <p>
                  {phase}
                  {progress > 0 ? ` · ${progress}% transferred` : ''}
                </p>
              </div>
            )}
          </form>
        </ResourceState>
      </Card>
      {pending.length > 0 && (
        <Card title={t('artifacts.transfersAndValidation')}>
          {transfers.controls}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <SortableHeader {...transfers.header('name')} />
                  <SortableHeader {...transfers.header('status')} />
                  <th>{t('common.labels.action')}</th>
                </tr>
              </thead>
              <tbody>
                {transfers.items.map((item) => (
                  <tr key={text(item.id)}>
                    <td>{text(item.name)}</td>
                    <td>
                      <Badge>{text(item.state).toLowerCase()}</Badge>
                    </td>
                    <td>
                      {['RECEIVING', 'FAILED', 'READY'].includes(text(item.state)) ? (
                        <button
                          className="secondary small"
                          disabled={busy || action.busy}
                          onClick={() =>
                            void action.run(() =>
                              transfer.cancel(text(item.id)).then(() => ({ success: true })),
                            )
                          }
                        >
                          {item.state === 'RECEIVING'
                            ? t('common.cancelTransfer')
                            : t('common.dismissReceipt')}
                        </button>
                      ) : item.state === 'NEEDS_REVIEW' ? (
                        <button
                          className="secondary small"
                          disabled={busy || action.busy}
                          onClick={() =>
                            void action.run(
                              () =>
                                request('/api/admin/artifact-uploads/' + text(item.id) + '/retry', {
                                  method: 'POST',
                                  body: {},
                                }),
                              resource.reload,
                            )
                          }
                        >
                          {t('artifacts.retryValidation')}
                        </button>
                      ) : (
                        <span className="muted">{t('artifacts.validationIsPending')}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">{t('artifacts.resumeInstructions')}</p>
        </Card>
      )}
      <ResourceState {...resource}>
        <Card
          title={t('artifacts.yourArtifactLibrary')}
          action={
            <button className="secondary small" onClick={resource.reload}>
              {t('artifacts.refresh')}
            </button>
          }
        >
          {library.controls}
          {items.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <SortableHeader {...library.header('name')} />
                    <SortableHeader {...library.header('os')} />
                    <SortableHeader {...library.header('size')} />
                    <th>{t('common.labels.action')}</th>
                  </tr>
                </thead>
                <tbody>
                  {library.items.map((item) => (
                    <tr key={text(item.id)}>
                      <td>
                        <strong>{text(item.display_name ?? item.filename)}</strong>
                        <small>#{text(item.id)}</small>
                      </td>
                      <td>{text(item.guest_os)}</td>
                      <td>
                        {number(item.file_size ?? item.size)
                          ? (number(item.file_size ?? item.size) / 1024 ** 2).toFixed(1) + ' MiB'
                          : '—'}
                      </td>
                      <td>
                        <button className="danger subtle small" onClick={() => setDeleting(item)}>
                          {t('common.actions.delete')}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title={t('artifacts.yourArtifactLibraryIsEmpty')}>
              {t('artifacts.uploadAVmArtifactToStartBuildingAnExercise')}
            </Empty>
          )}
        </Card>
      </ResourceState>
      {deleting && (
        <Confirm
          title={t('artifacts.deleteThisArtifact')}
          confirm={t('artifacts.deleteArtifact')}
          busy={action.busy}
          onClose={() => setDeleting(null)}
          onConfirm={() =>
            void action.run(
              () => request('/api/admin/artifacts/' + text(deleting.id), { method: 'DELETE' }),
              () => {
                setDeleting(null);
                resource.reload();
              },
            )
          }
        >
          <p>{t('artifacts.delete.inUseWarning')}</p>
          <Notice error={action.error} />
        </Confirm>
      )}
    </>
  );
}
