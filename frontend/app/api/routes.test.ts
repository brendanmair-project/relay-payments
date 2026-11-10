// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GET as getPayments } from "./payments/route";
import { GET as getPayment } from "./payments/[id]/route";
import { GET as getExplanation } from "./payments/[id]/explanation/route";
import { GET as getHealth } from "./processors/health/route";
import * as outage from "./demo/outage/route";
import * as demoState from "./demo/state/route";

const SENTINEL = "relay-test-sentinel";
const ID = "5f0e6c52-3f3b-4b2e-9a51-7a4f2c9d1e10";

const fetchMock = vi.fn();

function upstreamJson(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

beforeEach(() => {
  vi.stubEnv("API_URL", "http://api.test:8000");
  vi.stubEnv("SIMULATOR_CONTROL_URL", "http://sim.test:8101");
  vi.stubEnv("RELAY_API_KEY", SENTINEL);
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

function lastCall() {
  const [url, init] = fetchMock.mock.calls.at(-1)!;
  return { url: String(url), init: (init ?? {}) as RequestInit };
}

describe("GET /api/payments", () => {
  it("calls the api with the key and passes the query string and body through", async () => {
    fetchMock.mockResolvedValue(upstreamJson({ items: [], next_cursor: null }));
    const res = await getPayments(new Request("http://localhost:3000/api/payments?limit=20&status=failed"));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ items: [], next_cursor: null });
    const { url, init } = lastCall();
    expect(url).toBe("http://api.test:8000/payments?limit=20&status=failed");
    expect(new Headers(init.headers).get("x-api-key")).toBe(SENTINEL);
  });

  it("never puts the key in the response body or headers", async () => {
    fetchMock.mockResolvedValue(upstreamJson({ items: [] }));
    const res = await getPayments(new Request("http://localhost:3000/api/payments"));
    expect(await res.text()).not.toContain(SENTINEL);
    expect([...res.headers.values()].join("\n")).not.toContain(SENTINEL);
  });

  it("passes the api error shape and status through unchanged", async () => {
    const err = { error: { code: "unauthorized", message: "no", correlation_id: "c1" } };
    fetchMock.mockResolvedValue(upstreamJson(err, 401));
    const res = await getPayments(new Request("http://localhost:3000/api/payments"));
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual(err);
  });

  it("answers 503 dependency_unavailable in the error shape when the api is unreachable", async () => {
    fetchMock.mockRejectedValue(new TypeError(`fetch failed ${SENTINEL}`));
    const res = await getPayments(new Request("http://localhost:3000/api/payments"));
    expect(res.status).toBe(503);
    const text = await res.text();
    expect(JSON.parse(text).error.code).toBe("dependency_unavailable");
    expect(text).not.toContain(SENTINEL);
  });

  it("does not cache", async () => {
    fetchMock.mockResolvedValue(upstreamJson({ items: [] }));
    const res = await getPayments(new Request("http://localhost:3000/api/payments"));
    expect(res.headers.get("cache-control")).toBe("no-store");
  });
});

describe("GET /api/payments/[id]", () => {
  it("fetches one payment", async () => {
    fetchMock.mockResolvedValue(upstreamJson({ id: ID, events: [] }));
    const res = await getPayment(new Request(`http://localhost:3000/api/payments/${ID}`), {
      params: Promise.resolve({ id: ID }),
    });
    expect(res.status).toBe(200);
    const { url, init } = lastCall();
    expect(url).toBe(`http://api.test:8000/payments/${ID}`);
    expect(new Headers(init.headers).get("x-api-key")).toBe(SENTINEL);
  });

  it("encodes the id so it cannot change the upstream path", async () => {
    fetchMock.mockResolvedValue(upstreamJson({ error: { code: "not_found" } }, 404));
    await getPayment(new Request("http://localhost:3000/api/payments/x"), {
      params: Promise.resolve({ id: "../processors/health" }),
    });
    expect(lastCall().url).toBe("http://api.test:8000/payments/..%2Fprocessors%2Fhealth");
  });
});

describe("GET /api/payments/[id]/explanation", () => {
  it("fetches the explanation and passes a 409 through", async () => {
    const err = { error: { code: "payment_not_final", message: "x", correlation_id: "c" } };
    fetchMock.mockResolvedValue(upstreamJson(err, 409));
    const res = await getExplanation(new Request("http://localhost:3000/x"), { params: Promise.resolve({ id: ID }) });
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual(err);
    expect(lastCall().url).toBe(`http://api.test:8000/payments/${ID}/explanation`);
  });
});

describe("GET /api/processors/health", () => {
  it("fetches processor health", async () => {
    fetchMock.mockResolvedValue(upstreamJson({ strategy: "rules", processors: [] }));
    const res = await getHealth();
    expect(res.status).toBe(200);
    expect(lastCall().url).toBe("http://api.test:8000/processors/health");
  });
});

describe("/api/demo/outage", () => {
  function post(headers: Record<string, string>, body: unknown = { enabled: true }) {
    return new Request("http://localhost:3000/api/demo/outage", {
      method: "POST",
      headers: { "content-type": "application/json", host: "localhost:3000", ...headers },
      body: JSON.stringify(body),
    });
  }

  it("forwards a same-origin POST to the simulator control API with the key", async () => {
    fetchMock.mockResolvedValue(upstreamJson({ processors: {} }));
    const res = await outage.POST(post({ "sec-fetch-site": "same-origin" }));
    expect(res.status).toBe(200);
    const { url, init } = lastCall();
    expect(url).toBe("http://sim.test:8101/control/processors/a/outage");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ enabled: true });
    expect(new Headers(init.headers).get("x-api-key")).toBe(SENTINEL);
  });

  it("accepts an Origin equal to the app's own origin", async () => {
    fetchMock.mockResolvedValue(upstreamJson({ processors: {} }));
    const res = await outage.POST(post({ origin: "http://localhost:3000" }, { enabled: false }));
    expect(res.status).toBe(200);
  });

  it.each([
    ["cross-site fetch metadata", { "sec-fetch-site": "cross-site" }],
    ["same-site fetch metadata", { "sec-fetch-site": "same-site" }],
    ["foreign Origin", { origin: "http://evil.example" }],
    ["no origin information", {}],
  ])("rejects %s with 403 and does not call the simulator", async (_name, headers) => {
    const res = await outage.POST(post(headers));
    expect(res.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a body that is not {enabled: boolean} with 422", async () => {
    const res = await outage.POST(post({ "sec-fetch-site": "same-origin" }, { enabled: "yes" }));
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accepts only POST", () => {
    const mod = outage as Record<string, unknown>;
    expect(mod.GET).toBeUndefined();
    expect(mod.PUT).toBeUndefined();
    expect(mod.DELETE).toBeUndefined();
  });

  it("passes a simulator 401 through unchanged", async () => {
    const err = { error: { code: "unauthorized", message: "no", correlation_id: "c1" } };
    fetchMock.mockResolvedValue(upstreamJson(err, 401));
    const res = await outage.POST(post({ "sec-fetch-site": "same-origin" }));
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual(err);
  });

  it("has no GET handler (Next.js answers 405)", () => {
    expect((outage as Record<string, unknown>).GET).toBeUndefined();
  });
});

