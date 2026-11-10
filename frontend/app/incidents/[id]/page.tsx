import Link from "next/link";

import IncidentDetail from "../../IncidentDetail";

export default async function IncidentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <main>
      <header>
        <h1>Relay</h1>
        <p>
          <Link href="/incidents">All incidents</Link>
        </p>
      </header>
      <IncidentDetail id={id} />
    </main>
  );
}
