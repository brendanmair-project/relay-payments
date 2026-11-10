"""REL-58: a push to main that changes only documentation runs just the secret scan.

Pull requests and the schedule are unchanged.

`ci.yml` is read as text. The classification shell step of the `changes` job is also run for real, in a throwaway Git
repository, on file lists that are documentation only, mixed, and on events other than a push.
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

CI = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
DOCS_ONLY = "needs.changes.outputs.docs_only != 'true'"
JOBS = ("changes", "backend", "simulator", "sdk", "frontend", "secrets", "e2e", "audit", "semgrep")


@pytest.fixture
def text() -> str:
    if not CI.exists():
        pytest.skip(".github/ is not part of the api image")
    return CI.read_text(encoding="utf-8")


def job(text: str, name: str) -> str:
    match = re.search(rf"^  {name}:\n(.*?)(?=^  \S|\Z)", text, re.S | re.M)
    assert match, f"ci.yml has no {name} job"
    return match.group(1)


def condition(text: str, name: str) -> str:
    match = re.search(r"^    if: (.*)$", job(text, name), re.M)
    assert match, f"{name} has no if"
    return match.group(1)


def test_changes_exposes_docs_only(text: str) -> None:
    assert re.search(r"^      docs_only: \$\{\{ steps\.diff\.outputs\.docs_only \}\}$", text, re.M)


@pytest.mark.parametrize("name", ["backend", "simulator", "sdk", "frontend", "e2e", "audit", "semgrep"])
def test_every_job_but_the_secret_scan_skips_a_docs_only_push(text: str, name: str) -> None:
    assert DOCS_ONLY in condition(text, name)
    assert re.search(r"^    needs: changes$", job(text, name), re.M)


def test_the_secret_scan_runs_on_every_push_and_pull_request(text: str) -> None:
    body = job(text, "secrets")
    assert "docs_only" not in body
    assert "needs:" not in body
    assert condition(text, "secrets") == "github.event_name != 'schedule'"


def test_pull_requests_and_the_schedule_are_not_affected(text: str) -> None:
    audit = condition(text, "audit")
    assert audit.startswith("always() && ")  # still runs on the schedule and when `changes` itself fails
    assert "schedule" not in audit
    for name in ("backend", "simulator", "sdk", "frontend", "semgrep"):
        assert "github.event_name != 'schedule'" in condition(text, name), name
    assert "github.event_name == 'pull_request'" in condition(text, "e2e")


def test_no_job_loses_its_timeout_or_pinned_runner(text: str) -> None:
    for name in JOBS:
        body = job(text, name)
        assert re.search(r"^    timeout-minutes: \d+$", body, re.M), name
        assert re.search(r"^    runs-on: ubuntu-24\.04$", body, re.M), name
    for use in re.findall(r"^\s+- uses: (\S+)", text, re.M):
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", use), use


def classify(text: str, files: list[str], event: str) -> dict[str, str]:
    bash, git = shutil.which("bash"), shutil.which("git")
    if not (bash and git):
        pytest.skip("bash and git are needed to run the classification step")
    step = re.search(r"- id: diff\n.*?run: \|\n(.*?)(?=^  \S|\Z)", text, re.S | re.M)
    assert step
    script = "\n".join(line[10:] for line in step.group(1).splitlines())
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        def run(*args: str) -> str:
            result = subprocess.run(  # noqa: S603 - fixed git arguments in a temporary repository
                [git, "-c", "user.name=t", "-c", "user.email=t@example.test", *args],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()

        run("init", "-q")
        (root / "seed.txt").write_text("x", encoding="utf-8")
        run("add", "-A")
        run("commit", "-q", "-m", "base")
        base = run("rev-parse", "HEAD")
        for name in files:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("changed", encoding="utf-8")
        run("add", "-A")
        run("commit", "-q", "-m", "change")
        output = root / "github_output.txt"
        output.write_text("", encoding="utf-8")
        env = {**os.environ, "EVENT": event, "PR_BASE": base, "PUSH_BEFORE": base, "GITHUB_OUTPUT": str(output)}
        subprocess.run([bash, "-c", script], cwd=root, env=env, capture_output=True, check=True)  # noqa: S603
        pairs = (line.partition("=") for line in output.read_text(encoding="utf-8").splitlines())
        return {key: value for key, _, value in pairs}


@pytest.mark.parametrize(
    ("files", "event", "docs_only"),
    [
        (["docs/guides/sdk.md", "README.md", "api/README.md", "HANDOFF.md"], "push", "true"),
        (["docs/delivery/tasks/REL-58.md", "docs/guides/openapi.json"], "push", "true"),
        (["docs/guides/sdk.md", "api/app/main.py"], "push", "false"),
        (["README.md", ".github/workflows/ci.yml"], "push", "false"),
        (["docs/guides/sdk.md"], "pull_request", "false"),
        (["docs/guides/sdk.md"], "workflow_dispatch", "false"),
        (["docs/guides/sdk.md"], "schedule", "false"),
    ],
)
def test_the_classification_step_marks_only_documentation_pushes(
    text: str, files: list[str], event: str, docs_only: str
) -> None:
    assert classify(text, files, event)["docs_only"] == docs_only
