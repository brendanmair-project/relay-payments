"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { FALLBACK_WORDS, formatAmount } from "./lib/format";
import type { AnalyticsData, BaselineData, Percentiles } from "./lib/types";

const REFRESH_MS = 10000;
const HOUR_MS = 3_600_000;

export const RANGES = [
  { value: "1h", label: "Last hour", ms: HOUR_MS },
  { value: "24h", label: "Last 24 hours", ms: 24 * HOUR_MS },
  { value: "7d", label: "Last 7 days", ms: 7 * 24 * HOUR_MS },
  { value: "31d", label: "Last 31 days", ms: 31 * 24 * HOUR_MS },
] as const;

const PATH_WORDS: Record<string, string> = { retry: "Retry", failover: "Failover", redrive: "Redrive" };

const pct = (rate: number | null) => (rate === null ? "-" : `${(rate * 100).toFixed(1)}%`);
const ms = (value: number | null | undefined) =>
  value === null || value === undefined ? "-" : `${Math.round(value * 10) / 10} ms`;

function money(byCurrency: Record<string, number>): string {
  const parts = Object.entries(byCurrency).map(([currency, amount]) => formatAmount(amount, currency));
  return parts.length === 0 ? "-" : parts.join(", ");
}

export default function AnalyticsView({ intervalMs = REFRESH_MS }: { intervalMs?: number }) {
  const [range, setRange] = useState<string>("24h");
  const [processor, setProcessor] = useState("");
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [baseline, setBaseline] = useState<BaselineData | null>(null);
  const [failed, setFailed] = useState(false);
  const latest = useRef(0);

  const load = useCallback(async () => {
    const ticket = ++latest.current;
    const spec = RANGES.find((r) => r.value === range) ?? RANGES[1];
    const to = new Date();
    const query = new URLSearchParams({ from: new Date(to.getTime() - spec.ms).toISOString(), to: to.toISOString() });
    if (processor) query.set("processor", processor);
    try {
      const res = await fetch(`/api/analytics?${query.toString()}`, { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      const body = (await res.json()) as AnalyticsData;
      if (ticket !== latest.current) return;
      setData(body);
      setFailed(false);
    } catch {
      if (ticket === latest.current) setFailed(true);
    }
  }, [range, processor]);

  useEffect(() => {
    // Deferred a tick so the effect itself sets no state synchronously.
    const first = setTimeout(() => void load(), 0);
    const timer = setInterval(() => void load(), intervalMs);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [load, intervalMs]);

  useEffect(() => {
    let active = true;
    const read = async () => {
      try {
        const res = await fetch("/api/analytics/baseline", { cache: "no-store" });
        if (!res.ok) throw new Error(String(res.status));
        const body = (await res.json()) as BaselineData;
        if (active) setBaseline(body);
      } catch {
        if (active) setBaseline({ available: false });
      }
    };
    const first = setTimeout(() => void read(), 0);
    return () => {
      active = false;
      clearTimeout(first);
    };
  }, []);

  const names = data ? Object.keys(data.processors) : [];
  const percentileRows: [string, (p: Percentiles) => number | null | undefined, "latency" | "call_latency"][] = [
    ["Latency P50 (received to final)", (p) => p.p50_ms, "latency"],
    ["Latency P95 (received to final)", (p) => p.p95_ms, "latency"],
    ["Latency P99 (received to final)", (p) => p.p99_ms, "latency"],
    ["Call latency P50 (processor call)", (p) => p.p50_ms, "call_latency"],
    ["Call latency P95 (processor call)", (p) => p.p95_ms, "call_latency"],
    ["Call latency P99 (processor call)", (p) => p.p99_ms, "call_latency"],
  ];
  const reasonRows = data
    ? names.flatMap((name) =>
        Object.entries(data.processors[name].failure_reasons).map(([reason, count]) => ({ name, reason, count })),
      )
    : [];
  const explained = data?.time_to_explanation;

  return (
    <section aria-labelledby="analytics-heading">
      <div className="bar">
        <h2 id="analytics-heading">Analytics</h2>
        <p role="status" className="mono">
          {failed ? "Error" : data === null ? "Loading" : `${data.volume.payments} payments`}
        </p>
      </div>
      <div className="filters">
        <label>
          Range
          <select value={range} onChange={(e) => setRange(e.target.value)}>
            {RANGES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Processor
          <select value={processor} onChange={(e) => setProcessor(e.target.value)}>
            <option value="">All</option>
            <option value="A">A</option>
            <option value="B">B</option>
          </select>
        </label>
      </div>
      {failed && (
        <p className="banner">Could not load analytics. Retrying every {Math.round(intervalMs / 1000)} seconds.</p>
      )}
      {data === null ? (
        <p className="note">{failed ? "No data yet." : "Loading analytics..."}</p>
      ) : (
        <>
          <p className="note">
            Payments created from <span className="mono">{data.window.from}</span> to{" "}
            <span className="mono">{data.window.to}</span> (UTC)
            {data.window.processor ? `, routed to processor ${data.window.processor}` : ""}. Figures come from the
            payment events; amounts and currency from the payments.
          </p>
          <div className="scroll short" tabIndex={0} role="region" aria-label="Figures table">
            <table aria-label="Figures by processor">
              <thead>
                <tr>
                  <th scope="col">Measure</th>
                  {names.map((name) => (
                    <th key={name} scope="col" className="num">
                      Processor {name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    ["Payments routed", (p) => String(p.volume)],
                    ["Captured", (p) => String(p.captured)],
                    ["Failed", (p) => String(p.failed)],
                    ["Declined", (p) => String(p.declined)],
                    ["Success rate", (p) => pct(p.success_rate)],
                  ] as [string, (p: AnalyticsData["processors"][string]) => string][]
                ).map(([label, value]) => (
                  <tr key={label}>
                    <th scope="row">{label}</th>
                    {names.map((name) => (
                      <td key={name} className="mono num">
                        {value(data.processors[name])}
                      </td>
                    ))}
                  </tr>
                ))}
                {percentileRows.map(([label, pick, key]) => (
                  <tr key={label}>
                    <th scope="row">{label}</th>
                    {names.map((name) => (
                      <td key={name} className="mono num">
                        {ms(pick(data.processors[name][key]))}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="note">
            Success rate is captured over captured plus failed; declines are counted apart. Latency covers final
            payments the processor handled.
          </p>

          <h3>Failure reasons</h3>
          {reasonRows.length === 0 ? (
            <p className="note">No failures in this range.</p>
          ) : (
            <div className="scroll short" tabIndex={0} role="region" aria-label="Failure reasons table">
              <table aria-label="Failure reasons">
                <thead>
                  <tr>
                    <th scope="col">Processor</th>
                    <th scope="col">Reason</th>
                    <th scope="col" className="num">
                      Count
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {reasonRows.map((r) => (
                    <tr key={`${r.name}-${r.reason}`}>
                      <td className="mono">{r.name}</td>
                      <td className="mono">{r.reason}</td>
                      <td className="mono num">{r.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h3>Revenue recovered</h3>
          <p className="note">
            Simulated revenue of captured payments that a retry, a failover or a re-drive rescued, per currency.
          </p>
          <div className="scroll short" tabIndex={0} role="region" aria-label="Revenue recovered table">
            <table aria-label="Revenue recovered by rescue path">
              <thead>
                <tr>
                  <th scope="col">Rescue path</th>
                  <th scope="col" className="num">
                    Payments
                  </th>
                  <th scope="col" className="num">
                    Amount
                  </th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.revenue_recovered_by_rescue_path).map(([path, row]) => (
                  <tr key={path}>
                    <th scope="row">{PATH_WORDS[path] ?? path}</th>
                    <td className="mono num">{row.count}</td>
                    <td className="mono num">{money(row.amount_minor_by_currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3>Time to explanation</h3>
          {explained === undefined || !explained.available ? (
            <p className="note">No explanations in this range yet.</p>
          ) : (
            <>
              <div className="scroll short" tabIndex={0} role="region" aria-label="Time to explanation table">
                <table aria-label="Time to explanation by source">
                  <thead>
                    <tr>
                      <th scope="col">Source</th>
                      <th scope="col" className="num">
                        Explanations
                      </th>
                      <th scope="col" className="num">
                        P50
                      </th>
                      <th scope="col" className="num">
                        P95
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(explained.sources).map(([source, row]) => (
                      <tr key={source}>
                        <th scope="row">{source.charAt(0).toUpperCase() + source.slice(1)}</th>
                        <td className="mono num">{row.count}</td>
                        <td className="mono num">{ms(row.p50_ms)}</td>
                        <td className="mono num">{ms(row.p95_ms)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="note">
                Fallback rate: <span className="mono">{pct(explained.fallback_rate)}</span> (rules text instead of the
                model).
              </p>
              {Object.keys(explained.fallback_reasons).length > 0 && (
                <ul>
                  {Object.entries(explained.fallback_reasons).map(([reason, count]) => (
                    <li key={reason}>
                      <span>{FALLBACK_WORDS[reason] ?? reason}</span> <span className="mono">{count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </>
      )}

      <section aria-labelledby="baseline-heading" className="baseline">
        <h3 id="baseline-heading">Against the static-routing baseline</h3>
        <p>Synthetic data; baseline is static routing.</p>
        {baseline === null ? (
          <p className="note">Loading baseline...</p>
        ) : !baseline.available ? (
          <p className="note">Baseline unavailable: the REL-30 results file was not found or could not be read.</p>
        ) : (
          <>
            <p className="note">
              From the REL-30 outage demo: run {baseline.run}, seed {baseline.seed}, scenario {baseline.scenario};
              {baseline.run_date ? (
                <>
                  run of <span className="mono">{baseline.run_date}</span>.
                </>
              ) : (
                "run date not recorded."
              )}{" "}
              {baseline.baseline_description}.
            </p>
            <dl className="figures">
              <dt>Success rate, static routing</dt>
              <dd className="mono">{baseline.success_rate_static_pct.toFixed(1)}%</dd>
              <dt>Success rate, Relay routing</dt>
              <dd className="mono">{baseline.success_rate_relay_pct.toFixed(1)}%</dd>
              <dt>Uplift</dt>
              <dd className="mono">+{baseline.uplift_pp.toFixed(1)} pp</dd>
              <dt>Revenue recovered in the demo run</dt>
              <dd className="mono">{money(baseline.revenue_recovered)}</dd>
            </dl>
            <div className="scroll short" tabIndex={0} role="region" aria-label="Baseline revenue table">
              <table aria-label="Baseline revenue recovered by rescue path">
                <thead>
                  <tr>
                    <th scope="col">Rescue path</th>
                    <th scope="col" className="num">
                      Amount
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(baseline.revenue_by_rescue_path).map(([path, byCurrency]) => (
                    <tr key={path}>
                      <th scope="row">{PATH_WORDS[path] ?? path}</th>
                      <td className="mono num">{money(byCurrency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </section>
  );
}
