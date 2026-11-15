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
  const [storyActive, setStoryActive] = useState(false);
  const [reload, setReload] = useState(0);

  // The story run (StoryMode) switches the outage itself, so the manual toggle steps aside while it runs and the
  // state is read again once it ends.
  useEffect(() => {
    const onStory = (e: Event) => {
      const running = (e as CustomEvent<{ active: boolean }>).detail.active;
      setStoryActive((was) => {
        if (was && !running) setReload((n) => n + 1);
        return running;
      });
    };
    window.addEventListener("relay:story", onStory);
    return () => window.removeEventListener("relay:story", onStory);
  }, []);

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
  }, [reload]);

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
      <button type="button" onClick={toggle} disabled={pending || active === null || storyActive}>
        {active ? "Stop Processor A outage" : "Start Processor A outage"}
      </button>
      {storyActive && (
        <p className="fine-dark">
          The outage demo is running and controls the outage; this switch is read-only until it ends.
        </p>
      )}
      {error && (
        <p role="alert" className="banner">
          {error}
        </p>
      )}
    </section>
  );
}
