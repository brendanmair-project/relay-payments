"""REL-25.4/25.10: GET and POST /payments/{id}/explanation (api-contract.md); the model is always a fake."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.explain.store import explain_payment
from tests.api.test_read_payments import auth
from tests.explain.fakes import FakeModel, answer
from tests.explainer.helpers import SENTINEL, captured, declined, retrying

Factory = sessionmaker[Session]
FIELDS = {
    "payment_id",
    "source",
    "model",
    "text",
    "cited_event_seqs",
    "trigger",
    "generated_at",
    "fallback_reason",
    "attempted_model",
    "model_cause",
    "rules_cause",
    "generation_ms",
    "inputs",
    "cross_check",
}


@pytest.fixture
def factory(engine: Engine) -> Factory:
    return sessionmaker(engine, expire_on_commit=False)


def use(client: TestClient, model: FakeModel) -> FakeModel:
    client.app.state.model_client = model  # type: ignore[attr-defined]
    return model


def url(pid: object, suffix: str = "") -> str:
    return f"/payments/{pid}/explanation{suffix}"


def count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text("SELECT count(*) FROM payment_explanations")).scalar_one())


def good() -> FakeModel:
    return FakeModel(answer("Declined for insufficient funds.", [3, 4], "decline_insufficient_funds"))


@pytest.mark.parametrize("method", ["get", "post"])
def test_key_is_required(client: TestClient, method: str) -> None:
    pid = uuid.uuid4()
    path = url(pid) if method == "get" else url(pid, "/regenerate")
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, headers={"X-API-Key": "wrong"}).status_code == 401


def test_get_returns_the_stored_explanation_without_calling_the_model(
    client: TestClient, factory: Factory, api_key: str
) -> None:
    pid = declined(factory)
    explain_payment(factory, pid, "final_failure", good())
    spy = use(client, FakeModel(unavailable="model_unreachable"))
    response = client.get(url(pid), headers=auth(api_key))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == FIELDS
    assert body["payment_id"] == str(pid)
    assert body["source"] == "model"
    assert body["model"] == "granite3.3:2b"
    assert body["text"] == "Declined for insufficient funds."
    assert body["cited_event_seqs"] == [3, 4]
    assert body["trigger"] == "final_failure"
    assert body["fallback_reason"] is None
    assert body["generated_at"].endswith("Z")
    assert spy.prompts == []


def test_get_fills_a_missing_explanation_for_a_final_payment_once(
    client: TestClient, factory: Factory, engine: Engine, api_key: str
) -> None:
    pid = captured(factory)
    model = use(client, FakeModel(answer("Captured first time.", [4], "captured_first_time")))
    first = client.get(url(pid), headers=auth(api_key))
    assert first.status_code == 200
    assert first.json()["trigger"] == "on_request"
    assert first.json()["source"] == "model"
    again = client.get(url(pid), headers=auth(api_key))
    assert again.json() == first.json()
    assert len(model.prompts) == 1
    assert count(engine) == 1


def test_get_without_a_model_answers_from_the_rules_and_says_so(
    client: TestClient, factory: Factory, api_key: str
) -> None:
    pid = declined(factory)
    use(client, FakeModel(unavailable="model_timeout"))
    body = client.get(url(pid), headers=auth(api_key)).json()
    assert (body["source"], body["model"], body["fallback_reason"]) == ("rules", None, "model_timeout")
    assert body["text"]
    assert body["cited_event_seqs"]


def test_get_never_sends_the_description(client: TestClient, factory: Factory, api_key: str) -> None:
    pid = declined(factory)
    model = use(client, good())
    client.get(url(pid), headers=auth(api_key))
    assert model.prompts
    assert SENTINEL not in model.prompts[0]


def test_non_final_payment_is_409(client: TestClient, factory: Factory, api_key: str) -> None:
    pid = retrying(factory)
    for response in (
        client.get(url(pid), headers=auth(api_key)),
        client.post(url(pid, "/regenerate"), headers=auth(api_key)),
    ):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "payment_not_final"


@pytest.mark.parametrize("bad", [str(uuid.uuid4()), "not-a-uuid"])
def test_unknown_payment_is_404(client: TestClient, api_key: str, bad: str) -> None:
    assert client.get(url(bad), headers=auth(api_key)).status_code == 404
    assert client.post(url(bad, "/regenerate"), headers=auth(api_key)).status_code == 404


def test_regenerate_adds_a_row_returns_201_and_becomes_the_latest(
    client: TestClient, factory: Factory, engine: Engine, api_key: str
) -> None:
    pid = declined(factory)
    explain_payment(factory, pid, "final_failure", good())
    use(client, FakeModel(answer("A fresh explanation.", [3], "decline_insufficient_funds")))
    response = client.post(url(pid, "/regenerate"), headers=auth(api_key))
    assert response.status_code == 201
    body = response.json()
    assert set(body) == FIELDS
    assert body["trigger"] == "regenerate"
    assert body["text"] == "A fresh explanation."
    assert count(engine) == 2
    assert client.get(url(pid), headers=auth(api_key)).json()["text"] == "A fresh explanation."


def test_get_does_not_regenerate_on_repeat(client: TestClient, factory: Factory, engine: Engine, api_key: str) -> None:
    pid = declined(factory)
    explain_payment(factory, pid, "final_failure", good())
    use(client, good())
    for _ in range(3):
        client.get(url(pid), headers=auth(api_key))
    assert count(engine) == 1


RIGHT = "decline_insufficient_funds"
CROSS_CHECK_CASES = {
    "agreed": (FakeModel(answer("Declined for funds.", [3, 4], RIGHT)), "agreed", "granite3.3:2b", RIGHT),
    "disagreed": (
        FakeModel(answer("Timed out.", [3, 4], "authorize_timeout")),
        "disagreed_rules_used",
        "granite3.3:2b",
        "authorize_timeout",
    ),
    "unreachable": (FakeModel(unavailable="model_unreachable"), "model_unavailable", "granite3.3:2b", None),
    "timeout": (FakeModel(unavailable="model_timeout"), "model_unavailable", "granite3.3:2b", None),
    "unusable": (FakeModel(answer("Declined.", [99], RIGHT)), "model_unavailable", "granite3.3:2b", None),
}


@pytest.mark.parametrize("case", CROSS_CHECK_CASES)
def test_get_returns_the_generation_details_and_the_cross_check(
    client: TestClient, factory: Factory, api_key: str, case: str
) -> None:
    model, verdict, attempted, model_cause = CROSS_CHECK_CASES[case]
    pid = declined(factory)
    use(client, model)
    body = client.get(url(pid), headers=auth(api_key)).json()
    assert body["cross_check"] == verdict
    assert body["attempted_model"] == attempted
    assert body["model_cause"] == model_cause
    assert body["rules_cause"] == RIGHT
    assert isinstance(body["generation_ms"], int) and body["generation_ms"] >= 0
    assert body["inputs"]["status"] == "declined"
    assert body["inputs"]["amount"] == "12.50 USD"
    assert [e["seq"] for e in body["inputs"]["events"]] == [1, 2, 3, 4]


def test_rules_only_when_no_model_is_configured(client: TestClient, factory: Factory, api_key: str) -> None:
    pid = declined(factory)
    client.app.state.model_client = None  # type: ignore[attr-defined]
    body = client.get(url(pid), headers=auth(api_key)).json()
    assert body["cross_check"] == "rules_only"
    assert body["attempted_model"] is None
    assert body["generation_ms"] is None
    assert body["inputs"]["status"] == "declined"


def test_regenerate_returns_the_same_new_fields(client: TestClient, factory: Factory, api_key: str) -> None:
    pid = declined(factory)
    use(client, FakeModel(answer("Timed out.", [3], "authorize_timeout")))
    body = client.post(url(pid, "/regenerate"), headers=auth(api_key)).json()
    assert set(body) == FIELDS
    assert body["cross_check"] == "disagreed_rules_used"
    assert body["model_cause"] == "authorize_timeout"


@pytest.mark.parametrize("case", CROSS_CHECK_CASES)
def test_the_description_is_in_no_response_and_no_stored_input(
    client: TestClient, factory: Factory, engine: Engine, api_key: str, case: str
) -> None:
    pid = declined(factory)
    use(client, CROSS_CHECK_CASES[case][0])
    first = client.get(url(pid), headers=auth(api_key))
    second = client.post(url(pid, "/regenerate"), headers=auth(api_key))
    with engine.connect() as connection:
        stored = connection.execute(text("SELECT inputs::text FROM payment_explanations")).scalars().all()
    assert len(stored) == 2
    for blob in (first.text, second.text, *stored):
        assert SENTINEL not in blob


@pytest.mark.parametrize(
    ("columns", "verdict"),
    [
        ("source = 'model', model = 'granite3.3:2b'", "agreed"),
        ("fallback_reason = 'cause_mismatch'", "disagreed_rules_used"),
        ("fallback_reason = 'model_timeout'", "model_unavailable"),
        ("fallback_reason = 'model_error'", "model_unavailable"),
        ("fallback_reason = 'citation_check_failed'", "model_unavailable"),
        ("fallback_reason = 'model_unreachable'", None),
    ],
)
def test_a_row_stored_before_the_details_existed_reads_as_unknown(
    client: TestClient, factory: Factory, engine: Engine, api_key: str, columns: str, verdict: str | None
) -> None:
    pid = declined(factory)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO payment_explanations (payment_id, source, model, text, cited_event_seqs, trigger,"
                " final_event_at, generated_at)"
                " VALUES (:p, 'rules', NULL, 'old', ARRAY[3], 'final_failure', now(), now())"
            ),
            {"p": pid},
        )
        connection.execute(
            text("UPDATE payment_explanations SET " + columns + " WHERE payment_id = :p"),  # noqa: S608
            {"p": pid},
        )
    body = client.get(url(pid), headers=auth(api_key)).json()
    assert body["cross_check"] == verdict
    assert (body["attempted_model"], body["model_cause"], body["rules_cause"]) == (None, None, None)
    assert (body["generation_ms"], body["inputs"]) == (None, None)
