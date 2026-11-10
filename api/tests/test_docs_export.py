"""REL-40: the committed API reference and openapi.json equal what the live spec generates, and the guides exist.

The repository files are read from the checkout. The api image holds only `api/`, so the tests skip there; CI and a
host run (or a run with the repo's `docs/` mounted at `/docs`) execute them.
"""

import json
from pathlib import Path

import pytest

from app.docs_export import OPENAPI_FILE, REFERENCE_FILE, generate
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
GUIDES = ROOT / "docs" / "guides"
RERUN = (
    "cd api && python -m app.docs_export  "
    "(or: docker compose run --rm --no-deps -v ./docs:/docs api python -m app.docs_export)"
)
GUIDE_FILES = ["README.md", "quickstart.md", "authentication-and-idempotency.md", "webhooks.md", "sdk.md"]


@pytest.fixture(autouse=True)
def docs_present() -> None:
    if not (ROOT / "docs").exists():
        pytest.skip("docs/ is not part of the api image")


@pytest.mark.parametrize("name", [OPENAPI_FILE, REFERENCE_FILE])
def test_the_committed_generated_file_matches_the_live_spec(name: str) -> None:
    path = GUIDES / name
    assert path.exists(), f"{path} is missing; generate it with: {RERUN}"
    committed = path.read_bytes().decode("utf-8")
    assert committed == generate(app.openapi())[name], f"docs/guides/{name} is out of date; regenerate with: {RERUN}"


def test_generation_is_deterministic_and_formatted() -> None:
    first, second = generate(app.openapi()), generate(app.openapi())
    assert first == second
    text = first[OPENAPI_FILE]
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert "\r" not in text and "\r" not in first[REFERENCE_FILE]
    assert text.startswith('{\n  "components"')  # keys sorted, 2-space indent
    assert json.loads(text) == json.loads(json.dumps(app.openapi()))


def test_the_reference_has_a_section_for_every_operation() -> None:
    reference = generate(app.openapi())[REFERENCE_FILE]
    spec = app.openapi()
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            assert f"`{method.upper()} {path}`" in reference
            assert operation["summary"] in reference
    assert "`GET /webhooks/deliveries/summary`" in reference
    assert "Idempotency-Key" in reference and "X-API-Key" in reference
    assert "USD" in reference and "payment.final" in reference  # enum values are listed
    assert "`idempotency_key_missing`" in reference  # the error codes each response can carry


@pytest.mark.parametrize("name", GUIDE_FILES)
def test_the_guides_exist_and_the_index_lists_them(name: str) -> None:
    assert (GUIDES / name).exists(), f"docs/guides/{name} is missing"
    index = (GUIDES / "README.md").read_text(encoding="utf-8")
    if name != "README.md":
        assert f"({name})" in index
    for generated in (OPENAPI_FILE, REFERENCE_FILE):
        assert f"({generated})" in index


def test_the_quickstart_ends_with_next_steps_and_leaves_the_clean_room_section() -> None:
    text = (GUIDES / "quickstart.md").read_text(encoding="utf-8")
    assert "## Clean-room run" in text
    assert "Idempotency-Key" in text and "docker compose up -d --wait" in text
    assert "api-reference.md" in text and "Next: webhooks" in text


def test_readme_links_the_quickstart_and_the_contract_names_the_summary_endpoint() -> None:
    readme = ROOT / "README.md"
    if readme.exists():
        assert "docs/guides/quickstart.md" in readme.read_text(encoding="utf-8")
    contract = (ROOT / "docs" / "architecture" / "api-contract.md").read_text(encoding="utf-8")
    assert "### `GET /webhooks/deliveries/summary`" in contract
    assert "Fixed in REL-40" in contract
