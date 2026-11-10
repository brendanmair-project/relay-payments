import { errorResponse, forwardToApi, isSameOrigin } from "../../../../../lib/upstream";

export const dynamic = "force-dynamic";

// Only POST is exported: Next.js answers 405 to every other method.
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!isSameOrigin(request)) return errorResponse(403, "forbidden_origin", "Cross-origin requests are not allowed");
  const { id } = await params;
  return forwardToApi(`/incidents/${encodeURIComponent(id)}/summary/regenerate`, { method: "POST" });
}
