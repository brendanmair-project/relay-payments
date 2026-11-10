import json
from collections import Counter

import pytest

from generator.__main__ import build_parser, main
from generator.client import RelayClient
from generator.mix import CURRENCIES, Mix, build_payment, parse_mix
from generator.runner import DrainTimeout, run_scenario
from generator.scenarios import SCENARIOS
from generator.settings import setting

API = "http://127.0.0.1:8000"
CONTROL = "http://127.0.0.1:8101"
KEY = "secret-test-key-123"
ENV = {"RELAY_API_KEY": KEY}


class FakeTransport:
    """Records every request; answers 201 for payments and 200 for control calls."""

    def __init__(self, status=201):
        self.calls = []
        self.status = status

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        return (self.status if url.startswith(API) else 200), "{}"

    def payments(self):
        return [c for c in self.calls if c[1] == f"{API}/payments"]

    def bodies(self):
        return [json.loads(c[3]) for c in self.payments()]


class FakeTime:
    """Injected clock and sleep: sleeping advances the clock, nothing really waits."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def run(scenario="normal-day", seed=42, rate=10.0, count=20, transport=None, **kwargs):
    transport = transport or FakeTransport()
    fake = FakeTime()
    client = RelayClient(API, CONTROL, KEY, transport)
    result = run_scenario(SCENARIOS[scenario], client, seed, rate, count, sleep=fake.sleep, clock=fake.clock, **kwargs)
    return result, transport, fake


def test_rate_paces_payments_without_real_waiting():
    result, _, fake = run(rate=4.0, count=9)
    assert result.sent == 9
    assert len(fake.sleeps) == 8  # none before the first payment
    assert all(s == pytest.approx(0.25) for s in fake.sleeps)
    assert fake.now - 1000.0 == pytest.approx(2.0)


def test_duration_stops_the_run():
    result, _, _ = run(rate=2.0, count=None, duration=5.0)
    assert result.sent == 10


def test_default_count_comes_from_the_scenario():
    result, _, _ = run(count=None)
    assert result.sent == SCENARIOS["normal-day"].default_count


def test_requests_have_exact_url_method_headers_and_body():
    result, transport, _ = run(count=3)
    assert len(transport.calls) == 3
    for i, (method, url, headers, body) in enumerate(transport.calls):
        assert (method, url) == ("POST", f"{API}/payments")
        assert set(headers) == {"X-API-Key", "Idempotency-Key", "Content-Type"}
        assert headers["X-API-Key"] == KEY
        assert headers["Content-Type"] == "application/json"
        parsed = json.loads(body)
        assert set(parsed) == {"amount_minor", "currency", "reference"}
        assert parsed["reference"] == f"normal-day-42-{i:06d}"
        assert 1 <= len(headers["Idempotency-Key"]) <= 255
    assert result.statuses == Counter({201: 3})


def test_amounts_and_currencies_are_valid():
    _, transport, _ = run(count=300)
    bodies = transport.bodies()
    assert {b["currency"] for b in bodies} == set(CURRENCIES)
    for b in bodies:
        assert isinstance(b["amount_minor"], int)
        assert 1 <= b["amount_minor"] <= 1_000_000_000_000
        assert len(b["reference"]) <= 64


def test_mix_distribution_is_deterministic_and_weighted():
    def counts(seed):
        mix = Mix(weights={"USD": 80, "EUR": 20})
        return Counter(build_payment("normal-day", seed, i, mix).body["currency"] for i in range(500))

    assert counts(7) == counts(7)
    c = counts(7)
    assert set(c) == {"USD", "EUR"}
    assert c["USD"] > c["EUR"] * 2


def test_parse_mix_and_rejects_unsupported_currency():
    assert parse_mix("USD=1,JPY=3").weights == {"USD": 1.0, "JPY": 3.0}
    with pytest.raises(ValueError):
        parse_mix("CHF=1")
    with pytest.raises(ValueError):
        parse_mix("USD")


def test_two_runs_are_identical_and_seeds_differ():
    _, t1, _ = run(seed=42, count=30)
    _, t2, _ = run(seed=42, count=30)
    _, t3, _ = run(seed=43, count=30)
    assert [(c[2], c[3]) for c in t1.calls] == [(c[2], c[3]) for c in t2.calls]
    assert [b["reference"] for b in t1.bodies()] == [f"normal-day-42-{i:06d}" for i in range(30)]
    assert t1.bodies() != t3.bodies()
    assert {c[2]["Idempotency-Key"] for c in t1.calls}.isdisjoint({c[2]["Idempotency-Key"] for c in t3.calls})


def test_idempotency_keys_are_unique_per_payment():
    _, transport, _ = run(count=100)
    keys = [c[2]["Idempotency-Key"] for c in transport.payments()]
    assert len(set(keys)) == 100


def test_normal_day_makes_no_control_calls():
    result, transport, _ = run("normal-day", count=50)
    assert result.control_calls == []
    assert all(c[1] == f"{API}/payments" for c in transport.calls)


def test_outage_scenario_switches_at_defined_points():
    result, transport, _ = run("processor-a-outage", count=300)
    control = [c for c in transport.calls if c[1].startswith(CONTROL)]
    assert [json.loads(c[3]) for c in control] == [{"enabled": True}, {"enabled": False}]
    for method, url, headers, _ in control:
        assert (method, url) == ("POST", f"{CONTROL}/control/processors/a/outage")
        assert headers["X-API-Key"] == KEY
    assert [(i, p, e) for i, p, e, _ in result.control_calls] == [(100, "a", True), (200, "a", False)]


def test_outage_position_in_call_order():
    _, transport, _ = run("processor-a-outage", count=300)
    positions = [i for i, c in enumerate(transport.calls) if c[1].startswith(CONTROL)]
    assert positions == [100, 201]  # 100 payments, switch on, 100 payments, switch off


def test_outage_is_cleared_if_run_ends_early():
    _, transport, _ = run("processor-a-outage", count=150)
    enabled = [json.loads(c[3])["enabled"] for c in transport.calls if c[1].startswith(CONTROL)]
    assert enabled == [True, False]


def test_only_allowed_hosts_and_paths_are_called():
    _, transport, _ = run("processor-a-outage", count=250, drain=False)
    allowed = {f"{API}/payments", f"{CONTROL}/control/processors/a/outage"}
    assert {c[1] for c in transport.calls} <= allowed
    assert {c[0] for c in transport.calls} == {"POST"}


def test_unreachable_api_stops_the_run():
    result, transport, _ = run(count=10, transport=FakeTransport(status=0))
    assert result.unreachable
    assert result.sent == 1
    assert len(transport.calls) == 1


def test_cli_prints_summary_without_the_key(capsys):
    fake = FakeTime()
    transport = FakeTransport()
    code = main(
        ["--scenario", "normal-day", "--seed", "42", "--rate", "10", "--count", "5"],
        transport=transport,
        sleep=fake.sleep,
        clock=fake.clock,
        environ=ENV,
    )
    out = capsys.readouterr()
    assert code == 0
    assert "sent 5 payments" in out.out and "201: 5" in out.out
    assert KEY not in out.out + out.err
    assert len(fake.sleeps) == 4


def test_cli_exits_nonzero_when_unreachable(capsys):
    fake = FakeTime()
    code = main(["--count", "3"], transport=FakeTransport(status=0), sleep=fake.sleep, clock=fake.clock, environ=ENV)
    out = capsys.readouterr()
    assert code == 1
    assert KEY not in out.out + out.err


def test_cli_without_key_fails_and_bad_arguments_fail(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr("generator.settings.SETTINGS_FILE", tmp_path / "missing")
    assert main(["--count", "1"], transport=FakeTransport(), environ={}) == 2
    assert main(["--mix", "CHF=1"], transport=FakeTransport(), environ=ENV) == 2
    assert main(["--rate", "0"], transport=FakeTransport(), environ=ENV) == 2


def test_setting_prefers_environment_then_file(tmp_path):
    f = tmp_path / "settings"
    f.write_text('RELAY_API_KEY="from-file"\nOTHER=1\n', encoding="utf-8")
    assert setting("RELAY_API_KEY", environ={"RELAY_API_KEY": "from-env"}, settings_file=f) == "from-env"
    assert setting("RELAY_API_KEY", environ={}, settings_file=f) == "from-file"
    assert setting("MISSING", "dflt", environ={}, settings_file=f) == "dflt"


class DrainTransport:
    """Payments answer 201 with an id; GET /payments/{id} says final only after `polls_needed` polls of that id."""

    def __init__(self, polls_needed=2, never_final=False):
        self.calls = []
        self.polls = Counter()
        self.polls_needed = polls_needed
        self.never_final = never_final
        self.posted = 0

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        if method == "POST" and url == f"{API}/payments":
            self.posted += 1
            return 201, json.dumps({"id": f"p{self.posted - 1}"})
        if method == "GET" and url.startswith(f"{API}/payments/"):
            pid = url.rsplit("/", 1)[-1]
            self.polls[pid] += 1
            final = not self.never_final and self.polls[pid] >= self.polls_needed
            return 200, json.dumps({"id": pid, "is_final": final})
        return 200, "{}"

    def index_of_control(self, n):
        return [i for i, c in enumerate(self.calls) if c[1].startswith(CONTROL)][n]


def test_switch_waits_until_every_earlier_payment_is_final():
    needed = 3
    transport = DrainTransport(polls_needed=needed)
    result, _, _ = run("processor-a-outage", count=300, transport=transport)
    assert [(i, e) for i, _, e, _ in result.control_calls] == [(100, True), (200, False)]
    for n, earlier in enumerate((100, 200)):
        before = transport.calls[: transport.index_of_control(n)]
        assert sum(c[0] == "POST" and c[1] == f"{API}/payments" for c in before) == earlier
        polls = Counter(c[1].rsplit("/", 1)[-1] for c in before if c[0] == "GET")
        assert all(polls[f"p{k}"] >= needed for k in range(earlier))  # each was seen final before the switch


def test_only_unfinished_payments_are_polled_again():
    transport = DrainTransport(polls_needed=2)
    run("processor-a-outage", count=150, transport=transport)
    assert max(transport.polls.values()) == 2  # polled until final, then never again


def test_drain_timeout_raises_before_any_switch():
    transport = DrainTransport(never_final=True)
    with pytest.raises(DrainTimeout, match="100"):
        run("processor-a-outage", count=300, transport=transport, drain_timeout=5.0)
    assert not [c for c in transport.calls if c[1].startswith(CONTROL)]


class StatusTransport(DrainTransport):
    """A DrainTransport whose payment reads also carry a status and an attempt number."""

    def __call__(self, method, url, headers, body):
        status, text = super().__call__(method, url, headers, body)
        if method == "GET" and url.startswith(f"{API}/payments/"):
            data = json.loads(text)
            data.update({"status": "processing", "attempt_no": 2})
            text = json.dumps(data)
        return status, text


def test_the_default_drain_limit_covers_the_redrive_cycle():
    # 2 x (REDRIVE_AFTER_SECONDS 30 + SWEEP_TIMEOUT_GRACE_SECONDS 5) + 30
    assert build_parser(ENV).get_default("drain_timeout") == 100.0
    transport = DrainTransport(never_final=True)
    fake = FakeTime()
    with pytest.raises(DrainTimeout):
        client = RelayClient(API, CONTROL, KEY, transport)
        run_scenario(SCENARIOS["processor-a-outage"], client, 42, 100.0, 300, sleep=fake.sleep, clock=fake.clock)
    assert fake.now - 1000.0 >= 100.0


def test_a_drain_timeout_lists_the_unfinished_payments():
    transport = StatusTransport(never_final=True)
    with pytest.raises(DrainTimeout) as caught:
        run("processor-a-outage", count=300, transport=transport, drain_timeout=2.0)
    unfinished = caught.value.unfinished
    assert len(unfinished) == 100
    assert unfinished[0] == {"id": "p0", "status": "processing", "attempt_no": 2}
    assert [u["id"] for u in unfinished] == sorted(u["id"] for u in unfinished)


def test_cli_prints_each_unfinished_payment_on_a_drain_timeout(capsys):
    fake = FakeTime()
    transport = StatusTransport(never_final=True)
    argv = ["--scenario", "processor-a-outage", "--count", "150", "--rate", "100", "--drain-timeout", "2"]
    code = main(argv, transport=transport, sleep=fake.sleep, clock=fake.clock, environ=ENV)
    err = capsys.readouterr().err
    assert code == 1 and "the outage was not switched" in err
    lines = [line for line in err.splitlines() if line.startswith("  unfinished payment ")]
    assert len(lines) == 100
    assert lines[0] == "  unfinished payment p0: status processing, attempt 2"
    assert KEY not in err


def test_a_payment_without_a_readable_status_is_listed_as_unknown():
    transport = DrainTransport(never_final=True)
    with pytest.raises(DrainTimeout) as caught:
        run("processor-a-outage", count=300, transport=transport, drain_timeout=2.0)
    assert caught.value.unfinished[0] == {"id": "p0", "status": "unknown", "attempt_no": None}


def test_each_outage_switch_records_its_wall_clock_time():
    ticks = iter([1_700_000_000.5, 1_700_000_100.25])
    result, _, _ = run("processor-a-outage", count=300, wall_clock=lambda: next(ticks), drain=False)
    assert result.switch_times == [
        {"index": 100, "processor": "a", "outage": True, "at": "2023-11-14T22:13:20.500Z"},
        {"index": 200, "processor": "a", "outage": False, "at": "2023-11-14T22:15:00.250Z"},
    ]


def test_cli_prints_the_switch_times_for_the_timing_script(capsys):
    fake = FakeTime()
    transport = DrainTransport()
    argv = ["--scenario", "processor-a-outage", "--count", "250", "--rate", "100", "--no-drain"]
    code = main(
        argv, transport=transport, sleep=fake.sleep, clock=fake.clock, environ=ENV, wall_clock=lambda: 1_700_000_000.5
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "switch time processor a outage on at 2023-11-14T22:13:20.500Z" in out
    assert "switch time processor a outage off at 2023-11-14T22:13:20.500Z" in out


def test_no_drain_keeps_the_old_behaviour():
    transport = DrainTransport(never_final=True)
    result, _, _ = run("processor-a-outage", count=300, transport=transport, drain=False)
    assert not [c for c in transport.calls if c[0] == "GET"]
    assert [(i, e) for i, _, e, _ in result.control_calls] == [(100, True), (200, False)]


def test_a_scenario_without_control_steps_never_polls():
    transport = DrainTransport()
    run("normal-day", count=30, transport=transport)
    assert not [c for c in transport.calls if c[0] == "GET"]


def test_drain_only_uses_the_public_payments_api():
    transport = DrainTransport()
    run("processor-a-outage", count=250, transport=transport)
    urls = {c[1] for c in transport.calls if c[0] == "GET"} - {f"{API}/processors/health"}
    assert urls and all(u.startswith(f"{API}/payments/p") for u in urls)
    assert all(c[2]["X-API-Key"] == KEY for c in transport.calls if c[0] == "GET")


def test_cli_no_drain_flag_and_timeout_exit(capsys):
    fake = FakeTime()
    transport = DrainTransport(never_final=True)
    argv = ["--scenario", "processor-a-outage", "--count", "150", "--rate", "100"]
    code = main(argv + ["--no-drain"], transport=transport, sleep=fake.sleep, clock=fake.clock, environ=ENV)
    assert code == 0 and not [c for c in transport.calls if c[0] == "GET"]
    capsys.readouterr()
    transport = DrainTransport(never_final=True)
    code = main(argv + ["--drain-timeout", "3"], transport=transport, sleep=fake.sleep, clock=fake.clock, environ=ENV)
    err = capsys.readouterr().err
    assert code == 1 and "did not become final" in err and KEY not in err


def test_the_outage_scenario_describes_the_drain():
    assert "final" in SCENARIOS["processor-a-outage"].description


class HealthTransport(DrainTransport):
    """Payments are final at once. GET /processors/health says `avoided` for processor A until `recovers_after`
    seconds after the outage-off control call (never when None); times come from the shared fake clock."""

    def __init__(self, fake, recovers_after=12.0, window=60):
        super().__init__(polls_needed=1)
        self.fake = fake
        self.recovers_after = recovers_after
        self.window = window
        self.times = []
        self.off_at = None

    def __call__(self, method, url, headers, body):
        self.times.append(self.fake.now)
        if url.startswith(CONTROL) and json.loads(body) == {"enabled": False}:
            self.off_at = self.fake.now
        if method == "GET" and url == f"{API}/processors/health":
            recovered = self.recovers_after is not None and self.off_at is not None
            recovered = recovered and self.fake.now - self.off_at >= self.recovers_after
            state = "healthy" if recovered or self.off_at is None else "avoided"
            payload = {"window_seconds": self.window, "processors": [{"name": "A", "state": state}]}
            self.calls.append((method, url, dict(headers), body))
            return 200, json.dumps(payload)
        return super().__call__(method, url, headers, body)

    def health_polls(self):
        return [t for t, c in zip(self.times, self.calls, strict=True) if c[1] == f"{API}/processors/health"]


def run_health(count=260, rate=10.0, **kwargs):
    fake = FakeTime()
    transport = HealthTransport(fake, **{k: kwargs.pop(k) for k in ("recovers_after", "window") if k in kwargs})
    client = RelayClient(API, CONTROL, KEY, transport)
    result = run_scenario(
        SCENARIOS["processor-a-outage"], client, 7, rate, count, sleep=fake.sleep, clock=fake.clock, **kwargs
    )
    return result, transport, fake


def post_times(transport):
    return [
        t for t, c in zip(transport.times, transport.calls, strict=True) if c[0] == "POST" and c[1] == f"{API}/payments"
    ]


def test_next_payment_waits_one_health_window_after_the_outage_ends():
    _, transport, _ = run_health()
    times = post_times(transport)
    assert transport.off_at is not None
    after = [t for t in times if t > transport.off_at]
    assert after[0] - transport.off_at >= 65  # window_seconds (60) + 5
    assert 0.09 <= after[1] - after[0] <= 0.11  # pacing continues; the wait is not followed by a burst
    # switching the outage ON is not followed by a health wait
    assert times[100] - times[99] < 5


def test_recovery_lag_is_measured_from_the_health_polls():
    result, transport, _ = run_health(recovers_after=12.0)
    assert len(result.recovery_lags) == 1
    lag = result.recovery_lags[0]
    assert lag["processor"] == "a"
    assert 12.0 <= lag["lag_seconds"] <= 13.0  # polled every second
    assert lag["waited_seconds"] >= 65
    polls = transport.health_polls()
    assert 12 <= len(polls) <= 16  # polling stops once the processor is no longer avoided
    assert all(0.9 <= b - a <= 1.1 for a, b in zip(polls[1:], polls[2:], strict=False))


def test_a_processor_that_never_recovers_reports_no_lag():
    result, _, _ = run_health(recovers_after=None)
    assert result.recovery_lags[0]["lag_seconds"] is None
    assert result.recovery_lags[0]["waited_seconds"] >= 65


def test_window_comes_from_the_health_endpoint():
    _, transport, _ = run_health(window=20)
    after = [t for t in post_times(transport) if t > transport.off_at]
    assert 25 <= after[0] - transport.off_at < 30


def test_no_drain_skips_the_health_wait_too():
    result, transport, _ = run_health(drain=False)
    assert result.recovery_lags == []
    assert f"{API}/processors/health" not in {c[1] for c in transport.calls}


def test_cli_prints_the_recovery_lag(capsys):
    fake = FakeTime()
    transport = HealthTransport(fake, recovers_after=12.0)
    argv = ["--scenario", "processor-a-outage", "--count", "210", "--rate", "100"]
    assert main(argv, transport=transport, sleep=fake.sleep, clock=fake.clock, environ=ENV) == 0
    assert "recovery lag processor a: 12.0 s" in capsys.readouterr().out
    transport = HealthTransport(fake, recovers_after=None)
    assert main(argv, transport=transport, sleep=fake.sleep, clock=fake.clock, environ=ENV) == 0
    assert "recovery lag processor a: not recovered within the wait" in capsys.readouterr().out


# REL-43: partial degradation, a profile change beside the outage switch.
def test_degraded_scenario_raises_a_timeout_rate_then_restores_the_default():
    from generator.scenarios import ProfileStep

    scenario = SCENARIOS["processor-a-degraded"]
    assert scenario.default_count == 300
    on, off = scenario.steps
    assert isinstance(on, ProfileStep) and isinstance(off, ProfileStep)
    assert (on.at_index, on.processor, off.at_index, off.processor) == (100, "a", 200, "a")
    assert on.profile["timeout_rate"] == 0.35
    assert off.profile == ProfileStep.default_profile("a")


def test_default_profile_copies_match_the_simulator_defaults():
    from generator.scenarios import ProfileStep
    from processors.profiles import DEFAULT_PROFILES

    for name in ("a", "b"):
        assert ProfileStep.default_profile(name) == DEFAULT_PROFILES[name].model_dump()


def test_existing_scenarios_keep_their_counts_and_steps():
    from generator.scenarios import ControlStep

    assert SCENARIOS["normal-day"].default_count == 200 and SCENARIOS["normal-day"].steps == ()
    outage = SCENARIOS["processor-a-outage"]
    assert outage.default_count == 300
    assert outage.steps == (ControlStep(100, "a", True), ControlStep(200, "a", False))


def _profile_calls(transport):
    return [
        (c[0], c[1], json.loads(c[3])) for c in transport.calls if c[1] == f"{CONTROL}/control/processors/a/profile"
    ]


def test_degraded_scenario_puts_the_profile_at_the_defined_points():
    result, transport, fake = run("processor-a-degraded", count=300)
    calls = _profile_calls(transport)
    assert [(m, u) for m, u, _ in calls] == [("PUT", f"{CONTROL}/control/processors/a/profile")] * 2
    assert calls[0][2]["timeout_rate"] == 0.35
    assert calls[1][2]["timeout_rate"] == 0.02
    positions = [i for i, c in enumerate(transport.calls) if c[1].startswith(CONTROL)]
    assert positions == [100, 201]
    assert result.sent == 300
    # A degradation is not an outage: no outage call and no wait for the health window afterwards.
    assert not [c for c in transport.calls if c[1].endswith("/outage")]
    assert result.recovery_lags == []
    assert max(fake.sleeps, default=0) < 5


def test_degraded_profile_is_restored_if_run_ends_early():
    _, transport, _ = run("processor-a-degraded", count=150)
    calls = _profile_calls(transport)
    assert [body["timeout_rate"] for _, _, body in calls] == [0.35, 0.02]
