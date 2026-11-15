import { FALLBACK_WORDS } from "./lib/format";
import type { Explanation, ExplanationInputs } from "./lib/types";

// "How the AI explained this" (REL-63): what the model saw and was asked, what it answered, how long it took and
// how the rules cross-check came out. Every verdict is words, never colour alone (AGENTS.md). The payment
// description is never in the explanation response, so it cannot appear here (ADR-0012).

export function takenText(ms: number | null | undefined, noModelCall: boolean): string {
  if (typeof ms === "number") return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  return noModelCall ? "no model call was made" : "not recorded";
}

function verdictText(x: Explanation): string {
  const reason = x.fallback_reason ? (FALLBACK_WORDS[x.fallback_reason] ?? x.fallback_reason) : null;
  switch (x.cross_check) {
    case "agreed":
      return `Cross-check: agreed. The model and the rules named the same cause (${x.rules_cause ?? "unknown"}), so the model's text is shown.`;
    case "disagreed_rules_used":
      return `Cross-check: disagreed. The model named ${x.model_cause ?? "no cause"} and the rules named ${x.rules_cause ?? "unknown"}, so the rules text is shown.`;
    case "model_unavailable":
      return `Cross-check: not possible. The model was asked but gave no usable answer${reason ? ` (${reason})` : ""}, so the rules text is shown.`;
    case "rules_only":
      return "Cross-check: not run. No model was asked, so this explanation comes from the rules only.";
    default:
      return "Cross-check: not recorded. This explanation was stored before Relay kept how it was made.";
  }
}

function Saw({ inputs }: { inputs: ExplanationInputs | null | undefined }) {
  if (!inputs) return <p>Saw: not recorded.</p>;
  return (
    <div>
      <p>Saw: the facts below, never the payment description.</p>
      <p className="mono">{`Status ${inputs.status ?? "unknown"} | Amount ${inputs.amount}`}</p>
      <p className="mono">{`Reason codes: ${inputs.reason_codes.length ? inputs.reason_codes.join(", ") : "none"}`}</p>
      <ul aria-label="Events the model saw">
        {inputs.events.map((e) => (
          <li key={e.seq} className="mono">
            {`#${e.seq} ${e.type}${e.processor ? ` on processor ${e.processor}` : ""}${e.reason ? `, reason ${e.reason}` : ""}${e.result ? `, result ${e.result}` : ""}${e.outcome ? `, outcome ${e.outcome}` : ""}`}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function ExplanationPanel({ explanation: x }: { explanation: Explanation }) {
  const answered =
    x.source === "model"
      ? `Answered: ${x.text}`
      : x.cross_check === "rules_only"
        ? "Answered: no model was asked."
        : x.cross_check === null || x.cross_check === undefined
          ? "Answered: not recorded."
          : "Answered: the model's answer was not used; see the explanation above.";
  return (
    <section aria-label="How the AI explained this" className="ai-panel">
      <h4>How the AI explained this</h4>
      <Saw inputs={x.inputs} />
      <p>Asked: explain the failure in plain language and cite the timeline events it relies on.</p>
      <p>{answered}</p>
      <p>
        {x.attempted_model
          ? `Model: ${x.attempted_model}, running locally on this machine.`
          : x.cross_check === "rules_only"
            ? "No model was asked."
            : "Which model was asked: not recorded."}
      </p>
      <p className="mono">{`Time taken: ${takenText(x.generation_ms, x.cross_check === "rules_only")}`}</p>
      <p>{verdictText(x)}</p>
    </section>
  );
}
