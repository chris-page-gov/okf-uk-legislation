#!/usr/bin/env python3
"""Bounded offline diagnostic preflight before expensive release validation.

This is not release authorisation, Security assurance or a substitute for the
exact-candidate gates. External inputs are retained evidence, never refreshed
or modified. The only output is a new diagnostic receipt outside the checkout.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

import capture_github_pages_observation as pages
import finalize_release_candidate as finalization
import reproduce_release_candidate as reproduction


ROOT = Path(__file__).resolve().parents[1]
ASSURANCE_ONLY = (
    "bundle/release-assurance/",
    "bundle/checksums.json",
    "bundle/docs/maintenance.md",
    "bundle/docs/maintenance.html",
)
TESTS = (
    "tests.test_release_toolchain_preflight",
    "tests.test_github_pages_observation",
    "tests.test_release_contract_schemas",
    "tests.test_pre_rc_assurance_receipts",
    "tests.test_release_finalization",
    "tests.test_release_reproduction",
    "tests.test_release_runbook_commands",
)


def verify_inventory_interoperability(explorer_root: Path, runtime: dict) -> dict:
    """Exercise the real producer-to-pinned-Explorer digest boundary offline.

    The runtime copy is explicitly synthetic diagnostic evidence. It proves
    that the native finaliser accepts the common inventory identity, not that
    any new candidate has passed browser acceptance.
    """
    contract = json.loads((ROOT / "release-assurance/external-finalization-contract.json").read_text())
    required = contract["explorer"]["required_commit"]
    explorer_root = explorer_root.resolve(strict=True)
    observed = subprocess.run(
        ["git", "-C", str(explorer_root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(explorer_root), "status", "--porcelain=v1", "--untracked-files=all"],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout
    if observed != required or dirty:
        raise RuntimeError("cross-language preflight requires the exact clean pinned Explorer checkout")
    declared = runtime["invocation"]["executable_materials"]["runtime_acceptance_contract"]
    helper = explorer_root / declared["path"]
    helper_material = material(helper)
    if any(helper_material[key] != declared[key] for key in ("bytes", "sha256")):
        raise RuntimeError("Explorer canonical-inventory helper differs from the retained pinned invocation")
    profile = json.loads((ROOT / "release-assurance/reproduction-profile.json").read_text())
    inventory = reproduction.inventory_publication(ROOT / "bundle", profile["archive"])
    # Invoke the actual published implementation; do not imitate its digest in
    # Python or accept a serializer-only fixture as interoperability evidence.
    command = """
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const { canonicalPublicationInventory } = await import(pathToFileURL(process.argv[1]).href);
const rows = JSON.parse(readFileSync(0, 'utf8'));
console.log(JSON.stringify(canonicalPublicationInventory(rows)));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", command, str(helper)],
        input=json.dumps(inventory["rows"], ensure_ascii=False),
        check=True, capture_output=True, text=True, timeout=60,
    )
    native = json.loads(result.stdout)
    expected = {
        "algorithm": "sha256-canonical-json-inventory-v1",
        "files": inventory["files"], "bytes": inventory["bytes"],
        "sha256": inventory["inventory_sha256"],
    }
    if native != expected:
        raise RuntimeError(f"producer/Explorer publication inventory mismatch: {expected!r} != {native!r}")
    synthetic = copy.deepcopy(runtime)
    synthetic["candidate"]["bundle_tree_sha256"] = native["sha256"]
    identity = synthetic["invocation"]["repository_identity"]["candidate"]
    identity["bundle_tree"] = native.copy()
    snapshot = synthetic["invocation"]["snapshots"]["bundle"]
    snapshot.update(native)
    snapshot["entries"] = len(list((ROOT / "bundle").rglob("*")))
    binding = synthetic["candidate"]
    finalization.reconstruct_explorer_runtime(
        synthetic, contract=contract, commit=binding["commit"], tree=binding["tree"],
        inventory=inventory["inventory_sha256"],
        explorer_commit=synthetic["explorer"]["commit"],
    )
    return {
        "id": "real-cross-language-publication-inventory", "status": "passed",
        "explorer_commit": observed, "native_helper": helper_material,
        "publication": native,
        "native_finaliser_inventory_binding": "passed-synthetic-diagnostic-only",
        "new_browser_acceptance_claimed": False,
    }


def git(*args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], check=True, capture_output=True,
        timeout=30,
    ).stdout


