"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { ProcessorHealth } from "./lib/types";

const REFRESH_MS = 5000;

// Status is a word plus a glyph and a border style, never colour alone (AGENTS.md).
const STATE_GLYPH: Record<string, string> = { preferred: "✓", avoided: "⛔", unknown: "○" };
const word = (s: string) => `${s.charAt(0).toUpperCase()}${s.slice(1)}`;

function failoverText(h: ProcessorHealth): string {
  if (h.strategy === "static") return "Static routing is on: every payment goes to Processor A and nothing fails over.";
  const avoided = h.processors.filter((p) => p.state === "avoided").map((p) => p.name);
  const window = `error rate above ${Math.round(h.error_threshold * 100)}% in the ${h.window_seconds} s window`;
  if (avoided.length === 0) return "No failover: no processor is avoided, so new payments go to Processor A.";
  if (avoided.length >= 2)
    return `Both processors are avoided (${window}): new payments stay on Processor A and are retried on Processor B.`;
  if (avoided[0] === "A")
    return `Failover active: new payments go to Processor B while Processor A is avoided (${window}).`;
  return `Processor ${avoided[0]} is avoided (${window}): new payments stay on Processor A.`;
}

export default function ProcessorHealthPanel({ intervalMs = REFRESH_MS }: { intervalMs?: number }) {
  const [health, setHealth] = useState<ProcessorHealth | null>(null);
  const [failed, setFailed] = useState(false);
  const active = useRef(true);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/processors/health", { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      const body = (await res.json()) as ProcessorHealth;
      if (!active.current) return;
      setHealth(body);
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

  // Missing data is unknown, not healthy: after a failed read nothing is shown as a state.
  const usable = health !== null && !failed;
  return (
    <section aria-labelledby="health-heading" className="card">
      <div className="bar">
        <h2 id="health-heading">Processor health</h2>
      </div>
      {!usable ? (
        <p className="note">{failed ? "Processor health is unavailable right now." : "Loading processor health..."}</p>
      ) : (
        <>
          <p
            role="status"
            aria-label="Failover state"
            className={`failover${health.processors.some((p) => p.state === "avoided") ? " failover-on" : ""}`}
          >
            {failoverText(health)}
          </p>
          <div className="procs">
            {health.processors.map((p) => (
              <div key={p.name} role="group" aria-label={`Processor ${p.name}`} className={`proc proc-${p.state}`}>
                <strong>{`Processor ${p.name}`}</strong>
                <span className={`state state-${p.state}`}>
                  <span aria-hidden="true">{STATE_GLYPH[p.state] ?? "○"}</span> {word(p.state)}
                </span>
                <span className="mono">{`${p.errors} of ${p.attempts} attempts failed (${Math.round(p.error_rate * 100)}%)`}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
