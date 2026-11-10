# ADR-0006: Observability stack

Template: claude/decision@1

Status: Accepted  
Decision owner: Brendan  
Date: 2026-09-29 (proposed); accepted 2026-11-02  
Supersedes: None  
Superseded by: None

## Context and forces

Phase 2 adds monitoring dashboards. The fixed stack names no metrics or dashboard tools, so the choice was deferred to Phase 2 kickoff (REL-33) and nothing was built on it before then. The owner's tooling review on 2026-10-27 asked to compare the proposal with Sentry (error tracking) and PostHog (product analytics) first.

- Constraint: free and open source, self-hosted under Docker Compose (AGENTS.md, ADR-0001). Images and libraries are pinned to exact versions with the licence checked at that version (ADR-0012).
- Quality attribute: the guardrail metrics in `docs/product/metrics.md` (throughput, success rate, P50/P95/P99 latency, processor error rate, API 5xx rate, publish lag) must be visible on a dashboard.
- Cost: the default stack, the clean-clone run and CI should not grow (ADR-0014 puts this stack under the `observability` profile).
- Evidence: licences and versions were checked on 2026-11-02 against each project's repository (`LICENSE` files through the GitHub API) and Docker Hub tags.

## Decision

We will use Prometheus v3.15.1 (`prom/prometheus:v3.15.1`, Apache-2.0) for metrics collection and Grafana 13.3.0 (`grafana/grafana:13.3.0`, AGPL-3.0) for dashboards. `grafana/grafana` is the open-source edition; `grafana/grafana-enterprise` is the Enterprise edition and is not used. The services expose metrics through the Python `prometheus-client` 0.26.0 library (Apache-2.0), which is added to the runtime libraries of ADR-0011 by this decision. Both containers run under the compose profile `observability` (ADR-0014), and the scrape config, data source and dashboards are provisioned from files under `observability/`. We chose them because they are open source, standard, light, and cover exactly the guardrail metrics. The owner accepted this on 2026-11-02.

Grafana runs unmodified and only on the local machine. The AGPL obligation applies to modified versions offered over a network, so it places no requirement on Relay's own code.

## Alternatives considered

| Alternative | Licence (checked 2026-11-02) | Benefits | Costs/risks | Why not selected |
|---|---|---|---|---|
| Prometheus and Grafana | Apache-2.0 and AGPL-3.0 | Standard, two containers, dashboards as files | Two more containers (profile only) | Selected |
| Sentry self-hosted (26.10.1) | FSL-1.1-Apache-2.0: source-available, becomes Apache-2.0 only two years after each release | Error tracking with stack traces | Fails the open-source rule; dozens of containers | Fails the free and open-source rule |
| PostHog self-hosted | MIT core, `ee/` directory under a proprietary licence | Product analytics | Targets product analytics, not operations metrics; heavy stack (ClickHouse, Kafka) | Partly proprietary, and not the Phase 2 need |
| OpenTelemetry with Loki and Tempo | Open source | Traces and logs as well as metrics | More components and setup | Larger than the Phase 2 need |
| Dashboards built in the Next.js UI | Own code | One less service | Reinvents charting and alerting | Grafana already solves it |
| No monitoring | n/a | No work | Guardrail metrics stay invisible | Phase 2 requires dashboards |

## Consequences

### Positive

- Standard, recognisable tooling that reviewers know; dashboards are reviewable configuration.

### Negative and tradeoffs

- Two more containers under the `observability` profile, and one more runtime library in the api image.

### Follow-on work

- REL-33: instrument the api, worker and publisher with `prometheus-client`; add both services with restart policy, health check, per-service variables and 127.0.0.1 ports, covered by `api/tests/test_compose_stack.py`; write the dashboard spec first.
- Re-check both licences whenever a pinned version changes (ADR-0012).

## Validation and review

- Validate with: the guardrail metrics visible on Grafana dashboards after `docker compose --profile observability up -d --wait` with a seeded demo run.
- Revisit when: resource use makes local runs impractical, a licence changes at a new version, or tracing becomes a need.
- Reversal/migration cost: low; dashboards are configuration and metrics use the standard exposition format.
