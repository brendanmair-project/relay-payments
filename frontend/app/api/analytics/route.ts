import { forwardToApi } from "../../lib/upstream";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  return forwardToApi(`/analytics${new URL(request.url).search}`);
}
