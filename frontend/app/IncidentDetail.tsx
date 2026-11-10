"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { statusWord } from "./IncidentsList";
import { FALLBACK_WORDS, formatAmount, formatTime, reasonText } from "./lib/format";
import type { IncidentDetailData, IncidentSummary } from "./lib/types";

type Load<T> = { state: "loading" } | { state: "error" } | { state: "ready"; data: T };
type IncidentLoad = Load<IncidentDetailData> | { state: "missing" };

const NEXT_ACTION = {
  detected: { to: "triaged", label: "Triage" },
  triaged: { to: "resolved", label: "Resolve" },
} as const;
const PAGE_SIZE = 20;
const SOURCE_TEXT = { rule: "Detected by the router rule", manual: "Opened by hand" } as const;

async function getJson(url: string): Promise<{ status: number; body: unknown }> {
  const res = await fetch(url, { cache: "no-store" });
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  return { status: res.status, body };
}

function errorText(body: unknown, fallback: string): string {
  const message = (body as { error?: { message?: unknown } } | null)?.error?.message;
  return typeof message === "string" && message ? message : fallback;
}

async function post(url: string, body?: unknown): Promise<{ ok: boolean; body: unknown }> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let parsed: unknown = null;
  try {
    parsed = await res.json();
  } catch {
    parsed = null;
  }
  return { ok: res.ok, body: parsed };
}

