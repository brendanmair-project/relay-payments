"""Coverage gate (REL-13, ADR-0007): line coverage of the domain and idempotency modules must stay at or above
the minimum. A module that does not exist yet (before REL-14 and REL-17) is reported and skipped; the project-wide
threshold is set at the Phase 1 exit review (REL-32).

Run after `pytest --cov=app --cov-report=json:/tmp/coverage.json`.
"""

import json
import sys
from pathlib import Path

MINIMUM = 90.0
GATED = ("app/domain/", "app/idempotency/")


# /tmp is the only writable path for the non-root user inside the read-only image.
def main(report: str = "/tmp/coverage.json") -> int:  # noqa: S108
    files = json.loads(Path(report).read_text(encoding="utf-8"))["files"]
    failed = False
    for prefix in GATED:
        covered = total = 0
        for name, data in files.items():
            if name.replace("\\", "/").startswith(prefix):
                covered += data["summary"]["covered_lines"]
                total += data["summary"]["num_statements"]
        if total == 0:
            print(f"COVERAGE_GATE {prefix} not present yet, skipped")
            continue
        percent = 100.0 * covered / total
        ok = percent >= MINIMUM
        failed |= not ok
        print(f"COVERAGE_GATE {prefix} {percent:.1f}% (minimum {MINIMUM:.0f}%) {'PASS' if ok else 'FAIL'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
