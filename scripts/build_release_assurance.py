#!/usr/bin/env python3
"""Build or check deterministic, fail-closed release-assurance projections.

The authored release policy, gates and implementation traceability are kept in
``release-assurance/``. This builder verifies their evidence references and
projects them with immutable research evidence, rights, SBOM, provenance,
reproduction, constraint and model-cost reports into
``bundle/release-assurance/``. It never changes the research originals.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "release-assurance"
OUTPUT = ROOT / "bundle" / "release-assurance"
RESEARCH = ROOT / "research" / "whole-law-okf-research"
CLAUDE = ROOT / "research" / "Legislation-govuk Claude 4.8 run.docx"
CLAUDE_TRANSCRIPT = ROOT / "research" / "claude-4.8-evaluation-transcript.md"
POLICY = SOURCE / "release-policy.json"
GATES = SOURCE / "release-gates.json"
TRACEABILITY = SOURCE / "implementation-traceability.json"
TRACEABILITY_SOURCE = (
    ROOT / "evidence" / "requirements" / "controlling-requirements.md"
)
TRACEABILITY_SOURCE_DIGEST = TRACEABILITY_SOURCE.with_suffix(".sha256")
GAP_REGISTER = SOURCE / "gap-register.json"
AUTHORED_STATUS = SOURCE / "implementation-status.md"
VALID_STATUSES = {
    "proposed",
    "started",
    "implemented",
    "verified",
    "blocked",
    "superseded",
    "deferred",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def render(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def material(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": digest(path),
    }


def evidence_manifest(generated_at: str) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    integrity_path = RESEARCH / "integrity.json"
    integrity = load(integrity_path)
    records = integrity.get("files", [])
    rows: list[dict[str, Any]] = []
    if len(records) != 23:
        errors.append(
            f"research integrity must contain 23 artefacts, found {len(records)}"
        )
    rows.append(
        {
            "bytes": integrity_path.stat().st_size,
            "kind": "research-integrity-manifest",
            "path": integrity_path.relative_to(ROOT).as_posix(),
            "sha256": digest(integrity_path),
            "verified": True,
        }
    )
    for record in records:
        relative = record.get("path")
        expected = record.get("sha256")
        if not relative or not expected:
            errors.append(f"invalid research integrity row: {record!r}")
            continue
        path = RESEARCH / relative
        if not path.is_file():
            errors.append(f"research evidence is missing: {relative}")
            continue
        actual = digest(path)
        if actual != expected:
            errors.append(f"immutable research evidence changed: {relative}")
        rows.append(
            {
                "bytes": path.stat().st_size,
                "kind": "research-artefact",
                "path": path.relative_to(ROOT).as_posix(),
                "recorded_sha256": expected,
                "sha256": actual,
                "verified": actual == expected,
            }
        )
    validations = integrity.get("validation", [])
    if len(validations) != 40 or any(not row.get("passed") for row in validations):
        errors.append("research integrity must retain 40 successful validations")
    if not CLAUDE.is_file():
        errors.append("Claude evaluation DOCX is missing")
    else:
        claude_sha256 = digest(CLAUDE)
        rows.append(
            {
                "bytes": CLAUDE.stat().st_size,
                "kind": "adversarial-access-evaluation",
                "path": CLAUDE.relative_to(ROOT).as_posix(),
                "sha256": claude_sha256,
                "verified": True,
            }
        )
        if not CLAUDE_TRANSCRIPT.is_file():
            errors.append("normalized Claude evaluation transcript is missing")
        else:
            transcript_text = CLAUDE_TRANSCRIPT.read_text(encoding="utf-8")
            source_bound = claude_sha256 in transcript_text
            if not source_bound:
                errors.append(
                    "Claude transcript does not state the immutable DOCX SHA-256"
                )
            rows.append(
                {
                    "bytes": CLAUDE_TRANSCRIPT.stat().st_size,
                    "derived_from": CLAUDE.relative_to(ROOT).as_posix(),
                    "derived_from_sha256": claude_sha256,
                    "kind": "normalized-derived-projection",
                    "path": CLAUDE_TRANSCRIPT.relative_to(ROOT).as_posix(),
                    "sha256": digest(CLAUDE_TRANSCRIPT),
                    "tool": "Pandoc",
                    "verified": source_bound,
                }
            )
    return (
        {
            "algorithm": "sha256",
            "controlling_research_integrity": material(integrity_path),
            "counts": {
                "claude_evaluations": 1 if CLAUDE.is_file() else 0,
                "derived_projections": 1 if CLAUDE_TRANSCRIPT.is_file() else 0,
                "evidence_items": len(rows),
                "research_artefacts": len(records) + 1,
                "research_content_artefacts": len(records),
                "research_integrity_manifests": 1,
                "research_validations_passed": sum(
                    bool(row.get("passed")) for row in validations
                ),
            },
            "generated_at": generated_at,
            "immutability_rule": (
                "The 24-file research package (23 content artefacts plus its "
                "integrity manifest) and Claude DOCX are read-only evidence. "
                "Corrections, transcripts and reviews must be separate artefacts."
            ),
            "items": rows,
            "schema": "okf-evidence-manifest.v1",
            "verified": not errors,
        },
        errors,
    )


def build_claude_access_test(generated_at: str) -> dict[str, Any]:
    """Project only the access observations recorded in the Claude transcript."""
    docx = material(CLAUDE)
    transcript = material(CLAUDE_TRANSCRIPT)
    return {
        "evidence": {
            "immutable_source": docx,
            "normalized_projection": transcript,
            "projection_binding_verified": docx["sha256"]
            in CLAUDE_TRANSCRIPT.read_text(encoding="utf-8"),
        },
        "generated_at": generated_at,
        "observed_on": "2026-07-25",
        "observations": [
            {
                "id": "CLAUDE-ACCESS-01",
                "observation": (
                    "The repository URL was available but was not selected on "
                    "the first access attempt."
                ),
                "outcome": "initial-discovery-miss",
            },
            {
                "id": "CLAUDE-ACCESS-02",
                "observation": (
                    "The unauthenticated shared-sandbox GitHub API quota was "
                    "reported exhausted."
                ),
                "outcome": "rate-limited",
            },
            {
                "id": "CLAUDE-ACCESS-03",
                "observation": (
                    "A guessed raw repository-root descriptor path returned 404 "
                    "because the declared publication subpath is bundle/."
                ),
                "outcome": "raw-root-path-mismatch",
            },
            {
                "id": "CLAUDE-ACCESS-04",
                "observation": (
                    "The codeload archive route remained available and exposed "
                    "the version-controlled bundle/ subtree."
                ),
                "outcome": "archive-fallback-succeeded",
            },
            {
                "id": "CLAUDE-ACCESS-05",
                "observation": (
                    "The transcript records successful execution of the then-"
                    "current structural and checksum validators."
                ),
                "outcome": "historical-validation-observation",
            },
            {
                "id": "CLAUDE-ACCESS-06",
                "observation": (
                    "YAML was observed as served with an octet-stream media type."
                ),
                "outcome": "declared-hosting-exception",
            },
        ],
        "scope_note": (
            "This record is a machine-readable projection of the immutable "
            "evaluation transcript, not a fresh live access test and not "
            "independent legal or security assurance."
        ),
        "schema": "okf-observed-access-test.v1",
        "tooling_constraint": {
            "constraint": (
                "GUI-backed LibreOffice rendering aborts under the Codex/macOS "
                "execution environment."
            ),
            "future_extraction": [
                "Pandoc",
                "python-docx",
            ],
            "release_effect": "recorded-non-blocking",
        },
    }


def implementation_status(
    generated_at: str,
) -> tuple[dict[str, Any], list[str]]:
    traceability = load(TRACEABILITY)
    errors: list[str] = []
    requirements = traceability.get("requirements", [])
    ids: set[str] = set()
    phase_counts: dict[int, Counter[str]] = defaultdict(Counter)
    for row in requirements:
        identifier = row.get("id")
        status = row.get("status")
        phase = row.get("phase")
        if not identifier or identifier in ids:
            errors.append(f"missing or duplicate traceability id: {identifier!r}")
        ids.add(identifier)
        if status not in VALID_STATUSES:
            errors.append(f"{identifier}: invalid status {status!r}")
        if not isinstance(phase, int) or not 0 <= phase <= 10:
            errors.append(f"{identifier}: invalid phase {phase!r}")
            continue
        phase_counts[phase][str(status)] += 1
        disposition = row.get("release_disposition", {})
        if disposition.get("status") != status or not disposition.get("reason"):
            errors.append(f"{identifier}: invalid release disposition")
        implementation_evidence = row.get("implementation_evidence", [])
        if status in {"implemented", "verified"} and not implementation_evidence:
            errors.append(f"{identifier}: {status} requires evidence")
        for field in (
            "design_evidence",
            "implementation_evidence",
            "validation_evidence",
        ):
            references = row.get(field, [])
            if not isinstance(references, list):
                errors.append(f"{identifier}: {field} must be a list")
                continue
            for reference in references:
                if reference.startswith(("repo:", "http://", "https://")):
                    continue
                path = ROOT / reference
                if not path.exists():
                    errors.append(
                        f"{identifier}: {field} path is missing: {reference}"
                    )
    implementation_phases = set(phase_counts) - {0}
    if implementation_phases != set(range(1, 11)):
        errors.append("traceability must cover each of the ten phases")
    status_counts = Counter(str(row.get("status")) for row in requirements)
    complete = (
        status_counts["verified"]
        + status_counts["deferred"]
        + status_counts["superseded"]
    )
    accounted_for = complete + status_counts["blocked"]
    return (
        {
            "complete_for_release": (
                complete == len(requirements) and status_counts["blocked"] == 0
            ),
            "controlling_decisions": {
                "counts": dict(sorted(phase_counts[0].items())),
                "phase": 0,
                "requirements": sum(phase_counts[0].values()),
            },
            "requirements_accounted_for": accounted_for == len(requirements),
            "generated_at": generated_at,
            "phase_count": len(implementation_phases),
            "phases": [
                {
                    "counts": dict(sorted(phase_counts[phase].items())),
                    "phase": phase,
                    "requirements": sum(phase_counts[phase].values()),
                }
                for phase in sorted(implementation_phases)
            ],
            "requirements": requirements,
            "schema": "okf-implementation-status.v2",
            "source_manifest": traceability.get("source_manifest"),
            "status_counts": dict(sorted(status_counts.items())),
            "total_requirements": len(requirements),
            "validation_errors": errors,
        },
        errors,
    )


def release_state(
    generated_at: str,
    evidence_ok: bool,
    traceability_accounted_for: bool,
) -> tuple[dict[str, Any], list[str]]:
    policy = load(POLICY)
    gates_doc = load(GATES)
    errors: list[str] = []
    gates = []
    for authored in gates_doc["gates"]:
        row = dict(authored)
        if row["id"] == "GATE-01":
            row["status"] = (
                "passed" if traceability_accounted_for else "pending"
            )
            row["observed_reason"] = (
                "Every implementation clause is verified, explicitly deferred, "
                "superseded or externally blocked."
                if traceability_accounted_for
                else "One or more implementation clauses remain proposed, started or merely implemented."
            )
        if row["id"] == "GATE-02":
            row["status"] = "passed" if evidence_ok else "failed"
            row["observed_reason"] = (
                "All 24 research-package files (23 content hashes plus the "
                "integrity manifest) and the separately hashed Claude DOCX are present."
                if evidence_ok
                else "Immutable evidence verification failed."
            )
        gates.append(row)
    states = policy["transition_order"]
    by_name = {row["name"]: row for row in policy["states"]}
    gate_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for gate in gates:
        gate_groups[gate["group"]].append(gate)

    def state_passes(name: str) -> bool:
        return all(
            gate.get("status") == "passed"
            for group in by_name[name]["required_gate_groups"]
            for gate in gate_groups[group]
        )

    maximum = "draft"
    for name in states:
        if state_passes(name):
            maximum = name
        else:
            break
    current = policy["current_state"]
    if current not in states:
        errors.append(f"unknown current release state: {current}")
    elif states.index(current) > states.index(maximum):
        errors.append(
            f"current release state {current} exceeds evidenced state {maximum}"
        )
    next_state = (
        states[states.index(current) + 1]
        if current in states and states.index(current) + 1 < len(states)
        else None
    )
    return (
        {
            "current_state": current,
            "fail_closed": True,
            "gate_counts": dict(
                sorted(Counter(gate["status"] for gate in gates).items())
            ),
            "gates": gates,
            "generated_at": generated_at,
            "maximum_evidenced_state": maximum,
            "next_state": next_state,
            "next_transition_allowed": bool(
                next_state and states.index(next_state) <= states.index(maximum)
            ),
            "policy": POLICY.relative_to(ROOT).as_posix(),
            "schema": "okf-release-state.v1",
            "state_consistent": not errors,
        },
        errors,
    )


def parse_requirements() -> list[dict[str, str]]:
    rows = []
    for raw in (ROOT / "requirements-validation.txt").read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, version = line.partition("==")
        if not separator:
            raise ValueError(f"dependency is not exactly pinned: {line}")
        rows.append({"name": name, "version": version})
    return rows


def workflow_actions() -> list[dict[str, Any]]:
    found: dict[tuple[str, str], set[str]] = defaultdict(set)
    pattern = re.compile(r"^\s*(?:-\s+)?uses:\s*([^@\s]+)@([^\s#]+)")
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for line in workflow.read_text(encoding="utf-8").splitlines():
            match = pattern.match(line)
            if match:
                found[(match.group(1), match.group(2))].add(
                    workflow.relative_to(ROOT).as_posix()
                )
    return [
        {
            "name": name,
            "version": version,
            "workflows": sorted(workflows),
        }
        for (name, version), workflows in sorted(found.items())
    ]


def build_sbom(generated_at: str, materials_digest: str) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    for row in parse_requirements():
        normalized = row["name"].lower().replace("_", "-")
        components.append(
            {
                "bom-ref": f"pkg:pypi/{normalized}@{row['version']}",
                "name": row["name"],
                "purl": f"pkg:pypi/{normalized}@{row['version']}",
                "type": "library",
                "version": row["version"],
            }
        )
    for row in workflow_actions():
        purl = f"pkg:github/{row['name']}@{row['version']}"
        components.append(
            {
                "bom-ref": purl,
                "name": row["name"],
                "properties": [
                    {
                        "name": "okf:workflow",
                        "value": ", ".join(row["workflows"]),
                    },
                    {
                        "name": "okf:ref-kind",
                        "value": (
                            "commit-sha"
                            if re.fullmatch(r"[0-9a-fA-F]{40}", row["version"])
                            else "mutable-tag"
                        ),
                    },
                ],
                "purl": purl,
                "type": "application",
                "version": row["version"],
            }
        )
    root_ref = "pkg:github/chris-page-gov/okf-uk-legislation@candidate"
    serial = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"https://github.com/chris-page-gov/okf-uk-legislation/{materials_digest}",
    )
    return {
        "bomFormat": "CycloneDX",
        "components": components,
        "dependencies": [
            {
                "dependsOn": sorted(component["bom-ref"] for component in components),
                "ref": root_ref,
            }
        ],
        "metadata": {
            "component": {
                "bom-ref": root_ref,
                "licenses": [{"license": {"id": "MIT"}}],
                "name": "okf-uk-legislation",
                "type": "application",
                "version": "0.3.0-candidate",
            },
            "timestamp": generated_at,
            "tools": {
                "components": [
                    {
                        "name": "build_release_assurance.py",
                        "type": "application",
                        "version": "1.0.0",
                    }
                ]
            },
        },
        "serialNumber": f"urn:uuid:{serial}",
        "specVersion": "1.6",
        "version": 1,
    }


def build_spdx(generated_at: str, materials_digest: str) -> dict[str, Any]:
    namespace = (
        "https://chris-page-gov.github.io/okf-uk-legislation/"
        f"spdx/{materials_digest}"
    )
    packages = [
        {
            "SPDXID": "SPDXRef-Package-Code",
            "copyrightText": "Copyright contributors",
            "downloadLocation": "https://github.com/chris-page-gov/okf-uk-legislation",
            "filesAnalyzed": False,
            "licenseConcluded": "MIT",
            "licenseDeclared": "MIT",
            "name": "okf-uk-legislation code and original documentation",
            "versionInfo": "0.3.0-candidate",
        },
        {
            "SPDXID": "SPDXRef-Package-Government-Metadata",
            "copyrightText": "Crown copyright",
            "downloadLocation": "https://www.legislation.gov.uk/",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "OGL-UK-3.0",
            "name": "UK government source metadata and derived catalogue",
            "versionInfo": "2026-07-25-snapshot",
        },
        {
            "SPDXID": "SPDXRef-Package-Source-Specific",
            "copyrightText": "NOASSERTION",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseComments": (
                "EU-derived, third-party and item-level material can have "
                "additional terms. Record-level rights take precedence."
            ),
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "name": "Source-specific linked material",
            "versionInfo": "catalogued-not-redistributed",
        },
    ]
    return {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {
            "created": generated_at,
            "creators": ["Tool: build_release_assurance.py-1.0.0"],
            "licenseListVersion": "3.26",
        },
        "dataLicense": "CC0-1.0",
        "documentDescribes": [row["SPDXID"] for row in packages],
        "documentNamespace": namespace,
        "name": "UK Whole-Law OKF rights inventory",
        "packages": packages,
        "relationships": [
            {
                "relatedSpdxElement": row["SPDXID"],
                "relationshipType": "DESCRIBES",
                "spdxElementId": "SPDXRef-DOCUMENT",
            }
            for row in packages
        ],
        "spdxVersion": "SPDX-2.3",
    }


def build_model_cost(generated_at: str) -> dict[str, Any]:
    source_path = ROOT / "bundle" / "enrichment" / "codex-assisted-v2.json"
    if not source_path.is_file():
        return {
            "generated_at": generated_at,
            "release_effect": "blocked",
            "schema": "okf-model-cost-report.v1",
            "source_available": False,
        }
    source = load(source_path)
    cost = source.get("cost", {})
    usd = float(cost.get("incremental_openai_api_usd", 0))
    gbp = float(cost.get("incremental_openai_api_gbp", 0))
    accepted = int(
        source.get("accepted_assertions")
        or source.get("counts", {}).get("assertions", {}).get("accepted", 0)
    )
    return {
        "accepted_assertions": accepted,
        "cap": {
            "cap_triggered": bool(cost.get("cap_triggered")),
            "cap_usd": float(cost.get("cap_usd", 250)),
            "remaining_usd": max(0.0, float(cost.get("cap_usd", 250)) - usd),
        },
        "cost_per_accepted_assertion": {
            "gbp": gbp / accepted if accepted else None,
            "usd": usd / accepted if accepted else None,
        },
        "generated_at": generated_at,
        "incremental_cost": {"gbp": gbp, "usd": usd},
        "model_identity": source.get("model_identity", "not recorded"),
        "model_deployment_identity_available": source.get(
            "model_deployment_identity_available"
        ),
        "provider": source.get("provider"),
        "notes": [
            cost.get("note", ""),
            "Codex subscription/task usage and the user's weekly allowance are not exposed as billable token data.",
            (
                "No currency conversion was required because recorded "
                "incremental OpenAI API spend is zero."
                if usd == 0 and gbp == 0
                else "A dated exchange-rate source is required before release."
            ),
        ],
        "release_effect": (
            "candidate"
            if usd == 0 and gbp == 0
            else "blocked-pending-exchange-rate-evidence"
        ),
        "run_id": source.get("run_id"),
        "schema": "okf-model-cost-report.v1",
        "source": material(source_path),
        "usage": source.get("usage", {}),
    }


def build_constraint_report(generated_at: str) -> dict[str, Any]:
    source_path = (
        ROOT
        / "whole-law"
        / "acquisition"
        / "current"
        / "source-constraint-ledger.json"
    )
    source = load(source_path)
    projection_path = source_path.parent / "publication-projection.json"
    redactions_path = source_path.parent / "publication-redactions.json"
    projection = load(projection_path)
    redactions = load(redactions_path)
    constraints = source.get("constraints", [])
    by_kind = Counter(row.get("kind", "unknown") for row in constraints)
    by_state = Counter(
        row.get("escalation_state", "unknown") for row in constraints
    )
    triggered = [row for row in constraints if row.get("triggered_during_capture")]
    escalations = [
        {
            "effect": row.get("effect"),
            "id": row.get("id"),
            "kind": row.get("kind"),
            "owner": row.get("owner"),
            "source_id": row.get("source_id"),
            "state": row.get("escalation_state"),
            "trigger": row.get("trigger"),
        }
        for row in constraints
        if row.get("escalation_state") in {"escalated", "blocked"}
    ]
    action_components = workflow_actions()
    mutable_actions = [
        row
        for row in action_components
        if not re.fullmatch(r"[0-9a-fA-F]{40}", row["version"])
    ]
    return {
        "counts": {
            "by_escalation_state": dict(sorted(by_state.items())),
            "by_kind": dict(sorted(by_kind.items())),
            "escalations": len(escalations),
            "total": len(constraints),
            "triggered_during_capture": len(triggered),
        },
        "escalations": escalations,
        "generated_at": generated_at,
        "licence_and_fair_use_rule": (
            "Constraints remain visible and are escalated; they do not silently "
            "remove prototype functionality or authorise authentication bypass."
        ),
        "release_effect": (
            "candidate-internal-escalation-required"
            if escalations or mutable_actions
            else "no-open-escalation"
        ),
        "schema": "okf-constraint-report.v1",
        "source": material(source_path),
        "publication_content_handling": {
            "projection_id": projection.get("projection_id"),
            "projection_is_immutable_original": projection.get(
                "immutable_original"
            ),
            "source_archive_sha256": projection.get(
                "source_evidence",
                {},
            ).get("archive_sha256"),
            "redacted_body_entries": len(redactions.get("entries", [])),
            "detector_values_recorded": any(
                row.get("values_recorded") is not False
                for row in redactions.get("entries", [])
            ),
            "immutable_original_mutated": redactions.get(
                "assertions",
                {},
            ).get("immutable_original_mutated"),
            "mitigation": (
                "Original bytes remain in a deterministic integrity-bound "
                "archive; the Git publication is a separately identified "
                "metadata-only projection with value-free receipts."
            ),
            "projection_source": material(projection_path),
            "redaction_source": material(redactions_path),
        },
        "supply_chain": {
            "mutable_github_action_refs": mutable_actions,
            "release_requirement": (
                "Pin third-party GitHub Actions to reviewed 40-character commit "
                "SHAs before validated state."
            ),
        },
    }


def build_status_markdown(status: dict[str, Any], state: dict[str, Any]) -> bytes:
    lines = [
        "# UK Whole-Law OKF implementation status",
        "",
        f"Generated: `{status['generated_at']}`",
        "",
        f"Release state: **{state['current_state']}**. Maximum evidenced state: "
        f"**{state['maximum_evidenced_state']}**.",
        "",
        "This is a fail-closed candidate status. It does not claim executed "
        "security, browser, accessibility, performance, legal-practitioner or "
        "third-party assurance.",
        "",
        "| Phase | Requirements | Status counts |",
        "| ---: | ---: | --- |",
    ]
    decisions = status["controlling_decisions"]
    decision_counts = ", ".join(
        f"{key}: {value}" for key, value in decisions["counts"].items()
    )
    lines.append(
        f"| 0 (later decisions) | {decisions['requirements']} | "
        f"{decision_counts} |"
    )
    for phase in status["phases"]:
        counts = ", ".join(
            f"{key}: {value}" for key, value in phase["counts"].items()
        )
        lines.append(f"| {phase['phase']} | {phase['requirements']} | {counts} |")
    lines.extend(
        [
            "",
            "The machine-readable clause ledger is in "
            "[implementation-status.json](implementation-status.json); release "
            "gates are in [release-state.json](release-state.json).",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def build_readme() -> bytes:
    return b"""# Release assurance

