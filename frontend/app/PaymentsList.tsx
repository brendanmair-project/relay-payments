"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { formatAmount, formatTime, statusLabel } from "./lib/format";
import type { Payment } from "./lib/types";

const REFRESH_MS = 5000;
const STALE_MS = 15000;

export default function PaymentsList({ intervalMs = REFRESH_MS }: { intervalMs?: number }) {
  const [items, setItems] = useState<Payment[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const active = useRef(true);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/payments?limit=20", { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      const data = (await res.json()) as { items: Payment[] };
      if (!active.current) return;
      setItems(data.items);
      setFailed(false);
      setUpdatedAt(Date.now());
    } catch {
      if (active.current) setFailed(true);
    }
    if (active.current) setNow(Date.now());
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

  const stale = !failed && updatedAt !== null && now - updatedAt >= STALE_MS;
  const state = failed ? "Error" : stale ? "Stale" : updatedAt === null ? "Loading" : "Live";
  const retrying = (items ?? []).filter((p) => statusLabel(p) === "Retrying").length;

  return (
    <section aria-labelledby="payments-heading">
      <div className="bar">
        <h2 id="payments-heading">Latest payments</h2>
        <p role="status" className="mono">
          {state}
          {updatedAt !== null && ` | Last updated: ${formatTime(new Date(updatedAt).toISOString()).slice(11)}`}
          {items !== null && ` | Retrying: ${retrying}`}
        </p>
      </div>
      {failed && (
        <p className="banner">Could not load payments. Showing the last data if any. Retrying every 5 seconds.</p>
      )}
      <div className="scroll" tabIndex={0} role="region" aria-label="Payments table">
        {items === null ? (
          <p className="note">{failed ? "No data yet." : "Loading payments..."}</p>
        ) : items.length === 0 ? (
          <p className="note">No payments yet. Run the load generator to create synthetic payments.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th scope="col">Payment</th>
                <th scope="col">Status</th>
                <th scope="col">Processor</th>
                <th scope="col" className="num">
                  Amount
                </th>
                <th scope="col" className="num">
                  Attempt
                </th>
                <th scope="col">Changed (UTC)</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id}>
                  <td className="mono">
                    <Link href={`/payments/${p.id}`}>{p.id}</Link>
                  </td>
                  <td>
                    <span className={`status status-${statusLabel(p).toLowerCase()}`}>{statusLabel(p)}</span>
                  </td>
                  <td className="mono">{p.processor ?? <span aria-label="not routed yet">-</span>}</td>
                  <td className="mono num">{formatAmount(p.amount_minor, p.currency)}</td>
                  <td className="mono num">{p.attempt_no}</td>
                  <td className="mono">{formatTime(p.status_changed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
