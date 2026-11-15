import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import StoryMode from "./StoryMode";

type Run = {
  state: string;
  phase: string | null;
  sent: number;
  total: number;
  switches: { processor: string; outage: boolean; at: string }[];
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
};

const ON = { processor: "a", outage: true, at: "2026-11-14T10:00:00.000Z" };
const OFF = { processor: "a", outage: false, at: "2026-11-14T10:01:00.000Z" };
const run = (over: Partial<Run> = {}): Run => ({
  state: "idle",
  phase: null,
  sent: 0,
  total: 90,
  switches: [],
  started_at: null,
  finished_at: null,
  error_code: null,
  ...over,
});
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

// What the console's other routes say; each test changes these and the next poll sees them.
const server = {
  run: run(),
  startAnswer: null as Response | null,
  avoided: false,
  payments: [] as unknown[],
};
const fetchMock = vi.fn();

function health() {
  const state = server.avoided ? "avoided" : "preferred";
  return {
    strategy: "rules",
    window_seconds: 60,
    error_threshold: 0.5,
    computed_at: "x",
    processors: [
      { name: "A", attempts: 10, errors: 9, error_rate: 0.9, state },
      { name: "B", attempts: 1, errors: 0, error_rate: 0, state: "preferred" },
    ],
  };
}

