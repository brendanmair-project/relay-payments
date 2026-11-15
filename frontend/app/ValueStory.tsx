"use client";

import { useAnalytics } from "./AnalyticsProvider";
import { formatAmount, formatHours } from "./lib/format";
import type { BaselineData, MoneySaved } from "./lib/types";

function Currencies({ byCurrency }: { byCurrency: Record<string, number> }) {
  // One figure per currency, never a sum across currencies (docs/product/metrics.md).
  return (
    <ul className="amounts">
      {Object.entries(byCurrency).map(([currency, amount]) => (
        <li key={currency}>
          <span className="big mono">{formatAmount(amount, currency)}</span>{" "}
          <span className="cur mono">{currency}</span>
        </li>
      ))}
    </ul>
  );
}

function Figures({ saved }: { saved: MoneySaved }) {
  const rescued = saved.payments_rescued;
  const time = saved.investigation_time_saved;
  const failover = rescued.by_rescue_path.failover?.count ?? 0;
  const retry = rescued.by_rescue_path.retry?.count ?? 0;
  const none = Object.keys(saved.revenue_recovered.amount_minor_by_currency).length === 0;
  return (
    <>
      <div className="figure-row">
        <div role="group" aria-labelledby="fig-revenue" className="figure">
          <h3 id="fig-revenue">Revenue recovered</h3>
          {none ? (
            <p>No rescued payments in the last 24 hours yet.</p>
          ) : (
            <Currencies byCurrency={saved.revenue_recovered.amount_minor_by_currency} />
          )}
          <p className="fine">Per currency, never added together. Last 24 hours.</p>
        </div>
        <div role="group" aria-labelledby="fig-rescued" className="figure">
          <h3 id="fig-rescued">Payments rescued</h3>
          <p className="big mono">{rescued.count}</p>
          <p className="fine">{`${failover} by failover, ${retry} by retry`}</p>
        </div>
        <div role="group" aria-labelledby="fig-time" className="figure">
          <h3 id="fig-time">Investigation time saved</h3>
          <p className="big mono">{formatHours(time.seconds_saved)}</p>
          <p className="fine">
            <span className="lab">{time.label}</span>{" "}
            {`${time.explained_failures} ${time.explained_failures === 1 ? "failure" : "failures"} explained`}
          </p>
        </div>
      </div>
      <details className="how">
        <summary>How these are counted</summary>
        <p>{saved.revenue_recovered.definition}</p>
        <p>{time.definition}</p>
      </details>
    </>
  );
}

function BeforeAfter({ baseline }: { baseline: BaselineData | null }) {
  if (baseline === null) return <p className="note">Loading the baseline...</p>;
  if (!baseline.available)
    return <p className="note">Baseline unavailable: the REL-30 results file was not found or could not be read.</p>;
  return (
    <>
      <div className="ba">
        <div>
          <p className="mono">{`Static routing: ${baseline.success_rate_static_pct.toFixed(1)}%`}</p>
          <div className="meter" aria-hidden="true">
            <span className="fill muted-fill" style={{ width: `${baseline.success_rate_static_pct}%` }} />
          </div>
        </div>
        <div>
          <p className="mono">{`With Relay: ${baseline.success_rate_relay_pct.toFixed(1)}%`}</p>
          <div className="meter" aria-hidden="true">
            <span className="fill" style={{ width: `${baseline.success_rate_relay_pct}%` }} />
          </div>
        </div>
      </div>
      <p className="note">
        {`Success rate across the same seeded payments while Processor A was down: +${baseline.uplift_pp.toFixed(1)} percentage points. Committed outage demo, run ${baseline.run}, seed ${baseline.seed}; ${baseline.baseline_description}.`}
      </p>
    </>
  );
}

export default function ValueStory() {
  const { data, baseline, failed } = useAnalytics();
  return (
    <>
      <section aria-labelledby="saved-heading" className="band-hero">
        <p className="eyebrow">The problem</p>
        <p className="problem">
          Failed payments cost a merchant money, and finding out why takes hours. Relay recovers the money and explains
          each failure in plain language.
        </p>
        <div className="bar">
          <h2 id="saved-heading">Money saved</h2>
          <span className="lab">Synthetic data</span>
        </div>
        {data === null ? (
          <p className="note-hero">
            {failed
              ? "Could not load the money-saved figures. Retrying every 10 seconds."
              : "Loading the money-saved figures..."}
          </p>
        ) : (
          <>
            {failed && <p className="note-hero">Could not refresh the figures. Showing the last ones.</p>}
            <Figures saved={data.money_saved} />
          </>
        )}
      </section>
      <section aria-labelledby="ba-heading" className="card">
        <div className="bar">
          <h2 id="ba-heading">Before and after</h2>
          <span className="lab-dark">Synthetic data</span>
        </div>
        <BeforeAfter baseline={baseline} />
      </section>
    </>
  );
}