def material(path: Path) -> dict:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeError(f"not an independent regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "bytes": info.st_size, "sha256": digest.hexdigest()}


def verify_preservation(baseline: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", baseline):
        raise RuntimeError("baseline must be an exact full Git commit")
    changed = git("diff", "--name-only", baseline, "--", "bundle/").decode().splitlines()
    unexpected = [p for p in changed if not any(p == a or (a.endswith("/") and p.startswith(a)) for a in ASSURANCE_ONLY)]
    untracked = git("ls-files", "--others", "--exclude-standard", "--", "bundle/").decode().splitlines()
    if unexpected or untracked:
        raise RuntimeError(f"non-assurance publication changes: {unexpected}; untracked: {untracked}")
    protected = []
    for entry in git("ls-tree", "-r", "-z", baseline, "--", "bundle/").split(b"\0"):
        if not entry:
            continue
        header, raw_path = entry.split(b"\t", 1)
        path = raw_path.decode()
        if any(path == a or (a.endswith("/") and path.startswith(a)) for a in ASSURANCE_ONLY):
            continue
        mode, kind, expected = header.decode().split()
        target = ROOT / path
        info = target.lstat()
        if mode != "100644" or kind != "blob" or not stat.S_ISREG(info.st_mode):
            raise RuntimeError(f"protected publication is not a regular blob: {path}")
        digest = hashlib.sha1(f"blob {info.st_size}\0".encode())
        with target.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise RuntimeError(f"protected publication bytes changed: {path}")
        protected.append({"path": path, "git_blob": expected, "bytes": info.st_size})
    return {
        "baseline": baseline, "protected_files": len(protected),
        "protected_bytes": sum(p["bytes"] for p in protected),
        "protected_inventory_sha256": hashlib.sha256(json.dumps(protected, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "allowed_assurance_changes": changed,
    }


def run(args: argparse.Namespace) -> dict:
    started = time.monotonic()
    checks = []
    compiled = []
    for path in sorted((ROOT / "release-assurance/schemas").glob("*.json")):
        Draft202012Validator.check_schema(json.loads(path.read_text()))
        compiled.append(material(path))
    checks.append({"id": "schema-compilation", "status": "passed", "schemas": len(compiled)})

    scan = pages.scan_pages_zip(args.pages_zip, pages.DEFAULT_PROFILE)
    checks.append({
        "id": "real-explorer-pages-fixture", "status": "passed",
        "files": scan.inventory["file_count"],
        "materials_sha256": scan.inventory["materials_sha256"],
        "zip": material(args.pages_zip),
    })

    runtime = json.loads(args.runtime.read_text())
    finalization.validate_schema(runtime, ROOT / "release-assurance/schemas/explorer-runtime-receipt.schema.json", "real Explorer runtime fixture")
    invocation = runtime.get("invocation")
    if not isinstance(invocation, dict) or invocation.get("release_eligible") is not True:
        raise RuntimeError("the real v0.8.1 fixture must retain release invocation evidence")
    binding = runtime["candidate"]
    finalization.reconstruct_explorer_runtime(
        runtime, contract=json.loads((ROOT / "release-assurance/external-finalization-contract.json").read_text()),
        commit=binding["commit"], tree=binding["tree"],
        inventory=binding["bundle_tree_sha256"], explorer_commit=runtime["explorer"]["commit"],
    )
    checks.append({"id": "real-runtime-schema-and-reconstruction", "status": "passed", "fixture_candidate": binding, "receipt": material(args.runtime)})

    checks.append(verify_inventory_interoperability(args.explorer_root, runtime))

    result = subprocess.run(
        [sys.executable, "-m", "unittest", *TESTS, "-q"], cwd=ROOT,
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode:
        raise RuntimeError(f"targeted controller/finaliser round trip failed:\n{result.stdout[-12000:]}\n{result.stderr[-12000:]}")
    checks.append({"id": "controller-to-finaliser-regressions", "status": "passed", "modules": TESTS, "output": result.stderr[-2000:]})
    preservation = verify_preservation(args.baseline)
    checks.append({"id": "protected-product-byte-preservation", "status": "passed", **preservation})
    return {
        "schema": "okf-release-toolchain-preflight.v1", "status": "passed",
        "evidence_class": "diagnostic-not-release-authorisation",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "checkout_commit": git("rev-parse", "HEAD").decode().strip(),
        "checkout_dirty": bool(git("status", "--porcelain")),
        "schemas": compiled, "checks": checks,
        "limitations": [
            "The retained real runtime fixture targets its original candidate, not this successor.",
            "Finalisation round trips use clearly synthetic test evidence; they do not authorise publication.",
            "Exact-candidate reproduction, runtime acceptance, Security and public RC/final checks remain required.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--pages-zip", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--explorer-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error("output must be outside the candidate checkout")
    if output.exists():
        parser.error("output already exists; use a fresh immutable attempt")
    for path in (args.pages_zip, args.runtime):
        material(path)
    document = run(args)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"status": document["status"], "seconds": document["duration_seconds"], "output": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
