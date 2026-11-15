// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as run from "./route";

// REL-66: the story run route. Start and stop are same-origin only (ADR-0012); the Host rule is proxy.ts (proxy.test.ts).
const SENTINEL = "relay-test-sentinel";
const fetchMock = vi.fn();

const status = {
  state: "running",
  phase: "outage",
  sent: 30,
  total: 90,
  switches: [{ processor: "a", outage: true, at: "2026-11-14T10:00:00.000Z" }],
  started_at: "2026-11-14T09:59:00.000Z",
  finished_at: null,
  error_code: null,
};

const upstream = (body: unknown, code = 200) =>
  new Response(JSON.stringify(body), { status: code, headers: { "content-type": "application/json" } });

beforeEach(() => {
  vi.stubEnv("SIMULATOR_CONTROL_URL", "http://sim.test:8101");
  vi.stubEnv("RELAY_API_KEY", SENTINEL);
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

function req(method: string, headers: Record<string, string> = {}) {
  return new Request("http://localhost:3000/api/demo/run", { method, headers });
}

describe.each([
  ["POST", run.POST],
  ["DELETE", run.DELETE],
] as const)("%s /api/demo/run access rules", (method, handler) => {
  it.each([
    ["a cross-site fetch", { "sec-fetch-site": "cross-site" }],
    ["a same-site (sibling) fetch", { "sec-fetch-site": "same-site" }],
    ["a foreign Origin without fetch metadata", { origin: "http://evil.example" }],
    ["no origin information at all", {}],
  ])("answers 403 forbidden_origin for %s and never calls the simulator", async (_label, headers) => {
    const res = await handler(req(method, headers));
    expect(res.status).toBe(403);
    expect((await res.json()).error.code).toBe("forbidden_origin");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accepts Sec-Fetch-Site same-origin and forwards with the key held on the server", async () => {
    fetchMock.mockResolvedValue(upstream(status, method === "POST" ? 202 : 200));
    const res = await handler(req(method, { "sec-fetch-site": "same-origin" }));
    expect(res.status).toBe(method === "POST" ? 202 : 200);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://sim.test:8101/control/story/run");
    expect((init as RequestInit).method).toBe(method);
    expect(new Headers((init as RequestInit).headers).get("x-api-key")).toBe(SENTINEL);
    expect(await res.text()).not.toContain(SENTINEL);
  });

  it("accepts an Origin equal to the app origin when there is no fetch metadata", async () => {
    fetchMock.mockResolvedValue(upstream(status, 202));
    const res = await handler(req(method, { origin: "http://localhost:3000" }));
    expect(res.status).toBeLessThan(300);
  });

  it("passes an upstream 409 through in the error shape", async () => {
    const err = { error: { code: "run_in_progress", message: "a run is already in progress" } };
    fetchMock.mockResolvedValue(upstream(err, 409));
    const res = await handler(req(method, { "sec-fetch-site": "same-origin" }));
    expect(res.status).toBe(409);
    expect((await res.json()).error.code).toBe("run_in_progress");
  });

  it("answers 503 dependency_unavailable when the simulator is unreachable", async () => {
    fetchMock.mockRejectedValue(new TypeError(`fetch failed ${SENTINEL}`));
    const res = await handler(req(method, { "sec-fetch-site": "same-origin" }));
    expect(res.status).toBe(503);
    const text = await res.text();
    expect(JSON.parse(text).error.code).toBe("dependency_unavailable");
    expect(text).not.toContain(SENTINEL);
  });
});

describe("GET /api/demo/run", () => {
  it("returns only the whitelisted status fields and does not cache", async () => {
    fetchMock.mockResolvedValue(upstream({ ...status, api_key: SENTINEL, profiles: { a: {} }, extra: 1 }));
    const res = await run.GET();
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(await res.json()).toEqual(status);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://sim.test:8101/control/story/run");
    expect((init as RequestInit | undefined)?.method ?? "GET").toBe("GET");
    expect(new Headers((init as RequestInit).headers).get("x-api-key")).toBe(SENTINEL);
  });

  it("needs no same-origin proof (a read)", async () => {
    fetchMock.mockResolvedValue(upstream(status));
    expect((await run.GET()).status).toBe(200);
  });

  it("answers 502 bad_gateway for an unknown upstream shape", async () => {
    fetchMock.mockResolvedValue(upstream({ state: 7 }));
    const res = await run.GET();
    expect(res.status).toBe(502);
    expect((await res.json()).error.code).toBe("bad_gateway");
  });

  it("answers 503 when the simulator is unreachable", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    expect((await run.GET()).status).toBe(503);
  });
});

it("exports no other methods (Next.js answers 405)", () => {
  const mod = run as Record<string, unknown>;
  expect(mod.PUT).toBeUndefined();
  expect(mod.PATCH).toBeUndefined();
});
