// @vitest-environment node
import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { config, isAllowedHost, proxy } from "./proxy";

function req(host: string | null, path = "/api/payments") {
  const headers = new Headers();
  if (host !== null) headers.set("host", host);
  return new NextRequest(`http://localhost:3000${path}`, { headers });
}

describe("isAllowedHost", () => {
  it.each(["localhost", "localhost:3000", "127.0.0.1", "127.0.0.1:3000", "127.0.0.1:8080", "LOCALHOST:3000"])(
    "allows %s",
    (host) => {
      expect(isAllowedHost(host)).toBe(true);
    },
  );

  it.each([
    "evil.example",
    "evil.example:3000",
    "localhost.evil.example",
    "localhost.evil.example:3000",
    "127.0.0.1.evil.example",
    "0.0.0.0:3000",
    "192.168.1.5:3000",
    "[::1]:3000",
    "localhost:3000@evil.example",
    "evil.example/localhost",
    "localhost:abc",
    "",
    null,
  ])("rejects %s", (host) => {
    expect(isAllowedHost(host)).toBe(false);
  });
});

describe("proxy", () => {
  it("answers 403 for a foreign Host", async () => {
    const res = proxy(req("rebind.example:3000"));
    expect(res.status).toBe(403);
    const body = await res.json();
    expect(body.error.code).toBe("forbidden_host");
  });

  it("answers 403 when the Host header is missing", () => {
    expect(proxy(req(null)).status).toBe(403);
  });

  it("lets localhost and 127.0.0.1 through", () => {
    for (const host of ["localhost:3000", "127.0.0.1:3000"]) {
      const res = proxy(req(host));
      expect(res.status).toBe(200);
      expect(res.headers.get("x-middleware-next")).toBe("1");
    }
  });

  it("guards every server route under /api", () => {
    expect(config.matcher).toContain("/api/:path*");
  });
});
