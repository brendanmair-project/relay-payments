import { forwardToApi } from "../../../lib/upstream";

export const dynamic = "force-dynamic";

export async function GET() {
  return forwardToApi("/processors/health");
}
