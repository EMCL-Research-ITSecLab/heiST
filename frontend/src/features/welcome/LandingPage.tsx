import {useI18n} from '../../lib/i18n.tsx';
import { Card } from '../../components/ui.tsx';
import { Link } from '../../lib/router.tsx';
export function Landing() {
  const {t}=useI18n();
  return <>
    <section className="hero">
      <div>
        <h1>{t("heiST")}</h1>
        <p>{t("Heidelberg Security Training")}</p>
        <div className="button-row">
          <Link className="button" href="/explore">{t("Challenges")}</Link>
          <Link className="button secondary" href="/signup">{t("Create account")}</Link>
        </div>
      </div>
    </section>
    <div className="feature-grid">
      {[['Select a challenge', 'Browse exercises by category and difficulty.'], ['Start an environment', 'Connect to the exercise using your VPN configuration.'], ['Submit flags', 'Submit your results and track your progress.']].map(([title, description]) => <Card key={title}>
        <h2>{t(title)}</h2><p className="muted">{t(description)}</p>
      </Card>)}
    </div>
  </>;
}
