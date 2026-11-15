"""REL-66: the keyed story run control (POST/GET/DELETE /control/story/run) and the generator hooks behind it."""

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.apps import create_apps
from app.story import StoryController
from generator.client import RelayClient
from generator.runner import RunResult, run_scenario
from generator.scenarios import SCENARIOS
from processors.simulator import Simulator

KEY = {"X-API-Key": "test-key"}
API = "http://relay-api.test"
CONTROL = "http://sim-control.test"
STATUS_FIELDS = {"state", "phase", "sent", "total", "switches", "started_at", "finished_at", "error_code"}


class StoryTransport:
    """A fake Relay API plus control API: no network. Optionally parks the run at one payment until released."""

    def __init__(self, park_at: int | None = None, final: bool = True) -> None:
        self.calls: list[tuple[str, str, bytes | None]] = []
        self.payments = 0
        self.park_at = park_at
        self.final = final
        self.reached = threading.Event()
        self.release = threading.Event()

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, body))
        if method == "POST" and url == f"{API}/payments":
            self.payments += 1
            if self.park_at is not None and self.payments == self.park_at:
                self.reached.set()
                self.release.wait(timeout=10)
            return 201, json.dumps({"id": f"p{self.payments}"})
        if method == "GET" and url.startswith(f"{API}/payments/"):
            return 200, json.dumps({"is_final": self.final, "status": "captured", "attempt_no": 1})
        if url == f"{API}/processors/health":
            return 200, json.dumps({"window_seconds": 60, "processors": []})
        return 200, "{}"

    def outage_bodies(self) -> list[bool]:
        return [
            json.loads(body)["enabled"]
            for _, url, body in self.calls
            if url == f"{CONTROL}/control/processors/a/outage"
        ]


def make_runner(transport: StoryTransport):
    """A runner for StoryController: the real run_scenario on a fake transport, with a fake clock and no sleeping."""
    clock = {"now": 1000.0}

    def sleep(seconds: float) -> None:
        clock["now"] += seconds

    def runner(should_stop, on_progress):
        client = RelayClient(API, CONTROL, "story-test-value", transport)
        return run_scenario(
            SCENARIOS["outage-story"],
            client,
            seed=66,
            rate=4.0,
            sleep=sleep,
            clock=lambda: clock["now"],
            wall_clock=lambda: 1_700_000_000.0 + clock["now"],
            should_stop=should_stop,
            on_progress=on_progress,
        )

    return runner


def control_for(runner) -> TestClient:
    _, control_app = create_apps(
        Simulator(seed=42, timeout_seconds=5), api_key="test-key", story=StoryController(runner)
    )
    return TestClient(control_app)


