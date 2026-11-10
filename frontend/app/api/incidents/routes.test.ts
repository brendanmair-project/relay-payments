// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GET as getList } from "./route";
import { GET as getOne } from "./[id]/route";
import { GET as getSummary } from "./[id]/summary/route";
import { POST as regenerate } from "./[id]/summary/regenerate/route";
import * as transitions from "./[id]/transitions/route";
import * as regenerateModule from "./[id]/summary/regenerate/route";
import { INCIDENT_ID, detected, detail } from "../../../tests/fixtures/incidents";

const SENTINEL = "relay-test-sentinel";
const fetchMock = vi.fn();
const params = { params: Promise.resolve({ id: INCIDENT_ID }) };

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

function post(path: string, headers: Record<string, string>, body: unknown = { to: "triaged" }) {
  return new Request(`http://localhost:3000${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", host: "localhost:3000", ...headers },
    body: JSON.stringify(body),
  });
}

describe("GET incident routes", () => {
  it("lists incidents with the query string and the key", async () => {
    fetchMock.mockResolvedValue(upstreamJson({ items: [detected] }));
    const res = await getList(new Request("http://localhost:3000/api/incidents?limit=20&status=detected"));
    expect(res.status).toBe(200);
    expect(lastCall().url).toBe("http://api.test:8000/incidents?limit=20&status=detected");
    expect(new Headers(lastCall().init.headers).get("x-api-key")).toBe(SENTINEL);
    expect(await res.text()).not.toContain(SENTINEL);
  });

  it("fetches one incident and encodes the id", async () => {
    fetchMock.mockResolvedValue(upstreamJson(detail(detected)));
    await getOne(new Request("http://localhost:3000/x"), params);
    expect(lastCall().url).toBe(`http://api.test:8000/incidents/${INCIDENT_ID}`);
    await getOne(new Request("http://localhost:3000/x"), { params: Promise.resolve({ id: "../health" }) });
    expect(lastCall().url).toBe("http://api.test:8000/incidents/..%2Fhealth");
  });

  it("fetches the summary and passes a 404 through", async () => {
    const err = { error: { code: "not_found", message: "x", correlation_id: "c" } };
    fetchMock.mockResolvedValue(upstreamJson(err, 404));
    const res = await getSummary(new Request("http://localhost:3000/x"), params);
    expect(res.status).toBe(404);
    expect(lastCall().url).toBe(`http://api.test:8000/incidents/${INCIDENT_ID}/summary`);
  });
});

describe("POST /api/incidents/[id]/transitions", () => {
  const path = `/api/incidents/${INCIDENT_ID}/transitions`;

  it("forwards a same-origin POST with the key", async () => {
    fetchMock.mockResolvedValue(upstreamJson({ ...detected, status: "triaged" }));
    const res = await transitions.POST(post(path, { "sec-fetch-site": "same-origin" }), params);
    expect(res.status).toBe(200);
    const { url, init } = lastCall();
    expect(url).toBe(`http://api.test:8000/incidents/${INCIDENT_ID}/transitions`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ to: "triaged" });
    expect(new Headers(init.headers).get("x-api-key")).toBe(SENTINEL);
  });

  it.each([
    ["cross-site", { "sec-fetch-site": "cross-site" }],
    ["foreign Origin", { origin: "http://evil.example" }],
    ["no origin information", {}],
  ])("rejects %s with 403 and calls nothing", async (_n, headers) => {
    const res = await transitions.POST(post(path, headers), params);
    expect(res.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a body other than triaged or resolved with 422", async () => {
    const res = await transitions.POST(post(path, { "sec-fetch-site": "same-origin" }, { to: "detected" }), params);
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("passes the API's 409 through unchanged", async () => {
    const err = { error: { code: "invalid_incident_transition", message: "no", correlation_id: "c" } };
    fetchMock.mockResolvedValue(upstreamJson(err, 409));
    const res = await transitions.POST(post(path, { "sec-fetch-site": "same-origin" }, { to: "resolved" }), params);
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual(err);
  });

  it("exports only POST", () => {
    const mod = transitions as Record<string, unknown>;
    expect([mod.GET, mod.PUT, mod.DELETE]).toEqual([undefined, undefined, undefined]);
  });
});

describe("POST /api/incidents/[id]/summary/regenerate", () => {
  const path = `/api/incidents/${INCIDENT_ID}/summary/regenerate`;

  it("forwards a same-origin POST", async () => {
    fetchMock.mockResolvedValue(upstreamJson({ incident_id: INCIDENT_ID }, 201));
    const res = await regenerate(post(path, { "sec-fetch-site": "same-origin" }), params);
    expect(res.status).toBe(201);
    expect(lastCall().url).toBe(`http://api.test:8000/incidents/${INCIDENT_ID}/summary/regenerate`);
    expect(lastCall().init.method).toBe("POST");
  });

  it("rejects a cross-site POST with 403", async () => {
    const res = await regenerate(post(path, { "sec-fetch-site": "cross-site" }), params);
    expect(res.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("exports only POST", () => {
    expect((regenerateModule as Record<string, unknown>).GET).toBeUndefined();
  });
});
