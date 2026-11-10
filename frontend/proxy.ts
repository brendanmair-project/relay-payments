// Next.js 16 request guard (the former middleware). Every server route under /api answers only
// localhost or 127.0.0.1 hosts (any port), which blocks DNS rebinding (ADR-0012).
import { NextResponse, type NextRequest } from "next/server";

const ALLOWED = new Set(["localhost", "127.0.0.1"]);

export function isAllowedHost(host: string | null): boolean {
  if (!host) return false;
  const m = /^([a-z0-9.-]+)(?::(\d{1,5}))?$/i.exec(host.trim());
  return m !== null && ALLOWED.has(m[1].toLowerCase());
}

export function proxy(request: NextRequest) {
  if (!isAllowedHost(request.headers.get("host"))) {
    return NextResponse.json(
      { error: { code: "forbidden_host", message: "Host not allowed", correlation_id: "frontend" } },
      { status: 403 },
    );
  }
  return NextResponse.next();
}

export const config = { matcher: ["/api/:path*"] };
