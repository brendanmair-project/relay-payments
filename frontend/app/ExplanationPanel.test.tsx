import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { agreedExplanation, disagreedExplanation, unavailableExplanation } from "../tests/fixtures/explanations";
import ExplanationPanel from "./ExplanationPanel";
import type { Explanation } from "./lib/types";

afterEach(cleanup);

// Real responses (tests/fixtures/explanations.ts). The rules-only and pre-REL-63 shapes are derived from them: the
// running api always has a model client, so those two cannot be captured from the stack.
const as = (x: unknown) => x as Explanation;
const rulesOnly = as({
  ...unavailableExplanation,
  fallback_reason: "model_unreachable",
  attempted_model: null,
  model_cause: null,
  generation_ms: null,
  cross_check: "rules_only",
});
const legacy = as({
  ...unavailableExplanation,
  fallback_reason: "model_unreachable",
  attempted_model: null,
  model_cause: null,
  rules_cause: null,
  generation_ms: null,
  inputs: null,
  cross_check: null,
});

function panel(x: Explanation) {
  render(<ExplanationPanel explanation={x} />);
  return screen.getByRole("region", { name: "How the AI explained this" });
}

describe("ExplanationPanel", () => {
  it("is titled, and says what the model saw and was asked", () => {
    const p = panel(as(agreedExplanation));
    expect(within(p).getByRole("heading", { name: "How the AI explained this" })).toBeTruthy();
    expect(within(p).getByText("Saw: the facts below, never the payment description.")).toBeTruthy();
    expect(within(p).getByText(/Status declined/)).toBeTruthy();
    expect(within(p).getByText(/Amount 23\.70 USD/)).toBeTruthy();
    expect(within(p).getByText(/Reason codes: card_expired, failover/)).toBeTruthy();
    expect(within(p).getAllByRole("listitem").length).toBeGreaterThanOrEqual(agreedExplanation.inputs.events.length);
    expect(within(p).getByText(/#3 attempt\.authorize_result on processor B, reason card_expired/)).toBeTruthy();
    expect(
      within(p).getByText("Asked: explain the failure in plain language and cite the timeline events it relies on."),
    ).toBeTruthy();
  });

  it("agreed: shows the model's answer, its name, that it runs locally, the time and the verdict in words", () => {
    const p = panel(as(agreedExplanation));
    expect(within(p).getByText(`Answered: ${agreedExplanation.text}`)).toBeTruthy();
    expect(within(p).getByText("Model: granite3.3:2b, running locally on this machine.")).toBeTruthy();
    expect(within(p).getByText("Time taken: 650 ms")).toBeTruthy();
    expect(
      within(p).getByText(
        "Cross-check: agreed. The model and the rules named the same cause (decline_card_expired), so the model's text is shown.",
      ),
    ).toBeTruthy();
  });

  it("disagreed: names both causes and says the rules text is shown", () => {
    const p = panel(as(disagreedExplanation));
    expect(
      within(p).getByText(
        "Cross-check: disagreed. The model named authorize_outage and the rules named captured_after_retry, so the rules text is shown.",
      ),
    ).toBeTruthy();
    expect(within(p).getByText("Model: granite3.3:2b, running locally on this machine.")).toBeTruthy();
    expect(within(p).getByText("Answered: the model's answer was not used; see the explanation above.")).toBeTruthy();
    expect(within(p).getByText(/Time taken: 5\d\d ms|Time taken: \d+ ms/)).toBeTruthy();
  });

  it("model unavailable: says why, with the time spent waiting in seconds", () => {
    const p = panel(as(unavailableExplanation));
    expect(
      within(p).getByText(
        "Cross-check: not possible. The model was asked but gave no usable answer (the model took too long to answer), so the rules text is shown.",
      ),
    ).toBeTruthy();
    expect(within(p).getByText("Time taken: 20.1 s")).toBeTruthy();
    expect(within(p).getByText("Model: granite3.3:2b, running locally on this machine.")).toBeTruthy();
  });

  it("rules only: says plainly that no model was asked", () => {
    const p = panel(rulesOnly);
    expect(
      within(p).getByText("Cross-check: not run. No model was asked, so this explanation comes from the rules only."),
    ).toBeTruthy();
    expect(within(p).getByText("No model was asked.")).toBeTruthy();
    expect(within(p).getByText("Time taken: no model call was made")).toBeTruthy();
    expect(within(p).queryByText(/running locally/)).toBeNull();
  });

  it("a row stored before the details were kept says so instead of inventing them", () => {
    const p = panel(legacy);
    expect(
      within(p).getByText("Cross-check: not recorded. This explanation was stored before Relay kept how it was made."),
    ).toBeTruthy();
    expect(within(p).getByText("Saw: not recorded.")).toBeTruthy();
    expect(within(p).getByText("Time taken: not recorded")).toBeTruthy();
  });

  it("an old payload without the new keys does not crash", () => {
    const old = as({ ...legacy, attempted_model: undefined, inputs: undefined, cross_check: undefined });
    const p = panel(old);
    expect(within(p).getByText("Saw: not recorded.")).toBeTruthy();
  });

  it("never shows the payment description", () => {
    for (const x of [agreedExplanation, disagreedExplanation, unavailableExplanation]) {
      cleanup();
      render(<ExplanationPanel explanation={as(x)} />);
      expect(document.body.textContent ?? "").not.toContain("sentinel-desc");
      expect(JSON.stringify(x)).not.toContain("sentinel-desc");
    }
  });
});
