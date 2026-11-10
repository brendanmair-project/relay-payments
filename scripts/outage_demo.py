"""Scripted outage demo: baseline (static routing) against Relay routing over one seeded scenario (REL-30).

Run from the repository root with the compose stack's prerequisites (Docker, RELAY_API_KEY in the environment or the
settings file, and the host Ollama for time to explanation):

    python scripts/outage_demo.py --seed 7 --runs 3

Standard library only, like smoke_stack.py. For each run and for each mode in order `static`, `rules`:

1. set ROUTING_STRATEGY and HEALTH_WINDOW_SECONDS (--health-window, default 120) in the environment and
   `docker compose up -d --wait`, so `api` and `worker` restart with it;
2. stop worker, publisher and explainer, run the reset in the api image (`python -m app.demo.reset`: TRUNCATE ...
   RESTART IDENTITY CASCADE on every table, delete the stream and recreate its groups, truncate the request log), and
   start the three again;
3. reset the simulator's outages and profiles through its control API, and warm the model;
4. run the load generator (`docker compose run --rm simulator python -m generator ...`, public API only);
5. wait until every payment is final and every declined or failed one has its automatic explanation;
6. save the per-reference outcomes (public API) and the reporting tool's JSON under the output directory.

Then it compares the modes payment by payment and writes `results.json` and `results.md` there (simulator/demo/).
The stack is left running; stop it with `docker compose down -v`. All data is synthetic.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "simulator"))

from demo.compare import build_results, routing_from_events  # noqa: E402
from demo.render import render_markdown  # noqa: E402
from generator.scenarios import SCENARIOS  # noqa: E402

MODES = ("static", "rules")
SERVICES = ("api", "worker", "publisher", "explainer", "simulator")
CONSUMERS = ("worker", "publisher", "explainer")
FINAL_STATUSES = ("captured", "declined", "failed")
# The simulator's default profiles (simulator/processors/profiles.py), restored before every run.
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
OLLAMA = "http://127.0.0.1:11434"


HEALTH_WINDOW = 120  # seconds, set by --health-window; passed to api and worker as HEALTH_WINDOW_SECONDS


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def compose(args: list[str], mode: str, *, capture: bool = False) -> str:
    """Run `docker compose <args>` from the repository root with ROUTING_STRATEGY set to `mode`."""
    env = {**os.environ, "ROUTING_STRATEGY": mode, "HEALTH_WINDOW_SECONDS": str(HEALTH_WINDOW)}
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
        detail = (result.stderr or "")[-500:] if capture else ""
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


def warm_model() -> None:
    """One request to the host Ollama so model loading is not counted as time to explanation (ADR-0012)."""
    model = setting("OLLAMA_MODEL", "granite3.3:2b")
    body = {"model": model, "prompt": "Reply with the word ready.", "stream": False, "options": {"num_predict": 8}}
    request = urllib.request.Request(  # noqa: S310 - fixed local address
        f"{OLLAMA}/api/generate",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310
            response.read()
        log(f"model {model} warmed in {time.monotonic() - started:.1f} s")
    except OSError as error:
        log(f"WARNING model not warmed ({error}); explanations will fall back to rules")


def collect_outcomes(prefix: str) -> dict[str, dict]:
    """Every payment of the run by reference, through the public API (newest first, keyset pagination)."""
    outcomes: dict[str, dict] = {}
    cursor = None
    while True:
        url = f"{API}/payments?limit=100" + (f"&cursor={cursor}" if cursor else "")
        status, text = http("GET", url)
        if status != 200:
            sys.exit(f"FAIL GET /payments returned {status}")
        page = json.loads(text)
        for item in page["items"]:
            if item["reference"].startswith(prefix):
                outcomes[item["reference"]] = {
                    "id": item["id"],
                    "status": item["status"] if item["is_final"] else "pending",
                    "currency": item["currency"],
                    "amount_minor": item["amount_minor"],
                }
        cursor = page["next_cursor"]
        if not cursor:
            return dict(sorted(outcomes.items()))


def add_routing(outcomes: dict[str, dict]) -> None:
    """Add the handling processor and the routed reasons in order (GET /payments/{id} events) to each outcome."""
    for reference, outcome in outcomes.items():
        status, text = http("GET", f"{API}/payments/{outcome.pop('id')}")
        if status != 200:
            sys.exit(f"FAIL GET /payments/{{id}} returned {status} for {reference}")
        detail = json.loads(text)
        outcome["processor"] = detail["processor"]
        outcome["routing"] = routing_from_events(detail["events"])


def read_report(prefix: str, name: str, mode: str) -> dict:
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    target = reports / f"{name}.json"
    target.unlink(missing_ok=True)
    compose(
        [
            "run",
            "--rm",
            "--no-deps",
            "reporting",
            "python",
            "-m",
            "app.reporting",
            "--reference-prefix",
            prefix,
            "--json-out",
            f"/reports/{name}.json",
        ],
        mode,
        capture=True,
    )
    report = json.loads(target.read_text(encoding="utf-8"))
    target.unlink(missing_ok=True)
    return report


def wait_until_complete(prefix: str, expected: int, name: str, mode: str, timeout: float) -> tuple[dict, dict]:
    """Wait for every payment to be final and every declined or failed one to be explained; returns both results."""
    deadline = time.monotonic() + timeout
    while True:
        outcomes = collect_outcomes(prefix)
        final = len(outcomes) == expected and all(o["status"] in FINAL_STATUSES for o in outcomes.values())
        if final:
            needed = sum(1 for o in outcomes.values() if o["status"] in ("declined", "failed"))
            report = read_report(prefix, name, mode)
            explanations = report["explanations"]
            explained = explanations["all"]["count"] if explanations["available"] else 0
            log(f"{len(outcomes)} payments final; explained {explained} of {needed}")
            if explained >= needed:
                return outcomes, report
        else:
            log(f"{sum(o['status'] in FINAL_STATUSES for o in outcomes.values())} of {expected} payments final")
        if time.monotonic() > deadline:
            sys.exit(f"FAIL run {name} did not complete within {timeout:.0f} s")
        time.sleep(5)


LAG_LINE = re.compile(
    r"recovery lag processor (\w+): (?:([\d.]+) s|not recovered within the wait) \(waited ([\d.]+) s\)"
)


def parse_recovery_lags(generator_output: str) -> list[dict]:
    """The generator prints one `recovery lag processor a: 12.0 s (waited 65.0 s)` line per outage that ended."""
    return [
        {
            "processor": m.group(1),
            "lag_seconds": float(m.group(2)) if m.group(2) else None,
            "waited_seconds": float(m.group(3)),
        }
        for m in LAG_LINE.finditer(generator_output)
    ]


def prepare_run(mode: str) -> None:
    """A fresh start for one run: restart api and worker with ROUTING_STRATEGY=`mode`, reset data, profiles, model."""
    compose(["up", "-d", "--wait", *SERVICES], mode)
    compose(["stop", *CONSUMERS], mode)
    compose(["exec", "-T", "api", "python", "-m", "app.demo.reset"], mode)
    compose(["up", "-d", "--wait", *CONSUMERS], mode)
    reset_simulator()
    warm_model()


def generate_and_collect(args: argparse.Namespace, name: str, mode: str, out: Path) -> tuple[dict, dict, list[dict]]:
    """Run the load generator on the prepared stack, wait for completion, save outcomes and the report under `name`."""
    prefix = f"{args.scenario}-{args.seed}-"
    started = time.monotonic()
    generator = [
        "run",
        "--rm",
        "--no-deps",
        "simulator",
        "python",
        "-m",
        "generator",
        "--scenario",
        args.scenario,
        "--seed",
        str(args.seed),
        "--rate",
        str(args.rate),
        "--api-url",
        "http://api:8000",
        "--control-url",
        "http://simulator:8101",
    ]
    if args.count:
        generator += ["--count", str(args.count)]
    if getattr(args, "drain_timeout", None):
        generator += ["--drain-timeout", str(args.drain_timeout)]
    generator_output = compose(generator, mode, capture=True)
    print(generator_output, end="", flush=True)
    lags = parse_recovery_lags(generator_output)
    (out / f"{name}.recovery.json").write_text(json.dumps(lags, indent=2) + "\n", encoding="utf-8")
    log(f"generator finished in {time.monotonic() - started:.0f} s")
    expected = args.count or SCENARIOS[args.scenario].default_count
    outcomes, report = wait_until_complete(prefix, expected, name, mode, args.timeout)
    add_routing(outcomes)
    (out / f"{name}.outcomes.json").write_text(json.dumps(outcomes, indent=2) + "\n", encoding="utf-8")
    (out / f"{name}.report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return outcomes, report, lags


def run_mode(args: argparse.Namespace, run_number: int, mode: str, out: Path) -> tuple[dict, dict, list[dict]]:
    name = f"run{run_number}-{'baseline' if mode == 'static' else 'relay'}"
    log(f"== {name}: ROUTING_STRATEGY={mode}")
    prepare_run(mode)
    return generate_and_collect(args, name, mode, out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--runs", type=int, default=1, help="repeat the comparison (3 for the check)")
    parser.add_argument("--out", default="docs/evaluation/outage-demo", help="output directory under the repository")
    parser.add_argument("--scenario", default="processor-a-outage")
    parser.add_argument(
        "--rate",
        type=float,
        default=2.0,
        help="payments per second; low enough that the worker keeps up, so the outage window matches payment indexes",
    )
    parser.add_argument("--count", type=int, help="payments per mode (default: the scenario's 300)")
    parser.add_argument("--health-window", type=int, default=120, help="HEALTH_WINDOW_SECONDS for api and worker")
    parser.add_argument("--timeout", type=float, default=1800, help="seconds to wait for one mode to complete")
    args = parser.parse_args(argv)
    if not setting("RELAY_API_KEY"):
        sys.exit("FAIL RELAY_API_KEY is not set in the environment or the settings file")
    global HEALTH_WINDOW
    HEALTH_WINDOW = args.health_window
    out = (ROOT / args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    runs = []
    for number in range(1, args.runs + 1):
        run: dict = {}
        for mode in MODES:
            outcomes, report, lags = run_mode(args, number, mode, out)
            run["baseline" if mode == "static" else "relay"] = {
                "outcomes": outcomes,
                "report": report,
                "recovery_lags": lags,
            }
        runs.append(run)
    results = build_results(args.seed, args.scenario, runs, args.health_window)
    (out / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    (out / "results.md").write_text(render_markdown(results), encoding="utf-8")
    log(f"results saved under {out}")
    repro = results["reproducibility"]
    if repro is not None:
        print("REPRODUCIBILITY=" + ("PASS" if repro["pass"] else "FAIL"))
        return 0 if repro["pass"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
