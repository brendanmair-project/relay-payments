"""REL-51: `python -m app.reporting` prints a table and writes the same numbers as JSON with a stable key order."""

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.reporting.__main__ import main
from tests.reporting.test_report_db import seed

TOP_LEVEL_KEYS = [
    "window",
    "payments",
    "latency",
    "publish_lag",
    "processor_success",
    "not_final",
    "rescue_paths",
    "explanations",
    "api_5xx",
]
ARGS = ["--as-of", "2100-01-01T00:00:00Z", "--request-log", "/nonexistent/api-requests.jsonl"]


def test_prints_a_table_and_writes_json(
    factory: sessionmaker[Session], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(factory)
    out = tmp_path / "report.json"
    assert main([*ARGS, "--reference-prefix", "scn-1-", "--json-out", str(out)]) == 0
    table = capsys.readouterr().out
    for heading in ("Processing latency", "Publish lag", "Processor success", "Revenue recovered", "Explanations"):
        assert heading in table
    assert "P95" in table
    assert "not available yet" in table
    data = json.loads(out.read_text(encoding="utf-8"))
    assert list(data) == TOP_LEVEL_KEYS
    assert data["window"] == {
        "since": None,
        "until": None,
        "reference_prefix": "scn-1-",
        "as_of": "2100-01-01T00:00:00Z",
    }
    assert data["payments"] == {"selected": 5, "final": 4}


def test_json_is_identical_for_the_same_data(
    factory: sessionmaker[Session], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(factory)
    first, second = tmp_path / "1.json", tmp_path / "2.json"
    assert main([*ARGS, "--json-out", str(first)]) == 0
    assert main([*ARGS, "--json-out", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()
    capsys.readouterr()


def test_since_and_until_are_parsed_as_iso_times(
    factory: sessionmaker[Session], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(factory)
    out = tmp_path / "report.json"
    assert main([*ARGS, "--since", "2100-01-01T00:00:00Z", "--json-out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["window"]["since"] == "2100-01-01T00:00:00Z"
    assert data["payments"] == {"selected": 0, "final": 0}
    capsys.readouterr()


def test_a_bad_time_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--since", "yesterday-ish"])
    assert raised.value.code == 2
    capsys.readouterr()
