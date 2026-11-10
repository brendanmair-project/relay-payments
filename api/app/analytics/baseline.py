"""The REL-30 static-routing baseline, read from the results file named by `BASELINE_RESULTS_PATH` (REL-37).

A missing, unreadable or malformed file is never an error: the answer is `{"available": false}` (a malformed file is
also logged as a warning), so the analytics page can say the baseline is unavailable instead of failing.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("relay.analytics")

LABEL = "synthetic data, static-routing baseline"
UNAVAILABLE: dict[str, Any] = {"available": False}


def _headline(data: dict[str, Any], path: Path) -> dict[str, Any]:
    run = data["runs"][0]  # the headline of results.md is run 1; the runs agree within the tolerance
    generated = data.get("generated_at")
    # Only a date recorded in the file is a run date; a file timestamp is just the checkout time.
    run_date = generated if isinstance(generated, str) else None
    return {
        "available": True,
        "label": LABEL,
        "synthetic": bool(data["synthetic"]),
        "scenario": str(data["scenario"]),
        "seed": int(data["seed"]),
        "run": int(run["run"]),
        "run_date": run_date,
        "baseline_description": str(data["baseline_description"]),
        "success_rate_static_pct": float(run["baseline_success_rate_pct"]),
        "success_rate_relay_pct": float(run["relay_success_rate_pct"]),
        "uplift_pp": float(run["uplift_pp"]),
        "revenue_recovered": dict(run["revenue_recovered"]),
        "revenue_by_rescue_path": dict(run["revenue_by_rescue_path"]),
    }


def read_baseline(path: str) -> dict[str, Any]:
    file = Path(path)
    try:
        raw = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return dict(UNAVAILABLE)
    except OSError:
        logger.warning("baseline results file %s could not be read", path)
        return dict(UNAVAILABLE)
    try:
        return _headline(json.loads(raw), file)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        logger.warning("baseline results file %s is malformed", path)
        return dict(UNAVAILABLE)
