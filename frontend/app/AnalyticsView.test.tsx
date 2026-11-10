import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AnalyticsView from "./AnalyticsView";
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

async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

function analyticsUrls(): URL[] {
  return fetchMock.mock.calls
    .map((c) => String(c[0]))
    .filter((u) => u.startsWith("/api/analytics?"))
    .map((u) => new URL(u, "http://localhost"));
}

function row(table: HTMLElement, name: string | RegExp) {
  const found = within(table)
    .getAllByRole("row")
    .find((r) => within(r).queryByRole("rowheader", { name }) !== null);
  if (!found) throw new Error(`no row ${String(name)}`);
  return within(found);
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

describe("AnalyticsView", () => {
  it("reads only the frontend's own /api/analytics routes and defaults to the last 24 hours", async () => {
    serve();
    render(<AnalyticsView />);
    await flush();
    const urls = analyticsUrls();
    expect(urls).toHaveLength(1);
    expect(urls[0].searchParams.get("to")).toBe("2026-11-03T16:00:00.000Z");
    expect(urls[0].searchParams.get("from")).toBe("2026-11-02T16:00:00.000Z");
    expect(urls[0].searchParams.has("processor")).toBe(false);
    const all = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(all.every((u) => u.startsWith("/api/analytics"))).toBe(true);
    expect(all).toContain("/api/analytics/baseline");
    expect(screen.getByRole("status")).toHaveTextContent("5 payments");
  });

  it("shows the figures per processor in monospace", async () => {
    serve();
    render(<AnalyticsView />);
    await flush();
    const table = screen.getByRole("table", { name: "Figures by processor" });
    expect(within(table).getByRole("columnheader", { name: "Processor A" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Processor B" })).toBeInTheDocument();
    const cell = (name: string | RegExp, col: number) => row(table, name).getAllByRole("cell")[col];
    expect(cell("Payments routed", 0)).toHaveTextContent("4");
    expect(cell("Payments routed", 1)).toHaveTextContent("2");
    expect(cell("Captured", 0)).toHaveTextContent("1");
    expect(cell("Failed", 0)).toHaveTextContent("2");
    expect(cell("Declined", 0)).toHaveTextContent("1");
    expect(cell("Success rate", 0)).toHaveTextContent("33.3%");
    expect(cell("Success rate", 1)).toHaveTextContent("100.0%");
    expect(cell(/^Latency P50/, 0)).toHaveTextContent("3000 ms");
    expect(cell(/^Latency P95/, 1)).toHaveTextContent("6000 ms");
    expect(cell(/^Latency P99/, 0)).toHaveTextContent("8000 ms");
    expect(cell(/^Call latency P50/, 0)).toHaveTextContent("200 ms");
    expect(cell(/^Call latency P99/, 1)).toHaveTextContent("400 ms");
    expect(cell("Success rate", 0)).toHaveClass("mono");
    expect(cell("Captured", 1)).toHaveClass("mono");
  });

  it("lists the failure reasons per processor with counts", async () => {
    serve();
    render(<AnalyticsView />);
    await flush();
    const table = screen.getByRole("table", { name: "Failure reasons" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.textContent)).toEqual(["Ado_not_honor1", "Aoutage1", "Atimeout1"]);
  });

  it("says so when a range has no failures", async () => {
    const quiet = {
      ...analyticsData,
      processors: Object.fromEntries(
        Object.entries(analyticsData.processors).map(([k, v]) => [k, { ...v, failure_reasons: {} }]),
      ),
    };
    serve(quiet);
    render(<AnalyticsView />);
    await flush();
    expect(screen.getByText("No failures in this range.")).toBeInTheDocument();
  });

  it("splits revenue recovered by rescue path and currency in exact amounts", async () => {
    serve();
    render(<AnalyticsView />);
    await flush();
    const table = screen.getByRole("table", { name: "Revenue recovered by rescue path" });
    const retry = row(table, "Retry").getAllByRole("cell");
    expect(retry[0]).toHaveTextContent("1");
    expect(retry[1]).toHaveTextContent("$20.00");
    expect(row(table, "Failover").getAllByRole("cell")[1]).toHaveTextContent("€30.00");
    const redrive = row(table, "Redrive").getAllByRole("cell");
    expect(redrive[0]).toHaveTextContent("0");
    expect(redrive[1]).toHaveTextContent("-");
    expect(screen.getByText(/simulated/i)).toBeInTheDocument();
  });

  it("shows time to explanation per source with the fallback reasons in plain words", async () => {
    serve();
    render(<AnalyticsView />);
    await flush();
    const table = screen.getByRole("table", { name: "Time to explanation by source" });
    const cells = (name: string) =>
      row(table, name)
        .getAllByRole("cell")
        .map((c) => c.textContent);
    expect(cells("Model")).toEqual(["1", "2000 ms", "2000 ms"]);
    expect(cells("Rules")).toEqual(["1", "3000 ms", "3000 ms"]);
    expect(screen.getByText(/Fallback rate/)).toHaveTextContent("50.0%");
    expect(screen.getByText("the model took too long to answer")).toBeInTheDocument();
  });

  it("says when no explanation exists yet", async () => {
    serve({ ...analyticsData, time_to_explanation: { available: false, note: "not available yet" } });
    render(<AnalyticsView />);
    await flush();
    expect(screen.getByText(/No explanations in this range/)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Time to explanation by source" })).not.toBeInTheDocument();
  });

  it("states that the baseline is synthetic static routing and which run it came from", async () => {
    serve();
    render(<AnalyticsView />);
    await flush();
    const section = screen.getByRole("region", { name: "Against the static-routing baseline" });
    const text = within(section);
    expect(text.getByText("Synthetic data; baseline is static routing.")).toBeInTheDocument();
    expect(section).toHaveTextContent("run 1, seed 7, scenario processor-a-outage");
    expect(section).toHaveTextContent("run date not recorded.");
    expect(text.getByText("58.0%")).toHaveClass("mono");
    expect(text.getByText("89.0%")).toBeInTheDocument();
    expect(text.getByText("+31.0 pp")).toBeInTheDocument();
    expect(section).toHaveTextContent("$68,100.94");
    expect(section).toHaveTextContent("€30,323.28");
  });

  it("says the baseline is unavailable instead of failing", async () => {
    serve(analyticsData, unavailableBaseline);
    render(<AnalyticsView />);
    await flush();
    const section = screen.getByRole("region", { name: "Against the static-routing baseline" });
    expect(section).toHaveTextContent("Baseline unavailable");
    expect(screen.getByRole("table", { name: "Figures by processor" })).toBeInTheDocument();
  });

  it("filters by processor through the query and shows only that column", async () => {
    serve();
    render(<AnalyticsView />);
    await flush();
    const onlyB = { ...analyticsData, processors: { B: analyticsData.processors.B } };
    serve(onlyB);
    fireEvent.change(screen.getByLabelText("Processor"), { target: { value: "B" } });
    await flush();
    expect(analyticsUrls().at(-1)!.searchParams.get("processor")).toBe("B");
    const table = screen.getByRole("table", { name: "Figures by processor" });
    expect(within(table).queryByRole("columnheader", { name: "Processor A" })).not.toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Processor B" })).toBeInTheDocument();
  });

  it("filters by time range through the query", async () => {
    serve();
    render(<AnalyticsView />);
    await flush();
    fireEvent.change(screen.getByLabelText("Range"), { target: { value: "7d" } });
    await flush();
    const last = analyticsUrls().at(-1)!;
    expect(last.searchParams.get("to")).toBe("2026-11-03T16:00:00.000Z");
    expect(last.searchParams.get("from")).toBe("2026-10-27T16:00:00.000Z");
  });

  it("refreshes on a timer", async () => {
    serve();
    render(<AnalyticsView intervalMs={1000} />);
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });
    expect(analyticsUrls().length).toBeGreaterThanOrEqual(3);
  });

  it("shows an error banner when the read fails and keeps retrying", async () => {
    serve(json({ error: { code: "dependency_unavailable", message: "x", correlation_id: "c" } }, 503));
    render(<AnalyticsView />);
    await flush();
    expect(screen.getByText(/Could not load analytics/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Error");
  });

  it("shows an empty range as zero payments with dashes for rates", async () => {
    const empty: AnalyticsData = {
      ...analyticsData,
      volume: { payments: 0, final: 0 },
      processors: Object.fromEntries(
        Object.keys(analyticsData.processors).map((k) => [
          k,
          {
            volume: 0,
            captured: 0,
            failed: 0,
            declined: 0,
            success_rate: null,
            latency: { count: 0, p50_ms: null, p95_ms: null, p99_ms: null },
            call_latency: { count: 0, p50_ms: null, p95_ms: null, p99_ms: null },
            failure_reasons: {},
          },
        ]),
      ),
    };
    serve(empty);
    render(<AnalyticsView />);
    await flush();
    expect(screen.getByRole("status")).toHaveTextContent("0 payments");
    const table = screen.getByRole("table", { name: "Figures by processor" });
    expect(row(table, "Success rate").getAllByRole("cell")[0]).toHaveTextContent("-");
  });
});
