import { useI18n } from '../../lib/i18n.tsx';
import { useState } from 'react';
import { Badge, Card, Confirm, Field, Notice, ResourceState } from '../../components/ui.tsx';
import { NetworkPreview } from '../../components/NetworkPreview.tsx';
import { request } from '../../lib/api.ts';
import { date, number, payload, row, rows, text, truth } from '../../lib/data.ts';
import { Link, useRouter } from '../../lib/router.tsx';
import { useAction, useResource } from '../../lib/state.tsx';

export function ExerciseHistoryPanel({
  identifier,
  name,
  onClose,
}: {
  identifier: number;
  name: string;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const resource = useResource('/api/admin/challenges/' + identifier + '/revisions'),
    data = payload(resource.data),
    action = useAction(),
    router = useRouter();
  const [selected, setSelected] = useState<number | null>(null),
    [clone, setClone] = useState<number | null>(null),
    [draftName, setDraftName] = useState('');
  return (
    <Card
      title={t('authoring.history.title', { name })}
      action={
        <button className="secondary small" onClick={onClose}>
          {t('authoring.closeHistory')}
        </button>
      }
    >
      <Notice error={action.error} message={action.message} />
      <p>{t('authoring.history.snapshotExplanation')}</p>
      <button
        className="secondary"
        disabled={action.busy}
        onClick={() =>
          void action.run(
            () =>
              request('/api/admin/challenges/' + identifier + '/revisions', {
                method: 'POST',
                body: {},
              }),
            resource.reload,
          )
        }
      >
        {t('authoring.recordCurrentRevision')}
      </button>
      <ResourceState {...resource}>
        {truth(data.has_more) && (
          <p className="notice">{t('authoring.showingTheLatest50Configurations')}</p>
        )}
        {rows(data.revisions).length ? (
          <div className="table-wrap">
            <table aria-label={t('authoring.exerciseConfigurationHistory')}>
              <thead>
                <tr>
                  <th>{t('audit.revision')}</th>
                  <th>{t('authoring.recorded')}</th>
                  <th>{t('audit.administrator')}</th>
                  <th>{t('common.labels.state')}</th>
                  <th>{t('authoring.definition')}</th>
                  <th>{t('common.labels.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {rows(data.revisions).map((revision) => (
                  <tr key={number(revision.id)}>
                    <td>#{number(revision.id)}</td>
                    <td>{date(revision.recorded_at)}</td>
                    <td>{text(revision.actor, 'Deleted account')}</td>
                    <td>
                      <Badge>
                        {truth(revision.is_active) ? t('common.published') : t('common.inactive')}
                      </Badge>
                    </td>
                    <td>
                      {number(revision.machines)}
                      {' ' + t('authoring.vms') + ' '}
                      {number(revision.networks)}
                      {' ' + t('authoring.networksLabel')}
                      <small>
                        {t('authoring.sha256') + ' '}
                        <code>{text(revision.fingerprint)}</code>
                      </small>
                    </td>
                    <td>
                      <div className="button-row">
                        <button
                          className="secondary small"
                          onClick={() => setSelected(number(revision.id))}
                        >
                          {t('authoring.inspectRevision')}
                        </button>
                        <button
                          className="secondary small"
                          onClick={() => {
                            action.clear();
                            setClone(number(revision.id));
                            setDraftName((name + ' copy').slice(0, 100));
                          }}
                        >
                          {t('authoring.cloneAsDraft')}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>{t('authoring.history.emptyDescription')}</p>
        )}
      </ResourceState>
      {selected && <RevisionDetails key={selected} identifier={identifier} revision={selected} />}
      {clone && (
        <Confirm
          title={t('authoring.cloneConfigurationAsDraft')}
          confirm={t('authoring.cloneDraft')}
          busy={action.busy}
          disabled={!draftName.trim()}
          onClose={() => setClone(null)}
          onConfirm={() =>
            void action.run(
              () =>
                request(`/api/admin/challenges/${identifier}/revisions/${clone}/clone`, {
                  method: 'POST',
                  body: { name: draftName },
                }),
              (result) => {
                setClone(null);
                router.navigate('/manage-ctf?exercise=' + number(result.id));
                resource.reload();
              },
            )
          }
        >
          <Notice error={action.error} />
          <p>{t('authoring.clone.explanation')}</p>
          <Field
            label={t('authoring.newDraftName')}
            value={draftName}
            maxLength={100}
            onChange={(event) => setDraftName(event.target.value)}
          />
        </Confirm>
      )}
    </Card>
  );
}

function RevisionDetails({ identifier, revision }: { identifier: number; revision: number }) {
  const { t } = useI18n();
  const resource = useResource(`/api/admin/challenges/${identifier}/revisions/${revision}`),
    definition = row(payload(resource.data).definition);
  const machines = rows(definition.vms),
    networks = rows(definition.subnets);
  return (
    <ResourceState {...resource}>
      <Card title={t('authoring.history.revisionTitle', { id: revision })}>
        <p>
          {text(definition.name)} · {text(definition.category)} · {text(definition.difficulty)}
        </p>
        <p>{text(definition.description)}</p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('monitoring.vm')}</th>
                <th>{t('authoring.image')}</th>
                <th>{t('common.labels.resources')}</th>
                <th>{t('authoring.domain')}</th>
              </tr>
            </thead>
            <tbody>
              {machines.map((vm) => (
                <tr key={text(vm.name)}>
                  <td>{text(vm.name)}</td>
                  <td>
                    {text(vm.ova_name)} · #{number(vm.artifact_id)}
                  </td>
                  <td>
                    {number(vm.cores)}
                    {' ' + t('authoring.vcpu') + ' '}
                    {number(vm.ram_gb)}
                    {' ' + t('authoring.gib')}
                  </td>
                  <td>{text(vm.domain_name, 'None')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <NetworkPreview
          machines={machines.map((vm) => ({ key: text(vm.name), name: text(vm.name) }))}
          networks={networks.map((network) => ({
            key: text(network.name),
            name: text(network.name),
            accessible: truth(network.accessible),
            dmz: truth(network.dmz),
            machines: Array.isArray(network.attached_vms)
              ? network.attached_vms.map((value) => text(value))
              : [],
          }))}
        />
        <p>
          {rows(definition.flags).length}
          {' ' + t('authoring.flagsLabel') + ' '}
          {rows(definition.hints).length}
          {' ' + t('authoring.hintsFlagValuesAreNotDisplayedInThisHistory')}
        </p>
        <Link href={'/manage-instances?template_id=' + identifier}>
          {t('authoring.inspectCurrentInstances')}
        </Link>
      </Card>
    </ResourceState>
  );
}
