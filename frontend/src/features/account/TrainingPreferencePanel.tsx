import { useState } from 'react';
import { Card, Notice, ResourceState } from '../../components/ui.tsx';
import { request } from '../../lib/api.ts';
import { payload, truth } from '../../lib/data.ts';
import { useAction, useResource } from '../../lib/state.tsx';

export function TrainingPreferencePanel() {
  const resource = useResource('/api/profile/training-preference'), action = useAction();
  const data = payload(resource.data);
  const [choice, setChoice] = useState<boolean | null>(null);
  function change(selected: boolean) {
    if (action.busy) return;
    setChoice(selected);
    void action.run(async () => {
      try {
        const result = await request('/api/profile/training-preference', { method: 'PUT', body: { opted_out: selected } });
        if (payload(result).opted_out !== selected) throw new Error('Training preference was not confirmed.');
        return result;
      } catch (error) {
        setChoice(null);
        resource.reload();
        throw error;
      }
    });
  }
  return <Card title="Training data">
    <p>Challenge network traffic, including packet contents, is eligible for machine-learning datasets by default. You can opt out at any time.</p>
    <p className="muted">Operational security monitoring is separate from training use.</p>
    <Notice error={action.error} message={action.message} />
    <ResourceState {...resource}>
      {typeof data.opted_out === 'boolean' ? <label className="check">
        <input type="checkbox" checked={choice ?? truth(data.opted_out)} disabled={action.busy}
          onChange={event => change(event.target.checked)} />
        <span>Exclude my challenge traffic from training datasets.</span>
      </label> : <p>Training preference could not be loaded. <button className="secondary small" onClick={resource.reload}>Try again</button></p>}
    </ResourceState>
  </Card>;
}
