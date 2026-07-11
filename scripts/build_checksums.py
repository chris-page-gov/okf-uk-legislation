#!/usr/bin/env python3
"""Build or verify deterministic SHA-256 checksums for the published bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"
OUTPUT = BUNDLE / "checksums.json"


def build() -> str:
    rows = {}
    for path in sorted(BUNDLE.rglob("*")):
        if path.is_file() and path != OUTPUT:
            rows[path.relative_to(BUNDLE).as_posix()] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
    return json.dumps({"schema": "okf-checksums.v1", "files": rows}, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = build()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            print("bundle/checksums.json is missing or out of date")
            return 1
        print(f"checksums verified for {len(json.loads(expected)['files']):,} files")
        return 0
    OUTPUT.write_text(expected, encoding="utf-8")
    print(f"wrote checksums for {len(json.loads(expected)['files']):,} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