describe("/api/demo/state", () => {
  const profile = { latency_ms_p50: 120, latency_ms_p95: 400, decline_rate: 0.1, timeout_rate: 0.02 };
  const snapshot = { processors: { a: { profile, outage: true }, b: { profile, outage: false } } };

  it("reads GET /control/processors with the key and returns only the outage flags", async () => {
    fetchMock.mockResolvedValue(upstreamJson(snapshot));
    const res = await demoState.GET();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ processors: { a: { outage: true }, b: { outage: false } } });
    const { url, init } = lastCall();
    expect(url).toBe("http://sim.test:8101/control/processors");
    expect(new Headers(init.headers).get("x-api-key")).toBe(SENTINEL);
  });

  it("passes a simulator error through unchanged", async () => {
    const err = { error: { code: "unauthorized", message: "no", correlation_id: "c1" } };
    fetchMock.mockResolvedValue(upstreamJson(err, 401));
    const res = await demoState.GET();
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual(err);
  });

  it("answers 502 when the simulator body is not the expected shape", async () => {
    fetchMock.mockResolvedValue(upstreamJson({ nope: 1 }));
    const res = await demoState.GET();
    expect(res.status).toBe(502);
  });

  it("is GET only", () => {
    const mod = demoState as Record<string, unknown>;
    expect(mod.POST).toBeUndefined();
    expect(mod.PUT).toBeUndefined();
  });
});
