"""REL-19: simulated Processors A and B (docs/architecture/api-contract.md, "Simulator APIs")."""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.apps import create_apps
from processors.outcomes import uniform
from processors.simulator import Simulator

KEY = {"X-API-Key": "test-key"}


class RecordingSleep:
    """Replaces asyncio.sleep so tests never wait; records each requested delay in seconds."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        await asyncio.sleep(0)


@pytest.fixture
def sim() -> Simulator:
    return Simulator(seed=42, timeout_seconds=5)


@pytest.fixture
def sleep() -> RecordingSleep:
    return RecordingSleep()


@pytest.fixture
def clients(sim: Simulator, sleep: RecordingSleep) -> tuple[TestClient, TestClient]:
    processor_app, control_app = create_apps(sim, sleep=sleep, api_key="test-key")
    return TestClient(processor_app), TestClient(control_app)


def body(payment_id: str = "pay_1", attempt_no: int = 1) -> dict:
    return {"payment_id": payment_id, "attempt_no": attempt_no, "amount_minor": 1999, "currency": "USD"}


def call(client: TestClient, processor: str, operation: str, payment_id: str = "pay_1", attempt_no: int = 1):
    return client.post(
        f"/processors/{processor}/{operation}",
        json=body(payment_id, attempt_no),
        headers={"Idempotency-Key": f"{payment_id}:{attempt_no}"},
    )


def set_profile(control: TestClient, processor: str, **changes: float) -> None:
    profile = {"latency_ms_p50": 100, "latency_ms_p95": 300, "decline_rate": 0.0, "timeout_rate": 0.0}
    profile.update(changes)
    response = control.put(f"/control/processors/{processor}/profile", json=profile, headers=KEY)
    assert response.status_code == 200, response.text


# Endpoints per processor


@pytest.mark.parametrize("processor", ["a", "b"])
def test_authorize_and_capture_answer_per_processor(clients, processor):
    processor_client, control = clients
    set_profile(control, processor)
    authorized = call(processor_client, processor, "authorize")
    assert authorized.status_code == 200
    assert authorized.json()["result"] == "approved"
    assert authorized.json()["reason"] is None
    assert authorized.json()["latency_ms"] > 0
    captured = call(processor_client, processor, "capture")
    assert captured.status_code == 200
    assert captured.json()["result"] == "captured"


def test_unknown_processor_is_404(clients):
    processor_client, control = clients
    response = call(processor_client, "c", "authorize")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_processor"
    assert control.post("/control/processors/c/outage", json={"enabled": True}, headers=KEY).status_code == 404


def test_processor_api_needs_no_key_but_the_idempotency_key_must_match_the_body(clients):
    processor_client, _ = clients
    response = processor_client.post(
        "/processors/a/authorize", json=body("pay_1", 1), headers={"Idempotency-Key": "pay_1:2"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "idempotency_key_mismatch"


def test_missing_idempotency_key_and_bad_body_use_the_error_shape(clients):
    processor_client, _ = clients
    missing = processor_client.post("/processors/a/authorize", json=body())
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "validation_error"
    bad = processor_client.post(
        "/processors/a/authorize",
        json={**body(), "amount_minor": 0, "currency": "usd"},
        headers={"Idempotency-Key": "pay_1:1"},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "validation_error"


# Profiles


def test_decline_rate_one_declines_with_a_reason(clients):
    processor_client, control = clients
    set_profile(control, "a", decline_rate=1.0)
    response = call(processor_client, "a", "authorize")
    assert response.json()["result"] == "declined"
    assert response.json()["reason"] in {"insufficient_funds", "do_not_honor", "card_expired"}


def test_decline_rate_matches_the_profile_over_many_payments(clients):
    processor_client, control = clients
    set_profile(control, "b", decline_rate=0.3)
    results = [call(processor_client, "b", "authorize", f"pay_{n}").json()["result"] for n in range(400)]
    assert 0.24 <= results.count("declined") / len(results) <= 0.36


def test_latency_follows_the_profile_and_the_processor_sleeps_for_it(clients, sleep):
    processor_client, control = clients
    set_profile(control, "a", latency_ms_p50=200, latency_ms_p95=600)
    answered = [call(processor_client, "a", "authorize", f"pay_{n}").json()["latency_ms"] for n in range(400)]
    assert sleep.calls == [latency / 1000 for latency in answered]
    latencies = sorted(answered)
    assert 160 <= latencies[200] <= 240
    assert 480 <= latencies[380] <= 720


def test_profiles_differ_between_a_and_b_by_default(clients):
    _, control = clients
    response = control.get("/control/processors", headers=KEY)
    assert response.status_code == 200
    processors = response.json()["processors"]
    assert set(processors) == {"a", "b"}
    assert processors["a"]["profile"] != processors["b"]["profile"]
    assert processors["a"]["outage"] is False


def test_profile_change_is_visible_and_validated(clients):
    _, control = clients
    set_profile(control, "b", decline_rate=0.5)
    assert control.get("/control/processors", headers=KEY).json()["processors"]["b"]["profile"]["decline_rate"] == 0.5
    invalid = {"latency_ms_p50": 300, "latency_ms_p95": 100, "decline_rate": 0.7, "timeout_rate": 0.5}
    response = control.put("/control/processors/b/profile", json=invalid, headers=KEY)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_capture_failure_rate_fails_captures(clients):
    processor_client, control = clients
    set_profile(control, "a", capture_failure_rate=1.0)
    call(processor_client, "a", "authorize")
    response = call(processor_client, "a", "capture").json()
    assert (response["result"], response["reason"]) == ("failed", "capture_failed")


def test_capture_needs_an_approved_authorize_for_the_same_attempt_on_the_same_processor(clients):
    processor_client, control = clients
    set_profile(control, "a")
    set_profile(control, "b", decline_rate=1.0)
    never = call(processor_client, "a", "capture")
    assert never.status_code == 409
    assert never.json()["error"]["code"] == "not_authorized"
    call(processor_client, "a", "authorize")
    assert call(processor_client, "b", "capture").status_code == 409
    assert call(processor_client, "a", "capture", attempt_no=2).status_code == 409
    call(processor_client, "b", "authorize", "pay_2")
    assert call(processor_client, "b", "capture", "pay_2").status_code == 409
    assert call(processor_client, "a", "capture").json()["result"] == "captured"


def test_answers_stay_below_the_worker_timeout(clients):
    processor_client, control = clients
    set_profile(control, "a", latency_ms_p50=4000, latency_ms_p95=60000)
    latencies = [call(processor_client, "a", "authorize", f"pay_{n}").json()["latency_ms"] for n in range(200)]
    assert max(latencies) == 4900


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/control/processors", None),
        (
            "put",
            "/control/processors/a/profile",
            {"latency_ms_p50": 1, "latency_ms_p95": 1, "decline_rate": 0, "timeout_rate": 0},
        ),
        ("post", "/control/processors/a/outage", {"enabled": True}),
    ],
)
def test_control_routes_require_the_key_and_change_nothing_without_it(clients, method, path, payload):
    _, control = clients
    response = control.request(method.upper(), path, json=payload, headers={"X-API-Key": "wrong"})
    assert response.status_code == 401
    assert control.get("/control/processors", headers=KEY).json()["processors"]["a"]["outage"] is False


def test_processor_and_control_routes_stay_on_their_own_ports(clients):
    processor_client, control = clients
    assert processor_client.get("/control/processors", headers=KEY).status_code == 404
    assert (
        control.post("/processors/a/authorize", json=body(), headers={**KEY, "Idempotency-Key": "pay_1:1"}).status_code
        == 404
    )


def test_concurrent_requests_with_one_key_get_one_outcome(sim, sleep):
    processor_app, _ = create_apps(sim, sleep=sleep, api_key="test-key")

    async def both() -> list[dict]:
        transport = httpx.ASGITransport(app=processor_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://sim") as client:
            responses = await asyncio.gather(
                *(
                    client.post("/processors/b/authorize", json=body("pay_c"), headers={"Idempotency-Key": "pay_c:1"})
                    for _ in range(5)
                )
            )
        return [response.json() for response in responses]

    results = asyncio.run(both())
    assert all(result == results[0] for result in results)
    assert len(sleep.calls) == 1


# Outages and timeouts


def test_outage_toggles_at_runtime(clients):
    processor_client, control = clients
    set_profile(control, "a")
    assert control.post("/control/processors/a/outage", json={"enabled": True}, headers=KEY).status_code == 200
    down = call(processor_client, "a", "authorize")
    assert down.status_code == 503
    assert down.json()["error"]["code"] == "processor_outage"
    assert call(processor_client, "b", "authorize", "pay_2").status_code == 200
    assert control.get("/control/processors", headers=KEY).json()["processors"]["a"]["outage"] is True
    control.post("/control/processors/a/outage", json={"enabled": False}, headers=KEY)
    assert call(processor_client, "a", "authorize").status_code == 200


def test_outage_responses_are_not_remembered_for_the_key(clients):
    processor_client, control = clients
    set_profile(control, "a")
    control.post("/control/processors/a/outage", json={"enabled": True}, headers=KEY)
    assert call(processor_client, "a", "authorize").status_code == 503
    control.post("/control/processors/a/outage", json={"enabled": False}, headers=KEY)
    assert call(processor_client, "a", "authorize").json()["result"] == "approved"


def test_timeout_is_a_distinct_failure_that_answers_after_the_worker_gives_up(clients, sleep):
    processor_client, control = clients
    set_profile(control, "a", timeout_rate=1.0)
    response = call(processor_client, "a", "authorize")
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "processor_timeout"
    assert sleep.calls == [6.0]
    assert call(processor_client, "a", "authorize").status_code == 504
    assert sleep.calls == [6.0, 6.0]


def test_outage_hides_stored_results_until_it_ends(clients):
    processor_client, control = clients
    set_profile(control, "a")
    first = call(processor_client, "a", "authorize").json()
    control.post("/control/processors/a/outage", json={"enabled": True}, headers=KEY)
    assert call(processor_client, "a", "authorize").status_code == 503
    control.post("/control/processors/a/outage", json={"enabled": False}, headers=KEY)
    assert call(processor_client, "a", "authorize").json() == first


# Idempotency and reproducibility


def test_repeated_key_returns_the_first_result_without_waiting_again(clients, sleep):
    processor_client, control = clients
    set_profile(control, "a", decline_rate=0.5)
    first = call(processor_client, "a", "authorize", "pay_9")
    set_profile(control, "a", decline_rate=1.0 if first.json()["result"] == "approved" else 0.0)
    again = call(processor_client, "a", "authorize", "pay_9")
    assert again.json() == first.json()
    assert len(sleep.calls) == 1


def test_reused_key_with_a_different_body_is_a_conflict(clients):
    processor_client, control = clients
    set_profile(control, "a")
    call(processor_client, "a", "authorize")
    response = processor_client.post(
        "/processors/a/authorize",
        json={**body(), "amount_minor": 5},
        headers={"Idempotency-Key": "pay_1:1"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_key_reused"


def test_authorize_and_capture_keys_are_separate(clients):
    processor_client, control = clients
    set_profile(control, "a")
    assert call(processor_client, "a", "authorize").json()["result"] == "approved"
    assert call(processor_client, "a", "capture").json()["result"] == "captured"


def run(order: list[tuple[str, str, int]], seed: int = 42) -> dict[tuple[str, str, int], dict]:
    sim = Simulator(seed=seed, timeout_seconds=5)
    processor_app, control_app = create_apps(sim, sleep=RecordingSleep(), api_key="test-key")
    processor_client, control = TestClient(processor_app), TestClient(control_app)
    for name in ("a", "b"):
        set_profile(control, name, decline_rate=0.4, timeout_rate=0.1, capture_failure_rate=0.2)
    results = {}
    for operation in ("authorize", "capture"):
        for processor, payment_id, attempt_no in order:
            response = call(processor_client, processor, operation, payment_id, attempt_no)
            results[(operation, processor, payment_id, attempt_no)] = {
                "status": response.status_code,
                "body": response.json(),
            }
    return results


REQUESTS = [(p, f"pay_{n}", attempt) for n in range(60) for p in ("a", "b") for attempt in (1, 2)]


def test_same_seed_gives_the_same_outcomes_in_a_different_arrival_order():
    forward = run(REQUESTS)
    backward = run(list(reversed(REQUESTS)))
    assert forward == backward


def test_a_different_seed_changes_outcomes():
    assert run(REQUESTS, seed=42) != run(REQUESTS, seed=7)


def test_uniform_is_stable_and_in_range():
    value = uniform(42, "a", "pay_1", 1, "authorize")
    assert value == uniform(42, "a", "pay_1", 1, "authorize")
    assert 0.0 <= value < 1.0
    assert value != uniform(42, "b", "pay_1", 1, "authorize")


# REL-54: draws seeded on the payment reference (ADR-0012)


def ref_call(client, processor, operation, payment_id, reference=None, attempt_no=1):
    payload = body(payment_id, attempt_no)
    if reference is not None:
        payload["reference"] = reference
    return client.post(
        f"/processors/{processor}/{operation}",
        json=payload,
        headers={"Idempotency-Key": f"{payment_id}:{attempt_no}"},
    )


def set_mixed_profiles(control) -> None:
    for name in ("a", "b"):
        set_profile(control, name, decline_rate=0.4, timeout_rate=0.1, capture_failure_rate=0.2)


def test_payments_with_one_reference_draw_identical_outcomes_and_latencies(clients):
    processor_client, control = clients
    set_mixed_profiles(control)
    seen = set()
    for processor in ("a", "b"):
        for operation in ("authorize", "capture"):
            for n in range(40):
                reference = f"run-42-{n}"
                first = ref_call(processor_client, processor, operation, f"pay_first_{n}", reference)
                second = ref_call(processor_client, processor, operation, f"pay_second_{n}", reference)
                assert (first.status_code, first.json()) == (second.status_code, second.json())
                if first.status_code == 200:
                    seen.add((operation, first.json()["result"], first.json()["latency_ms"]))
    assert len({latency for _, _, latency in seen}) > 10
    assert {result for _, result, _ in seen} >= {"approved", "declined", "captured", "failed"}


def test_the_reference_replaces_the_payment_id_as_the_draw_key(clients):
    processor_client, control = clients
    set_mixed_profiles(control)
    for n in range(40):
        with_reference = ref_call(processor_client, "a", "authorize", f"pay_{n}", reference=f"other_{n}")
        as_payment_id = ref_call(processor_client, "a", "authorize", f"other_{n}")
        assert (with_reference.status_code, with_reference.json()) == (as_payment_id.status_code, as_payment_id.json())


def test_without_a_reference_the_draws_still_use_the_payment_id(clients):
    from processors.outcomes import decide
    from processors.profiles import DEFAULT_PROFILES

    processor_client, _ = clients
    for n in range(20):
        payment_id = f"pay_{n}"
        response = ref_call(processor_client, "a", "authorize", payment_id)
        expected = decide(42, "a", "authorize", payment_id, 1, DEFAULT_PROFILES["a"], max_latency_ms=4900)
        if expected.kind == "result":
            assert response.json() == {
                "result": expected.result,
                "reason": expected.reason,
                "latency_ms": expected.latency_ms,
            }
        else:
            assert response.status_code == 504


@pytest.mark.parametrize("reference", ["", "x" * 65, "has space", "slash/ed", "ünï", 5])
def test_an_invalid_reference_is_a_validation_error(clients, reference):
    processor_client, _ = clients
    for operation in ("authorize", "capture"):
        response = processor_client.post(
            f"/processors/a/{operation}",
            json={**body(), "reference": reference},
            headers={"Idempotency-Key": "pay_1:1"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("reference", ["a", "A-b_c.9", "x" * 64])
def test_a_valid_reference_is_accepted(clients, reference):
    processor_client, control = clients
    set_profile(control, "a")
    assert ref_call(processor_client, "a", "authorize", "pay_1", reference).status_code == 200


def test_reused_key_with_a_different_reference_is_a_conflict(clients):
    processor_client, control = clients
    set_profile(control, "a")
    assert ref_call(processor_client, "a", "authorize", "pay_1", "ref-1").status_code == 200
    changed = ref_call(processor_client, "a", "authorize", "pay_1", "ref-2")
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "idempotency_key_reused"
    dropped = ref_call(processor_client, "a", "authorize", "pay_1")
    assert dropped.status_code == 409
    same = ref_call(processor_client, "a", "authorize", "pay_1", "ref-1")
    assert same.status_code == 200
