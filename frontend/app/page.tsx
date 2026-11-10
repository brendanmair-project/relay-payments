import Link from "next/link";

import OutageControl from "./OutageControl";
import PaymentsList from "./PaymentsList";

export default function Home() {
  return (
    <main>
      <header>
        <h1>Relay</h1>
        <p>
          Payments console. Synthetic data only. <Link href="/incidents">Incidents</Link>{" "}
          <Link href="/analytics">Analytics</Link>
        </p>
      </header>
      <OutageControl />
      <PaymentsList />
    </main>
  );
}
