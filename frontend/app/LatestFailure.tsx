"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import ExplanationPanel from "./ExplanationPanel";
import { formatAmount } from "./lib/format";
import type { Explanation, Payment } from "./lib/types";

const REFRESH_MS = 10000;
const FAILURES = ["Declined", "Failed"];

type Shown =
  | { state: "loading" }
  | { state: "none" }
  | { state: "error" }
  | { state: "ready"; payment: Payment; explanation: Explanation };

// One real failure, with the AI panel (REL-63): the newest final Declined or Failed payment in the latest 20.
export default function LatestFailure({ intervalMs = REFRESH_MS }: { intervalMs?: number }) {
  const [shown, setShown] = useState<Shown>({ state: "loading" });
  const active = useRef(true);
  const current = useRef<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/payments?limit=20", { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      const { items } = (await res.json()) as { items: Payment[] };
      if (!active.current) return;
      const failure = items.find((p) => p.is_final && FAILURES.includes(p.display_status));
      if (!failure) {
        current.current = null;
        setShown({ state: "none" });
        return;
      }
      if (failure.id === current.current) return;
      const exp = await fetch(`/api/payments/${encodeURIComponent(failure.id)}/explanation`, { cache: "no-store" });
      if (!exp.ok) throw new Error(String(exp.status));
      const explanation = (await exp.json()) as Explanation;
      if (!active.current) return;
      current.current = failure.id;
      setShown({ state: "ready", payment: failure, explanation });
    } catch {
      if (active.current) setShown((prev) => (prev.state === "ready" ? prev : { state: "error" }));
    }
  }, []);

  useEffect(() => {
    active.current = true;
    // Deferred a tick so the effect itself sets no state synchronously.
    const first = setTimeout(() => void load(), 0);
    const timer = setInterval(() => void load(), intervalMs);
    return () => {
      active.current = false;
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [load, intervalMs]);

  return (
    <section aria-labelledby="failure-heading" className="failure">
      <h3 id="failure-heading">One failure, explained</h3>
      {shown.state === "loading" && <p className="note">Looking for a failed payment...</p>}
      {shown.state === "none" && (
        <p className="note">No failed payment to explain yet. Start the Processor A outage to create some.</p>
      )}
      {shown.state === "error" && <p className="note">Could not load the explanation. Retrying every 10 seconds.</p>}
      {shown.state === "ready" && (
        <>
          <p className="mono">
            <Link href={`/payments/${shown.payment.id}`}>{shown.payment.id}</Link>
            {` ${formatAmount(shown.payment.amount_minor, shown.payment.currency)} ${shown.payment.display_status}`}
          </p>
          <p className="quote">{shown.explanation.text}</p>
          <ExplanationPanel explanation={shown.explanation} />
        </>
      )}
    </section>
  );
}
