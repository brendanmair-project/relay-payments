"""One seeded outage-story run at a time (REL-66), started and stopped through the keyed control API.

The run is the load generator's `run_scenario` on a thread. It reaches Relay only through the public API and the
control API (RelayClient), exactly as `python -m generator` does. Contract: docs/architecture/api-contract.md,
"Simulator APIs".
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from generator.client import RelayClient
from generator.runner import DrainTimeout, RunResult, run_scenario
from generator.scenarios import SCENARIOS

SCENARIO = "outage-story"
CONTROL_URL = "http://127.0.0.1:8101"

# runner(should_stop, on_progress) runs the whole scenario and returns its result; tests inject a fake.
Runner = Callable[[Callable[[], bool], Callable[[RunResult], None]], RunResult]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def default_runner(should_stop: Callable[[], bool], on_progress: Callable[[RunResult], None]) -> RunResult:
    client = RelayClient(
        api_url=os.environ.get("RELAY_API_URL", "http://api:8000"),
        control_url=CONTROL_URL,
        api_key=os.environ["RELAY_API_KEY"],
    )
    return run_scenario(
        SCENARIOS[SCENARIO],
        client,
        seed=int(os.environ.get("STORY_SEED", "66")),
        rate=float(os.environ.get("STORY_RATE", "4")),
        should_stop=should_stop,
        on_progress=on_progress,
    )


class StoryController:
    def __init__(self, runner: Runner = default_runner) -> None:
        self._runner = runner
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = "idle"
        self._sent = 0
        self._switches: list[dict] = []
        self._started_at: str | None = None
        self._finished_at: str | None = None
        self._error_code: str | None = None

    def _phase(self) -> str | None:
        if self._state == "finished":
            return "done"
        if self._state not in ("running", "stopping"):
            return None
        if any(not s["outage"] for s in self._switches):
            return "recovering"
        return "outage" if any(s["outage"] for s in self._switches) else "flowing"

    def _snapshot(self) -> dict:
        return {
            "state": self._state,
            "phase": self._phase(),
            "sent": self._sent,
            "total": SCENARIOS[SCENARIO].default_count,
            "switches": [dict(s) for s in self._switches],
            "started_at": self._started_at,
            "finished_at": self._finished_at,
            "error_code": self._error_code,
        }

    def status(self) -> dict:
        with self._lock:
            return self._snapshot()

    def start(self) -> tuple[bool, dict]:
        """Starts a run; (False, status) when one is already running or stopping."""
        with self._lock:
            if self._state in ("running", "stopping"):
                return False, self._snapshot()
            self._stop = threading.Event()
            self._state = "running"
            self._sent = 0
            self._switches = []
            self._started_at = _now()
            self._finished_at = None
            self._error_code = None
            thread = threading.Thread(target=self._work, args=(self._stop,), name="story-run", daemon=True)
            self._thread = thread
            thread.start()
            return True, self._snapshot()

    def stop(self) -> dict:
        """Asks a running run to stop; the generator then switches any outage back off. A no-op when nothing runs."""
        with self._lock:
            if self._state == "running":
                self._state = "stopping"
                self._stop.set()
            return self._snapshot()

    def _progress(self, result: RunResult) -> None:
        with self._lock:
            self._sent = result.sent
            self._switches = [
                {"processor": s["processor"], "outage": s["outage"], "at": s["at"]} for s in result.switch_times
            ]

    def _work(self, stop: threading.Event) -> None:
        state, code = "finished", None
        try:
            result = self._runner(stop.is_set, self._progress)
            self._progress(result)
            if result.unreachable:
                state, code = "failed", "api_unreachable"
        except DrainTimeout:
            state, code = "failed", "drain_timeout"
        except Exception:  # noqa: BLE001 - the detail stays out of the status; the code says what happened
            state, code = "failed", "run_failed"
        with self._lock:
            if state == "finished" and stop.is_set():
                state = "stopped"
            self._state, self._error_code, self._finished_at = state, code, _now()
