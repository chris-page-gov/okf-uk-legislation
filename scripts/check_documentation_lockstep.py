#!/usr/bin/env python3
"""Require publication documentation and changelog changes in lockstep."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _git_lines(root: Path, arguments: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def changed_files(root: Path, base: str | None) -> set[str]:
    if base:
        return set(_git_lines(root, ["diff", "--name-only", base]))
    files = set(_git_lines(root, ["diff", "--name-only"]))
    files.update(_git_lines(root, ["diff", "--cached", "--name-only"]))
    files.update(_git_lines(root, ["ls-files", "--others", "--exclude-standard"]))
    return files


def path_matches(path: str, pattern: str) -> bool:
    path_parts = path.split("/")
    pattern_parts = pattern.split("/")

    def match(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        component = pattern_parts[pattern_index]
        if component == "**":
            return match(path_index, pattern_index + 1) or (
                path_index < len(path_parts)
                and match(path_index + 1, pattern_index)
            )
        return (
            path_index < len(path_parts)
            and fnmatch.fnmatchcase(path_parts[path_index], component)
            and match(path_index + 1, pattern_index + 1)
        )

    return match(0, 0)


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    return any(path_matches(path, pattern) for pattern in patterns)


def lockstep_errors(
    contract: Mapping[str, Any], changed: Iterable[str]
) -> tuple[list[str], list[str], list[str]]:
    files = set(changed)
    lockstep = contract["lockstep"]
    controlled = sorted(
        path for path in files if matches_any(path, lockstep["controlled_paths"])
    )
    if not controlled:
        return [], [], []
    documentation = sorted(
        path for path in files if matches_any(path, lockstep["documentation_paths"])
    )
    errors: list[str] = []
    if not documentation:
        errors.append(
            "controlled publication files changed without maintained documentation"
        )
    changelog = lockstep["changelog_path"]
    if changelog not in files:
        errors.append(f"controlled publication files changed without {changelog}")
    return errors, controlled, documentation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="git revision or range to compare with HEAD")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        contract = json.loads((root / "okf.publication.json").read_text(encoding="utf-8"))
        files = changed_files(root, args.base)
        errors, controlled, documentation = lockstep_errors(contract, files)
    except (
        OSError,
        json.JSONDecodeError,
        KeyError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"documentation lockstep could not be evaluated: {error}", file=sys.stderr)
        return 2

    if not controlled:
        print("documentation lockstep: no controlled publication files changed")
        return 0
    if errors:
        print("documentation lockstep failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        print("Controlled files:", file=sys.stderr)
        for path in controlled[:40]:
            print(f"- {path}", file=sys.stderr)
        return 1
    print(
        "documentation lockstep: "
        f"{len(controlled)} controlled file(s), "
        f"{len(documentation)} documentation file(s), changelog updated"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
