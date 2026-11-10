import { forwardToApi } from "../../../../lib/upstream";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return forwardToApi(`/payments/${encodeURIComponent(id)}/explanation`);
}
