import { Card } from '../../components/ui.tsx';
import { Link } from '../../lib/router.tsx';
export function Landing() {
  return <>
    <section className="hero">
      <div>
        <h1>heiST</h1>
        <p>Heidelberg Security Training</p>
        <div className="button-row">
          <Link className="button" href="/explore">Challenges</Link>
          <Link className="button secondary" href="/signup">Create account</Link>
        </div>
      </div>
    </section>
    <div className="feature-grid">
      {[['Select a challenge', 'Browse exercises by category and difficulty.'], ['Start an environment', 'Connect to the exercise using your VPN configuration.'], ['Submit flags', 'Submit your results and track your progress.']].map(([title, description]) => <Card key={title}>
        <h2>{title}</h2><p className="muted">{description}</p>
      </Card>)}
    </div>
  </>;
}
