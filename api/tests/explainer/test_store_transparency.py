"""REL-63: each stored explanation keeps the attempted model, both causes, the time taken and the inputs."""

import json
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.explain.store import explain_payment, latest_explanation
from tests.explain.fakes import FakeModel, answer
from tests.explainer.helpers import SENTINEL, declined

Factory = sessionmaker[Session]
RIGHT = "decline_insufficient_funds"


def whole_row(factory: Factory, pid: uuid.UUID) -> dict[str, object]:
    with factory() as session:
        row = session.execute(
            sa.text("SELECT row_to_json(e) FROM payment_explanations e WHERE payment_id = :p"), {"p": pid}
        ).scalar_one()
    assert isinstance(row, dict)
    return row


CASES = {
    "agreed": (FakeModel(answer("Declined for funds.", [3, 4], RIGHT)), "model", RIGHT, None),
    "disagreed": (FakeModel(answer("Timed out.", [3, 4], "authorize_timeout")), "rules", "authorize_timeout", None),
    "timeout": (FakeModel(unavailable="model_timeout"), "rules", None, "model_timeout"),
    "absent": (None, "rules", None, "model_unreachable"),
}


@pytest.mark.parametrize("case", CASES)
def test_each_path_stores_the_right_fields(factory: Factory, case: str) -> None:
    model, source, model_cause, reason = CASES[case]
    pid = declined(factory)
    explain_payment(factory, pid, "final_failure", model)
    row = whole_row(factory, pid)
    assert row["source"] == source
    assert row["model_cause"] == model_cause
    assert row["rules_cause"] == RIGHT
    assert row["inputs"]["status"] == "declined"  # type: ignore[index]
    assert row["inputs"]["reason_codes"] == ["initial", "insufficient_funds"]  # type: ignore[index]
    if reason:
        assert row["fallback_reason"] == reason
    if model is None:
        assert row["attempted_model"] is None
        assert row["generation_ms"] is None
    else:
        assert row["attempted_model"] == "granite3.3:2b"
        assert isinstance(row["generation_ms"], int) and row["generation_ms"] >= 0


def test_disagreement_is_stored_as_rules_text_with_cause_mismatch(factory: Factory) -> None:
    pid = declined(factory)
    explain_payment(factory, pid, "on_request", CASES["disagreed"][0])
    row = whole_row(factory, pid)
    assert (row["source"], row["model"], row["fallback_reason"]) == ("rules", None, "cause_mismatch")
    with factory() as session:
        stored = latest_explanation(session, pid)
    assert stored is not None
    assert stored.attempted_model == "granite3.3:2b"
    assert (stored.model_cause, stored.rules_cause) == ("authorize_timeout", RIGHT)


@pytest.mark.parametrize("case", CASES)
def test_the_description_never_reaches_the_stored_row(factory: Factory, case: str) -> None:
    pid = declined(factory)
    explain_payment(factory, pid, "final_failure", CASES[case][0])
    assert SENTINEL not in json.dumps(whole_row(factory, pid))
