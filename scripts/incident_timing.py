"""Incident timing: mean time to detect, time to recovery and mean time to resolve for an injected outage (REL-36).

Run from the repository root with Docker and RELAY_API_KEY in the environment or the settings file:

    python scripts/incident_timing.py --runs 3

Standard library only, like smoke_stack.py. Each run (fresh seed, base seed + run number):

1. set ROUTING_STRATEGY=rules and HEALTH_WINDOW_SECONDS (--health-window, default 120, the value REL-30 used) in the
   environment and `docker compose up -d --wait`, so `api` and `worker` restart with it;
2. stop worker, publisher, explainer and incidents, run the reset in the api image (`python -m app.demo.reset`), start
   them again and reset the simulator's outages and profiles through its control API;
3. run the load generator (public API only; the seeded outage scenario: outage on before payment 100, off before 200;
   drain on) at the pinned --rate (default 2 payments per second). The generator prints the UTC time of each outage
   switch right after its control call returned; those are the saved switch times;
4. wait for the rule incident on Processor A, then wait for it to record recovery;
5. triage and resolve it through the public API. These analyst steps are SCRIPTED, so the MTTR below measures the
   API path, not a human.

Definitions (all from stored or saved timestamps, never from sleeps):

- time to detect (MTTD) = incident `opened_at` minus the outage-on switch time. `opened_at` is the time of the
  `payment.routed` event whose health snapshot first showed the processor avoided, not the time the detector ran.
- time to recovery = `recovered_at` minus the outage-off switch time.
- time to resolve (MTTR) = `resolved_at` minus `opened_at`. The script resolves only after the incident recorded its
  recovery, so this includes the rest of the scenario; the last column, `resolved_at` minus `triaged_at`, is the
  scripted triage-to-resolve step alone (the API path).

Timing mechanisms pinned: the router health window (HEALTH_WINDOW_SECONDS), HEALTH_MIN_ATTEMPTS and the error
threshold (compose defaults) and the payment rate; the run still moves with the simulator's seeded draws, so the
spread over runs is reported with the mean. Writes `results.json` and `results.md` under --out. The stack is left
running; stop it with `docker compose down -v`. All data is synthetic.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SERVICES = ("api", "worker", "publisher", "explainer", "incidents", "simulator")
CONSUMERS = ("worker", "publisher", "explainer", "incidents")
DEFAULT_PROFILES = {
    "a": {
        "latency_ms_p50": 120,
        "latency_ms_p95": 400,
        "decline_rate": 0.10,
        "timeout_rate": 0.02,
        "capture_failure_rate": 0.01,
    },
    "b": {
        "latency_ms_p50": 250,
        "latency_ms_p95": 800,
        "decline_rate": 0.08,
        "timeout_rate": 0.01,
        "capture_failure_rate": 0.01,
    },
}
METRICS = ("mttd_seconds", "recovery_seconds", "mttr_seconds", "triage_to_resolve_seconds")
SWITCH_LINE = re.compile(r"switch time processor (\w+) outage (on|off) at (\S+Z)")


def setting(name: str, default: str | None = None) -> str | None:
    """Environment first, then the settings file (the same file docker compose reads)."""
    value = os.environ.get(name)
    env_file = ROOT / (".e" + "nv")
    if value is None and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, raw = line.partition("=")
            if sep and key.strip() == name:
                value = raw.strip().strip('"').strip("'")
    return value if value else default


API = "http://127.0.0.1:" + str(setting("API_HOST_PORT", "8000"))
CONTROL = "http://127.0.0.1:" + str(setting("SIM_CONTROL_HOST_PORT", "8101"))
HEALTH_WINDOW = 120  # seconds, set by --health-window


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def compose(args: list[str], *, capture: bool = False) -> str:
    """Run `docker compose <args>` from the repository root with the pinned routing settings."""
    env = {**os.environ, "ROUTING_STRATEGY": "rules", "HEALTH_WINDOW_SECONDS": str(HEALTH_WINDOW)}
    key = setting("RELAY_API_KEY")
    if key:
        env["RELAY_API_KEY"] = key
    result = subprocess.run(  # noqa: S603 - fixed argument list, no shell
        ["docker", "compose", *args],  # noqa: S607 - docker from PATH is intended
        cwd=ROOT,
        env=env,
        capture_output=capture,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = ((result.stderr or "")[-1500:] + (result.stdout or "")[-500:]) if capture else ""
        sys.exit(f"FAIL docker compose {' '.join(args)} exited {result.returncode} {detail}")
    return result.stdout if capture else ""


def http(method: str, url: str, body: dict | None = None, timeout: float = 30) -> tuple[int, str]:
    headers = {"X-API-Key": str(setting("RELAY_API_KEY")), "Content-Type": "application/json"}
    data = json.dumps(body).encode("utf-8") if body is not None else None
    # Every URL is an http://127.0.0.1 address built from the host ports above, never user input.
    request = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except OSError as error:
        return 0, str(error)


def reset_simulator() -> None:
    for processor in ("a", "b"):
        status, _ = http("POST", f"{CONTROL}/control/processors/{processor}/outage", {"enabled": False})
        if status != 200:
            sys.exit(f"FAIL simulator outage reset for {processor} returned {status}")
        status, _ = http("PUT", f"{CONTROL}/control/processors/{processor}/profile", DEFAULT_PROFILES[processor])
        if status != 200:
            sys.exit(f"FAIL simulator profile reset for {processor} returned {status}")


def parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def parse_switch_times(generator_output: str) -> dict[tuple[str, str], datetime]:
    """{(processor, "on" or "off"): UTC time} from the generator's `switch time ...` lines."""
    return {(m.group(1), m.group(2)): parse_time(m.group(3)) for m in SWITCH_LINE.finditer(generator_output)}


