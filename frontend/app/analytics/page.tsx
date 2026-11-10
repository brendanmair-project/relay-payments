import Link from "next/link";

import AnalyticsView from "../AnalyticsView";

export default function AnalyticsPage() {
  return (
    <main>
      <header>
        <h1>Relay</h1>
        <p>
          <Link href="/">All payments</Link> <Link href="/incidents">Incidents</Link>
        </p>
      </header>
      <AnalyticsView />
    </main>
  );
}
