import { forwardToApi } from "../../lib/upstream";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  return forwardToApi(`/payments${new URL(request.url).search}`);
}