def wait_for_state(control: TestClient, states: set[str], timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = control.get("/control/story/run", headers=KEY).json()
        if status["state"] in states:
            return status
        time.sleep(0.01)
    raise AssertionError(f"state did not reach {states}: {status}")


def test_status_is_idle_before_any_run():
    control = control_for(make_runner(StoryTransport()))
    response = control.get("/control/story/run", headers=KEY)
    assert response.status_code == 200
    status = response.json()
    assert set(status) == STATUS_FIELDS
    assert status["state"] == "idle"
    assert status["phase"] is None
    assert status["sent"] == 0
    assert status["switches"] == []
    assert status["started_at"] is None and status["finished_at"] is None and status["error_code"] is None


def test_start_answers_202_and_the_run_is_running():
    transport = StoryTransport(park_at=30)
    control = control_for(make_runner(transport))
    response = control.post("/control/story/run", headers=KEY)
    assert response.status_code == 202
    assert response.json()["state"] in {"running"}
    assert transport.reached.wait(timeout=10)
    status = control.get("/control/story/run", headers=KEY).json()
    assert set(status) == STATUS_FIELDS
    assert status["state"] == "running"
    assert status["phase"] == "outage"  # payment 30 is after the outage switched on before payment 25
    assert status["sent"] == 29
    assert status["total"] == SCENARIOS["outage-story"].default_count
    assert [(s["processor"], s["outage"]) for s in status["switches"]] == [("a", True)]
    assert status["switches"][0]["at"].endswith("Z")
    assert status["started_at"] is not None and status["finished_at"] is None
    transport.release.set()
    wait_for_state(control, {"finished"})


def test_a_second_start_while_one_runs_is_refused_with_409():
    transport = StoryTransport(park_at=5)
    control = control_for(make_runner(transport))
    assert control.post("/control/story/run", headers=KEY).status_code == 202
    assert transport.reached.wait(timeout=10)
    second = control.post("/control/story/run", headers=KEY)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "run_in_progress"
    transport.release.set()
    wait_for_state(control, {"finished"})


def test_a_finished_run_reports_phase_done_and_both_switches():
    transport = StoryTransport()
    control = control_for(make_runner(transport))
    assert control.post("/control/story/run", headers=KEY).status_code == 202
    status = wait_for_state(control, {"finished", "failed", "stopped"})
    assert status["state"] == "finished"
    assert status["phase"] == "done"
    assert status["sent"] == status["total"] == 90
    assert [(s["processor"], s["outage"]) for s in status["switches"]] == [("a", True), ("a", False)]
    assert status["finished_at"] is not None and status["error_code"] is None
    assert transport.outage_bodies() == [True, False]
    # A finished run no longer blocks a new one.
    assert control.post("/control/story/run", headers=KEY).status_code == 202
    wait_for_state(control, {"finished"})


def test_stop_switches_the_outage_back_off_and_reports_stopped():
    transport = StoryTransport(park_at=30)
    control = control_for(make_runner(transport))
    assert control.post("/control/story/run", headers=KEY).status_code == 202
    assert transport.reached.wait(timeout=10)
    stopping = control.delete("/control/story/run", headers=KEY)
    assert stopping.status_code == 200
    assert stopping.json()["state"] == "stopping"
    transport.release.set()
    status = wait_for_state(control, {"stopped", "finished", "failed"})
    assert status["state"] == "stopped"
    assert status["phase"] is None
    assert status["sent"] < status["total"]
    assert status["finished_at"] is not None
    assert transport.outage_bodies() == [True, False]  # the outage was on, and the run switched it off on stopping


def test_stop_when_nothing_runs_answers_200_with_the_current_state():
    control = control_for(make_runner(StoryTransport()))
    response = control.delete("/control/story/run", headers=KEY)
    assert response.status_code == 200
    assert response.json()["state"] == "idle"


def test_a_crashing_run_is_reported_as_failed_with_an_error_code():
    def runner(should_stop, on_progress):
        raise RuntimeError("boom with detail that must not leak")

    control = control_for(runner)
    assert control.post("/control/story/run", headers=KEY).status_code == 202
    status = wait_for_state(control, {"failed", "finished"})
    assert status["state"] == "failed"
    assert status["error_code"] == "run_failed"
    assert "boom" not in json.dumps(status)


def test_an_unreachable_api_is_reported_as_failed():
    def runner(should_stop, on_progress):
        return RunResult(sent=1, unreachable=True)

    control = control_for(runner)
    assert control.post("/control/story/run", headers=KEY).status_code == 202
    status = wait_for_state(control, {"failed", "finished"})
    assert status["state"] == "failed"
    assert status["error_code"] == "api_unreachable"


@pytest.mark.parametrize("method", ["get", "post", "delete"])
def test_every_story_endpoint_needs_the_key(method):
    control = control_for(make_runner(StoryTransport()))
    missing = getattr(control, method)("/control/story/run")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "unauthorized"
    wrong = getattr(control, method)("/control/story/run", headers={"X-API-Key": "not-the-key"})
    assert wrong.status_code == 401


def test_the_story_scenario_is_short_and_leaves_the_measured_scenario_alone():
    story = SCENARIOS["outage-story"]
    assert story.default_count == 90
    assert [(s.at_index, s.processor, s.outage) for s in story.steps] == [(25, "a", True), (65, "a", False)]
    measured = SCENARIOS["processor-a-outage"]
    assert measured.default_count == 300
    assert [(s.at_index, s.outage) for s in measured.steps] == [(100, True), (200, False)]


def test_on_progress_reports_the_sent_count_and_the_switches():
    seen: list[tuple[int, int]] = []
    transport = StoryTransport()
    clock = {"now": 0.0}
    client = RelayClient(API, CONTROL, "story-test-value", transport)
    run_scenario(
        SCENARIOS["outage-story"],
        client,
        seed=66,
        rate=4.0,
        sleep=lambda s: clock.__setitem__("now", clock["now"] + s),
        clock=lambda: clock["now"],
        on_progress=lambda result: seen.append((result.sent, len(result.switch_times))),
    )
    assert seen[0][0] <= 1
    assert seen[-1] == (90, 2)
    assert any(switches == 1 for _, switches in seen)
    assert [s for s, _ in seen] == sorted(s for s, _ in seen)


def test_should_stop_is_honoured_between_payments_and_switches_the_outage_off():
    transport = StoryTransport()
    clock = {"now": 0.0}
    client = RelayClient(API, CONTROL, "story-test-value", transport)
    result = run_scenario(
        SCENARIOS["outage-story"],
        client,
        seed=66,
        rate=4.0,
        sleep=lambda s: clock.__setitem__("now", clock["now"] + s),
        clock=lambda: clock["now"],
        should_stop=lambda: transport.payments >= 40,
    )
    assert result.sent == 40
    assert transport.outage_bodies() == [True, False]


def test_should_stop_is_honoured_while_draining_before_a_switch():
    # No payment ever becomes final, so the drain before the switch at payment 25 would wait out its whole timeout.
    transport = StoryTransport(final=False)
    clock = {"now": 0.0}
    polls = {"n": 0}

    def sleep(seconds: float) -> None:
        clock["now"] += seconds
        polls["n"] += 1

    client = RelayClient(API, CONTROL, "story-test-value", transport)
    result = run_scenario(
        SCENARIOS["outage-story"],
        client,
        seed=66,
        rate=4.0,
        sleep=sleep,
        clock=lambda: clock["now"],
        should_stop=lambda: polls["n"] >= 30,
    )
    assert result.sent == 25  # stopped inside the drain: payment 25 was never sent
    assert transport.outage_bodies() == []
    assert clock["now"] < 60  # far short of the 100 s drain timeout


def test_should_stop_is_honoured_while_waiting_for_the_health_window():
    transport = StoryTransport()
    clock = {"now": 0.0}
    stop_after_off = {"on": False}

    def sleep(seconds: float) -> None:
        clock["now"] += seconds
        if transport.outage_bodies()[-1:] == [False]:
            stop_after_off["on"] = True

    client = RelayClient(API, CONTROL, "story-test-value", transport)
    switched_at = {}

    def stop() -> bool:
        if stop_after_off["on"] and "t" not in switched_at:
            switched_at["t"] = clock["now"]
        return stop_after_off["on"] and clock["now"] - switched_at["t"] >= 3

    result = run_scenario(
        SCENARIOS["outage-story"],
        client,
        seed=66,
        rate=4.0,
        sleep=sleep,
        clock=lambda: clock["now"],
        should_stop=stop,
    )
    assert result.sent == 65  # the health-window wait before payment 65 ended early
    assert result.sent < 90
    assert transport.outage_bodies() == [True, False]
