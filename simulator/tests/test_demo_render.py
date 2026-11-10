"""REL-30.4: the results page defines its numbers, names the baselines and says the data is synthetic."""

from demo.compare import build_results
from demo.render import render_markdown
from tests.test_demo_compare import run


def page(runs: int = 3) -> str:
    return render_markdown(build_results(7, "processor-a-outage", [run() for _ in range(runs)]))


def test_page_states_synthetic_data_and_the_static_baseline() -> None:
    text = page()
    assert "All data is synthetic" in text
    assert "static routing" in text
    assert "ROUTING_STRATEGY=static" in text


def test_page_defines_the_metrics_next_to_the_results() -> None:
    text = page()
    for phrase in ("Median time to explanation", "Revenue recovered", "per currency", "minor units", "Success rate"):
        assert phrase in text


def test_page_compares_with_the_two_hour_manual_baseline_as_an_assumption() -> None:
    text = page()
    assert "2 hours" in text
    assert "assumption" in text.lower()


def test_page_prints_headline_numbers_rescue_split_and_reasons() -> None:
    text = page()
    assert "+20.0" in text  # uplift in percentage points
    assert "| EUR | 3000 |" in text and "| JPY | -700 |" in text
    assert "retry" in text and "failover" in text
    assert "cause_mismatch" in text
    assert "1500" in text  # median time to explanation in ms


def test_page_prints_the_tolerance_and_the_verdict() -> None:
    text = page()
    assert "1 percentage point" in text and "1%" in text
    assert "PASS" in text and "FAIL" not in text


def test_a_drifting_run_is_reported_as_fail_not_hidden() -> None:
    drifted = run()
    captured = {"status": "captured", "currency": "USD", "amount_minor": 500}
    drifted["relay"]["outcomes"] = {**drifted["relay"]["outcomes"], "r4": captured}
    text = render_markdown(build_results(7, "processor-a-outage", [run(), run(), drifted]))
    assert "FAIL" in text


def test_single_run_says_reproducibility_was_not_measured() -> None:
    assert "not measured" in page(1)


def test_page_has_a_method_section_that_names_the_drain() -> None:
    text = page()
    assert "## Method" in text
    assert "waits until every earlier payment is final" in text


def test_page_reports_recovery_lag_and_the_health_window_wait() -> None:
    text = page()
    assert "waits one health window" in text
    assert "Recovery lag (Relay)" in text and "12 s" in text
    never = run()
    never["relay"]["recovery_lags"] = [{"processor": "a", "lag_seconds": None, "waited_seconds": 65.0}]
    assert "not recovered within the wait" in render_markdown(build_results(7, "processor-a-outage", [never]))


def test_method_states_the_demo_health_window_and_why() -> None:
    text = render_markdown(build_results(7, "processor-a-outage", [run()], health_window_seconds=120))
    assert "health window of 120 s" in text
    assert "default configuration stays 60 s" in text
    assert "ages out" in text


def test_page_lists_differing_references_with_their_routing() -> None:
    first, second = run(), run()
    base = {"currency": "USD", "amount_minor": 500}
    first["relay"]["outcomes"] = {
        **first["relay"]["outcomes"],
        "r4": {"status": "declined", "processor": "A", "routing": ["A:initial"]} | base,
    }
    second["relay"]["outcomes"] = {
        **second["relay"]["outcomes"],
        "r4": {"status": "captured", "processor": "B", "routing": ["A:initial", "B:failover"]} | base,
    }
    text = render_markdown(build_results(7, "processor-a-outage", [first, second], health_window_seconds=120))
    assert "Differing references" in text
    assert "r4" in text and "A:initial > B:failover" in text and "declined" in text
    assert "No reference differs" in page()