These deterministic candidate artefacts bind the implementation status,
immutable research evidence, release state, rights, dependencies, provenance,
constraints and model cost. They are projections, not substitutes for gates
which must still be executed on a frozen release candidate.

- [Implementation status](implementation-status.md)
- [Controlling requirements](controlling-requirements.md)
- [Clause-level traceability](implementation-traceability.json)
- [Implementation gap register](gap-register.json)
- [Fail-closed release state](release-state.json)
- [Immutable evidence manifest](evidence-manifest.json)
- [Claude observed-access test](claude-observed-access-test.json)
- [SPDX 2.3 rights inventory](rights.spdx.json)
- [CycloneDX 1.6 SBOM](sbom.cdx.json)
- [Provenance](provenance.json)
- [Reproduction contract](reproduction.json)
- [Constraint report](constraint-report.json)
- [Model cost report](model-cost-report.json)
- [Assurance checksums](checksums.json)
"""


def build_files() -> tuple[dict[Path, bytes], list[str]]:
    policy = load(POLICY)
    generated_at = policy["generated_at"]
    evidence, evidence_errors = evidence_manifest(generated_at)
    status, status_errors = implementation_status(generated_at)
    traceability_accounted_for = (
        bool(status["requirements_accounted_for"]) and not status_errors
    )
    state, state_errors = release_state(
        generated_at,
        evidence_ok=not evidence_errors,
        traceability_accounted_for=traceability_accounted_for,
    )
    errors = evidence_errors + status_errors + state_errors

    input_paths = [
        POLICY,
        GATES,
        TRACEABILITY,
        TRACEABILITY_SOURCE,
        TRACEABILITY_SOURCE_DIGEST,
        GAP_REGISTER,
        AUTHORED_STATUS,
        RESEARCH / "integrity.json",
        ROOT / "requirements-validation.txt",
        ROOT / "LICENSE.md",
        ROOT / ".github" / "workflows" / "ci.yml",
        ROOT / ".github" / "workflows" / "pages.yml",
        ROOT
        / "whole-law"
        / "acquisition"
        / "current"
        / "source-constraint-ledger.json",
        CLAUDE_TRANSCRIPT,
    ]
    enrichment = ROOT / "bundle" / "enrichment" / "codex-assisted-v2.json"
    if enrichment.is_file():
        input_paths.append(enrichment)
    inputs = [material(path) for path in input_paths]
    materials_digest = digest_bytes(
        "".join(f"{row['path']}:{row['sha256']}\n" for row in inputs).encode(
            "utf-8"
        )
    )
    provenance = {
        "builder": {
            "command": "python3 scripts/build_release_assurance.py",
            "name": "build_release_assurance.py",
            "version": "1.0.0",
        },
        "generated_at": generated_at,
        "materials": inputs,
        "materials_digest": f"sha256:{materials_digest}",
        "outputs": {
            "checksum_manifest": "checksums.json",
            "deterministic": True,
        },
        "release_snapshot": {
            "frozen": False,
            "state": state["current_state"],
            "warning": (
                "This projection describes a mutable candidate worktree. "
                "A release-candidate provenance attestation must bind the final "
                "commit and identical promoted artefact digests."
            ),
        },
        "schema": "okf-build-provenance.v1",
    }
    reproduction = {
        "check_command": "python3 scripts/build_release_assurance.py --check",
        "clean_room_execution": {
            "evidence": None,
            "status": "not-executed",
        },
        "environment": {
            "network_required": False,
            "python": ">=3.12",
            "requirements": material(ROOT / "requirements-validation.txt"),
        },
        "generated_at": generated_at,
        "inputs": {
            "materials_digest": f"sha256:{materials_digest}",
            "research_evidence_verified": not evidence_errors,
        },
        "limitations": [
            "This builder verifies only the release-assurance projection.",
            "Clean-clone reproduction of every corpus and semantic byte digest remains a separate release gate.",
            "The candidate is not a frozen release candidate and no external assurance is claimed.",
            "GUI-backed LibreOffice rendering aborts under Codex/macOS; DOCX transcript extraction uses Pandoc or python-docx.",
        ],
        "output_directory": "bundle/release-assurance",
        "schema": "okf-reproduction-contract.v1",
        "write_command": "python3 scripts/build_release_assurance.py",
    }
    files: dict[Path, bytes] = {
        Path("README.md"): build_readme(),
        Path("controlling-requirements.md"): TRACEABILITY_SOURCE.read_bytes(),
        Path(
            "controlling-requirements.sha256"
        ): TRACEABILITY_SOURCE_DIGEST.read_bytes(),
        Path("constraint-report.json"): render(build_constraint_report(generated_at)),
        Path("claude-observed-access-test.json"): render(
            build_claude_access_test(generated_at)
        ),
        Path("evidence-manifest.json"): render(evidence),
        Path("implementation-status.json"): render(status),
        Path("implementation-status.md"): build_status_markdown(status, state),
        Path("implementation-traceability.json"): TRACEABILITY.read_bytes(),
        Path("gap-register.json"): GAP_REGISTER.read_bytes(),
        Path("model-cost-report.json"): render(build_model_cost(generated_at)),
        Path("provenance.json"): render(provenance),
        Path("release-state.json"): render(state),
        Path("reproduction.json"): render(reproduction),
        Path("rights.spdx.json"): render(build_spdx(generated_at, materials_digest)),
        Path("sbom.cdx.json"): render(build_sbom(generated_at, materials_digest)),
    }
    checksum_rows = [
        {
            "bytes": len(body),
            "path": path.as_posix(),
            "sha256": digest_bytes(body),
        }
        for path, body in sorted(files.items(), key=lambda item: item[0].as_posix())
    ]
    files[Path("checksums.json")] = render(
        {
            "algorithm": "sha256",
            "files": checksum_rows,
            "generated_at": generated_at,
            "schema": "okf-release-assurance-checksums.v1",
        }
    )
    return files, errors


def compare(files: dict[Path, bytes], output: Path) -> list[str]:
    errors: list[str] = []
    expected = set(files)
    actual = (
        {
            path.relative_to(output)
            for path in output.rglob("*")
            if path.is_file()
        }
        if output.exists()
        else set()
    )
    for relative in sorted(expected | actual):
        if relative not in expected:
            errors.append(f"unexpected generated file: {relative}")
        elif relative not in actual:
            errors.append(f"missing generated file: {relative}")
        elif (output / relative).read_bytes() != files[relative]:
            errors.append(f"out-of-date generated file: {relative}")
    return errors


def write(files: dict[Path, bytes], output: Path) -> None:
    if output.exists():
        shutil.rmtree(output)
    for relative, body in files.items():
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    files, validation_errors = build_files()
    if validation_errors:
        print("Release-assurance inputs are invalid:")
        for error in validation_errors:
            print(f"- {error}")
        return 1
    if args.check:
        errors = compare(files, output)
        if errors:
            print("Release-assurance projection is not synchronized:")
            for error in errors:
                print(f"- {error}")
            return 1
        print(f"release assurance verified: {len(files)} files; state=candidate")
        return 0
    write(files, output)
    try:
        display_output = output.relative_to(ROOT)
    except ValueError:
        display_output = output
    print(f"wrote {len(files)} release-assurance files to {display_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
