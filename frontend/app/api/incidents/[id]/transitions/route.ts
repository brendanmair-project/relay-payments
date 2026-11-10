import { errorResponse, forwardToApi, isSameOrigin } from "../../../../lib/upstream";

export const dynamic = "force-dynamic";

// Only POST is exported: Next.js answers 405 to every other method. The API enforces the allowed moves
// (detected to triaged, triaged to resolved) and answers 409 otherwise; this route only checks the shape.
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!isSameOrigin(request)) return errorResponse(403, "forbidden_origin", "Cross-origin requests are not allowed");
  let to: unknown;
  try {
    to = ((await request.json()) as { to?: unknown }).to;
  } catch {
    return errorResponse(400, "malformed_request", "Body must be JSON");
  }
  if (to !== "triaged" && to !== "resolved")
    return errorResponse(422, "validation_failed", "to must be triaged or resolved");
  const { id } = await params;
  return forwardToApi(`/incidents/${encodeURIComponent(id)}/transitions`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ to }),
  });
}
