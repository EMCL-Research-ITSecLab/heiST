import { useI18n } from '../../lib/i18n.tsx';
import { useEffect, useState, type FormEvent } from 'react';
import {
  Badge,
  Card,
  Confirm,
  Empty,
  Field,
  Notice,
  PageTitle,
  ResourceState,
} from '../../components/ui.tsx';
import { post } from '../../lib/api.ts';
import { duration, number, row, rows, text, truth } from '../../lib/data.ts';
import { Link } from '../../lib/router.tsx';
import { useAction, useResource } from '../../lib/state.tsx';
export function Challenge() {
  const { t } = useI18n();
  const id = number(new URLSearchParams(window.location.search).get('id'));
  const resource = useResource(`/api/challenge?id=${id}`, 15000),
    challenge = row(resource.data.challenge),
    status = row(challenge.challenge_status),
    action = useAction();
  const [flag, setFlag] = useState(''),
    [confirm, setConfirm] = useState(false),
    [tick, setTick] = useState(0);
  const running = text(status.challenge_status) === 'running';
  const timingReady = challenge.timing_ready !== false && challenge.remaining_seconds != null;
  useEffect(() => {
    const timer = window.setInterval(() => setTick((v) => v + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    setTick(0);
  }, [resource.data]);
  const remaining = Math.max(0, number(challenge.remaining_seconds) - tick);
  async function operate(name: string, fields = {}) {
    await action.run(
      () => post('challenge', { action: name, challenge_id: id, ...fields }),
      () => {
        setConfirm(false);
        setFlag('');
        resource.reload();
      },
    );
  }
  return (
    <>
      <div className="breadcrumbs">
        <Link href="/explore">{t('navigation.challengeLibrary')}</Link>
        <span>/</span>
        <span>
          {t('challenge.investigation') + ' '}
          {id || '—'}
        </span>
      </div>
      <ResourceState {...resource}>
        <PageTitle
          eyebrow={text(challenge.category, 'INVESTIGATION').toUpperCase()}
          title={text(challenge.name, 'Challenge')}
          description={`Created by ${text(challenge.creator_username, 'the heiST team')}`}
          action={<Badge tone={text(challenge.difficulty)}>{text(challenge.difficulty)}</Badge>}
        />
        <Notice error={action.error} message={action.message} />
        <div className="challenge-layout">
          <div>
            <Card>
              <div className="spread">
                <Badge tone={running ? 'active' : ''}>
                  {text(status.challenge_status, 'Not started').replaceAll('_', ' ')}
                </Badge>
                <span className="muted">
                  {number(challenge.challenge_points)}
                  {' ' + t('challenge.points') + ' '}
                  {number(challenge.solve_count)}
                  {' ' + t('common.solves')}
                </span>
              </div>
              <h2>{t('challenge.theInvestigation')}</h2>
              <p className="prose">{text(challenge.description)}</p>
            </Card>
            <Card title={t('challenge.submitAFlag')}>
              <p className="muted">
                {t('challenge.foundSomethingSubmitYourFlagToRecordYourProgress')}
              </p>
              <form
                className="inline-form"
                onSubmit={(e: FormEvent) => {
                  e.preventDefault();
                  void operate('submit_flag', { flag });
                }}
              >
                <Field
                  label={t('authoring.flag')}
                  placeholder={t('challenge.enterTheFlagYouFound')}
                  value={flag}
                  onChange={(e) => setFlag(e.target.value)}
                  required
                  autoComplete="off"
                />
                <button disabled={action.busy || !flag.trim()}>{t('challenge.submitFlag')}</button>
              </form>
              <p className="muted">
                {number(challenge.flags_submitted)}
                {' ' + t('common.of') + ' '}
                {number(challenge.flags_total)}
                {' ' + t('challenge.flagsSubmitted')}
              </p>
              <progress
                max={number(challenge.flags_total) || 1}
                value={number(challenge.flags_submitted)}
              />
            </Card>
            {(text(challenge.hint) || rows(challenge.hints).length > 0) && (
              <Card title={t('challenge.hints')}>
                {text(challenge.hint) && (
                  <details>
                    <summary>{t('challenge.generalHint')}</summary>
                    <p className="prose">{text(challenge.hint)}</p>
                  </details>
                )}
                {rows(challenge.hints).map((hint, i) => (
                  <details key={text(hint.id, String(i))}>
                    <summary>
                      {t('common.labels.hint') + ' '}
                      {i + 1}
                    </summary>
                    <p className="prose">{text(hint.hint_text)}</p>
                  </details>
                ))}
              </Card>
            )}
            {truth(challenge.isSolved) && text(challenge.solution) && (
              <Card title={t('challenge.walkthrough')}>
                <details>
                  <summary>{t('challenge.revealTheSolution')}</summary>
                  <p className="prose">{text(challenge.solution)}</p>
                </details>
              </Card>
            )}
            <Card title={t('authoring.leaderboard')}>
              {rows(challenge.leaderboard).length ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>{t('authoring.rank')}</th>
                        <th>{t('challenge.investigator')}</th>
                        <th>{t('common.labels.time')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows(challenge.leaderboard).map((entry, i) => (
                        <tr key={i}>
                          <td>{number(entry.rank) || i + 1}</td>
                          <td>
                            <Link href={'/profile/' + encodeURIComponent(text(entry.username))}>
                              {text(entry.username)}
                            </Link>
                          </td>
                          <td className="mono">{duration(entry.total_seconds)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty title={t('challenge.noSubmissionsYet')} />
              )}
            </Card>
          </div>
          <aside>
            <Card title={t('challenge.yourEnvironment')}>
              <span className="environment-glyph" aria-hidden>
                ⌘
              </span>
              <h3>
                {running
                  ? timingReady
                    ? t('challenge.environment.runningTitle')
                    : t('challenge.environment.preparingTitle')
                  : t('challenge.environment.readyTitle')}
              </h3>
              <p className="muted">{t('challenge.environment.connectionHint')}</p>
              {running ? (
                <>
                  <div className="time-remaining">
                    <small>{t('challenge.timeRemaining')}</small>
                    <strong className="mono">
                      {timingReady ? duration(remaining) : 'Preparing…'}
                    </strong>
                  </div>
                  <button
                    className="full secondary"
                    disabled={
                      action.busy || !timingReady || number(challenge.remaining_extensions) === 0
                    }
                    onClick={() => void operate('extend_time')}
                  >
                    {t('challenge.extendTime')}
                    {number(challenge.remaining_extensions)}
                    {' ' + t('challenge.left')}
                  </button>
                  <button
                    className="full danger subtle"
                    disabled={action.busy}
                    onClick={() => setConfirm(true)}
                  >
                    {t('challenge.stopThisInstance')}
                  </button>
                  <div className="connection-info">
                    <strong>{t('challenge.connectionDetails')}</strong>
                    {(Array.isArray(challenge.entrypoints) ? challenge.entrypoints : []).map(
                      (entry, i) => (
                        <code key={i}>
                          {typeof entry === 'string'
                            ? entry
                            : text(row(entry).subnet ?? row(entry).ip ?? row(entry).address)}
                        </code>
                      ),
                    )}
                  </div>
                </>
              ) : (
                <button
                  className="full"
                  disabled={
                    action.busy ||
                    !truth(challenge.is_active) ||
                    truth(challenge.marked_for_deletion)
                  }
                  onClick={() => void operate('deploy')}
                >
                  {action.busy
                    ? t('challenge.environment.preparingTitle')
                    : t('challenge.environment.start')}
                </button>
              )}
              <Link className="text-link" href="/profile">
                {t('challenge.getYourVpnConfiguration')}
              </Link>
            </Card>
          </aside>
        </div>
      </ResourceState>
      {confirm && (
        <Confirm
          title={t('challenge.stopThisInstanceLabel')}
          confirm={t('challenge.stopInstance')}
          busy={action.busy}
          onClose={() => setConfirm(false)}
          onConfirm={() => void operate('cancel')}
        >
          <p>{t('challenge.stopConfirmation')}</p>
        </Confirm>
      )}
    </>
  );
}
