"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { formatTime } from "./lib/format";
import type { Incident } from "./lib/types";

const REFRESH_MS = 5000;

export const SOURCE_WORDS: Record<string, string> = { rule: "Rule", manual: "Manual" };

export function statusWord(status: string): string {
  return `${status.charAt(0).toUpperCase()}${status.slice(1)}`;
}

export default function IncidentsList({ intervalMs = REFRESH_MS }: { intervalMs?: number }) {
  const [items, setItems] = useState<Incident[] | null>(null);
  const [failed, setFailed] = useState(false);
  const active = useRef(true);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/incidents?limit=20", { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      const data = (await res.json()) as { items: Incident[] };
      if (!active.current) return;
      setItems(data.items);
      setFailed(false);
    } catch {
      if (active.current) setFailed(true);
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
    <section aria-labelledby="incidents-heading">
      <div className="bar">
        <h2 id="incidents-heading">Incidents</h2>
        <p role="status" className="mono">
          {failed ? "Error" : items === null ? "Loading" : `${items.length} shown`}
        </p>
      </div>
      {failed && <p className="banner">Could not load incidents. Retrying every 5 seconds.</p>}
      <div className="scroll" tabIndex={0} role="region" aria-label="Incidents table">
        {items === null ? (
          <p className="note">{failed ? "No data yet." : "Loading incidents..."}</p>
        ) : items.length === 0 ? (
          <p className="note">No incidents yet. Start the Processor A outage to open one.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th scope="col">Incident</th>
                <th scope="col">Status</th>
                <th scope="col">Processor</th>
                <th scope="col">Source</th>
                <th scope="col">Opened (UTC)</th>
                <th scope="col">Recovered (UTC)</th>
                <th scope="col">Resolved (UTC)</th>
                <th scope="col" className="num">
                  Affected
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.id}>
                  <td>
                    <Link href={`/incidents/${i.id}`}>{i.title}</Link>
                  </td>
                  <td>
                    <span className={`status status-${i.status}`}>{statusWord(i.status)}</span>
                  </td>
                  <td className="mono">{i.processor ?? <span aria-label="no processor">-</span>}</td>
                  <td>{SOURCE_WORDS[i.source] ?? i.source}</td>
                  <td className="mono">{formatTime(i.opened_at)}</td>
                  <td className="mono">{formatTime(i.recovered_at)}</td>
                  <td className="mono">{formatTime(i.resolved_at)}</td>
                  <td className="mono num">{i.affected_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
