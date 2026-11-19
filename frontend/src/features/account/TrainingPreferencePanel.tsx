import { useI18n } from '../../lib/i18n.tsx';
import { useState } from 'react';
import { Card, Notice, ResourceState } from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { payload, truth } from '../../lib/data.ts';
import { useAction, useResource } from '../../lib/state.tsx';

export function TrainingPreferencePanel() {
  const { t } = useI18n();
  const resource = useResource('/api/profile/training-preference'),
    action = useAction();
  const data = payload(resource.data);
  const [choice, setChoice] = useState<boolean | null>(null);
  function change(selected: boolean) {
    if (action.busy) return;
    setChoice(selected);
    void action.run(async () => {
      try {
        const result = await request('/api/profile/training-preference', {
          method: 'PUT',
          body: { opted_out: selected },
        });
        if (payload(result).opted_out !== selected)
          throw new Error('Training preference was not confirmed.');
        return result;
      } catch (error) {
        setChoice(null);
        resource.reload();
        throw error;
      }
    });
  }
  return (
    <Card title={t('privacy.trainingData')}>
      <p>{t('privacy.trainingConsentDescription')}</p>
      <p className="muted">{t('privacy.securityMonitoringExplanation')}</p>
      <Notice error={action.error} message={action.message} />
      <ResourceState {...resource}>
        {typeof data.opted_out === 'boolean' ? (
          <label className="check">
            <input
              type="checkbox"
              checked={!(choice ?? truth(data.opted_out))}
              disabled={action.busy}
              onChange={(event) => change(!event.target.checked)}
            />
            <span>{t('privacy.allowMyChallengeTrafficInTrainingDatasets')}</span>
          </label>
        ) : (
          <p>
            {t('privacy.trainingPreferenceCouldNotBeLoaded') + ' '}
            <button className="secondary small" onClick={resource.reload}>
              {t('routing.tryAgain')}
            </button>
          </p>
        )}
      </ResourceState>
    </Card>
  );
}
