"use client";

import { useEffect, useState } from "react";

type Snapshot = { processors: { a: { outage: boolean } } };

function readOutage(body: unknown): boolean | null {
  const outage = (body as Snapshot | null)?.processors?.a?.outage;
  return typeof outage === "boolean" ? outage : null;
}

// Demo control: talks only to /api/demo/*; the API key stays on the server.
export default function OutageControl() {
  const [active, setActive] = useState<boolean | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/demo/state")
      .then(async (res) => {
        const outage = res.ok ? readOutage(await res.json()) : null;
        if (cancelled) return;
        if (outage === null) setError("Could not read the outage state.");
        else setActive(outage);
      })
      .catch(() => {
        if (!cancelled) setError("Could not read the outage state.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function toggle() {
    const enabled = !active;
    setPending(true);
    setError(null);
    try {
      const res = await fetch("/api/demo/outage", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      const outage = res.ok ? readOutage(await res.json()) : null;
      if (outage === null) setError("Could not change the outage. The state shown is the last known one.");
      else setActive(outage);
    } catch {
      setError("Could not change the outage. The state shown is the last known one.");
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label="Demo controls" className="bar">
      <p role="status" className="mono">
        Processor A outage: {active === null ? "Unknown" : active ? "Active" : "Inactive"}
      </p>
      <button type="button" onClick={toggle} disabled={pending || active === null}>
        {active ? "Stop Processor A outage" : "Start Processor A outage"}
      </button>
      {error && (
        <p role="alert" className="banner">
          {error}
        </p>
      )}
    </section>
  );
}
