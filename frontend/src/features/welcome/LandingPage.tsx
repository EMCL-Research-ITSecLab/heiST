import { Card } from '../../components/ui.tsx';
import { Link } from '../../lib/router.tsx';
export function Landing() { return <>
    <section className="hero">
      <div>
        <p className="eyebrow">HEIDELBERG SECURITY TRAINING</p>
        <h1>Curiosity is<br />your best exploit.</h1>
        <p>A place to investigate, experiment and build real security skills. Find your next challenge. Make the environment your own.</p>
        <div className="button-row">
          <Link className="button" href="/explore">Explore the labs <span>↗</span>
          </Link>
          <Link className="button secondary" href="/signup">Join heiST</Link>
        </div>
        <div className="hero-caption">
          <span className="status-dot"/>Purpose-built environments. Practical learning.</div>
      </div>
      <div className="hero-workbench" aria-hidden>
        <div className="terminal-toolbar">
          <i />
          <i />
          <i />
          <span>investigation / workspace</span>
        </div>
        <div className="workbench-code">
          <span>01 <b>observe</b> the unexpected</span>
          <span>02 <b>question</b> your assumptions</span>
          <span>03 <b>test</b> a hypothesis</span>
          <span>04 <b>discover</b> something new</span>
        </div>
        <div className="workbench-bottom">
          <span>YOUR NEXT BREAKTHROUGH</span>
          <strong>starts with a question<span>_</span>
          </strong>
        </div>
      </div>
    </section>
    <div className="feature-grid">
      {[['01', 'Choose your investigation', 'From identity systems to web security, find a challenge that sparks your interest.'], ['02', 'Make it practical', 'Connect to an isolated environment and work with real systems and services.'], ['03', 'See your progress', 'Submit flags, earn points and build a record of what you’ve learned.']].map(([index, title, description]) => <Card key={index}>
        <span className="feature-number">
          {index}
        </span>
        <h2>
          {title}
        </h2>
        <p className="muted">
          {description}
        </p>
      </Card>)}
    </div>
  </>; }
