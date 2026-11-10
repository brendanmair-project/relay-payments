import { errorResponse, forwardToSimulator } from "../../../lib/upstream";

export const dynamic = "force-dynamic";

// Read-only outage flags for the demo control (REL-28). Profiles are not exposed to the browser.
export async function GET() {
  const res = await forwardToSimulator("/control/processors");
  if (!res.ok) return res;
  try {
    const { processors } = (await res.json()) as { processors: Record<"a" | "b", { outage: unknown }> };
    if (typeof processors.a.outage !== "boolean" || typeof processors.b.outage !== "boolean") throw new Error("shape");
    return Response.json(
      { processors: { a: { outage: processors.a.outage }, b: { outage: processors.b.outage } } },
      { headers: { "cache-control": "no-store" } },
    );
  } catch {
    return errorResponse(502, "bad_gateway", "The simulator answered with an unexpected body");
  }
}