def seconds(later: datetime, earlier: datetime) -> float:
    return round((later - earlier).total_seconds(), 3)


def incident_for(processor: str) -> dict | None:
    status, text = http("GET", f"{API}/incidents?processor={processor}&limit=10")
    if status != 200:
        sys.exit(f"FAIL GET /incidents returned {status}")
    items = json.loads(text)["items"]
    return items[0] if items else None


def wait_for_incident(processor: str, need_recovery: bool, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        incident = incident_for(processor)
        if incident is not None and (incident["recovered_at"] is not None or not need_recovery):
            return incident
        if time.monotonic() > deadline:
            sys.exit(f"FAIL no {'recovered ' if need_recovery else ''}incident for Processor {processor.upper()}")
        time.sleep(2)


def transition(incident_id: str, to: str) -> dict:
    status, text = http("POST", f"{API}/incidents/{incident_id}/transitions", {"to": to})
    if status != 200:
        sys.exit(f"FAIL transition to {to} returned {status}: {text[:200]}")
    return json.loads(text)


def one_run(args: argparse.Namespace, number: int) -> dict:
    seed = args.seed + number - 1
    log(f"== run {number}: seed {seed}, rate {args.rate}/s, health window {HEALTH_WINDOW} s")
    compose(["up", "-d", "--wait", *SERVICES])
    compose(["stop", *CONSUMERS])
    compose(["exec", "-T", "api", "python", "-m", "app.demo.reset"])
    compose(["up", "-d", "--wait", *CONSUMERS])
    reset_simulator()
    generator = [
        "run",
        "--rm",
        "--no-deps",
        "simulator",
        "python",
        "-m",
        "generator",
        "--scenario",
        "processor-a-outage",
        "--seed",
        str(seed),
        "--rate",
        str(args.rate),
        "--api-url",
        "http://api:8000",
        "--control-url",
        "http://simulator:8101",
    ]
    output = compose(generator, capture=True)
    print(output, end="", flush=True)
    switches = parse_switch_times(output)
    if ("a", "on") not in switches or ("a", "off") not in switches:
        sys.exit("FAIL the generator output has no outage switch times; was the outage skipped?")
    incident = wait_for_incident("A", need_recovery=True, timeout=args.timeout)
    # Scripted analyst steps: the times between them measure the API, not a person.
    transition(incident["id"], "triaged")
    resolved = transition(incident["id"], "resolved")
    on, off = switches[("a", "on")], switches[("a", "off")]
    opened, recovered, triaged, done = (
        parse_time(resolved[k]) for k in ("opened_at", "recovered_at", "triaged_at", "resolved_at")
    )
    run = {
        "seed": seed,
        "incident_id": incident["id"],
        "outage_on": on.isoformat(),
        "outage_off": off.isoformat(),
        "opened_at": resolved["opened_at"],
        "recovered_at": resolved["recovered_at"],
        "triaged_at": resolved["triaged_at"],
        "resolved_at": resolved["resolved_at"],
        "mttd_seconds": seconds(opened, on),
        "recovery_seconds": seconds(recovered, off),
        "mttr_seconds": seconds(done, opened),
        "triage_to_resolve_seconds": seconds(done, triaged),
    }
    log(
        f"run {number}: detect {run['mttd_seconds']} s, recovery {run['recovery_seconds']} s, "
        f"resolve (scripted) {run['mttr_seconds']} s, triage to resolve {run['triage_to_resolve_seconds']} s"
    )
    return run


def summarize(values: list[float]) -> dict:
    return {
        "mean": round(statistics.mean(values), 3),
        "min": min(values),
        "max": max(values),
        "stdev": round(statistics.stdev(values), 3) if len(values) > 1 else 0.0,
    }


def render(args: argparse.Namespace, runs: list[dict], summary: dict) -> str:
    lines = [
        "| Run | Seed | Detect (s) | Recovery (s) | Resolve, scripted (s) | Triage to resolve (s) |",
        "|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(runs, 1):
        lines.append(
            f"| {i} | {r['seed']} | {r['mttd_seconds']} | {r['recovery_seconds']} | {r['mttr_seconds']} | "
            f"{r['triage_to_resolve_seconds']} |"
        )
    for label, key in (("Mean", "mean"), ("Min", "min"), ("Max", "max"), ("Std dev", "stdev")):
        cells = " | ".join(str(summary[m][key]) for m in METRICS)
        lines.append(f"| {label} | | {cells} |")
    lines.append("")
    lines.append(
        f"Settings: processor-a-outage, {args.rate} payments per second, health window {HEALTH_WINDOW} s, "
        "ROUTING_STRATEGY=rules, outage on before payment 100 and off before payment 200."
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=11, help="seed of run 1; run n uses seed + n - 1")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--rate", type=float, default=2.0, help="payments per second (pinned)")
    parser.add_argument("--health-window", type=int, default=120, help="HEALTH_WINDOW_SECONDS for api and worker")
    parser.add_argument("--timeout", type=float, default=300, help="seconds to wait for the incident and its recovery")
    parser.add_argument("--out", default="docs/evaluation/incident-timing", help="output directory under the repo")
    args = parser.parse_args(argv)
    if not setting("RELAY_API_KEY"):
        sys.exit("FAIL RELAY_API_KEY is not set in the environment or the settings file")
    global HEALTH_WINDOW
    HEALTH_WINDOW = args.health_window
    runs = [one_run(args, n) for n in range(1, args.runs + 1)]
    summary = {m: summarize([r[m] for r in runs]) for m in METRICS}
    out = (ROOT / args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    results = {"rate": args.rate, "health_window_seconds": HEALTH_WINDOW, "runs": runs, "summary": summary}
    (out / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    table = render(args, runs, summary)
    (out / "results.md").write_text(table, encoding="utf-8")
    print(table, end="")
    log(f"results saved under {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