export default function IncidentDetail({ id }: { id: string }) {
  const [incident, setIncident] = useState<IncidentLoad>({ state: "loading" });
  const [summary, setSummary] = useState<Load<IncidentSummary>>({ state: "loading" });
  const [run, setRun] = useState(0);
  const [summaryRun, setSummaryRun] = useState(0);
  const [pending, setPending] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [page, setPage] = useState(0);

  useEffect(() => {
    let active = true;
    // Deferred a tick so the effect itself sets no state synchronously.
    const timer = setTimeout(() => {
      void (async () => {
        try {
          const { status, body } = await getJson(`/api/incidents/${encodeURIComponent(id)}`);
          if (!active) return;
          if (status === 404) return setIncident({ state: "missing" });
          if (status >= 400) return setIncident({ state: "error" });
          setIncident({ state: "ready", data: body as IncidentDetailData });
        } catch {
          if (active) setIncident({ state: "error" });
        }
      })();
    }, 0);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [id, run]);

  useEffect(() => {
    let active = true;
    const timer = setTimeout(() => {
      void (async () => {
        try {
          const { status, body } = await getJson(`/api/incidents/${encodeURIComponent(id)}/summary`);
          if (!active) return;
          setSummary(status < 400 ? { state: "ready", data: body as IncidentSummary } : { state: "error" });
        } catch {
          if (active) setSummary({ state: "error" });
        }
      })();
    }, 0);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [id, summaryRun]);

  async function move(to: string) {
    setPending(to);
    setActionError(null);
    try {
      const result = await post(`/api/incidents/${encodeURIComponent(id)}/transitions`, { to });
      if (result.ok) setRun((n) => n + 1);
      else setActionError(errorText(result.body, "Could not change the incident. Reload to see its current state."));
    } catch {
      setActionError("Could not reach the server. Try again.");
    } finally {
      setPending(null);
    }
  }

  async function regenerate() {
    setPending("regenerate");
    setActionError(null);
    try {
      const result = await post(`/api/incidents/${encodeURIComponent(id)}/summary/regenerate`);
      if (result.ok) setSummary({ state: "ready", data: result.body as IncidentSummary });
      else setActionError(errorText(result.body, "Could not regenerate the summary."));
    } catch {
      setActionError("Could not reach the server. Try again.");
    } finally {
      setPending(null);
    }
  }

  if (incident.state === "loading") return <p className="note">Loading incident...</p>;
  if (incident.state === "missing")
    return <p className="note">Incident not found. Check the id or return to the list.</p>;
  if (incident.state === "error")
    return (
      <div className="note">
        <p>Could not load this incident.</p>
        <button type="button" onClick={() => setRun((n) => n + 1)}>
          Retry
        </button>
      </div>
    );

  const i = incident.data;
  const action = i.status === "resolved" ? null : NEXT_ACTION[i.status];
  const total = i.affected_payments.length;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const first = current * PAGE_SIZE;
  const visible = i.affected_payments.slice(first, first + PAGE_SIZE);

  return (
    <article>
      <div className="bar">
        <h2>{i.title}</h2>
        <p className="mono">
          <span className={`status status-${i.status}`}>{statusWord(i.status)}</span>
        </p>
      </div>
      <p className="mono">{`${SOURCE_TEXT[i.source]} | Processor ${i.processor ?? "-"} | Opened ${formatTime(i.opened_at)}`}</p>
      <p className="mono">{`Triaged ${formatTime(i.triaged_at)} | Recovered ${formatTime(i.recovered_at)} | Resolved ${formatTime(i.resolved_at)}`}</p>

      {action && (
        <p>
          <button type="button" onClick={() => void move(action.to)} disabled={pending !== null}>
            {pending === action.to ? `${action.label}...` : action.label}
          </button>
        </p>
      )}
      {actionError && (
        <p role="alert" className="banner">
          {actionError}
        </p>
      )}

      <section aria-label="Summary">
        <h3>Summary</h3>
        <SummaryView
          state={summary}
          pending={pending === "regenerate"}
          onRegenerate={() => void regenerate()}
          onRetry={() => {
            setSummary({ state: "loading" });
            setSummaryRun((n) => n + 1);
          }}
        />
      </section>

      <section aria-label="Affected payments">
        <h3>{`Affected payments (${i.affected_payments.length})`}</h3>
        {i.affected_payments.length === 0 ? (
          <p className="note">No payments are linked to this incident.</p>
        ) : (
          <>
            <ul>
              {visible.map((p) => (
                <li key={p.id}>
                  <p className="mono">
                    <Link href={`/payments/${p.id}`}>{p.id}</Link>
                    {` ${formatAmount(p.amount_minor, p.currency)} ${p.status} processor ${p.processor ?? "-"}`}
                  </p>
                  <details>
                    <summary aria-label={`Events of payment ${p.id} (${p.events.length})`}>
                      {`Events (${p.events.length})`}
                    </summary>
                    <ul aria-label={`Events of payment ${p.id}`}>
                      {p.events.map((e) => (
                        <li key={e.id} className="mono">
                          {`${formatTime(e.occurred_at)} #${e.id} ${e.type}${e.processor ? ` processor ${e.processor}` : ""}${reasonText(e.type, e.reason)}`}
                        </li>
                      ))}
                    </ul>
                  </details>
                </li>
              ))}
            </ul>
            {pages > 1 && (
              <div className="bar">
                <button type="button" onClick={() => setPage(current - 1)} disabled={current === 0}>
                  Previous page
                </button>
                <p role="status" className="mono">
                  {`Page ${current + 1} of ${pages}, payments ${first + 1} to ${first + visible.length} of ${total}`}
                </p>
                <button type="button" onClick={() => setPage(current + 1)} disabled={current >= pages - 1}>
                  Next page
                </button>
              </div>
            )}
          </>
        )}
      </section>
    </article>
  );
}

function SummaryView({
  state,
  pending,
  onRegenerate,
  onRetry,
}: {
  state: Load<IncidentSummary>;
  pending: boolean;
  onRegenerate: () => void;
  onRetry: () => void;
}) {
  switch (state.state) {
    case "loading":
      return <p className="note">Generating the summary. This can take a few seconds.</p>;
    case "error":
      return (
        <div className="note">
          <p>Could not load the summary.</p>
          <button type="button" onClick={onRetry}>
            Retry
          </button>
        </div>
      );
    case "ready": {
      const x = state.data;
      const label = x.source === "model" ? `Model: ${x.model ?? "unknown"}` : "Rule-based";
      return (
        <>
          <p>{x.text}</p>
          <p className="mono">{`${label} | Generated ${formatTime(x.generated_at)}`}</p>
          {x.fallback_reason && (
            <p className="mono">{`Why rules text: ${FALLBACK_WORDS[x.fallback_reason] ?? x.fallback_reason}.`}</p>
          )}
          <button type="button" onClick={onRegenerate} disabled={pending}>
            {pending ? "Regenerating..." : "Regenerate summary"}
          </button>
        </>
      );
    }
  }
}