beforeEach(() => {
  server.run = run();
  server.startAnswer = null;
  server.avoided = false;
  server.payments = [];
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/api/demo/run") {
      if (method === "POST") {
        if (server.startAnswer) return server.startAnswer;
        server.run = run({ state: "running", phase: "flowing", started_at: "2026-11-14T09:59:00.000Z" });
        return json(server.run, 202);
      }
      if (method === "DELETE") {
        server.run = { ...server.run, state: "stopping" };
        return json(server.run);
      }
      return json(server.run);
    }
    if (url === "/api/processors/health") return json(health());
    if (url.startsWith("/api/payments?")) return json({ items: server.payments, next_cursor: null });
    if (url.endsWith("/explanation")) return json({ payment_id: "p1", source: "rules", text: "x" });
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const caption = () => screen.getByRole("status", { name: "Story step" });

async function startRun() {
  await act(async () => {
    screen.getByRole("button", { name: "Run the outage demo" }).click();
  });
}

describe("StoryMode", () => {
  it("offers the control and no caption while idle", async () => {
    render(<StoryMode intervalMs={10} />);
    expect(await screen.findByRole("button", { name: "Run the outage demo" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Stop the demo" })).not.toBeInTheDocument();
    expect(caption()).toHaveTextContent("");
  });

  it("starts the run with a POST and shows Payments flowing in an aria-live region", async () => {
    render(<StoryMode intervalMs={10} />);
    await screen.findByRole("button", { name: "Run the outage demo" });
    await startRun();
    await waitFor(() => expect(caption()).toHaveTextContent("Payments flowing"));
    expect(caption()).toHaveAttribute("aria-live", "polite");
    expect(fetchMock.mock.calls.some(([u, i]) => u === "/api/demo/run" && i?.method === "POST")).toBe(true);
  });

  it("disables the start control and shows Stop while the run is active", async () => {
    render(<StoryMode intervalMs={10} />);
    await screen.findByRole("button", { name: "Run the outage demo" });
    await startRun();
    await waitFor(() => expect(screen.getByRole("button", { name: "Run the outage demo" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "Stop the demo" })).toBeEnabled();
  });

  it("shows the server's 409 as a message and keeps the control usable", async () => {
    server.startAnswer = json({ error: { code: "run_in_progress", message: "a run is already in progress" } }, 409);
    render(<StoryMode intervalMs={10} />);
    await screen.findByRole("button", { name: "Run the outage demo" });
    await startRun();
    expect(await screen.findByRole("alert")).toHaveTextContent(/already running/i);
  });

  it("picks up a run that is already going when the page loads", async () => {
    server.run = run({ state: "running", phase: "flowing", sent: 4 });
    render(<StoryMode intervalMs={10} />);
    await waitFor(() => expect(caption()).toHaveTextContent("Payments flowing"));
    expect(screen.getByRole("button", { name: "Run the outage demo" })).toBeDisabled();
  });

  it("follows the run state: Processor A failing while the outage is on and A is not yet avoided", async () => {
    server.run = run({ state: "running", phase: "outage", sent: 30, switches: [ON] });
    render(<StoryMode intervalMs={10} />);
    await waitFor(() => expect(caption()).toHaveTextContent("Processor A failing"));
  });

  it("moves to Relay routing to Processor B once the health read shows A avoided", async () => {
    server.run = run({ state: "running", phase: "outage", sent: 30, switches: [ON] });
    render(<StoryMode intervalMs={10} />);
    await waitFor(() => expect(caption()).toHaveTextContent("Processor A failing"));
    server.avoided = true;
    await waitFor(() => expect(caption()).toHaveTextContent("Relay routing to Processor B"));
  });

  it("moves to Explanations arriving once a failure after the outage start has a stored explanation", async () => {
    server.avoided = true;
    server.payments = [
      { id: "old", is_final: true, display_status: "Declined", final_at: "2026-11-14T09:00:00.000Z" },
      { id: "p1", is_final: true, display_status: "Declined", final_at: "2026-11-14T10:00:05.000Z" },
    ];
    server.run = run({ state: "running", phase: "outage", sent: 40, switches: [ON] });
    render(<StoryMode intervalMs={10} />);
    await waitFor(() => expect(caption()).toHaveTextContent("Explanations arriving"));
    const explained = fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.endsWith("/explanation"));
    expect(explained).toEqual(expect.arrayContaining(["/api/payments/p1/explanation"]));
    expect(explained.some((u) => u.includes("/old/"))).toBe(false);
  });

  it("does not claim explanations for failures from before the outage", async () => {
    server.avoided = true;
    server.payments = [{ id: "old", is_final: true, display_status: "Declined", final_at: "2026-11-14T09:00:00.000Z" }];
    server.run = run({ state: "running", phase: "outage", sent: 40, switches: [ON] });
    render(<StoryMode intervalMs={10} />);
    await waitFor(() => expect(caption()).toHaveTextContent("Relay routing to Processor B"));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 60));
    });
    expect(caption()).not.toHaveTextContent("Explanations arriving");
  });

  it("ends on Money recovered, pointing at the headline, when the run finishes", async () => {
    server.run = run({
      state: "finished",
      phase: "done",
      sent: 90,
      switches: [ON, OFF],
      finished_at: "2026-11-14T10:02:00.000Z",
    });
    render(<StoryMode intervalMs={10} />);
    await waitFor(() => expect(caption()).toHaveTextContent("Money recovered"));
    expect(screen.getByText(/revenue recovered/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run the outage demo" })).toBeEnabled();
  });

  it("stops the run with a DELETE and says it is stopping", async () => {
    server.run = run({ state: "running", phase: "outage", sent: 30, switches: [ON] });
    render(<StoryMode intervalMs={10} />);
    const stop = await screen.findByRole("button", { name: "Stop the demo" });
    await act(async () => {
      stop.click();
    });
    expect(fetchMock.mock.calls.some(([u, i]) => u === "/api/demo/run" && i?.method === "DELETE")).toBe(true);
    await waitFor(() => expect(caption()).toHaveTextContent(/stopping/i));
    server.run = run({ state: "stopped", sent: 33, switches: [ON, OFF] });
    await waitFor(() => expect(caption()).toHaveTextContent(/stopped/i));
    expect(screen.getByRole("button", { name: "Run the outage demo" })).toBeEnabled();
  });

  it("says when the run failed, in words", async () => {
    server.run = run({ state: "failed", error_code: "api_unreachable" });
    render(<StoryMode intervalMs={10} />);
    await waitFor(() => expect(caption()).toHaveTextContent(/failed/i));
  });

  it("tells the rest of the page when a run is active, so the manual toggle can step aside", async () => {
    const seen: boolean[] = [];
    const listener = (e: Event) => seen.push((e as CustomEvent<{ active: boolean }>).detail.active);
    window.addEventListener("relay:story", listener);
    server.run = run({ state: "running", phase: "flowing" });
    render(<StoryMode intervalMs={10} />);
    await waitFor(() => expect(seen).toContain(true));
    server.run = run({ state: "finished", phase: "done", switches: [ON, OFF] });
    await waitFor(() => expect(seen.at(-1)).toBe(false));
    window.removeEventListener("relay:story", listener);
  });
});
