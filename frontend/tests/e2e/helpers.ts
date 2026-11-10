// Node-side helpers: they talk to the api and the simulator control API directly, never from the browser.
import { randomUUID } from "node:crypto";

export const API = "http://localhost:8000";
export const SIM = "http://localhost:8101";

export function apiKey(): string {
  const value = process.env.RELAY_API_KEY;
  if (!value) throw new Error("RELAY_API_KEY must be set in the environment");
  return value;
}

const keyHeader = () => ({ "X-API-Key": apiKey() });

// Default synthetic profiles from docs/architecture/api-contract.md.
const DEFAULTS = {
  a: { latency_ms_p50: 120, latency_ms_p95: 400, decline_rate: 0.1, timeout_rate: 0.02, capture_failure_rate: 0.01 },
  b: { latency_ms_p50: 250, latency_ms_p95: 800, decline_rate: 0.08, timeout_rate: 0.01, capture_failure_rate: 0.01 },
};

async function putProfile(name: "a" | "b", body: object): Promise<void> {
  const res = await fetch(`${SIM}/control/processors/${name}/profile`, {
    method: "PUT",
    headers: { ...keyHeader(), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`profile ${name}: ${res.status}`);
}

export async function declineEverything(): Promise<void> {
  const profile = { ...DEFAULTS.a, decline_rate: 1, timeout_rate: 0, capture_failure_rate: 0 };
  await putProfile("a", profile);
  await putProfile("b", {
    ...profile,
    latency_ms_p50: DEFAULTS.b.latency_ms_p50,
    latency_ms_p95: DEFAULTS.b.latency_ms_p95,
  });
}

export async function restoreProfiles(): Promise<void> {
  await putProfile("a", DEFAULTS.a);
  await putProfile("b", DEFAULTS.b);
}

export async function createPayment(): Promise<string> {
  const res = await fetch(`${API}/payments`, {
    method: "POST",
    headers: { ...keyHeader(), "Idempotency-Key": randomUUID(), "Content-Type": "application/json" },
    body: JSON.stringify({ amount_minor: 4200, currency: "USD", description: "e2e order" }),
  });
  if (res.status !== 201) throw new Error(`create payment: ${res.status}`);
  return ((await res.json()) as { id: string }).id;
}

export async function waitForFinal(id: string, timeoutMs = 60_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = await fetch(`${API}/payments/${id}`, { headers: keyHeader() });
    if (res.ok && ((await res.json()) as { is_final: boolean }).is_final) return;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`payment ${id} did not become final in ${timeoutMs} ms`);
}

export type IncidentRow = { id: string; processor: string | null; status: string; title: string };

async function transition(id: string, to: "triaged" | "resolved"): Promise<void> {
  const res = await fetch(`${API}/incidents/${id}/transitions`, {
    method: "POST",
    headers: { ...keyHeader(), "Content-Type": "application/json" },
    body: JSON.stringify({ to }),
  });
  if (!res.ok) throw new Error(`transition ${id} to ${to}: ${res.status}`);
}

/** Resolves every open incident of a processor, so a manual one can be opened for it (one open per processor). */
export async function resolveOpenIncidents(processor: "A" | "B"): Promise<void> {
  const res = await fetch(`${API}/incidents?processor=${processor}&limit=100`, { headers: keyHeader() });
  if (!res.ok) throw new Error(`list incidents: ${res.status}`);
  for (const item of ((await res.json()) as { items: IncidentRow[] }).items) {
    if (item.status === "detected") await transition(item.id, "triaged");
    if (item.status !== "resolved") await transition(item.id, "resolved");
  }
}

/** Opens a manual incident through the API from the test process. */
export async function createIncident(processor: "A" | "B" | null, title: string): Promise<IncidentRow> {
  const res = await fetch(`${API}/incidents`, {
    method: "POST",
    headers: { ...keyHeader(), "Content-Type": "application/json" },
    body: JSON.stringify({ processor, title }),
  });
  if (res.status !== 201) throw new Error(`create incident: ${res.status}`);
  return (await res.json()) as IncidentRow;
}
