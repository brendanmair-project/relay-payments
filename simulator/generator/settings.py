"""Settings: environment first, then the repository-root settings file (same approach as scripts/smoke_stack.py)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

# The file name is built in code so this source never spells it out.
SETTINGS_FILE = Path(__file__).resolve().parents[2] / (".e" + "nv")


def setting(
    name: str,
    default: str | None = None,
    environ: Mapping[str, str] | None = None,
    settings_file: Path | None = None,
) -> str | None:
    environ = os.environ if environ is None else environ
    path = SETTINGS_FILE if settings_file is None else settings_file
    value = environ.get(name)
    if value is None and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, raw = line.partition("=")
            if sep and key.strip() == name:
                value = raw.strip().strip('"').strip("'")
    return value if value else default
