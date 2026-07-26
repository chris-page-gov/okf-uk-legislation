#!/usr/bin/env python3
"""Validate the authored Phase 1 requirement, traceability and status evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evidence" / "requirements" / "controlling-requirements.md"
SOURCE_DIGEST = SOURCE.with_suffix(".sha256")
TRACE = ROOT / "release-assurance" / "implementation-traceability.json"
GAPS = ROOT / "release-assurance" / "gap-register.json"
STATUS = ROOT / "release-assurance" / "implementation-status.md"

VALID_STATUSES = {
    "proposed",
    "started",
    "implemented",
    "verified",
    "blocked",
    "superseded",
    "deferred",
}
VALID_GAP_STATUSES = {"open", "blocked", "deferred", "resolved"}
CLAUSE_PATTERN = re.compile(
    r"^## (?P<id>[A-Z0-9-]+)\n"
    r"Source: (?P<source>.+)\n"
    r"Verbatim: (?P<verbatim>yes|no)\n\n"
    r"> (?P<text>.+)$",
    re.MULTILINE,
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def is_external(reference: str) -> bool:
    return reference.startswith(("repo:", "http://", "https://"))


def parse_clauses() -> tuple[dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    text = SOURCE.read_text(encoding="utf-8")
    clauses: dict[str, dict[str, Any]] = {}
    for match in CLAUSE_PATTERN.finditer(text):
        clause = match.groupdict()
        identifier = clause["id"]
        if identifier in clauses:
            errors.append(f"duplicate source clause id: {identifier}")
            continue
        clauses[identifier] = {
            "id": identifier,
            "sha256": sha256_bytes(clause["text"].encode("utf-8")),
            "source": clause["source"],
            "text": clause["text"],
            "verbatim": clause["verbatim"] == "yes",
        }
    expected_phase = {
        f"P{phase:02d}-{item:02d}"
        for phase, count in {
            1: 4,
            2: 4,
            3: 4,
            4: 4,
            5: 6,
            6: 5,
            7: 6,
            8: 7,
            9: 5,
            10: 5,
        }.items()
        for item in range(1, count + 1)
    }
    expected_decisions = {f"D-{item:02d}" for item in range(1, 13)}
    expected = expected_phase | expected_decisions
    if set(clauses) != expected:
        errors.append(
            "source clause ids differ: "
            f"missing={sorted(expected - set(clauses))}; "
            f"unexpected={sorted(set(clauses) - expected)}"
        )
    non_verbatim = sorted(
        identifier
        for identifier, clause in clauses.items()
        if not clause["verbatim"]
    )
    if non_verbatim != ["D-09"]:
        errors.append(
            "only the handoff-recorded security-order decision may be "
            f"non-verbatim, found {non_verbatim}"
        )
    return clauses, errors


def validate_source_digest() -> list[str]:
    errors: list[str] = []
    parts = SOURCE_DIGEST.read_text(encoding="utf-8").strip().split()
    if len(parts) != 2:
        return ["controlling-requirements.sha256 is not a two-column record"]
    expected, filename = parts
    if filename != SOURCE.name:
        errors.append(f"source digest names {filename!r}, expected {SOURCE.name!r}")
    actual = sha256_bytes(SOURCE.read_bytes())
    if expected != actual:
        errors.append(
            f"controlling requirement source digest changed: {expected} != {actual}"
        )
    return errors


def validate_references(
    identifier: str, field: str, references: Any
) -> list[str]:
    errors: list[str] = []
    if not isinstance(references, list):
        return [f"{identifier}: {field} must be a list"]
    for reference in references:
        if not isinstance(reference, str) or not reference:
            errors.append(f"{identifier}: invalid {field} reference {reference!r}")
        elif not is_external(reference) and not (ROOT / reference).exists():
            errors.append(f"{identifier}: missing {field} path: {reference}")
    return errors


def validate_traceability(
    clauses: dict[str, dict[str, Any]],
) -> tuple[Counter[str], list[str]]:
    errors: list[str] = []
    trace = load(TRACE)
    if trace.get("schema") != "okf-implementation-traceability.v2":
        errors.append("traceability schema must be v2")
    manifest = trace.get("source_manifest", {})
    actual_source_digest = sha256_bytes(SOURCE.read_bytes())
    if manifest.get("document_sha256") != actual_source_digest:
        errors.append("traceability source manifest does not bind source document")
    if manifest.get("requirements") != len(clauses):
        errors.append("traceability source manifest has the wrong clause count")
    rows = trace.get("requirements", [])
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = row.get("id")
        if not isinstance(identifier, str) or identifier in by_id:
            errors.append(f"missing or duplicate traceability id: {identifier!r}")
            continue
        by_id[identifier] = row
    if set(by_id) != set(clauses):
        errors.append(
            "traceability coverage differs: "
            f"missing={sorted(set(clauses) - set(by_id))}; "
            f"unexpected={sorted(set(by_id) - set(clauses))}"
        )
    for identifier, clause in clauses.items():
        row = by_id.get(identifier)
        if row is None:
            continue
        source = row.get("source_clause", {})
        for field in ("id", "sha256", "source", "verbatim"):
            if source.get(field) != clause[field]:
                errors.append(f"{identifier}: source_clause.{field} is not bound")
        if source.get("path") != SOURCE.relative_to(ROOT).as_posix():
            errors.append(f"{identifier}: source path is not canonical")
        if row.get("requirement") != clause["text"]:
            errors.append(f"{identifier}: requirement is not verbatim source text")
        status = row.get("status")
        disposition = row.get("release_disposition", {})
        if status not in VALID_STATUSES:
            errors.append(f"{identifier}: invalid status {status!r}")
        if disposition.get("status") != status:
            errors.append(f"{identifier}: disposition/status mismatch")
        if not disposition.get("reason"):
            errors.append(f"{identifier}: release disposition needs a reason")
        phase = row.get("phase")
        expected_phase = int(identifier[1:3]) if identifier.startswith("P") else 0
        if phase != expected_phase:
            errors.append(
                f"{identifier}: phase is {phase!r}, expected {expected_phase}"
            )
        for field in (
            "design_evidence",
            "implementation_evidence",
            "validation_evidence",
        ):
            errors.extend(validate_references(identifier, field, row.get(field)))
        if not row.get("design_evidence"):
            errors.append(f"{identifier}: design evidence is empty")
        if status in {"implemented", "verified"} and not row.get(
            "implementation_evidence"
        ):
            errors.append(f"{identifier}: {status} implementation evidence is empty")
        if status == "verified":
            validation = row.get("validation_evidence", [])
            if not validation:
                errors.append(f"{identifier}: verified validation evidence is empty")
            if all(
                reference.endswith(("gap-register.json", "release-gates.json"))
                for reference in validation
            ):
                errors.append(
                    f"{identifier}: verified status relies only on status ledgers"
                )
        if status == "blocked" and "release-assurance/gap-register.json" not in row.get(
            "validation_evidence", []
        ):
            errors.append(f"{identifier}: blocked status is not linked to gap register")
    return Counter(row.get("status") for row in rows), errors


def validate_gap_register() -> list[str]:
    errors: list[str] = []
    document = load(GAPS)
    rows = document.get("gaps", [])
    identifiers = [row.get("id") for row in rows]
    if len(identifiers) != len(set(identifiers)):
        errors.append("gap register ids are not unique")
    counts = Counter(row.get("status") for row in rows)
    if set(counts) - VALID_GAP_STATUSES:
        errors.append(f"invalid gap statuses: {sorted(set(counts) - VALID_GAP_STATUSES)}")
    expected_counts = dict(sorted(counts.items()))
    expected_counts["total"] = len(rows)
    if document.get("counts") != expected_counts:
        errors.append(
            f"gap counts differ: recorded={document.get('counts')}; "
            f"actual={expected_counts}"
        )
    for row in rows:
        identifier = str(row.get("id"))
        if not row.get("summary") or not row.get("next_action"):
            errors.append(f"{identifier}: summary and next_action are required")
        errors.extend(validate_references(identifier, "evidence", row.get("evidence")))
    source = document.get("source_research_gap_register", {})
    path = ROOT / str(source.get("path", ""))
    if not path.is_file():
        errors.append("immutable research gap register reference is missing")
    else:
        research = load(path)
        if source.get("records") != len(research.get("records", [])):
            errors.append("research gap count does not match immutable source")
    return errors


def validate_status_markdown(counts: Counter[str]) -> list[str]:
    text = STATUS.read_text(encoding="utf-8")
    normalized_text = " ".join(text.split())
    errors: list[str] = []
    labels = {
        "verified": "Verified",
        "implemented": "Implemented",
        "started": "Started",
        "blocked": "Blocked",
        "deferred": "Deferred",
        "proposed": "Proposed",
        "superseded": "Superseded",
    }
    for status, label in labels.items():
        expected = f"| {label} | {counts[status]} |"
        if expected not in text:
            errors.append(f"status report is missing exact row: {expected}")
    total = sum(counts.values())
    if f"| **Total** | **{total}** |" not in text:
        errors.append("status report total is not synchronized")
    required_truthful_phrases = [
        "not a frozen release candidate",
        "Release claim: **none**",
        "No qualified legal-practitioner",
        "The security scan is intentionally ordered after",
    ]
    for phrase in required_truthful_phrases:
        if phrase not in normalized_text:
            errors.append(f"status report omits truthful limitation: {phrase!r}")
    return errors


def validate() -> list[str]:
    missing = [
        path.relative_to(ROOT).as_posix()
        for path in (SOURCE, SOURCE_DIGEST, TRACE, GAPS, STATUS)
        if not path.is_file()
    ]
    if missing:
        return [f"required Phase 1 artefact is missing: {path}" for path in missing]
    clauses, errors = parse_clauses()
    errors.extend(validate_source_digest())
    counts, trace_errors = validate_traceability(clauses)
    errors.extend(trace_errors)
    errors.extend(validate_gap_register())
    errors.extend(validate_status_markdown(counts))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="retained for consistency; validation is always non-mutating",
    )
    parser.parse_args()
    errors = validate()
    if errors:
        print("Phase 1 requirements evidence failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    trace = load(TRACE)
    counts = Counter(row["status"] for row in trace["requirements"])
    summary = ", ".join(
        f"{status}={counts[status]}"
        for status in (
            "verified",
            "implemented",
            "started",
            "blocked",
            "deferred",
        )
    )
    print(
        f"Phase 1 requirements evidence verified: "
        f"{len(trace['requirements'])} clauses; {summary}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
