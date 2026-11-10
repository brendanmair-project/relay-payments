"""Command line for the load generator. Run from the `simulator/` directory:

    python -m generator --scenario normal-day --seed 42 --rate 10 --count 200

Standard library only; talks to the public API (default http://127.0.0.1:8000) and the simulator control API
(default http://127.0.0.1:8101). `RELAY_API_KEY` comes from the environment, then the repository-root settings file.
Flags override the URLs: --api-url and --control-url (or the RELAY_API_URL and RELAY_CONTROL_URL variables). Prints
counts by HTTP status; before an outage switch it waits for every earlier payment to be final (GET /payments/{id}
on the public API; --drain-timeout sets the limit, default 100 s, two sweeper re-drive cycles). After an outage
ends it also waits one router health window (GET /processors/health) and prints the recovery lag; --no-drain
skips both. It prints each outage switch's UTC time (`switch time processor a outage on at ...Z`). Exits 1 when the API
is unreachable or the drain times out (it then lists each unfinished payment) and 2 on bad arguments or a missing
key. Payments carry the reference `<scenario>-<seed>-<index>`, so one seed repeats payment by payment.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Mapping, Sequence

from .client import RelayClient, Transport, urllib_transport
from .mix import parse_mix
from .runner import DEFAULT_DRAIN_TIMEOUT_SECONDS, DrainTimeout, run_scenario
from .scenarios import SCENARIOS
from .settings import setting


def build_parser(environ: Mapping[str, str] | None = None) -> argparse.ArgumentParser:
    api_default = setting("RELAY_API_URL", "http://127.0.0.1:8000", environ=environ)
    control_default = setting("RELAY_CONTROL_URL", "http://127.0.0.1:8101", environ=environ)
    parser = argparse.ArgumentParser(prog="python -m generator", description="Relay synthetic load generator")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="normal-day")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rate", type=float, default=10.0, help="payments per second")
    parser.add_argument("--count", type=int, help="number of payments (default: the scenario default)")
    parser.add_argument("--duration", type=float, help="stop after this many seconds")
    parser.add_argument("--mix", help="currency weights, for example USD=50,EUR=30,GBP=15,JPY=5")
    parser.add_argument("--api-url", default=api_default)
    parser.add_argument("--control-url", default=control_default)
    parser.add_argument("--no-drain", action="store_true", help="do not wait for earlier payments before a switch")
    parser.add_argument(
        "--drain-timeout",
        type=float,
        default=DEFAULT_DRAIN_TIMEOUT_SECONDS,
        help="seconds to wait before a switch",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    transport: Transport = urllib_transport,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    environ: Mapping[str, str] | None = None,
    wall_clock: Callable[[], float] = time.time,
) -> int:
    args = build_parser(environ).parse_args(argv)
    key = setting("RELAY_API_KEY", environ=environ)
    if not key:
        print("RELAY_API_KEY is not set in the environment or the settings file", file=sys.stderr)
        return 2
    try:
        mix = parse_mix(args.mix) if args.mix else None
        if args.rate <= 0:
            raise ValueError("rate must be positive")
    except ValueError as error:
        print(f"invalid argument: {error}", file=sys.stderr)
        return 2
    client = RelayClient(args.api_url, args.control_url, key, transport)
    try:
        result = run_scenario(
            SCENARIOS[args.scenario],
            client,
            args.seed,
            args.rate,
            args.count,
            args.duration,
            mix,
            sleep,
            clock,
            drain=not args.no_drain,
            drain_timeout=args.drain_timeout,
            wall_clock=wall_clock,
        )
    except DrainTimeout as error:
        print(f"drain failed: {error}; the outage was not switched", file=sys.stderr)
        for item in error.unfinished:
            attempt = "unknown" if item["attempt_no"] is None else item["attempt_no"]
            print(
                f"  unfinished payment {item['id'][:8]}: status {item['status']}, attempt {attempt}",
                file=sys.stderr,
            )
        return 1
    counts = ", ".join(f"{status or 'unreachable'}: {n}" for status, n in sorted(result.statuses.items()))
    print(f"scenario {args.scenario} seed {args.seed}: sent {result.sent} payments ({counts})")
    for index, processor, enabled, status in result.control_calls:
        print(f"  at payment {index}: processor {processor} outage {'on' if enabled else 'off'} -> HTTP {status}")
    for index, processor, timeout_rate, status in result.profile_calls:
        print(f"  at payment {index}: processor {processor} timeout_rate {timeout_rate} -> HTTP {status}")
    for switch in result.switch_times:
        state = "on" if switch["outage"] else "off"
        print(f"switch time processor {switch['processor']} outage {state} at {switch['at']}")
    for lag in result.recovery_lags:
        outcome = "not recovered within the wait" if lag["lag_seconds"] is None else f"{lag['lag_seconds']:.1f} s"
        print(f"recovery lag processor {lag['processor']}: {outcome} (waited {lag['waited_seconds']:.1f} s)")
    if result.unreachable:
        print("the API is unreachable; is the stack running?", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
