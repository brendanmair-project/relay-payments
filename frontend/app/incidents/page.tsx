import Link from "next/link";

import IncidentsList from "../IncidentsList";

export default function IncidentsPage() {
  return (
    <main>
      <header>
        <h1>Relay</h1>
        <p>
          <Link href="/">All payments</Link> <Link href="/analytics">Analytics</Link>
        </p>
      </header>
      <IncidentsList />
    </main>
  );
}
