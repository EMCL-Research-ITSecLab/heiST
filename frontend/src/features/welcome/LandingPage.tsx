import { useI18n } from '../../lib/i18n.tsx';
import { Card } from '../../components/ui.tsx';
import { Link } from '../../lib/router.tsx';
export function Landing() {
  const { t } = useI18n();
  return (
    <>
      <section className="hero">
        <div>
          <h1>{t('navigation.heist')}</h1>
          <p>{t('welcome.heidelbergSecurityTraining')}</p>
          <div className="button-row">
            <Link className="button" href="/explore">
              {t('navigation.challenges')}
            </Link>
            <Link className="button secondary" href="/signup">
              {t('auth.signup.title')}
            </Link>
          </div>
        </div>
      </section>
      <div className="feature-grid">
        {(
          [
            ['welcome.steps.selectTitle', 'library.browseExercisesByCategoryAndDifficulty'],
            ['welcome.steps.connectTitle', 'welcome.steps.connectDescription'],
            ['welcome.steps.submitTitle', 'welcome.steps.submitDescription'],
          ] as const
        ).map(([title, description]) => (
          <Card key={title}>
            <h2>{t(title)}</h2>
            <p className="muted">{t(description)}</p>
          </Card>
        ))}
      </div>
    </>
  );
}
