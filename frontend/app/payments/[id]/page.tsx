import Link from "next/link";

import PaymentDetail from "../../PaymentDetail";

export default async function PaymentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <main>
      <header>
        <h1>Relay</h1>
        <p>
          <Link href="/">All payments</Link>
        </p>
      </header>
      <PaymentDetail id={id} />
    </main>
  );
}
