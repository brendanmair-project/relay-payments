import type { Payment } from "./types";

/**
 * Formats integer minor units for a currency without floating point: the digits are split as a
 * decimal string, which Intl.NumberFormat formats exactly. JPY has 0 decimals, USD/EUR/GBP 2.
 */
export function formatAmount(amountMinor: number, currency: string): string {
  try {
    const nf = new Intl.NumberFormat("en-US", { style: "currency", currency });
    const decimals = nf.resolvedOptions().maximumFractionDigits ?? 2;
    const digits = BigInt(amountMinor)
      .toString()
      .padStart(decimals + 1, "0");
    const split = digits.length - decimals;
    const decimal = decimals === 0 ? digits : `${digits.slice(0, split)}.${digits.slice(split)}`;
    // TS lib es2022 lacks the string overload (ES2023 Intl); Node and browsers accept decimal strings.
    return nf.format(decimal as unknown as number);
  } catch {
    return `${amountMinor} ${currency} (minor units)`;
  }
}

/** "2026-10-01T14:03:22.418Z" -> "2026-10-01 14:03:22Z"; UTC so it is the same everywhere. */
export function formatTime(iso: string | null): string {
  if (!iso) return "-";
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return "-";
  return `${t.toISOString().slice(0, 19).replace("T", " ")}Z`;
}

/** Plain words for a stored fallback_reason; shared by the payment explanation and the incident summary. */
export const FALLBACK_WORDS: Record<string, string> = {
  cause_mismatch: "the model's cause disagreed with the rules",
  model_timeout: "the model took too long to answer",
  model_unreachable: "the model could not be reached",
  model_error: "the model returned an error",
  citation_check_failed: "the model's answer did not cite the timeline correctly",
  no_linked_events: "no failed payments were linked to this incident, so the model was not asked",
};

/** Plain words for a routed reason that is more than a code; the label is text, never colour (AGENTS.md). */
const ROUTED_REASON_WORDS: Record<string, string> = {
  adaptive: "adaptive: chosen from recent processor outcomes",
};

/** The suffix after an event type in a timeline line: the stored reason in brackets, in words where one exists. */
export function reasonText(type: string, reason: string | null): string {
  if (!reason) return "";
  const words = type === "payment.routed" ? ROUTED_REASON_WORDS[reason] : undefined;
  return ` (${words ?? reason})`;
}

/** The API derives display_status (a non-final failed payment is "Retrying"); the UI shows it as is. */
export function statusLabel(p: Payment): string {
  return p.display_status;
}
