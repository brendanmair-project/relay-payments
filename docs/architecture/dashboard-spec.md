# Payments list dashboard specification

Template: claude/dashboard@1

Status: Active (REL-26)  
Owner: Brendan  
Last reviewed: 2026-10-29  
Review due: 2026-11-29

## Decision question

This dashboard answers: **Which payments are failing, stuck or being retried right now, and on which processor?**

Expected action when the answer is abnormal: open the payment (detail view, REL-27) to read its timeline and explanation; if one processor shows many Retrying or Failed rows, check processor health and, in the demo, use the outage controls (REL-28).

## Audience and use moment

- Primary audience: a payment analyst (or the demo viewer playing one) who triages failed and stuck payments for one merchant.
- Used during: live triage and the scripted outage demo, with the page left open in a browser tab.
- Expected comprehension time: under 5 seconds to see the newest payments and any Retrying or Failed rows.

Design direction (project `AGENTS.md`): dense, restrained, trustworthy. Monospace for payment ids, amounts and timestamps. Status is always a text label (never color alone). No decorative motion; motion only in response to a user action.

## Data sources and freshness

| Source | Authority | Refresh | Stale after | Failure behavior |
|---|---|---|---|---|
| `GET /api/payments?limit=20` (frontend server route, proxies `GET /payments` on the api) | PostgreSQL via the api (`payments` table) | Every 5 seconds while the tab is visible | 15 seconds without a successful refresh | Keep the last rows, mark them stale, show the error banner; keep retrying every 5 seconds |

Display `Last updated: <time in UTC, HH:MM:SS>` and the refresh status ("Live", "Stale" or "Error") in the interface. The refresh interval is fixed at 5 seconds; the browser never calls the api directly and never holds the API key (ADR-0009).

## At-a-glance summary

| Signal | Meaning | Healthy | Warning | Critical |
|---|---|---|---|---|
| Refresh status | Is the list current? | Live: last success within 15 s | Stale: 15 s or more since the last success | Error: the last request failed |
| Retrying count (rows in view) | Are payments being retried? | 0 | 1 or more | Not thresholded in Phase 1 |

Counts are for the rows in view only (latest 20). Both signals are text, not color alone.

## Primary signals

### Latest payments

- Question: What happened to the most recent payments?
- Measure and unit: one row per payment: id, status label, processor (A, B or a dash before routing), amount (formatted from integer minor units and currency), attempt number, time of last status change (UTC).
- Time range and comparison: the latest 20 payments, newest first; no comparison in Phase 1.
- Visualization: a dense table. A table fits exact ids and amounts that analysts copy; a chart would hide them.
- Text alternative/table: the table is the text form; each status is a text label (Received, Processing, Retrying, Captured, Declined, Failed) from the API's `display_status`. A failed payment that is not final shows as Retrying.
- Source/query: `GET /api/payments?limit=20`, which calls `GET /payments?limit=20` ([api-contract.md](api-contract.md)).
- Drill-down: the payment id links to the detail view when REL-27 adds it; until then it is plain text.

### Incidents list (REL-36)

- Question: Which processor incidents are open or recent, and how far along is each?
- Measure and unit: one row per incident: title (links to the detail), status as a text label (Detected, Triaged, Resolved), processor (A, B or a dash for a manual incident without one), source (Rule or Manual), opened, recovered and resolved times (UTC, monospace, a dash when not set) and the affected payment count.
- Time range and comparison: the latest 20 incidents, newest first by `opened_at`; refreshed every 5 s like the payments list.
- Visualization: a dense table, for the same reason as the payments table. Triaged is drawn with a double border and Detected with a plain one, so status never relies on colour.
- Text alternative/table: the table is the text form.
- Source/query: `GET /api/incidents?limit=20` (calls `GET /incidents`). Each row of the response carries `affected_count` (REL-57), so the page makes exactly one request per refresh and no per-incident detail request.
- Drill-down: the title links to `/incidents/<id>`; the payments list header links to `/incidents`.

### Incident detail (REL-36)

- Question: What happened in this incident, which payments did it hit, and what should the analyst do next?
- Measure and unit: title, status label, processor, source in words ("Detected by the router rule", "Opened by hand"), opened, triaged, recovered and resolved times (UTC, monospace); the summary with its source label (Rule-based or Model: name), generation time and, when the rules text was stored, the reason in plain words (`citation_check_failed`, `model_timeout`, `model_unreachable`, `model_error`, `cause_mismatch`, `no_linked_events`; the same wording as the payment explanation, REL-27); the affected payments (id linking to `/payments/<id>`, amount, status, processor), 20 per page with "Previous page" and "Next page" buttons and a text status ("Page 2 of 3, payments 21 to 40 of 45"; no pager when everything fits on one page; sliced client-side from the one detail response, see `api-contract.md`), each payment's incident events (`#id type processor (reason)`) collapsed by default in a `<details>` whose summary reads "Events (n)" and is named "Events of payment <id> (n)".
- Actions: only the valid next action shows. "Triage" when the status is detected, "Resolve" when triaged, nothing when resolved. While a request runs the button is disabled and reads "Triage..." or "Resolve...". An error from the API (for example 409) appears as plain text in an alert; after success the incident is read again. "Regenerate summary" calls the regenerate route.
- Source/query: `GET /api/incidents/{id}`, `GET /api/incidents/{id}/summary`, `POST /api/incidents/{id}/transitions` and `POST /api/incidents/{id}/summary/regenerate`. Every POST accepts only same-origin requests (ADR-0012) and the host guard covers `/api`; the key stays on the server.
- States: loading ("Loading incident..."), not found ("Incident not found. Check the id or return to the list."), error (message and Retry). The summary has its own loading text because the model can take seconds.

