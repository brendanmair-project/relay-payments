import { errorResponse, forwardToSimulator, isSameOrigin } from "../../../lib/upstream";

export const dynamic = "force-dynamic";

// REL-66 story mode. POST starts and DELETE stops the seeded outage run on the simulator; both are same-origin only
// (ADR-0012, like the outage switch). GET reads the status. The browser gets only the whitelisted status fields:
// never the key and never a processor profile. Only these three methods are exported: Next.js answers 405 to others.
const STATES = ["idle", "running", "stopping", "finished", "stopped", "failed"];

type Status = {
  state: string;
  phase: string | null;
  sent: number;
  total: number;
  switches: { processor: string; outage: boolean; at: string }[];
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
};

const text = (v: unknown): string | null => (typeof v === "string" ? v : null);

function whitelist(body: unknown): Status {
  const b = body as Record<string, unknown>;
  if (typeof b?.state !== "string" || !STATES.includes(b.state)) throw new Error("shape");
  if (typeof b.sent !== "number" || typeof b.total !== "number" || !Array.isArray(b.switches)) throw new Error("shape");
  const switches = b.switches.map((s: Record<string, unknown>) => {
    if (typeof s.processor !== "string" || typeof s.outage !== "boolean" || typeof s.at !== "string")
      throw new Error("shape");
    return { processor: s.processor, outage: s.outage, at: s.at };
  });
  return {
    state: b.state,
    phase: text(b.phase),
    sent: b.sent,
    total: b.total,
    switches,
    started_at: text(b.started_at),
    finished_at: text(b.finished_at),
    error_code: text(b.error_code),
  };
}

// Passes an error (409 run_in_progress, 503, ...) through unchanged; checks and trims a successful status.
async function status(res: Response): Promise<Response> {
  if (!res.ok) return res;
  try {
    return Response.json(whitelist(await res.json()), { status: res.status, headers: { "cache-control": "no-store" } });
  } catch {
    return errorResponse(502, "bad_gateway", "The simulator answered with an unexpected body");
  }
}

const forbidden = () => errorResponse(403, "forbidden_origin", "Cross-origin requests are not allowed");

export async function GET() {
  return status(await forwardToSimulator("/control/story/run"));
}

export async function POST(request: Request) {
  if (!isSameOrigin(request)) return forbidden();
  return status(await forwardToSimulator("/control/story/run", { method: "POST" }));
}

export async function DELETE(request: Request) {
  if (!isSameOrigin(request)) return forbidden();
  return status(await forwardToSimulator("/control/story/run", { method: "DELETE" }));
}
