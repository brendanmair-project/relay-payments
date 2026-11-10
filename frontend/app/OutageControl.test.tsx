import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import OutageControl from "./OutageControl";

const profile = { latency_ms_p50: 120, latency_ms_p95: 400, decline_rate: 0.1, timeout_rate: 0.02 };
const snap = (a: boolean) => ({ processors: { a: { profile, outage: a }, b: { profile, outage: false } } });
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const state = (a: boolean) => json({ processors: { a: { outage: a }, b: { outage: false } } });

const fetchMock = vi.fn();

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function click(name: string) {
  await act(async () => {
    screen.getByRole("button", { name }).click();
  });
  await flush();
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("OutageControl", () => {
  it("reads /api/demo/state on load and shows Inactive with a start button", async () => {
    fetchMock.mockResolvedValue(state(false));
    render(<OutageControl />);
    await flush();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/demo/state");
    expect(screen.getByText("Processor A outage: Inactive")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start Processor A outage" })).toBeEnabled();
  });

  it("shows Active with a stop button when the outage is on", async () => {
    fetchMock.mockResolvedValue(state(true));
    render(<OutageControl />);
    await flush();
    expect(screen.getByText("Processor A outage: Active")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop Processor A outage" })).toBeInTheDocument();
  });

  it("starts an outage with a JSON POST and shows the state from the response", async () => {
    fetchMock.mockResolvedValueOnce(state(false)).mockResolvedValueOnce(json(snap(true)));
    render(<OutageControl />);
    await flush();
    await click("Start Processor A outage");
    const [url, init] = fetchMock.mock.calls[1];
    expect(url).toBe("/api/demo/outage");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("content-type")).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ enabled: true });
    expect(screen.getByText("Processor A outage: Active")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop Processor A outage" })).toBeInTheDocument();
  });

  it("stops an outage by posting enabled false", async () => {
    fetchMock.mockResolvedValueOnce(state(true)).mockResolvedValueOnce(json(snap(false)));
    render(<OutageControl />);
    await flush();
    await click("Stop Processor A outage");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ enabled: false });
    expect(screen.getByText("Processor A outage: Inactive")).toBeInTheDocument();
  });

  it("disables the button while the request runs", async () => {
    let resolve!: (r: Response) => void;
    fetchMock.mockResolvedValueOnce(state(false)).mockReturnValueOnce(new Promise<Response>((r) => (resolve = r)));
    render(<OutageControl />);
    await flush();
    await click("Start Processor A outage");
    expect(screen.getByRole("button")).toBeDisabled();
    await act(async () => {
      resolve(json(snap(true)));
    });
    await flush();
    expect(screen.getByRole("button")).toBeEnabled();
  });

  it.each([
    ["403", () => json({ error: { code: "forbidden_origin" } }, 403)],
    ["502", () => json({ error: { code: "bad_gateway" } }, 502)],
  ])("shows a plain message on %s and keeps the last state", async (_n, make) => {
    fetchMock.mockResolvedValueOnce(state(false)).mockResolvedValueOnce(make());
    render(<OutageControl />);
    await flush();
    await click("Start Processor A outage");
    expect(screen.getByRole("alert")).toHaveTextContent(/could not/i);
    expect(screen.getByText("Processor A outage: Inactive")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start Processor A outage" })).toBeEnabled();
  });

  it("shows a plain message on a network error and keeps the last state", async () => {
    fetchMock.mockResolvedValueOnce(state(true)).mockRejectedValueOnce(new TypeError("fetch failed"));
    render(<OutageControl />);
    await flush();
    await click("Stop Processor A outage");
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Processor A outage: Active")).toBeInTheDocument();
  });
});
