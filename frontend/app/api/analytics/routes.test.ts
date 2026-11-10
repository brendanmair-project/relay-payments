// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GET as getAnalytics } from "./route";
import { GET as getBaseline } from "./baseline/route";
import { analyticsData, baselineData } from "../../../tests/fixtures/analytics";

const SENTINEL = "relay-test-sentinel";
const fetchMock = vi.fn();

const upstreamJson = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

beforeEach(() => {
  vi.stubEnv("API_URL", "http://api.test:8000");
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

describe("GET /api/analytics", () => {
  it("forwards the query string with the key and returns the body without the key", async () => {
    fetchMock.mockResolvedValue(upstreamJson(analyticsData));
    const res = await getAnalytics(
      new Request("http://localhost:3000/api/analytics?from=2026-11-02T16%3A00%3A00.000Z&processor=B"),
    );
    expect(res.status).toBe(200);
    expect(lastCall().url).toBe("http://api.test:8000/analytics?from=2026-11-02T16%3A00%3A00.000Z&processor=B");
    expect(new Headers(lastCall().init.headers).get("x-api-key")).toBe(SENTINEL);
    expect(res.headers.get("cache-control")).toBe("no-store");
    const text = await res.text();
    expect(text).not.toContain(SENTINEL);
    expect(JSON.parse(text)).toEqual(analyticsData);
  });

  it("passes a 422 from the api through unchanged", async () => {
    const err = { error: { code: "validation_failed", message: "bad", correlation_id: "c" } };
    fetchMock.mockResolvedValue(upstreamJson(err, 422));
    const res = await getAnalytics(new Request("http://localhost:3000/api/analytics?processor=C"));
    expect(res.status).toBe(422);
    expect(await res.json()).toEqual(err);
  });

  it("answers 503 in the shared shape when the api is unreachable", async () => {
    fetchMock.mockRejectedValue(new Error("down"));
    const res = await getAnalytics(new Request("http://localhost:3000/api/analytics"));
    expect(res.status).toBe(503);
    expect((await res.json()).error.code).toBe("dependency_unavailable");
  });
});

describe("GET /api/analytics/baseline", () => {
  it("fetches the baseline with the key", async () => {
    fetchMock.mockResolvedValue(upstreamJson(baselineData));
    const res = await getBaseline();
    expect(res.status).toBe(200);
    expect(lastCall().url).toBe("http://api.test:8000/analytics/baseline");
    expect(new Headers(lastCall().init.headers).get("x-api-key")).toBe(SENTINEL);
    expect(await res.text()).not.toContain(SENTINEL);
  });
});