### Analytics (REL-37)

- Question: How are the two processors doing over a chosen period (volume, success, latency, failure reasons), what did routing recover, and how does that compare with static routing?
- Measure and unit: a figures table with one column per processor (A and B) and rows for payments routed, captured, failed, declined, success rate (captured over final payments, declines counted; the one definition of `docs/product/metrics.md`), end-to-end latency P50, P95 and P99 (received to final, final payments the processor handled) and processor call latency P50, P95 and P99 (from the attempt events); a failure reasons table (processor, reason, count); revenue recovered by rescue path (retry, failover, redrive) as payments and exact amounts per currency; time to explanation per source (model, rules) with P50 and P95, the fallback rate and the fallback reasons in plain words (the same wording as the payment explanation). All numbers are monospace; a dash means no data.
- Time range and comparison: a range select (last hour, 24 hours, 7 days, 31 days; default 24 hours) and a processor select (All, A, B), sent as `from`, `to` and `processor`; refreshed every 10 s and on every change. With a processor chosen only its column shows. The baseline section compares with static routing, using the REL-30 results, not this range.
- Visualization: tables only, for the same reason as the payments table; a chart would hide exact values and no trend is needed over a range this size.
- Baseline section: headed "Against the static-routing baseline"; it says "Synthetic data; baseline is static routing.", names the run it came from (run, seed, scenario, the results file date) and shows the static and Relay success rates, the uplift in percentage points and the simulated revenue recovered per currency and by rescue path. When the api answers `available: false` it says "Baseline unavailable: the REL-30 results file was not found or could not be read." and the rest of the page still works.
- Source/query: `GET /api/analytics?from=&to=&processor=` and `GET /api/analytics/baseline` (call `GET /analytics` and `GET /analytics/baseline`, [api-contract.md](api-contract.md)); the key stays on the server and both are reads, so the host guard covers them.
- Drill-down: none; the page is linked from the header next to Incidents on the payments page, and links back to the payments and the incidents.
- States: loading ("Loading analytics..."), error ("Could not load analytics. Retrying every 10 seconds." and the status reads Error), empty range (0 payments, dashes for rates, "No failures in this range."), no explanations ("No explanations in this range yet.").

## Exceptions and thresholds

- Show Retrying and Failed rows in place, in time order; Phase 1 does not reorder rows, so the table does not move under the cursor on refresh.
- The 5 s refresh and 15 s stale threshold are a demo-scale choice: a processor outage shows in the list within one or two refreshes, and three missed refreshes signal a real problem.
- Treat missing data as unknown, not healthy: when no refresh has succeeded the status reads "Error", never "Live", and no counts are shown.

## Interactions and drill-downs

- Global filters: none in Phase 1 (the api supports `status`, `processor` and `is_final`; a filter UI is later work).
- Preserved context in links: none yet; the detail link will carry the payment id.
- Keyboard and focus behavior: the table scrolls inside its own container, which is focusable (tab stop) so the keyboard can scroll it; refreshes never move focus.
- Runbook or action destination: payment detail (REL-27), outage controls (REL-28) and the incident views with their triage and resolve actions (REL-36).

## Empty, loading, error, and stale states

| State | Visible message | Available action |
|---|---|---|
| Loading | "Loading payments..." in the table area, which reserves its final height | None |
| Empty | "No payments yet. Run the load generator to create synthetic payments." | None |
| Partial | Not applicable: one source and one request | None |
| Error | "Could not load payments. Showing the last data if any. Retrying every 5 seconds." | Automatic retry; reload the page |
| Stale | Status reads "Stale" with the last updated time; rows stay visible | Automatic retry |

The status line is a polite live region (`role="status"`); it announces changes without moving focus. The page works at phone width: no horizontal page scroll, the table scrolls inside its container, and the layout reserves space so refreshes cause no layout shift.

## Ownership and lifecycle

- Definition location: this file, `docs/architecture/dashboard-spec.md`, with the code in `frontend/app/`.
- Change review: pull request review per the project workflow; update this spec in the same pull request as a behavior change.
- Usage review: at each phase exit review (REL-32).
- Retirement trigger: replaced by the Phase 2 operations dashboards, or the payments list moves into another view.
