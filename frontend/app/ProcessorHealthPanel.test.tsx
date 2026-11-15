import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProcessorHealthPanel from "./ProcessorHealthPanel";
import { healthBothAvoided, healthDuringOutage, healthNormal } from "../tests/fixtures/console";
import type { ProcessorHealth } from "./lib/types";

const fetchMock = vi.fn();
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

async function show(response: ProcessorHealth | Response) {
  fetchMock.mockImplementation(async () => (response instanceof Response ? response : json(response)));
  render(<ProcessorHealthPanel />);
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

describe("ProcessorHealthPanel", () => {
  it("shows each processor's state as a word with its error rate and attempts", async () => {
    await show(healthDuringOutage);
    const a = screen.getByRole("group", { name: "Processor A" });
    expect(a).toHaveTextContent("Avoided");
    expect(a).toHaveTextContent("54 of 94 attempts failed (57%)");
    const b = screen.getByRole("group", { name: "Processor B" });
    expect(b).toHaveTextContent("Preferred");
    expect(b).toHaveTextContent("3 of 25 attempts failed (12%)");
  });

  it("states the failover plainly when A is avoided and B is not", async () => {
    await show(healthDuringOutage);
    const failover = screen.getByRole("status", { name: "Failover state" });
    expect(failover).toHaveTextContent("Failover active");
    expect(failover).toHaveTextContent("new payments go to Processor B while Processor A is avoided");
    expect(failover).toHaveTextContent("60 s window");
  });

  it("says no failover is active when neither processor is avoided", async () => {
    await show(healthNormal);
    expect(screen.getByRole("status", { name: "Failover state" })).toHaveTextContent("No failover");
    expect(within(screen.getByRole("group", { name: "Processor B" })).getByText(/Unknown/)).toBeInTheDocument();
  });

  it("says so when both processors are avoided", async () => {
    await show(healthBothAvoided);
    expect(screen.getByRole("status", { name: "Failover state" })).toHaveTextContent("Both processors are avoided");
  });

  it("never claims health when the request fails", async () => {
    await show(json({}, 500));
    expect(screen.getByRole("region", { name: "Processor health" })).toHaveTextContent(
      "Processor health is unavailable right now",
    );
    expect(screen.queryByRole("group", { name: "Processor A" })).toBeNull();
  });

  it("refreshes every 5 seconds", async () => {
    await show(healthNormal);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
