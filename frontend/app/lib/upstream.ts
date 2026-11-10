// Server-only: reads the API key and upstream URLs from the server environment (ADR-0009).
// Never import this from a client component.

export function errorResponse(status: number, code: string, message: string): Response {
  return Response.json(
    { error: { code, message, correlation_id: "frontend" } },
    { status, headers: { "cache-control": "no-store" } },
  );
}

// Same-origin check (api-contract.md, ADR-0012): Sec-Fetch-Site must be "same-origin", or, when the
// browser sends no fetch metadata, Origin must equal the origin the request was made to.
export function isSameOrigin(request: Request): boolean {
  const site = request.headers.get("sec-fetch-site");
  if (site !== null) return site === "same-origin";
  const origin = request.headers.get("origin");
  return origin !== null && origin === new URL(request.url).origin;
}

async function forward(base: string | undefined, path: string, init: RequestInit = {}): Promise<Response> {
  if (!base) return errorResponse(503, "dependency_unavailable", "The server is not configured for this route");
  const headers = new Headers(init.headers);
  headers.set("x-api-key", process.env.RELAY_API_KEY ?? "");
  headers.set("accept", "application/json");
  try {
    const res = await fetch(`${base.replace(/\/+$/, "")}${path}`, { ...init, headers, cache: "no-store" });
    const body = await res.text();
    return new Response(body, {
      status: res.status,
      headers: {
        "content-type": res.headers.get("content-type") ?? "application/json",
        "cache-control": "no-store",
      },
    });
  } catch {
    return errorResponse(503, "dependency_unavailable", "The upstream service is unreachable");
  }
}

export const forwardToApi = (path: string, init?: RequestInit) => forward(process.env.API_URL, path, init);

export const forwardToSimulator = (path: string, init?: RequestInit) =>
  forward(process.env.SIMULATOR_CONTROL_URL, path, init);
