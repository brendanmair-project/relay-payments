"""The demo sink: records deliveries, verifies signatures given the secret, fails the next N requests on demand."""

import json
import time

from fastapi.testclient import TestClient

from app.webhooks.signing import sign
from app.webhooks.sink import create_app
from tests.webhooks.helpers import random_secret

BODY = json.dumps({"id": 5, "type": "payment.final"}, separators=(",", ":")).encode()


def post(client: TestClient, secret: str, body: bytes = BODY, event_id: str = "5") -> int:
    headers = {
        "Content-Type": "application/json",
        "Relay-Event-Id": event_id,
        "Relay-Signature": sign(secret, body),
    }
    return client.post("/hook", content=body, headers=headers).status_code


def test_the_sink_has_a_health_endpoint() -> None:
    assert TestClient(create_app()).get("/health").status_code == 200


def test_it_records_what_it_receives_and_marks_a_signature_unchecked_without_a_secret() -> None:
    client = TestClient(create_app())
    assert post(client, random_secret()) == 200
    items = client.get("/received").json()["items"]
    assert len(items) == 1
    assert items[0]["event_id"] == "5"
    assert items[0]["body"] == {"id": 5, "type": "payment.final"}
    assert items[0]["signature_valid"] is None
    assert items[0]["status"] == 200


def test_it_verifies_the_signature_with_the_secret_given_through_the_endpoint() -> None:
    client = TestClient(create_app())
    secret = random_secret()
    assert client.post("/config", json={"secret": secret}).status_code == 200
    post(client, secret)
    post(client, random_secret(), event_id="6")  # signed with another secret
    flags = [i["signature_valid"] for i in client.get("/received").json()["items"]]
    assert flags == [True, False]


def test_the_secret_can_come_from_the_environment_and_is_never_echoed() -> None:
    secret = random_secret()
    client = TestClient(create_app(secret=secret))
    post(client, secret)
    listing = client.get("/received")
    assert listing.json()["items"][0]["signature_valid"] is True
    assert secret not in listing.text
    assert listing.json()["secret_set"] is True


def test_it_fails_the_next_n_requests_then_recovers() -> None:
    client = TestClient(create_app())
    secret = random_secret()
    assert client.post("/config", json={"fail_next": 3}).status_code == 200
    assert [post(client, secret) for _ in range(5)] == [503, 503, 503, 200, 200]
    listing = client.get("/received").json()
    assert [i["status"] for i in listing["items"]] == [503, 503, 503, 200, 200]
    assert listing["fail_next"] == 0


def test_received_can_be_cleared_and_bad_config_is_422() -> None:
    client = TestClient(create_app())
    post(client, random_secret())
    assert client.delete("/received").status_code == 200
    assert client.get("/received").json()["items"] == []
    assert client.post("/config", json={"fail_next": -1}).status_code == 422


def test_a_non_ascii_signature_is_answered_with_401_not_500_and_recorded_as_invalid() -> None:
    secret = random_secret()
    client = TestClient(create_app(secret=secret), raise_server_exceptions=False)
    header = f"t={int(time.time())},v1={chr(0xE9)}".encode("latin-1")  # how the server reads a raw 0xE9 byte
    headers = {"Content-Type": "application/json", "Relay-Signature": header}
    response = client.post("/hook", content=BODY, headers=headers)
    assert response.status_code == 401
    item = client.get("/received").json()["items"][0]
    assert (item["signature_valid"], item["status"]) == (False, 401)


def test_a_wrong_signature_is_401_and_a_good_one_is_200() -> None:
    secret = random_secret()
    client = TestClient(create_app(secret=secret))
    assert post(client, random_secret()) == 401
    assert post(client, secret) == 200
