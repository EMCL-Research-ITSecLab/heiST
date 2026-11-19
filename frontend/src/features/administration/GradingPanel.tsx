import { useI18n } from '../../lib/i18n.tsx';
import { useState, type FormEvent } from 'react';
import { Card, Field, Notice, ResourceState, Select } from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { number, payload, rows, text } from '../../lib/data.ts';
import { useAction, useResource } from '../../lib/state.tsx';

export function GradingPanel() {
  const { t } = useI18n();
  const resource = useResource('/api/admin/challenges'),
    action = useAction();
  const [challenge, setChallenge] = useState(''),
    [flag, setFlag] = useState('');
  const options: [string, string][] = [
    ['', t('grading.chooseAChallenge')],
    ...rows(payload(resource.data).challenges).map(
      (c) => [text(c.id), text(c.name)] as [string, string],
    ),
  ];
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    void action.run(
      () =>
        request('/api/admin/grading/submissions', {
          method: 'POST',
          body: {
            user_id: number(values.get('user_id')),
            challenge_id: number(challenge),
            flag,
            confirmation: text(values.get('confirmation')),
            reason: text(values.get('reason')),
          },
        }),
      () => setFlag(''),
    );
  }
  return (
    <>
      <Notice error={action.error} message={action.message} />
      <ResourceState {...resource}>
        <Card title={t('grading.exportGrades')}>
          <Select
            label={t('grading.gradingChallenge')}
            value={challenge}
            options={options}
            onChange={(event) => setChallenge(event.target.value)}
          />
          <div className="button-row">
            <button
              className="secondary"
              disabled={action.busy}
              onClick={() =>
                void action.run(() =>
                  request(
                    '/api/admin/grading/submissions.csv' +
                      (challenge ? '?challenge_id=' + challenge : ''),
                    { download: true },
                  ),
                )
              }
            >
              {t('grading.exportSubmissions')}
            </button>
            <button
              className="secondary"
              disabled={!challenge || action.busy}
              onClick={() =>
                void action.run(() =>
                  request(
                    '/api/admin/grading/submissions.csv?format=moodle&challenge_id=' + challenge,
                    { download: true },
                  ),
                )
              }
            >
              {t('grading.exportMoodle')}
            </button>
          </div>
          <p className="muted">{t('grading.exportInstructions')}</p>
        </Card>
        <Card title={t('grading.submitAFlagForAStudent')}>
          <form onSubmit={submit}>
            <p>{t('grading.assistedSubmissionExplanation')}</p>
            <Field
              label={t('grading.studentUserId')}
              name="user_id"
              type="number"
              min={1}
              required
            />
            <Field
              label={t('grading.studentUsernameConfirmation')}
              name="confirmation"
              required
              autoComplete="off"
            />
            <Field
              label={t('grading.studentFlag')}
              type="password"
              value={flag}
              onChange={(event) => setFlag(event.target.value)}
              required
              autoComplete="off"
              maxLength={4096}
            />
            <Field
              label={t('grading.reasonForAssistedSubmission')}
              name="reason"
              required
              minLength={10}
              maxLength={500}
            />
            <button disabled={!challenge || action.busy}>{t('grading.submitForStudent')}</button>
          </form>
        </Card>
      </ResourceState>
    </>
  );
}
