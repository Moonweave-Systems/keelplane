#!/usr/bin/env python3
"""Check tracked source-style files for whitespace issues without requiring git."""

from __future__ import annotations

import sys
from pathlib import Path


SKIP_DIRS = {".git", "__pycache__", "out"}
TEXT_SUFFIXES = {
    ".json",
    ".md",
    ".py",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_NAMES = {"LICENSE", "SKILL.md", "README.md"}


def should_check(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    return path.suffix in TEXT_SUFFIXES or path.name in TEXT_NAMES


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    problems: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not should_check(path.relative_to(root)):
            continue
        text = path.read_text(errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            if line.rstrip(" \t") != line:
                problems.append(f"{path.relative_to(root)}:{number}: trailing whitespace")
        if text and not text.endswith("\n"):
            problems.append(f"{path.relative_to(root)}: missing final newline")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print("whitespace check: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
