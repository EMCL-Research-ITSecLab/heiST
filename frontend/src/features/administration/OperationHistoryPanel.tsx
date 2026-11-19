import { useI18n } from '../../lib/i18n.tsx';
import { useState } from 'react';
import { Badge, Card, Confirm, Field, Notice, ResourceState } from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { timestamp, number, payload, row, rows, text, truth } from '../../lib/data.ts';
import { useAction, useResource } from '../../lib/state.tsx';
import { Link } from '../../lib/router.tsx';

export function OperationHistoryPanel({
  scope,
  identifier,
}: {
  scope: string;
  identifier: number;
}) {
  const { t, optionLabel } = useI18n();
  const resource = useResource(
    '/api/admin/jobs/' + encodeURIComponent(scope) + '/' + identifier,
    10000,
  );
  const data = payload(resource.data);
  const action = useAction(),
    [pending, setPending] = useState<{
      id: string;
      kind: 'cancel' | 'resolve' | 'reconcile';
    } | null>(null);
  const [reason, setReason] = useState(''),
    [confirmation, setConfirmation] = useState('');
  return (
    <>
      <Card
        title={t('operations.history.title', { scope: optionLabel(scope), id: identifier })}
        action={
          <button className="secondary small" onClick={resource.reload}>
            {t('operations.refreshHistory')}
          </button>
        }
      >
        <Notice error={action.error} message={action.message} />
        <ResourceState {...resource}>
          {row(data.current).state === 'UNAVAILABLE' && (
            <p className="notice">{t('operations.currentReceiptUnavailable')}</p>
          )}
          {truth(data.truncated) && <p className="notice">{t('operations.historyLimitHint')}</p>}
          {rows(data.operations).length ? (
            rows(data.operations).map((operation) => (
              <details key={text(operation.id)}>
                <summary>
                  <Badge tone={operation.state === 'NEEDS_REVIEW' ? 'warning' : ''}>
                    {text(operation.state)}
                  </Badge>{' '}
                  {text(operation.action)} · {timestamp(operation.started)}
                </summary>
                <dl className="diagnostic-grid">
                  <dt>{t('overview.operation')}</dt>
                  <dd>
                    <code>{text(operation.id)}</code>
                  </dd>
                  <dt>{t('audit.administrator')}</dt>
                  <dd>{operation.actor ? '#' + number(operation.actor) : 'Not recorded'}</dd>
                  <dt>{t('operations.stage')}</dt>
                  <dd>{text(operation.stage, 'Not recorded').replaceAll('_', ' ')}</dd>
                  <dt>{t('operations.finished')}</dt>
                  <dd>{timestamp(operation.finished)}</dd>
                  {number(operation.instance_id) > 0 && (
                    <>
                      <dt>{t('instances.instance')}</dt>
                      <dd>
                        <Link href={'/manage-instances?instance=' + number(operation.instance_id)}>
                          #{number(operation.instance_id)}
                        </Link>
                      </dd>
                    </>
                  )}
                  {number(operation.cancelled_by) > 0 && (
                    <>
                      <dt>{t('operations.cancelledBy')}</dt>
                      <dd>#{number(operation.cancelled_by)}</dd>
                    </>
                  )}
                  {number(operation.resolved_by) > 0 && (
                    <>
                      <dt>{t('operations.reconciledBy')}</dt>
                      <dd>#{number(operation.resolved_by)}</dd>
                    </>
                  )}
                </dl>
                <ol>
                  {rows(operation.events).map((event, index) => (
                    <li key={index}>
                      {timestamp(event.at)} · {text(event.stage).replaceAll('_', ' ')}
                    </li>
                  ))}
                </ol>
                {operation.state === 'NEEDS_REVIEW' && (
                  <p className="notice">{t('operations.reconciliationWarning')}</p>
                )}
                {((truth(operation.managed_queue) && operation.state === 'QUEUED') ||
                  (operation.state === 'NEEDS_REVIEW' &&
                    (truth(operation.managed_queue) || row(data.current).id === operation.id))) && (
                  <button
                    className="secondary small"
                    onClick={() => {
                      action.clear();
                      setReason('');
                      setConfirmation('');
                      setPending({
                        id: text(operation.id),
                        kind:
                          operation.state === 'QUEUED'
                            ? 'cancel'
                            : truth(operation.managed_queue)
                              ? 'resolve'
                              : 'reconcile',
                      });
                    }}
                  >
                    {operation.state === 'QUEUED'
                      ? t('common.cancelQueuedOperation')
                      : t('common.recordReconciliation')}
                  </button>
                )}
              </details>
            ))
          ) : (
            <p>{t('operations.noOperationHistoryRecorded')}</p>
          )}
        </ResourceState>
      </Card>
      {pending && (
        <Confirm
          title={
            pending.kind === 'cancel'
              ? t('common.cancelQueuedOperation')
              : t('common.recordReconciliation')
          }
          confirm={
            pending.kind === 'cancel' ? t('common.cancelOperation') : t('common.markReconciled')
          }
          busy={action.busy}
          disabled={
            pending.kind !== 'cancel' && (reason.trim().length < 10 || confirmation !== pending.id)
          }
          onClose={() => setPending(null)}
          onConfirm={() =>
            void action.run(
              () =>
                request(
                  pending.kind === 'reconcile'
                    ? `/api/admin/jobs/${scope}/${identifier}/reconcile`
                    : '/api/admin/jobs/' + pending.id + '/' + pending.kind,
                  {
                    method: 'POST',
                    body:
                      pending.kind !== 'cancel' ? { reason, confirmation, job_id: pending.id } : {},
                  },
                ),
              () => {
                setPending(null);
                resource.reload();
              },
            )
          }
        >
          <Notice error={action.error} />
          <p>
            <code>{pending.id}</code>
          </p>
          {pending.kind === 'cancel' ? (
            <p>{t('operations.cancelExplanation')}</p>
          ) : (
            <>
              <p>{t('operations.reconciliationExplanation')}</p>
              <Field
                label={t('operations.recoveryChecks')}
                value={reason}
                minLength={10}
                maxLength={500}
                onChange={(event) => setReason(event.target.value)}
              />
              <Field
                label={t('operations.typeOperationId')}
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
              />
              <p className="muted">{t('operations.recoveryNotesHint')}</p>
            </>
          )}
        </Confirm>
      )}
    </>
  );
}
