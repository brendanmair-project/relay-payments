import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AnalyticsProvider from "./AnalyticsProvider";
import ValueStory from "./ValueStory";
import { analyticsData, baselineData, unavailableBaseline } from "../tests/fixtures/analytics";
import type { AnalyticsData, BaselineData } from "./lib/types";

const fetchMock = vi.fn();
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function serve(analytics: AnalyticsData | Response = analyticsData, baseline: BaselineData = baselineData) {
  fetchMock.mockImplementation(async (url: string) => {
    if (url.startsWith("/api/analytics/baseline")) return json(baseline);
    return analytics instanceof Response ? analytics : json(analytics);
  });
}

async function show() {
  render(
    <AnalyticsProvider>
      <ValueStory />
    </AnalyticsProvider>,
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-03T16:00:00.000Z"));
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("ValueStory headline band", () => {
  it("states the problem in one sentence and labels the band as synthetic data", async () => {
    serve();
    await show();
    const band = screen.getByRole("region", { name: "Money saved" });
    expect(within(band).getByText(/failed payments cost a merchant money/i)).toBeInTheDocument();
    expect(within(band).getByText("Synthetic data")).toBeInTheDocument();
  });

  it("shows revenue recovered per currency from money_saved, never one summed figure", async () => {
    serve();
    await show();
    const band = screen.getByRole("region", { name: "Money saved" });
    const revenue = within(band).getByRole("group", { name: "Revenue recovered" });
    expect(within(revenue).getByText("$45.00")).toBeInTheDocument();
    expect(within(revenue).getByText("€30.00")).toBeInTheDocument();
    expect(band).not.toHaveTextContent("$75.00");
    // the older revenue_recovered_by_rescue_path figure (one USD payment of $20.00) is not the headline
    expect(band).not.toHaveTextContent("$20.00");
  });

  it("shows payments rescued with the failover and retry split", async () => {
    serve();
    await show();
    const rescued = within(screen.getByRole("region", { name: "Money saved" })).getByRole("group", {
      name: "Payments rescued",
    });
    expect(rescued).toHaveTextContent("3");
    expect(rescued).toHaveTextContent("1 by failover");
    expect(rescued).toHaveTextContent("2 by retry");
  });

  it("shows investigation time saved with its exact estimate label", async () => {
    serve();
    await show();
    const saved = within(screen.getByRole("region", { name: "Money saved" })).getByRole("group", {
      name: "Investigation time saved",
    });
    expect(saved).toHaveTextContent("4.0 hours");
    expect(saved).toHaveTextContent("estimated against the 2-hour manual baseline");
    expect(saved).toHaveTextContent("2 failures explained");
  });

  it("explains an empty window instead of showing blank figures", async () => {
    serve({
      ...analyticsData,
      money_saved: {
        ...analyticsData.money_saved,
        payments_rescued: { count: 0, by_rescue_path: {} },
        revenue_recovered: { amount_minor_by_currency: {}, definition: "" },
        investigation_time_saved: {
          ...analyticsData.money_saved.investigation_time_saved,
          seconds_saved: 0,
          explained_failures: 0,
        },
      },
    });
    await show();
    const band = screen.getByRole("region", { name: "Money saved" });
    expect(band).toHaveTextContent("No rescued payments in the last 24 hours yet");
    expect(band).toHaveTextContent("0.0 hours");
  });

  it("says when the figures could not be loaded", async () => {
    serve(json({}, 500));
    await show();
    expect(screen.getByRole("region", { name: "Money saved" })).toHaveTextContent(
      "Could not load the money-saved figures",
    );
  });

  it("shows the static-routing before and after as text with the synthetic label", async () => {
    serve();
    await show();
    const ba = screen.getByRole("region", { name: "Before and after" });
    expect(ba).toHaveTextContent("Static routing: 58.0%");
    expect(ba).toHaveTextContent("With Relay: 89.0%");
    expect(ba).toHaveTextContent("Synthetic data");
  });

  it("says the baseline is unavailable without hiding the headline", async () => {
    serve(analyticsData, unavailableBaseline);
    await show();
    expect(screen.getByRole("region", { name: "Before and after" })).toHaveTextContent("Baseline unavailable");
    expect(screen.getByRole("group", { name: "Revenue recovered" })).toBeInTheDocument();
  });

  it("reads only the frontend's own /api routes", async () => {
    serve();
    await show();
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.length).toBeGreaterThan(0);
    expect(urls.every((u) => u.startsWith("/api/analytics"))).toBe(true);
  });
});
