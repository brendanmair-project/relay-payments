import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AiSection from "./AiSection";
import AnalyticsProvider from "./AnalyticsProvider";
import { analyticsData, baselineData } from "../tests/fixtures/analytics";
import type { AnalyticsData } from "./lib/types";

const fetchMock = vi.fn();
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

async function show(analytics: AnalyticsData = analyticsData) {
  fetchMock.mockImplementation(async (url: string) => {
    if (url.startsWith("/api/analytics/baseline")) return json(baselineData);
    if (url.startsWith("/api/analytics")) return json(analytics);
    return new Promise(() => {}); // payments and explanations never answer here: LatestFailure has its own tests
  });
  render(
    <AnalyticsProvider>
      <AiSection />
    </AnalyticsProvider>,
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("AiSection", () => {
  it("shows the five steps from a failed payment to a checked explanation", async () => {
    await show();
    const steps = within(screen.getByRole("list", { name: "How an explanation is made" })).getAllByRole("listitem");
    expect(steps).toHaveLength(5);
    expect(steps[2]).toHaveTextContent(/local model/i);
    expect(steps[2]).toHaveTextContent(/never the payment description/i);
    expect(steps[3]).toHaveTextContent(/rules/i);
  });

  it("says the model runs locally and what the cross-check does when it disagrees", async () => {
    await show();
    const section = screen.getByRole("region", { name: "How the AI explains failures" });
    expect(section).toHaveTextContent("runs locally");
    expect(section).toHaveTextContent(/when the model and the rules disagree, the rules text is shown/i);
  });

  it("shows measured explanation counts and the fallback rate from the analytics, in words", async () => {
    await show();
    const stats = screen.getByRole("group", { name: "Explanations in the last 24 hours" });
    expect(stats).toHaveTextContent("Written by the model: 1");
    expect(stats).toHaveTextContent("Rules text: 1");
    expect(stats).toHaveTextContent("Rules text instead of the model: 50.0%");
    expect(stats).toHaveTextContent("Median time to explanation: 2000 ms");
  });

  it("says there are no explanations yet when the analytics have none", async () => {
    await show({ ...analyticsData, time_to_explanation: { available: false, note: "none" } });
    expect(screen.getByRole("group", { name: "Explanations in the last 24 hours" })).toHaveTextContent(
      "No explanations in the last 24 hours yet",
    );
  });
});
