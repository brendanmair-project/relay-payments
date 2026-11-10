"""REL-37: the baseline endpoint reads the REL-30 results file named by a setting (present, absent, malformed)."""

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.analytics.baseline import LABEL, read_baseline
from app.config import get_settings

REAL = Path(__file__).resolve().parents[3] / "docs" / "evaluation" / "outage-demo" / "results.json"


def results(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "synthetic": True,
        "scenario": "processor-a-outage",
        "seed": 7,
        "baseline_description": "static routing: every payment to Processor A",
        "runs": [
            {
                "run": 1,
                "baseline_success_rate_pct": 58.0,
                "relay_success_rate_pct": 89.0,
                "uplift_pp": 31.0,
                "revenue_recovered": {"EUR": 300, "USD": 700},
                "revenue_by_rescue_path": {"retry": {"USD": 700}, "failover": {"EUR": 300}, "redrive": {}},
            }
        ],
    }
    data.update(changes)
    return data


@pytest.fixture
def point_at(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Callable[[Path], None]:
    def apply(path: Path) -> None:
        monkeypatch.setattr(get_settings(), "baseline_results_path", str(path))

    return apply


def test_a_present_file_gives_the_headline_figures(tmp_path: Path) -> None:
    file = tmp_path / "results.json"
    file.write_text(json.dumps(results()), encoding="utf-8")
    body = read_baseline(str(file))
    assert body["available"] is True
    assert body["label"] == LABEL == "synthetic data, static-routing baseline"
    assert (body["success_rate_static_pct"], body["success_rate_relay_pct"], body["uplift_pp"]) == (58.0, 89.0, 31.0)
    assert body["revenue_recovered"] == {"EUR": 300, "USD": 700}
    assert body["revenue_by_rescue_path"]["retry"] == {"USD": 700}
    assert (body["seed"], body["scenario"], body["run"]) == (7, "processor-a-outage", 1)
    assert body["run_date"] is None  # the fixture has no generated_at, and a file timestamp is not a run date


def test_the_endpoint_reads_the_path_from_the_setting(
    client: TestClient, point_at: Callable[[Path], None], tmp_path: Path, api_key: str
) -> None:
    file = tmp_path / "results.json"
    file.write_text(json.dumps(results(seed=99)), encoding="utf-8")
    point_at(file)
    response = client.get("/analytics/baseline", headers={"X-API-Key": api_key})
    assert response.status_code == 200
    assert response.json()["seed"] == 99


def test_an_absent_file_answers_200_unavailable(
    client: TestClient, point_at: Callable[[Path], None], tmp_path: Path, api_key: str
) -> None:
    point_at(tmp_path / "missing.json")
    response = client.get("/analytics/baseline", headers={"X-API-Key": api_key})
    assert response.status_code == 200
    assert response.json() == {"available": False}


@pytest.mark.parametrize("text", ["{not json", "[]", json.dumps({"runs": []}), json.dumps(results(runs=[{"run": 1}]))])
def test_a_malformed_file_answers_unavailable_and_logs_a_warning(
    client: TestClient,
    point_at: Callable[[Path], None],
    tmp_path: Path,
    api_key: str,
    caplog: pytest.LogCaptureFixture,
    text: str,
) -> None:
    file = tmp_path / "results.json"
    file.write_text(text, encoding="utf-8")
    point_at(file)
    with caplog.at_level(logging.WARNING, logger="relay.analytics"):
        response = client.get("/analytics/baseline", headers={"X-API-Key": api_key})
    assert response.status_code == 200
    assert response.json() == {"available": False}
    assert any("malformed" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)


def test_the_committed_rel30_file_gives_its_headline() -> None:
    if not REAL.exists():
        pytest.skip("the REL-30 results file is not part of the api image")
    body = read_baseline(str(REAL))
    assert body["available"] is True
    assert (body["success_rate_static_pct"], body["success_rate_relay_pct"], body["uplift_pp"]) == (58.0, 89.0, 31.0)
    assert body["seed"] == 7
    assert body["revenue_recovered"]["USD"] == 6810094
