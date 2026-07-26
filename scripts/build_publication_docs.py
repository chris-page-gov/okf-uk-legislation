#!/usr/bin/env python3
"""Synchronize authored publication documentation into the Pages bundle."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs"
OUTPUT = ROOT / "bundle" / "docs"
EVALUATION_SOURCE = ROOT / "evaluation" / "legislation"
EVALUATION_OUTPUT = ROOT / "bundle" / "evaluation"
EFFECTS_EVIDENCE_SOURCE = (
    ROOT / "evidence" / "source-acquisitions" / "legislation-effects"
)
EFFECTS_EVIDENCE_OUTPUT = (
    ROOT / "bundle" / "evidence" / "source-acquisitions" / "legislation-effects"
)


def files() -> dict[Path, bytes]:
    result = {
        path.relative_to(SOURCE): path.read_bytes()
        for path in SOURCE.rglob("*")
        if path.is_file()
    }
    result[Path("index.html")] = b"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>UK Legislation and Whole-Law OKF documentation</title>
<main><h1>UK Legislation and Whole-Law OKF documentation</h1><ul>
<li><a href="index.md">Documentation index</a></li>
<li><a href="getting-started.md">Getting started</a></li>
<li><a href="relationships.md">Relationships</a></li>
<li><a href="effects-and-enrichment.md">Effects and enrichment</a></li>
<li><a href="source-coverage.md">Source coverage</a></li>
<li><a href="maintenance.md">Maintenance</a></li>
<li><a href="../whole-law/docs/">Whole-Law guide</a></li>
<li><a href="../evaluation/">Legislation evaluation</a></li>
</ul></main></html>
"""
    return result


def evaluation_files() -> dict[Path, bytes]:
    result = {
        path.relative_to(EVALUATION_SOURCE): path.read_bytes()
        for path in EVALUATION_SOURCE.rglob("*")
        if path.is_file()
    }
    result[Path("index.html")] = b"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>UK legislation evaluation</title>
<main><h1>UK legislation evaluation</h1><ul>
<li><a href="README.md">Evaluation guide</a></li>
<li><a href="questions.json">100-question baseline</a></li>
<li><a href="answer-schema.json">Answer schema</a></li>
</ul></main></html>
"""
    return result


def effects_evidence_files() -> dict[Path, bytes]:
    """Publish safe evidence metadata while keeping raw archives off Pages."""

    result = {Path("README.md"): (EFFECTS_EVIDENCE_SOURCE / "README.md").read_bytes()}
    for directory in ("archive-receipts", "publication-projections"):
        for path in (EFFECTS_EVIDENCE_SOURCE / directory).glob("*.json"):
            result[path.relative_to(EFFECTS_EVIDENCE_SOURCE)] = path.read_bytes()
    result[Path("index.html")] = b"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Official effects acquisition evidence</title>
<main><h1>Official effects acquisition evidence</h1><ul>
<li><a href="README.md">Recovery and validation guide</a></li>
<li><a href="archive-receipts/legislation-effects-2026-07-25.json">Immutable archive receipt</a></li>
<li><a href="publication-projections/legislation-effects-2026-07-25.json">Safe publication projection</a></li>
</ul><p>The untrusted source archive is distributed only as an integrity-bound release asset, not served loose by Pages.</p>
</main></html>
"""
    return result


def differences(expected: dict[Path, bytes], output: Path) -> list[str]:
    actual = {
        path.relative_to(output)
        for path in output.rglob("*")
        if path.is_file()
    } if output.is_dir() else set()
    errors = []
    for path in sorted(set(expected) | actual):
        if path not in expected:
            errors.append(f"unexpected: {output.relative_to(ROOT) / path}")
        elif path not in actual:
            errors.append(f"missing: {output.relative_to(ROOT) / path}")
        elif (output / path).read_bytes() != expected[path]:
            errors.append(f"out of date: {output.relative_to(ROOT) / path}")
    return errors


def write(expected: dict[Path, bytes], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    unexpected = {
        path.relative_to(output)
        for path in output.rglob("*")
        if path.is_file()
    } - set(expected)
    if unexpected:
        raise SystemExit(
            "Refusing to delete unexpected publication documentation: "
            + ", ".join(str(path) for path in sorted(unexpected))
        )
    for relative, body in expected.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    groups = [
        (files(), OUTPUT),
        (evaluation_files(), EVALUATION_OUTPUT),
        (effects_evidence_files(), EFFECTS_EVIDENCE_OUTPUT),
    ]
    if args.check:
        errors = [
            error
            for expected, output in groups
            for error in differences(expected, output)
        ]
        if errors:
            print("Publication documentation is not synchronized:")
            for error in errors:
                print(f"- {error}")
            return 1
        print("Publication documentation synchronized")
        return 0
    for expected, output in groups:
        write(expected, output)
    print("Built publication documentation and evaluation routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
