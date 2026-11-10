import { forwardToApi } from "../../lib/upstream";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  return forwardToApi(`/incidents${new URL(request.url).search}`);
}
