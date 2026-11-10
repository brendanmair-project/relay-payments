"use client";

import { useEffect, useState } from "react";

import { FALLBACK_WORDS, formatAmount, formatTime, reasonText, statusLabel } from "./lib/format";
import type { Explanation, PaymentDetailData, ProcessorHealth } from "./lib/types";

type Load<T> = { state: "loading" } | { state: "error" } | { state: "ready"; data: T };
type PaymentLoad = Load<PaymentDetailData> | { state: "missing" };
type ExplanationLoad = Load<Explanation> | { state: "not_final" } | { state: "skipped" };

// Only failed outcomes and retried payments get an explanation; a first-attempt capture needs none.
function wantsExplanation(p: PaymentDetailData): boolean {
  return ["Declined", "Failed", "Retrying"].includes(statusLabel(p)) || p.attempt_no > 1;
}

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

export default function PaymentDetail({ id }: { id: string }) {
  const [payment, setPayment] = useState<PaymentLoad>({ state: "loading" });
  const [explanation, setExplanation] = useState<ExplanationLoad>({ state: "loading" });
  const [health, setHealth] = useState<Load<ProcessorHealth>>({ state: "loading" });
  const [paymentRun, setPaymentRun] = useState(0);
  const [explanationRun, setExplanationRun] = useState(0);

  useEffect(() => {
    let active = true;
    // Deferred a tick so the effect itself sets no state synchronously.
    const timer = setTimeout(() => {
      void (async () => {
        try {
          const { status, body } = await getJson(`/api/payments/${encodeURIComponent(id)}`);
          if (!active) return;
          if (status === 404) return setPayment({ state: "missing" });
          if (status >= 400) return setPayment({ state: "error" });
          setPayment({ state: "ready", data: body as PaymentDetailData });
        } catch {
          if (active) setPayment({ state: "error" });
        }
      })();
      void (async () => {
        try {
          const { status, body } = await getJson("/api/processors/health");
          if (active) setHealth(status < 400 ? { state: "ready", data: body as ProcessorHealth } : { state: "error" });
        } catch {
          if (active) setHealth({ state: "error" });
        }
      })();
    }, 0);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [id, paymentRun]);

  const loaded = payment.state === "ready" ? payment.data : null;
  const eligible = loaded !== null && wantsExplanation(loaded);

  useEffect(() => {
    if (loaded === null) return;
    let active = true;
    const timer = setTimeout(() => {
      if (!eligible) return setExplanation({ state: "skipped" });
      void (async () => {
        try {
          const { status, body } = await getJson(`/api/payments/${encodeURIComponent(id)}/explanation`);
          if (!active) return;
          if (status === 409) return setExplanation({ state: "not_final" });
          if (status >= 400) return setExplanation({ state: "error" });
          setExplanation({ state: "ready", data: body as Explanation });
        } catch {
          if (active) setExplanation({ state: "error" });
        }
      })();
    }, 0);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [id, loaded, eligible, explanationRun]);

  const retryPayment = () => {
    setPayment({ state: "loading" });
    setHealth({ state: "loading" });
    setExplanation({ state: "loading" });
    setPaymentRun((n) => n + 1);
  };
  const retryExplanation = () => {
    setExplanation({ state: "loading" });
    setExplanationRun((n) => n + 1);
  };

  if (payment.state === "loading") return <p className="note">Loading payment...</p>;
  if (payment.state === "missing")
    return <p className="note">Payment not found. Check the id or return to the list.</p>;
  if (payment.state === "error")
    return (
      <div className="note">
        <p>Could not load this payment.</p>
        <button type="button" onClick={retryPayment}>
          Retry
        </button>
      </div>
    );

  const p = payment.data;
  const events = [...p.events].sort((a, b) => a.seq - b.seq);
  const attemptNos = [...new Set(events.map((e) => e.attempt_no).filter((n) => n > 0))].sort((a, b) => a - b);
  const processorOf = (n: number) => events.find((e) => e.attempt_no === n && e.processor)?.processor ?? null;
  // An attempt's outcome is its last state event; later events of the same attempt (retry_scheduled, final,
  // explained) describe the payment, not that attempt.
  const OUTCOMES = ["payment.authorized", "payment.captured", "payment.declined", "payment.failed"];
  const outcomeOf = (n: number) => events.filter((e) => e.attempt_no === n && OUTCOMES.includes(e.type)).at(-1);

  return (
    <article>
      <div className="bar">
        <h2 className="mono">{p.id}</h2>
        <p className="mono">
          <span>{formatAmount(p.amount_minor, p.currency)}</span>{" "}
          <span className={`status status-${statusLabel(p).toLowerCase()}`}>{statusLabel(p)}</span>
        </p>
      </div>

      <section aria-label="Attempts">
        <h3>Attempts</h3>
        {attemptNos.length === 0 ? (
          <p className="note">Not routed yet.</p>
        ) : (
          <ul>
            {attemptNos.map((n) => (
              <li key={n} className="mono">
                {`Attempt ${n} on processor ${processorOf(n) ?? "-"}: ${
                  outcomeOf(n)?.type.replace("payment.", "") ?? "in progress"
                }${outcomeOf(n)?.reason ? ` (${outcomeOf(n)?.reason})` : ""}`}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Explanation">
        <h3>Explanation</h3>
        <ExplanationView state={explanation} onRetry={retryExplanation} />
      </section>

      <section aria-label="Processor health">
        <h3>Processor health</h3>
        {health.state === "loading" && <p className="note">Loading processor health...</p>}
        {health.state === "error" && <p className="note">Processor health is unavailable right now.</p>}
        {health.state === "ready" && (
          <ul>
            {health.data.processors.map((h) => (
              <li key={h.name} className="mono">
                {`Processor ${h.name}: ${h.state.charAt(0).toUpperCase()}${h.state.slice(1)}, error rate ${Math.round(
                  h.error_rate * 100,
                )}% (${h.errors} of ${h.attempts} attempts in ${health.data.window_seconds} s)`}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Timeline">
        <h3>Timeline</h3>
        <ol aria-label="Payment timeline">
          {events.map((e) => (
            <li key={e.seq} className="mono">
              {`${formatTime(e.occurred_at)} #${e.seq} ${e.type}${e.processor ? ` processor ${e.processor}` : ""}${reasonText(e.type, e.reason)}`}
            </li>
          ))}
        </ol>
      </section>
    </article>
  );
}

function ExplanationView({ state, onRetry }: { state: ExplanationLoad; onRetry: () => void }) {
  switch (state.state) {
    case "loading":
      return <p className="note">Generating the explanation. This can take a few seconds.</p>;
    case "skipped":
      return <p className="note">No explanation needed: the payment was captured on the first attempt.</p>;
    case "not_final":
      return <p className="note">Explanation after the payment finishes.</p>;
    case "error":
      return (
        <div className="note">
          <p>Could not load the explanation.</p>
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
        </>
      );
    }
  }
}
