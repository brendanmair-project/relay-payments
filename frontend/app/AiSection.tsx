"use client";

import { useAnalytics } from "./AnalyticsProvider";
import LatestFailure from "./LatestFailure";

const STEPS = [
  { title: "A payment fails", text: "The processor declines it or does not answer, and the failure is recorded." },
  { title: "One timeline", text: "Every state change is an event in one ordered timeline for that payment." },
  {
    title: "A local model explains",
    text: "A small open model on this machine reads the status, reason codes and timeline events, never the payment description, and answers in plain language citing the events.",
  },
  {
    title: "The rules check it",
    text: "A deterministic rules explainer names the cause too. The two must agree on the cause.",
  },
  {
    title: "You see the verdict",
    text: "The analyst gets the text with what the model saw, how long it took and the cross-check result in words.",
  },
];

const ms = (value: number | null | undefined) =>
  value === null || value === undefined ? "-" : `${Math.round(value)} ms`;

function Stats() {
  const { data, failed } = useAnalytics();
  const label = "Explanations in the last 24 hours";
  if (data === null)
    return (
      <p className="note" role="group" aria-label={label}>
        {failed ? "Could not load the explanation figures." : "Loading the explanation figures..."}
      </p>
    );
  const t = data.time_to_explanation;
  if (!t.available)
    return (
      <p className="note" role="group" aria-label={label}>
        No explanations in the last 24 hours yet.
      </p>
    );
  const rate = t.fallback_rate === null ? "-" : `${(t.fallback_rate * 100).toFixed(1)}%`;
  return (
    <div role="group" aria-label={label} className="ai-stats">
      <ul className="mono">
        <li>{`Written by the model: ${t.sources.model?.count ?? 0}`}</li>
        <li>{`Rules text: ${t.sources.rules?.count ?? 0}`}</li>
        <li>{`Rules text instead of the model: ${rate}`}</li>
        <li>{`Median time to explanation: ${ms(t.all.p50_ms)}`}</li>
      </ul>
    </div>
  );
}

export default function AiSection() {
  return (
    <section aria-labelledby="ai-heading" className="card">
      <div className="bar">
        <h2 id="ai-heading">How the AI explains failures</h2>
        <span className="lab-dark">Synthetic data</span>
      </div>
      <p>
        Every failure gets a plain-language explanation. The model runs locally, with no hosted AI service, and the
        rules cross-check it: when the model and the rules disagree, the rules text is shown.
      </p>
      <ol aria-label="How an explanation is made" className="steps">
        {STEPS.map((s, i) => (
          <li key={s.title}>
            <span className="n mono" aria-hidden="true">
              {i + 1}
            </span>
            <strong>{s.title}</strong>
            <span>{s.text}</span>
          </li>
        ))}
      </ol>
      <Stats />
      <LatestFailure />
    </section>
  );
}
