"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { Payment, ProcessorHealth } from "./lib/types";

const POLL_MS = 1000;
const FAILURES = ["Declined", "Failed"];

type Run = {
  state: string;
  phase: string | null;
  sent: number;
  total: number;
  switches: { processor: string; outage: boolean; at: string }[];
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
};

// What the console's own data adds to the run state; each fact latches for the rest of the run.
type Seen = { avoided: boolean; explained: boolean };

function readRun(body: unknown): Run | null {
  const b = body as Partial<Run> | null;
  return b && typeof b.state === "string" && typeof b.sent === "number" ? (b as Run) : null;
}

// One caption per moment, from the run's state (phase and switches) and what the console shows: A avoided in the
// processor health, a stored explanation for a failure after the outage began. Never from a timer.
export function captionFor(run: Run, seen: Seen): string {
  switch (run.state) {
    case "finished":
      return "Money recovered";
    case "stopping":
      return "Stopping the demo";
    case "stopped":
      return "Demo stopped";
    case "failed":
      return "Demo run failed";
    case "running":
      break;
    default:
      return "";
  }
  if (run.phase === "outage") {
    if (seen.explained) return "Explanations arriving";
    return seen.avoided ? "Relay routing to Processor B" : "Processor A failing";
  }
  if (run.phase === "recovering") return seen.explained ? "Explanations arriving" : "Relay routing to Processor B";
  return "Payments flowing";
}

const isActive = (run: Run | null) => run !== null && (run.state === "running" || run.state === "stopping");

// One-click outage story (REL-66): starts, follows and stops the simulator's seeded run through /api/demo/run.
// The API key stays on the server (ADR-0009, ADR-0012).
export default function StoryMode({ intervalMs = POLL_MS }: { intervalMs?: number }) {
  const [run, setRun] = useState<Run | null>(null);
  const [seen, setSeen] = useState<Seen>({ avoided: false, explained: false });
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const mounted = useRef(true);
  const startedAt = useRef<string | null>(null);
  const seenRef = useRef<Seen>(seen);

  const remember = useCallback((next: Seen) => {
    seenRef.current = next;
    setSeen(next);
  }, []);

  const apply = useCallback(
    (next: Run) => {
      if (!mounted.current) return;
      if (next.started_at !== startedAt.current) {
        startedAt.current = next.started_at;
        remember({ avoided: false, explained: false });
      }
      setRun(next);
    },
    [remember],
  );

  const look = useCallback(
    async (next: Run) => {
      const outageAt = next.switches.find((s) => s.outage)?.at;
      if (!outageAt || (next.phase !== "outage" && next.phase !== "recovering")) return;
      let current = seenRef.current;
      if (!current.avoided) {
        const res = await fetch("/api/processors/health", { cache: "no-store" });
        if (res.ok) {
          const health = (await res.json()) as ProcessorHealth;
          if (health.processors.some((p) => p.name === "A" && p.state === "avoided"))
            current = { ...current, avoided: true };
        }
      }
      if (current.avoided && !current.explained) {
        const res = await fetch("/api/payments?limit=20", { cache: "no-store" });
        if (res.ok) {
          const { items } = (await res.json()) as { items: Payment[] };
          const failure = items.find(
            (p) => p.is_final && FAILURES.includes(p.display_status) && p.final_at !== null && p.final_at >= outageAt,
          );
          if (failure) {
            const exp = await fetch(`/api/payments/${encodeURIComponent(failure.id)}/explanation`, {
              cache: "no-store",
            });
            if (exp.ok) current = { ...current, explained: true };
          }
        }
      }
      if (mounted.current && current !== seenRef.current) remember(current);
    },
    [remember],
  );

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/demo/run", { cache: "no-store" });
      const next = res.ok ? readRun(await res.json()) : null;
      if (!next) throw new Error("status");
      apply(next);
      await look(next);
    } catch {
      /* A missed poll changes nothing; the next one tries again. */
    }
  }, [apply, look]);

  useEffect(() => {
    mounted.current = true;
    // Deferred a tick so the effect itself sets no state synchronously.
    const first = setTimeout(() => void refresh(), 0);
    return () => {
      mounted.current = false;
      clearTimeout(first);
    };
  }, [refresh]);

  const active = isActive(run);
  useEffect(() => {
    window.dispatchEvent(new CustomEvent("relay:story", { detail: { active } }));
    if (!active) return;
    const timer = setInterval(() => void refresh(), intervalMs);
    return () => clearInterval(timer);
  }, [active, intervalMs, refresh]);

  async function start() {
    setPending(true);
    setError(null);
    try {
      const res = await fetch("/api/demo/run", { method: "POST" });
      const body = await res.json().catch(() => null);
      const next = res.ok ? readRun(body) : null;
      if (next) apply(next);
      else if (res.status === 409) {
        setError("A demo run is already running.");
        await refresh();
      } else setError("Could not start the demo run.");
    } catch {
      setError("Could not start the demo run.");
    } finally {
      setPending(false);
    }
  }

  async function stop() {
    setPending(true);
    setError(null);
    try {
      const res = await fetch("/api/demo/run", { method: "DELETE" });
      const next = res.ok ? readRun(await res.json()) : null;
      if (next) apply(next);
      else setError("Could not stop the demo run.");
    } catch {
      setError("Could not stop the demo run.");
    } finally {
      setPending(false);
    }
  }

  const caption = run ? captionFor(run, seen) : "";
  return (
    <section aria-label="Outage story" className="bar">
      <button type="button" onClick={() => void start()} disabled={pending || active}>
        Run the outage demo
      </button>
      {active && (
        <button type="button" onClick={() => void stop()} disabled={pending || run?.state === "stopping"}>
          Stop the demo
        </button>
      )}
      <p role="status" aria-label="Story step" aria-live="polite" className="mono">
        {caption}
      </p>
      {active && run && <p className="fine-dark mono">{`Payment ${run.sent} of ${run.total}`}</p>}
      {run?.state === "finished" && (
        <p className="fine-dark">See Revenue recovered in the Money saved headline below for what Relay rescued.</p>
      )}
      {run?.state === "failed" && run.error_code && <p className="fine-dark mono">{`Reason: ${run.error_code}`}</p>}
      {error && (
        <p role="alert" className="banner">
          {error}
        </p>
      )}
    </section>
  );
}
