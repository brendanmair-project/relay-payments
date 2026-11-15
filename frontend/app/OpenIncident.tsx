"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { statusWord } from "./IncidentsList";
import { FALLBACK_WORDS, formatTime } from "./lib/format";
import type { Incident, IncidentSummary } from "./lib/types";

const REFRESH_MS = 5000;

type Summary = { state: "loading" } | { state: "error" } | { state: "ready"; data: IncidentSummary };

// The newest incident that is not resolved, with its AI summary (REL-36 summary route; the model runs locally).
export default function OpenIncident({ intervalMs = REFRESH_MS }: { intervalMs?: number }) {
  const [incident, setIncident] = useState<Incident | null | undefined>(undefined);
  const [failed, setFailed] = useState(false);
  const [summary, setSummary] = useState<Summary>({ state: "loading" });
  const active = useRef(true);
  const summaryFor = useRef<string | null>(null);

  const loadSummary = useCallback(async (id: string) => {
    summaryFor.current = id;
    setSummary({ state: "loading" });
    try {
      const res = await fetch(`/api/incidents/${encodeURIComponent(id)}/summary`, { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      const data = (await res.json()) as IncidentSummary;
      if (active.current && summaryFor.current === id) setSummary({ state: "ready", data });
    } catch {
      if (active.current && summaryFor.current === id) setSummary({ state: "error" });
    }
  }, []);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/incidents?limit=20", { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      const { items } = (await res.json()) as { items: Incident[] };
      if (!active.current) return;
      const open = items.find((i) => i.status !== "resolved") ?? null;
      setIncident(open);
      setFailed(false);
      if (open === null) summaryFor.current = null;
      else if (summaryFor.current !== open.id) void loadSummary(open.id);
    } catch {
      if (active.current) setFailed(true);
    }
  }, [loadSummary]);

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
    <section aria-labelledby="incident-heading" className="card">
      <div className="bar">
        <h2 id="incident-heading">Open incident</h2>
      </div>
      {incident === undefined ? (
        <p className="note">
          {failed ? "Could not load incidents. Retrying every 5 seconds." : "Loading incidents..."}
        </p>
      ) : (
        <>
          {failed && (
            <p className="banner">Could not load incidents. Showing the last data. Retrying every 5 seconds.</p>
          )}
          {incident === null ? (
            <p className="note">No open incident. Start the Processor A outage to open one.</p>
          ) : (
            <>
              <p>
                <Link href={`/incidents/${incident.id}`}>{incident.title}</Link>{" "}
                <span className={`status status-${incident.status}`}>{statusWord(incident.status)}</span>
              </p>
              <p className="mono fine-dark">
                {`Opened ${formatTime(incident.opened_at)} | Recovered ${formatTime(incident.recovered_at)} | ${incident.affected_count} ${incident.affected_count === 1 ? "payment" : "payments"} affected`}
              </p>
              {summary.state === "loading" && (
                <p className="note">Generating the AI summary. This can take a few seconds.</p>
              )}
              {summary.state === "error" && <p className="note">Could not load the AI summary.</p>}
              {summary.state === "ready" && (
                <>
                  <p className="fine-dark">
                    {summary.data.source === "model"
                      ? `AI summary (model: ${summary.data.model ?? "unknown"})`
                      : "AI summary (rule-based)"}
                  </p>
                  <p className="quote">{summary.data.text}</p>
                  {summary.data.fallback_reason && (
                    <p className="fine-dark">{`Why rules text: ${FALLBACK_WORDS[summary.data.fallback_reason] ?? summary.data.fallback_reason}.`}</p>
                  )}
                </>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
