import { errorResponse, forwardToSimulator, isSameOrigin } from "../../../lib/upstream";

export const dynamic = "force-dynamic";

// Only POST is exported: Next.js answers 405 to every other method. The UI control is REL-28.
export async function POST(request: Request) {
  if (!isSameOrigin(request)) return errorResponse(403, "forbidden_origin", "Cross-origin requests are not allowed");
  let enabled: unknown;
  try {
    enabled = ((await request.json()) as { enabled?: unknown }).enabled;
  } catch {
    return errorResponse(400, "malformed_request", "Body must be JSON");
  }
  if (typeof enabled !== "boolean") return errorResponse(422, "validation_failed", "enabled must be true or false");
  // The demo outage is on Processor A (REL-28).
  return forwardToSimulator("/control/processors/a/outage", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
}
