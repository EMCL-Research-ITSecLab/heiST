import { useI18n } from '../../lib/i18n.tsx';
import { DashboardAnnouncements } from './DashboardAnnouncements.tsx';
import {
  ActivityList,
  Card,
  ChallengeCard,
  Empty,
  PageTitle,
  ResourceState,
  Stat,
} from '../../components/ui.tsx';
import { number, payload, row, rows, text } from '../../lib/data.ts';
import { Link } from '../../lib/router.tsx';
import { useResource } from '../../lib/state.tsx';
export function Dashboard() {
  const { t } = useI18n();
  const resource = useResource('/api/dashboard', 30000),
    data = payload(resource.data),
    user = row(data.user),
    progress = row(data.progress),
    active = row(data.active_challenge),
    timeline = row(data.timeline);
  return (
    <>
      <PageTitle
        eyebrow={t('dashboard.yourLearningWorkspace')}
        title={t('routing.dashboard')}
        action={
          <Link className="button" href="/explore">
            {t('dashboard.exploreChallenges')}
          </Link>
        }
      />
      <ResourceState {...resource}>
        <DashboardAnnouncements announcements={rows(data.news)} />
        <div className="stats-grid">
          <Stat label={t('profile.totalPoints')} value={user.points} />
          <Stat label={t('profile.challengesSolved')} value={progress.solved} />
          <Stat label={t('dashboard.successRate')} value={`${number(progress.success_rate)}%`} />
          <Stat
            label={t('profile.yourRank')}
            value={number(user.rank) ? '#' + text(user.rank) : '—'}
          />
        </div>
        {Object.keys(active).length > 0 &&
          number(active.id ?? active.challenge_template_id) > 0 && (
            <div className="active-banner">
              <span className="status-dot" />
              <div>
                <strong>{t('dashboard.yourLabIsReadyWhenYouAre')}</strong>
                <p>{text(active.name ?? active.challenge_name)}</p>
              </div>
              <Link
                className="button secondary"
                href={`/challenge?id=${number(active.challenge_template_id ?? active.id)}`}
              >
                {t('dashboard.continueInvestigation')}
              </Link>
            </div>
          )}
        <div className="section-heading">
          <div>
            <p className="eyebrow">{t('dashboard.keepYourCuriosityMoving')}</p>
            <h2>{t('dashboard.yourNextChallenge')}</h2>
          </div>
          <Link href="/explore">{t('dashboard.viewLibrary')}</Link>
        </div>
        <div className="challenge-grid">
          {rows(data.challenges).map((c) => (
            <ChallengeCard key={text(c.id)} challenge={c} />
          ))}
        </div>
        {rows(data.challenges).length === 0 && (
          <Empty title={t('dashboard.aFreshStart')}>
            {t('dashboard.browseTheLibraryToFindYourFirstInvestigation')}
          </Empty>
        )}
        <div className="two-columns">
          <Card
            title={t('profile.recentActivity')}
            action={<Link href="/activity">{t('dashboard.viewAll')}</Link>}
          >
            <ActivityList items={rows(data.activity)} />
          </Card>
          <Card title={t('dashboard.yourLearningRhythm')}>
            <div className="bar-chart" aria-label={t('dashboard.pointsEarnedOverTime')}>
              {Array.isArray(timeline.points) && timeline.points.length ? (
                timeline.points.map((point, i) => (
                  <div key={i}>
                    <span
                      style={{
                        height: `${Math.max(3, (number(point) / Math.max(1, ...(timeline.points as number[]))) * 120)}px`,
                      }}
                      title={`${text((timeline.labels as unknown[])?.[i])}: ${number(point)} points`}
                    />
                    <small>{text((timeline.labels as unknown[])?.[i])}</small>
                  </div>
                ))
              ) : (
                <Empty title={t('dashboard.progressStartsWithPractice')}>
                  {t('dashboard.yourPointsWillAppearHereAsYouSolveChallenges')}
                </Empty>
              )}
            </div>
            <Link href="/badges">{t('dashboard.exploreYourAchievements')}</Link>
          </Card>
        </div>
      </ResourceState>
    </>
  );
}
