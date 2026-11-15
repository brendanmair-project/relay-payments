import Link from "next/link";

import AiSection from "./AiSection";
import AnalyticsProvider from "./AnalyticsProvider";
import OpenIncident from "./OpenIncident";
import OutageControl from "./OutageControl";
import PaymentsList from "./PaymentsList";
import ProcessorHealthPanel from "./ProcessorHealthPanel";
import StoryMode from "./StoryMode";
import ValueStory from "./ValueStory";

// ADR-0018 order: the value story (problem, money saved), then the AI section, then the dense analyst console.
export default function Home() {
  return (
    <main>
      <a className="skip" href="#console">
        Skip to the payments console
      </a>
      <header className="top">
        <h1>Relay</h1>
        <p className="tagline">Payments console. Synthetic data only.</p>
        <nav aria-label="Pages">
          <Link href="/incidents">Incidents</Link> <Link href="/analytics">Analytics</Link>
        </nav>
      </header>
      <OutageControl />
      <StoryMode />
      <AnalyticsProvider>
        <ValueStory />
        <AiSection />
      </AnalyticsProvider>
      <div id="console" tabIndex={-1} className="console">
        <div className="console-grid">
          <ProcessorHealthPanel />
          <OpenIncident />
        </div>
        <PaymentsList />
      </div>
    </main>
  );
}
