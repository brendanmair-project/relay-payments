import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PaymentDetail from "./PaymentDetail";

const ID = "00000000-0000-4000-8000-000000000042";

const event = (seq: number, type: string, extra: Record<string, unknown> = {}) => ({
  seq,
  type,
  attempt_no: 1,
  from_status: null,
  to_status: null,
  processor: null,
  reason: null,
  data: {},
  occurred_at: `2026-10-01T14:03:2${seq}.000Z`,
  ...extra,
});

const retried = {
  id: ID,
  amount_minor: 1999,
  currency: "USD",
  description: null,
  reference: null,
  status: "captured",
  display_status: "Captured",
  attempt_no: 2,
  is_final: true,
  processor: "B",
  created_at: "2026-10-01T14:03:20.000Z",
  status_changed_at: "2026-10-01T14:03:29.000Z",
  final_at: "2026-10-01T14:03:29.000Z",
  events: [
    event(1, "payment.received", { attempt_no: 0 }),
    event(2, "payment.routed", { processor: "A", reason: "initial" }),
    event(3, "payment.failed", { processor: "A", reason: "timeout" }),
    event(4, "payment.routed", { attempt_no: 2, processor: "B", reason: "failover" }),
    event(5, "payment.captured", { attempt_no: 2, processor: "B" }),
  ],
};
const firstTime = { ...retried, attempt_no: 1, processor: "A", events: retried.events.slice(0, 2) };
const retrying = { ...retried, status: "failed", display_status: "Retrying", is_final: false, final_at: null };

const explanation = {
  payment_id: ID,
  source: "model",
  model: "granite3.3:2b",
  text: "The first attempt timed out and the retry was captured.",
  cited_event_seqs: [3, 5],
  trigger: "on_request",
  generated_at: "2026-10-01T14:03:40.000Z",
  fallback_reason: null,
};
const health = {
  strategy: "rules",
  window_seconds: 60,
  error_threshold: 0.5,
  processors: [
    { name: "A", attempts: 41, errors: 30, error_rate: 0.73, state: "avoided" },
    { name: "B", attempts: 12, errors: 0, error_rate: 0, state: "preferred" },
  ],
  computed_at: "2026-10-01T14:04:00.000Z",
};

type Reply = { status?: number; body?: unknown } | "hang" | "throw";
function stub(routes: Record<string, Reply>) {
  const fn = vi.fn((url: string) => {
    const reply = routes[url.split("?")[0]] ?? { status: 404, body: {} };
    if (reply === "hang") return new Promise(() => {});
    if (reply === "throw") return Promise.reject(new Error("network"));
    const status = reply.status ?? 200;
    return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(reply.body) });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}
const P = `/api/payments/${ID}`;
const X = `${P}/explanation`;
const H = "/api/processors/health";
const asked = (fn: ReturnType<typeof stub>) => fn.mock.calls.some(([u]) => String(u).includes("/explanation"));

beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("PaymentDetail", () => {
  it("shows header, attempts with processors and the ordered timeline", async () => {
    stub({ [P]: { body: retried }, [X]: { body: explanation }, [H]: { body: health } });
    render(<PaymentDetail id={ID} />);
    expect(await screen.findByText(ID)).toBeInTheDocument();
    expect(screen.getByText("$19.99")).toBeInTheDocument();
    expect(screen.getByText("Captured")).toBeInTheDocument();
    const attempts = screen.getByRole("region", { name: /attempts/i });
    expect(within(attempts).getByText(/attempt 1/i)).toHaveTextContent(/processor A/i);
    expect(within(attempts).getByText(/attempt 2/i)).toHaveTextContent(/processor B/i);
    const items = within(screen.getByRole("list", { name: /timeline/i })).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[0]).toHaveTextContent("payment.received");
    expect(items[0]).toHaveTextContent("2026-10-01 14:03:21Z");
    expect(items[4]).toHaveTextContent("payment.captured");
  });

  it("labels an adaptive routing in words in the timeline", async () => {
    const adaptive = {
      ...retried,
      attempt_no: 1,
      processor: "B",
      events: [
        event(1, "payment.received", { attempt_no: 0 }),
        event(2, "payment.routed", { processor: "B", reason: "adaptive" }),
        event(3, "payment.captured", { processor: "B" }),
      ],
    };
    stub({ [P]: { body: adaptive }, [X]: { body: explanation }, [H]: { body: health } });
    render(<PaymentDetail id={ID} />);
    const items = within(await screen.findByRole("list", { name: /timeline/i })).getAllByRole("listitem");
    expect(items[1]).toHaveTextContent("payment.routed processor B (adaptive: chosen from recent processor outcomes)");
    expect(items[2]).not.toHaveTextContent("adaptive");
  });

  it("labels each attempt with its outcome, not the payment's later events", async () => {
    // Event order as the live API returns it for a timeout on A then a decline on B.
    const declinedAfterRetry = {
      ...retried,
      status: "declined",
      display_status: "Declined",
      events: [
        event(1, "payment.received", { attempt_no: 0 }),
        event(2, "payment.routed", { processor: "A", reason: "initial" }),
        event(3, "attempt.authorize_result", { processor: "A", reason: "timeout" }),
        event(4, "payment.failed", { processor: "A", reason: "timeout" }),
        event(5, "payment.retry_scheduled"),
        event(6, "payment.routed", { attempt_no: 2, processor: "B", reason: "retry" }),
        event(7, "attempt.authorize_result", { attempt_no: 2, processor: "B", reason: "card_expired" }),
        event(8, "payment.declined", { attempt_no: 2, reason: "card_expired" }),
        event(9, "payment.final", { attempt_no: 2 }),
        event(10, "payment.explained", { attempt_no: 2 }),
      ],
    };
    stub({ [P]: { body: declinedAfterRetry }, [X]: { body: explanation }, [H]: { body: health } });
    render(<PaymentDetail id={ID} />);
    const attempts = await screen.findByRole("region", { name: /attempts/i });
    expect(within(attempts).getByText(/attempt 1/i)).toHaveTextContent("Attempt 1 on processor A: failed (timeout)");
    expect(within(attempts).getByText(/attempt 2/i)).toHaveTextContent(
      "Attempt 2 on processor B: declined (card_expired)",
    );
  });

  it("shows the model explanation with model name and generation time", async () => {
    stub({ [P]: { body: retried }, [X]: { body: explanation }, [H]: { body: health } });
    render(<PaymentDetail id={ID} />);
    expect(await screen.findByText(explanation.text)).toBeInTheDocument();
    expect(screen.getByText(/Model: granite3\.3:2b/)).toBeInTheDocument();
    expect(screen.getByText(/2026-10-01 14:03:40Z/)).toBeInTheDocument();
  });

  it("labels rules text as rule-based and explains a cause_mismatch fallback in words", async () => {
    const rules = { ...explanation, source: "rules", model: null, fallback_reason: "cause_mismatch" };
    stub({ [P]: { body: retried }, [X]: { body: rules }, [H]: { body: health } });
    render(<PaymentDetail id={ID} />);
    expect(await screen.findByText(/Rule-based/)).toBeInTheDocument();
    expect(screen.getByText(/the model's cause disagreed with the rules/i)).toBeInTheDocument();
    expect(screen.queryByText(/Model: /)).not.toBeInTheDocument();
  });

  it("shows the current health of both processors with text states", async () => {
    stub({ [P]: { body: retried }, [X]: { body: explanation }, [H]: { body: health } });
    render(<PaymentDetail id={ID} />);
    const region = await screen.findByRole("region", { name: /processor health/i });
    await waitFor(() => expect(within(region).getByText(/Avoided/)).toBeInTheDocument());
    expect(within(region).getByText(/Preferred/)).toBeInTheDocument();
    expect(within(region).getByText(/73%/)).toBeInTheDocument();
  });

  it("says health is unavailable when the health fetch fails", async () => {
    stub({ [P]: { body: retried }, [X]: { body: explanation }, [H]: "throw" });
    render(<PaymentDetail id={ID} />);
    expect(await screen.findByText(/processor health is unavailable/i)).toBeInTheDocument();
  });

  it("shows a not-found state for an unknown payment and requests no explanation", async () => {
    const fn = stub({ [P]: { status: 404, body: { error: { code: "not_found" } } }, [H]: { body: health } });
    render(<PaymentDetail id={ID} />);
    expect(await screen.findByText(/payment not found/i)).toBeInTheDocument();
    expect(asked(fn)).toBe(false);
  });

  it("shows an error with a working retry when the fetch fails", async () => {
    stub({ [P]: "throw", [H]: { body: health } });
    render(<PaymentDetail id={ID} />);
    expect(await screen.findByText(/could not load this payment/i)).toBeInTheDocument();
    stub({ [P]: { body: firstTime }, [H]: { body: health } });
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText(ID)).toBeInTheDocument();
  });

  it("shows a pending message while the explanation is slow", async () => {
    stub({ [P]: { body: retried }, [X]: "hang", [H]: { body: health } });
    render(<PaymentDetail id={ID} />);
    expect(await screen.findByText(/generating the explanation/i)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: /timeline/i })).toBeInTheDocument();
  });

  it("says the explanation comes after the payment finishes on 409", async () => {
    stub({
      [P]: { body: retrying },
      [X]: { status: 409, body: { error: { code: "payment_not_final" } } },
      [H]: { body: health },
    });
    render(<PaymentDetail id={ID} />);
    expect(await screen.findByText(/explanation after the payment finishes/i)).toBeInTheDocument();
    expect(screen.getByText("Retrying")).toBeInTheDocument();
  });

  it("shows an explanation error with retry", async () => {
    stub({ [P]: { body: retried }, [X]: { status: 503, body: {} }, [H]: { body: health } });
    render(<PaymentDetail id={ID} />);
    expect(await screen.findByText(/could not load the explanation/i)).toBeInTheDocument();
    stub({ [P]: { body: retried }, [X]: { body: explanation }, [H]: { body: health } });
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText(explanation.text)).toBeInTheDocument();
  });

  it("does not request an explanation for a payment captured on the first attempt", async () => {
    const fn = stub({ [P]: { body: firstTime }, [H]: { body: health } });
    render(<PaymentDetail id={ID} />);
    expect(await screen.findByText(ID)).toBeInTheDocument();
    expect(await screen.findByText(/no explanation needed/i)).toBeInTheDocument();
    expect(asked(fn)).toBe(false);
  });

  it("requests an explanation for a declined payment", async () => {
    const declined = { ...firstTime, status: "declined", display_status: "Declined" };
    const fn = stub({ [P]: { body: declined }, [X]: { body: explanation }, [H]: { body: health } });
    render(<PaymentDetail id={ID} />);
    expect(await screen.findByText(explanation.text)).toBeInTheDocument();
    expect(asked(fn)).toBe(true);
  });
});
