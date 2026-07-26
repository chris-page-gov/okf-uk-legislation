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

import build_model_enrichment_paid_publication as paid_publication

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "release-assurance"
OUTPUT = ROOT / "bundle" / "release-assurance"
RESEARCH = ROOT / "research" / "whole-law-okf-research"
CLAUDE = ROOT / "research" / "Legislation-govuk Claude 4.8 run.docx"
CLAUDE_TRANSCRIPT = ROOT / "research" / "claude-4.8-evaluation-transcript.md"
POLICY = SOURCE / "release-policy.json"
GATES = SOURCE / "release-gates.json"
EXTERNAL_FINALIZATION_CONTRACT = (
    SOURCE / "external-finalization-contract.json"
)
FINALIZER = ROOT / "scripts" / "finalize_release_candidate.py"
RELEASE_OBSERVATION_CONTROLLER = (
    ROOT / "scripts" / "capture_github_release_observation.py"
)
TRACEABILITY = SOURCE / "implementation-traceability.json"
TRACEABILITY_SOURCE = (
    ROOT / "evidence" / "requirements" / "controlling-requirements.md"
)
TRACEABILITY_SOURCE_DIGEST = TRACEABILITY_SOURCE.with_suffix(".sha256")
GAP_REGISTER = SOURCE / "gap-register.json"
AUTHORED_STATUS = SOURCE / "implementation-status.md"
GITHUB_OPERATION_ENVIRONMENT = SOURCE / "github-operation-environment.json"
HELPER_CRASH_STOP_RECEIPT = SOURCE / "helper-crash-stop-receipt.json"
RELATIONSHIP_COMPOSITION = (
    ROOT / "bundle" / "data" / "relationship-composition.json"
)
EFFECTS_COVERAGE = ROOT / "bundle" / "data" / "effects" / "coverage.json"
ENRICHMENT_COVERAGE = (
    ROOT / "bundle" / "data" / "enrichment" / "coverage.json"
)
WHOLE_LAW_COVERAGE = ROOT / "bundle" / "whole-law" / "data" / "coverage.json"
SOURCE_ACCESS_SUMMARY = (
    ROOT
    / "bundle"
    / "whole-law"
    / "acquisition"
    / "current"
    / "source-access-summary.json"
)
EVALUATION_EXECUTIONS = (
    ROOT / "bundle" / "whole-law" / "evaluation" / "executions"
)
EVALUATION_INDEX = EVALUATION_EXECUTIONS / "index.json"
PAID_MODEL_RUN = (
    ROOT / "enrichment" / "model-assisted-paid-v2" / "run.json"
)
PAID_MODEL_PUBLICATION = (
    ROOT / "bundle" / "enrichment" / "model-assisted-paid-v2.json"
)
HISTORICAL_MODEL_PUBLICATION = (
    ROOT / "bundle" / "enrichment" / "codex-assisted-v2.json"
)
VALID_STATUSES = {
    "proposed",
    "started",
    "implemented",
    "verified",
    "blocked",
    "superseded",
    "deferred",
}

# Traceability may cite these two projections as validation evidence even when
# a clean corpus rebuild has just removed ``bundle/``.  They are produced
# unconditionally by this builder later in the same transaction.  Keep this
# allow-list exact: all other evidence references must already exist.
SELF_PROJECTED_EVIDENCE = frozenset(
    {
        "bundle/release-assurance/claude-observed-access-test.json",
        "bundle/release-assurance/evidence-manifest.json",
    }
)


def evidence_reference_available(reference: str) -> bool:
    return reference in SELF_PROJECTED_EVIDENCE or (ROOT / reference).exists()


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


def projected_material(relative: str, body: bytes) -> dict[str, Any]:
    return {
        "path": f"bundle/release-assurance/{relative}",
        "bytes": len(body),
        "sha256": digest_bytes(body),
    }


def contract_schema_paths(value: Any) -> list[Path]:
    """Return safe, unique repository schema paths named by a contract."""

    references: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, str) and node.endswith(".schema.json"):
            references.add(node)

    visit(value)
    paths: list[Path] = []
    for reference in sorted(references):
        path = (ROOT / reference).resolve()
        if not path.is_relative_to(ROOT.resolve()):
            raise ValueError(
                f"external finalization schema escapes repository: {reference}"
            )
        paths.append(path)
    return paths


def external_finalization_projection(
    policy: dict[str, Any],
) -> tuple[dict[str, Any], list[Path], list[str]]:
    errors: list[str] = []
    contract = load(EXTERNAL_FINALIZATION_CONTRACT)
    if policy.get("schema") != "okf-release-state-policy.v2":
        errors.append("release policy must use okf-release-state-policy.v2")
    if (
        policy.get("external_finalization_contract")
        != EXTERNAL_FINALIZATION_CONTRACT.relative_to(ROOT).as_posix()
    ):
        errors.append(
            "release policy must link the external finalization contract"
        )
    if contract.get("schema") != "okf-external-finalization-contract.v2":
        errors.append(
            "external finalization contract must use its v2 schema"
        )
    if contract.get("evidence_plane") != "external-write-once":
        errors.append("external finalization evidence plane must be write-once")
    release_observations = contract.get("release_observations", {})
    expected_observation_controller = (
        RELEASE_OBSERVATION_CONTROLLER.relative_to(ROOT).as_posix()
    )
    if (
        not isinstance(release_observations, dict)
        or release_observations.get("controller")
        != expected_observation_controller
    ):
        errors.append(
            "external finalization contract must bind the canonical GitHub "
            "release-observation controller"
        )
    for label, rule in (
        ("pre-RC authorization", contract.get("pre_rc_authorization", {})),
        (
            "final-promotion authorization",
            contract.get("final_promotion_authorization", {}),
        ),
        ("finalization", contract.get("finalization", {})),
    ):
        if rule.get("write_once") is not True:
            errors.append(f"{label} output must be write-once")

    try:
        declared_schemas = contract_schema_paths(contract)
    except ValueError as exc:
        declared_schemas = []
        errors.append(str(exc))
    support_schemas = [
        SOURCE / "schemas" / name
        for name in (
            "deployed-entrypoint-attempt.schema.json",
            "deployed-entrypoint-projection.schema.json",
            "deployed-entrypoints-manifest.schema.json",
            "provenance-inputs.schema.json",
        )
    ]
    schema_paths = sorted(
        set(declared_schemas + support_schemas),
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )
    projected_names: set[str] = set()
    schema_rows: list[dict[str, Any]] = []
    for path in schema_paths:
        if not path.is_file():
            errors.append(
                "external finalization schema is missing: "
                f"{path.relative_to(ROOT).as_posix()}"
            )
            continue
        try:
            projected = path.relative_to(SOURCE).as_posix()
        except ValueError:
            errors.append(
                "external finalization schema is outside release-assurance: "
                f"{path.relative_to(ROOT).as_posix()}"
            )
            continue
        if projected in projected_names:
            errors.append(
                f"duplicate projected external finalization schema: {projected}"
            )
            continue
        projected_names.add(projected)
        schema_rows.append(
            {
                **material(path),
                "projected_path": projected,
            }
        )

    finalizer_text = FINALIZER.read_text(encoding="utf-8")
    workflow = [
        {
            "command": command,
            "effect": effect,
        }
        for command, effect in (
            (
                "authorize-rc",
                "write the immutable pre-RC authorization receipt",
            ),
            (
                "verify-rc",
                "reconstruct and verify the pre-RC authorization receipt",
            ),
            (
                "authorize-final-promotion",
                "write immutable authorization to publish the already sealed RC asset as final",
            ),
            (
                "finalize",
                "write the immutable finalization receipt after identical-byte promotion",
            ),
            (
                "verify-final",
                "reconstruct and verify the finalization receipt",
            ),
        )
    ]
    for step in workflow:
        if step["command"] not in finalizer_text:
            errors.append(
                f"finalizer does not expose {step['command']} workflow command"
            )
    projection = {
        "contract": {
            **material(EXTERNAL_FINALIZATION_CONTRACT),
            "projected_path": "external-finalization-contract.json",
        },
        "evidence_plane": contract.get("evidence_plane"),
        "finalizer": material(FINALIZER),
        "release_observation_controller": material(
            RELEASE_OBSERVATION_CONTROLLER
        ),
        "invariants": {
            "archive_rebuild_prohibited": contract.get(
                "finalization", {}
            ).get("archive_rebuild_prohibited"),
            "frozen_checkout_mutation_prohibited": contract.get(
                "finalization", {}
            ).get("frozen_checkout_mutation_prohibited"),
            "promotion_requires_identical_filename_bytes_and_sha256": (
                contract.get("finalization", {}).get(
                    "promotion_requires_identical_filename_bytes_and_sha256"
                )
            ),
            "write_once": contract.get("finalization", {}).get("write_once"),
        },
        "policy": {
            **material(POLICY),
            "projected_path": "release-policy.json",
            "schema": policy.get("schema"),
        },
        "schemas": schema_rows,
        "workflow": workflow,
    }
    return projection, schema_paths, errors


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
                if not evidence_reference_available(reference):
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


def build_release_report(
    generated_at: str,
    constraint_report: dict[str, Any],
    constraint_body: bytes,
    model_cost: dict[str, Any],
    model_cost_body: bytes,
) -> tuple[dict[str, Any], list[Path], list[str]]:
    """Build the complete embedded GATE-12 report without claiming later gates."""

    errors: list[str] = []
    source_paths = [
        RELATIONSHIP_COMPOSITION,
        EFFECTS_COVERAGE,
        ENRICHMENT_COVERAGE,
        WHOLE_LAW_COVERAGE,
        SOURCE_ACCESS_SUMMARY,
        EVALUATION_INDEX,
        GAP_REGISTER,
    ]
    missing = [path for path in source_paths if not path.is_file()]
    if missing:
        errors.extend(
            "release report source is missing: "
            f"{path.relative_to(ROOT).as_posix()}"
            for path in missing
        )
        return (
            {
                "gate": "GATE-12",
                "generated_at": generated_at,
                "schema": "okf-release-report.v1",
                "status": "failed",
            },
            source_paths,
            errors,
        )

    composition = load(RELATIONSHIP_COMPOSITION)
    effects = load(EFFECTS_COVERAGE)
    enrichment = load(ENRICHMENT_COVERAGE)
    whole_law = load(WHOLE_LAW_COVERAGE)
    access = load(SOURCE_ACCESS_SUMMARY)
    gaps = load(GAP_REGISTER)
    evaluation_index = load(EVALUATION_INDEX)

    composition_dimensions = (
        "by_predicate",
        "by_authority",
        "by_confidence",
        "by_freshness",
    )
    for dimension in composition_dimensions:
        value = composition.get(dimension)
        if not isinstance(value, dict) or not value:
            errors.append(
                f"release report relationship composition lacks {dimension}"
            )

    latest_run_id = evaluation_index.get("latest_run_id")
    execution = next(
        (
            row
            for row in evaluation_index.get("executions", [])
            if row.get("run_id") == latest_run_id
        ),
        None,
    )
    if not isinstance(latest_run_id, str) or execution is None:
        errors.append("release report cannot resolve the latest evaluation")
        evaluation_results_path = EVALUATION_INDEX
        evaluation_scores_path = EVALUATION_INDEX
        evaluation_results: dict[str, Any] = {}
        evaluation_scores: dict[str, Any] = {}
    else:
        evaluation_results_path = (
            EVALUATION_EXECUTIONS / str(execution.get("results", ""))
        ).resolve()
        evaluation_scores_path = (
            EVALUATION_EXECUTIONS / latest_run_id / "scores.json"
        ).resolve()
        if (
            not evaluation_results_path.is_relative_to(
                EVALUATION_EXECUTIONS.resolve()
            )
            or not evaluation_scores_path.is_relative_to(
                EVALUATION_EXECUTIONS.resolve()
            )
        ):
            errors.append("release report evaluation path escapes executions")
            evaluation_results = {}
            evaluation_scores = {}
        elif (
            not evaluation_results_path.is_file()
            or not evaluation_scores_path.is_file()
        ):
            errors.append("release report evaluation materials are missing")
            evaluation_results = {}
            evaluation_scores = {}
        else:
            evaluation_results = load(evaluation_results_path)
            evaluation_scores = load(evaluation_scores_path)
            source_paths.extend(
                [evaluation_results_path, evaluation_scores_path]
            )

    evaluation_analysis = evaluation_results.get("analysis", {})
    evaluated_release = evaluation_analysis.get("whole_law_release", {})
    if not (
        evaluated_release.get("answers_executed", 0) > 0
        and evaluation_scores.get("status") == "passed"
    ):
        errors.append("release report lacks a passing executed evaluation")

    unresolved = [
        {
            key: row.get(key)
            for key in (
                "id",
                "status",
                "area",
                "summary",
                "release_effect",
                "next_action",
            )
        }
        for row in gaps.get("gaps", [])
        if row.get("status") != "resolved"
    ]
    if len(unresolved) != sum(
        int(gaps.get("counts", {}).get(status, 0))
        for status in ("blocked", "deferred", "open")
    ):
        errors.append("release report unresolved-gap counts do not reconcile")

    cost = model_cost.get("incremental_cost", {})
    if not all(key in cost for key in ("usd", "gbp")):
        errors.append("release report must record model cost in USD and GBP")
    if not isinstance(constraint_report.get("escalations"), list):
        errors.append("release report must record licence/access escalations")

    contract = load(EXTERNAL_FINALIZATION_CONTRACT)
    sections = {
        "coverage_and_freshness": {
            "materials": [
                material(path)
                for path in (
                    EFFECTS_COVERAGE,
                    ENRICHMENT_COVERAGE,
                    WHOLE_LAW_COVERAGE,
                    SOURCE_ACCESS_SUMMARY,
                )
            ],
            "model_assisted": {
                "attempt_coverage": enrichment.get("attempt_coverage"),
                "counts": enrichment.get("counts"),
                "generated_at": enrichment.get("generated_at"),
            },
            "official_effects": {
                "generated_at": effects.get("generated_at"),
                "population": effects.get("population"),
                "snapshot_id": effects.get("snapshot_id"),
                "status": effects.get("status"),
            },
            "source_access": {
                "coverage": access.get("coverage"),
                "evidence_run_id": access.get("evidence_run_id"),
                "generated_at": access.get("generated_at"),
                "result_counts": access.get("result_counts"),
            },
            "whole_law": {
                "claim": whole_law.get("claim"),
                "denominator": whole_law.get("denominator"),
                "generated_at": whole_law.get("generated_at"),
                "source_family_status": whole_law.get(
                    "source_family_status"
                ),
            },
        },
        "evaluation": {
            "assurance_boundary": evaluation_analysis.get(
                "assurance_boundary"
            ),
            "answers_executed": evaluated_release.get("answers_executed"),
            "corpus_navigation_score": evaluated_release.get(
                "corpus_navigation_score"
            ),
            "executed_at": evaluation_results.get("executed_at"),
            "hard_failures": evaluated_release.get("hard_failures", []),
            "materials": [
                material(EVALUATION_INDEX),
                material(evaluation_results_path),
                material(evaluation_scores_path),
            ],
            "minimum_critical_family_score": evaluation_scores.get(
                "minimum_family_score"
            ),
            "run_id": evaluation_results.get("run_id"),
            "scope": evaluation_scores.get("evaluation_scope"),
            "status": evaluation_scores.get("status"),
        },
        "gaps": {
            "counts": gaps.get("counts"),
            "source": material(GAP_REGISTER),
            "unresolved": unresolved,
        },
        "licence_and_access_escalations": {
            "counts": constraint_report.get("counts"),
            "escalations": constraint_report.get("escalations"),
            "rule": constraint_report.get("licence_and_fair_use_rule"),
            "source": projected_material(
                "constraint-report.json", constraint_body
            ),
        },
        "model_cost": {
            "boundary": model_cost.get(
                "cost_boundary",
                (
                    "Governed paid-run cost is unavailable. Any recorded "
                    "historical Codex-assisted amount is a separate fallback "
                    "observation and cannot satisfy the paid-run gate."
                ),
            ),
            "governed_paid_cost": model_cost.get("governed_paid_cost"),
            "historical_fallback_cost": model_cost.get(
                "historical_fallback_cost"
            ),
            "incremental_cost": cost,
            "model_deployment_identity_available": model_cost.get(
                "model_deployment_identity_available"
            ),
            "model_identity": model_cost.get("model_identity"),
            "paid_run_gate": model_cost.get("paid_run_gate"),
            "release_effect": model_cost.get("release_effect"),
            "run_id": model_cost.get("run_id"),
            "source": projected_material(
                "model-cost-report.json", model_cost_body
            ),
            "source_kind": model_cost.get("source_kind"),
            "usage": model_cost.get("usage"),
        },
        "relationship_composition": {
            "by_authority": composition.get("by_authority"),
            "by_confidence": composition.get("by_confidence"),
            "by_datapack": composition.get("by_datapack"),
            "by_freshness": composition.get("by_freshness"),
            "by_predicate": composition.get("by_predicate"),
            "generated_at": composition.get("generated_at"),
            "notice": composition.get("notice"),
            "snapshot": composition.get("snapshot"),
            "source": material(RELATIONSHIP_COMPOSITION),
            "total": composition.get("total"),
        },
        "yaml_ld_mime_exception": {
            "expected_media_type": "application/ld+yaml",
            "fallbacks": [
                "JSON-LD",
                "the immutable release archive",
            ],
            "observed_media_type": "application/octet-stream",
            "scope": "GitHub Pages .yamlld responses",
            "status": "declared-hosting-exception",
        },
    }
    expected_sections = {
        "relationship_composition",
        "coverage_and_freshness",
        "gaps",
        "licence_and_access_escalations",
        "evaluation",
        "model_cost",
        "yaml_ld_mime_exception",
    }
    if set(sections) != expected_sections:
        errors.append("release report section inventory is incomplete")

    report = {
        "checksum_binding": {
            "algorithm": "sha256",
            "manifest": "bundle/release-assurance/checksums.json",
            "required_paths": [
                "constraint-report.json",
                "model-cost-report.json",
                "release-report.json",
            ],
            "rule": (
                "The deterministic assurance checksum manifest must bind this "
                "report and both generated supporting reports. Exact source "
                "materials are transitively bound by their hashes here."
            ),
            "status": "bound-by-generated-manifest",
        },
        "gate": "GATE-12",
        "generated_at": generated_at,
        "limitations": [
            "Passing GATE-12 means the required release facts and limitations are recorded; it does not pass any external gate.",
            "No public deployment, release-candidate publication or final promotion is claimed by this embedded report.",
            "The evaluation covers corpus-navigation metadata, not legal-answer correctness or qualified legal assurance.",
        ],
        "release": {
            "archive": contract.get("archive", {}).get("filename"),
            "candidate": contract.get("candidate"),
            "explorer": contract.get("explorer"),
        },
        "schema": "okf-release-report.v1",
        "sections": sections,
        "status": "passed" if not errors else "failed",
    }
    return report, source_paths, errors


def release_state(
    generated_at: str,
    evidence_ok: bool,
    traceability_accounted_for: bool,
    release_report_material: dict[str, Any],
    release_report_ok: bool,
    external_finalization: dict[str, Any],
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
        if row["id"] == "GATE-12":
            row["status"] = "passed" if release_report_ok else "failed"
            row["observed_reason"] = (
                "The checksum-bound embedded release report records exact "
                "relationship composition, coverage and snapshot currency, "
                "unresolved gaps, licence/access escalations, executed "
                "evaluation, model cost and the YAML-LD MIME exception."
                if release_report_ok
                else "The embedded release report is incomplete or invalid."
            )
        gates.append(row)
    states = policy["transition_order"]
    by_name = {row["name"]: row for row in policy["states"]}
    gate_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for gate in gates:
        gate_groups[gate["group"]].append(gate)

    def state_passes(name: str) -> bool:
        required_groups = by_name[name]["required_gate_groups"]
        missing_groups = [
            group for group in required_groups if not gate_groups.get(group)
        ]
        if missing_groups:
            message = (
                f"release state {name} names empty or absent gate groups: "
                f"{', '.join(missing_groups)}"
            )
            if message not in errors:
                errors.append(message)
            return False
        return all(
            gate.get("status") == "passed"
            for group in required_groups
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
            "embedded_state": {
                "gates": {
                    "GATE-12": (
                        "passed" if release_report_ok else "failed"
                    ),
                },
                "release_report": release_report_material,
            },
            "external_finalization": {
                "contract": external_finalization["contract"],
                "evidence_plane": external_finalization["evidence_plane"],
                "finalizer": external_finalization["finalizer"],
                "release_observation_controller": external_finalization[
                    "release_observation_controller"
                ],
                "workflow": external_finalization["workflow"],
            },
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
            "policy_projection": external_finalization["policy"],
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
    authored_entry_present = PAID_MODEL_RUN.exists() or PAID_MODEL_RUN.is_symlink()
    published_entry_present = (
        PAID_MODEL_PUBLICATION.exists()
        or PAID_MODEL_PUBLICATION.is_symlink()
    )
    dedicated_authored = (
        PAID_MODEL_RUN.is_file() and not PAID_MODEL_RUN.is_symlink()
    )
    dedicated_published = (
        PAID_MODEL_PUBLICATION.is_file()
        and not PAID_MODEL_PUBLICATION.is_symlink()
    )
    dedicated_errors: list[str] = []
    dedicated_materials: list[dict[str, Any]] = []
    if authored_entry_present and not dedicated_authored:
        dedicated_errors.append(
            "dedicated paid-run receipt must be a regular non-symlink file"
        )
    if published_entry_present and not dedicated_published:
        dedicated_errors.append(
            "dedicated paid-run public projection must be a regular "
            "non-symlink file"
        )
    if dedicated_authored:
        try:
            authored = load(PAID_MODEL_RUN)
        except (OSError, json.JSONDecodeError) as exc:
            authored = None
            dedicated_errors.append(
                f"dedicated paid-run receipt cannot be read: {exc}"
            )
        if authored is not None:
            result = paid_publication.validate_paid_run(authored)
            dedicated_errors.extend(result.errors)
            dedicated_materials = [
                material(path)
                for path in result.materials
                if path.is_file() and not path.is_symlink()
            ]
        if not dedicated_published:
            dedicated_errors.append(
                "dedicated paid-run public projection is missing"
            )
        elif PAID_MODEL_PUBLICATION.read_bytes() != PAID_MODEL_RUN.read_bytes():
            dedicated_errors.append(
                "dedicated paid-run public projection is not byte-identical "
                "to the authored receipt"
            )
    elif dedicated_published:
        dedicated_errors.append(
            "dedicated paid-run public projection exists without an authored "
            "receipt"
        )

    source_path = (
        PAID_MODEL_PUBLICATION
        if dedicated_published
        else HISTORICAL_MODEL_PUBLICATION
    )
    if not source_path.is_file():
        return {
            "cost_boundary": (
                "Governed paid-run cost is unavailable because no dedicated "
                "paid-run receipt exists."
            ),
            "generated_at": generated_at,
            "governed_paid_cost": {
                "available": False,
                "gbp": None,
                "reason": "missing-dedicated-paid-run",
                "usd": None,
            },
            "release_effect": "blocked-missing-model-run",
            "paid_run_gate": {
                "reason": "missing-dedicated-paid-run",
                "status": "blocked",
            },
            "schema": "okf-model-cost-report.v1",
            "source_available": False,
            "source_kind": "missing",
            "validation_errors": [
                "model-enrichment run material is missing"
            ],
        }
    source = load(source_path)
    errors: list[str] = list(dedicated_errors)
    source_kind = (
        "dedicated-paid-run"
        if dedicated_authored and dedicated_published
        else "historical-codex-assisted-fallback"
    )
    source_schema = source.get("schema")
    provider = source.get("provider")
    run_id = source.get("run_id")
    if not isinstance(provider, str) or not provider:
        errors.append("model provider is missing")
    if not isinstance(run_id, str) or not run_id:
        errors.append("model run identifier is missing")

    cost = source.get("cost")
    usage = source.get("usage")
    if not isinstance(cost, dict):
        errors.append("model cost object is missing")
        cost = {}
    if not isinstance(usage, dict):
        errors.append("model usage object is missing")
        usage = {}

    if source_schema == "okf-model-enrichment-run.v2":
        roles = source.get("roles")
        generator = (
            roles.get("generator")
            if isinstance(roles, dict)
            else None
        )
        model_identity = (
            generator.get("returned_model")
            if isinstance(generator, dict)
            else None
        )
        model_identity_available = bool(
            isinstance(model_identity, str) and model_identity
        )
        accepted_value = (
            source.get("counts", {}).get("accepted_assertions")
            if isinstance(source.get("counts"), dict)
            else None
        )
        cost_fields = {
            "usd": "actual_usd",
            "gbp": "actual_gbp",
            "cap": "cap_usd",
            "cap_triggered": "cap_exceeded",
        }
        required_usage = (
            "api_calls",
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "retries",
        )
    elif source_schema == "okf-model-enrichment-run.v1":
        model_identity = source.get("model_identity")
        available_value = source.get(
            "model_deployment_identity_available"
        )
        if not isinstance(available_value, bool):
            errors.append(
                "exact model-identity availability flag is missing"
            )
        model_identity_available = available_value is True
        counts = source.get("counts")
        assertion_counts = (
            counts.get("assertions")
            if isinstance(counts, dict)
            else None
        )
        accepted_value = (
            assertion_counts.get("accepted")
            if isinstance(assertion_counts, dict)
            else source.get("accepted_assertions")
        )
        cost_fields = {
            "usd": "incremental_openai_api_usd",
            "gbp": "incremental_openai_api_gbp",
            "cap": "cap_usd",
            "cap_triggered": "cap_triggered",
        }
        required_usage = (
            "api_calls",
            "api_input_tokens",
            "api_output_tokens",
        )
    else:
        errors.append(
            f"unsupported model-enrichment run schema: {source_schema!r}"
        )
        model_identity = None
        model_identity_available = False
        accepted_value = None
        cost_fields = {
            "usd": "incremental_openai_api_usd",
            "gbp": "incremental_openai_api_gbp",
            "cap": "cap_usd",
            "cap_triggered": "cap_triggered",
        }
        required_usage = ()

    if not isinstance(model_identity, str) or not model_identity:
        errors.append("model identity is missing")
    elif not model_identity_available:
        errors.append("exact model deployment identity is unavailable")

    missing_cost_fields = [
        name
        for name in cost_fields.values()
        if name not in cost
    ]
    if missing_cost_fields:
        errors.append(
            "model cost fields are missing: "
            + ", ".join(sorted(missing_cost_fields))
        )
    missing_usage_fields = [
        name for name in required_usage if name not in usage
    ]
    if missing_usage_fields:
        errors.append(
            "model usage fields are missing: "
            + ", ".join(sorted(missing_usage_fields))
        )
    if accepted_value is None:
        errors.append("accepted-assertion denominator is missing")

    numeric: dict[str, float] = {}
    for label in ("usd", "gbp", "cap"):
        source_key = cost_fields[label]
        if source_key not in cost:
            continue
        value = cost[source_key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"model {label} value is not numeric")
            continue
        converted = float(value)
        if converted < 0:
            errors.append(f"model {label} value is negative")
            continue
        numeric[label] = converted
    cap_triggered_value = cost.get(cost_fields["cap_triggered"])
    if not isinstance(cap_triggered_value, bool):
        errors.append("model cap-triggered value is not boolean")

    if errors and not all(
        key in numeric for key in ("usd", "gbp", "cap")
    ):
        return {
            "cost_boundary": (
                "Governed paid-run cost is unavailable. Historical fallback "
                "material, when present, is not governed paid-cost evidence."
            ),
            "generated_at": generated_at,
            "governed_paid_cost": {
                "available": False,
                "gbp": None,
                "reason": (
                    "invalid-dedicated-paid-run"
                    if dedicated_authored or dedicated_published
                    else "missing-dedicated-paid-run"
                ),
                "usd": None,
            },
            "model_deployment_identity_available": (
                model_identity_available
            ),
            "model_identity": model_identity,
            "provider": provider,
            "paid_run_gate": {
                "authored_receipt_available": dedicated_authored,
                "public_projection_available": dedicated_published,
                "reason": (
                    "invalid-dedicated-paid-run"
                    if dedicated_authored or dedicated_published
                    else "missing-dedicated-paid-run"
                ),
                "status": "blocked",
            },
            "paid_run_governance_materials": dedicated_materials,
            "release_effect": "blocked-missing-model-cost-data",
            "run_id": run_id,
            "schema": "okf-model-cost-report.v1",
            "source": material(source_path),
            "source_available": True,
            "source_kind": source_kind,
            "validation_errors": errors,
        }

    usd = numeric["usd"]
    gbp = numeric["gbp"]
    cap_usd = numeric["cap"]
    accepted = (
        int(accepted_value)
        if isinstance(accepted_value, int)
        and not isinstance(accepted_value, bool)
        and accepted_value >= 0
        else 0
    )
    if accepted_value != accepted:
        errors.append(
            "accepted-assertion denominator is not a non-negative integer"
        )
    if usd > cap_usd:
        errors.append("recorded model cost exceeds the configured cap")
    if cap_usd != 250.0:
        errors.append("model cost cap is not the approved US$250")

    exchange_rate = cost.get("exchange_rate") or cost.get("fx")
    if usd > 0:
        if not isinstance(exchange_rate, dict) or not all(
            exchange_rate.get(key) not in (None, "")
            for key in ("source", "date", "rate")
        ):
            errors.append(
                "paid model cost lacks dated exchange-rate evidence"
            )

    if cap_triggered_value is True or usd > cap_usd:
        release_effect = "blocked-model-cost-cap"
    elif not model_identity_available:
        release_effect = "blocked-missing-exact-model-identity"
    elif errors:
        release_effect = "blocked-invalid-model-cost-data"
    elif source_kind != "dedicated-paid-run":
        release_effect = "blocked-missing-dedicated-paid-run"
    else:
        release_effect = "candidate"

    return {
        "accepted_assertions": accepted,
        "cap": {
            "cap_triggered": cap_triggered_value,
            "cap_usd": cap_usd,
            "remaining_usd": max(0.0, cap_usd - usd),
        },
        "cost_per_accepted_assertion": {
            "gbp": gbp / accepted if accepted else None,
            "usd": usd / accepted if accepted else None,
        },
        "cost_boundary": (
            "Exact governed paid-run API cost with dated currency evidence."
            if source_kind == "dedicated-paid-run"
            else (
                "Governed paid-run cost is unavailable. The numeric "
                "incremental_cost field is retained only as the historical "
                "Codex-assisted fallback observation and cannot satisfy the "
                "paid-run gate."
            )
        ),
        "generated_at": generated_at,
        "governed_paid_cost": {
            "available": source_kind == "dedicated-paid-run",
            "gbp": gbp if source_kind == "dedicated-paid-run" else None,
            "reason": (
                None
                if source_kind == "dedicated-paid-run"
                else "missing-dedicated-paid-run"
            ),
            "usd": usd if source_kind == "dedicated-paid-run" else None,
        },
        "historical_fallback_cost": (
            {
                "accepted_assertions": accepted,
                "gbp": gbp,
                "scope": "historical-codex-assisted-only",
                "usd": usd,
            }
            if source_kind == "historical-codex-assisted-fallback"
            else None
        ),
        "incremental_cost": {"gbp": gbp, "usd": usd},
        "model_identity": model_identity,
        "model_deployment_identity_available": model_identity_available,
        "provider": provider,
        "paid_run_gate": {
            "authored_receipt_available": dedicated_authored,
            "public_projection_available": dedicated_published,
            "reason": (
                None
                if release_effect == "candidate"
                else (
                    "invalid-dedicated-paid-run"
                    if dedicated_authored or dedicated_published
                    else "missing-dedicated-paid-run"
                )
            ),
            "status": (
                "passed" if release_effect == "candidate" else "blocked"
            ),
        },
        "paid_run_governance_materials": dedicated_materials,
        "notes": [
            cost.get("note", ""),
            "Codex subscription/task usage and the user's weekly allowance are not exposed as billable token data.",
            (
                "Historical Codex-assisted fallback spend is zero; governed "
                "paid-run USD/GBP cost remains unavailable."
                if source_kind == "historical-codex-assisted-fallback"
                else (
                    "No currency conversion was required because recorded "
                    "incremental OpenAI API spend is zero."
                    if usd == 0 and gbp == 0
                    else "A dated exchange-rate source is required before release."
                )
            ),
        ],
        "release_effect": release_effect,
        "run_id": run_id,
        "schema": "okf-model-cost-report.v1",
        "source": material(source_path),
        "source_kind": source_kind,
        "source_run_schema": source_schema,
        "usage": usage,
        "validation_errors": errors,
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


def build_readme(external_finalization: dict[str, Any]) -> bytes:
    lines = """# Release assurance

These deterministic candidate artefacts bind the implementation status,
immutable research evidence, release state, rights, dependencies, provenance,
constraints and model cost. They are projections, not substitutes for gates
which must still be executed on a frozen release candidate.

- [Implementation status](implementation-status.md)
- [Controlling requirements](controlling-requirements.md)
- [Clause-level traceability](implementation-traceability.json)
- [Implementation gap register](gap-register.json)
- [Fail-closed release state](release-state.json)
- [Projected release gates](release-gates.json)
- [Embedded GATE-12 release report](release-report.json)
- [Release policy v2](release-policy.json)
- [External finalization contract](external-finalization-contract.json)
- [External evidence workflow and finalizer hash](reproduction.json)
- [Immutable evidence manifest](evidence-manifest.json)
- [Claude observed-access test](claude-observed-access-test.json)
- [GUI helper crash stop receipt](helper-crash-stop-receipt.json)
- [SPDX 2.3 rights inventory](rights.spdx.json)
- [CycloneDX 1.6 SBOM](sbom.cdx.json)
- [Provenance](provenance.json)
- [Reproduction contract](reproduction.json)
- [Constraint report](constraint-report.json)
- [Model cost report](model-cost-report.json)
- [Assurance checksums](checksums.json)
""".splitlines()
    lines.extend(
        [
            "",
            "## External finalization schemas",
            "",
        ]
    )
    lines.extend(
        f"- [{Path(row['projected_path']).name}]({row['projected_path']})"
        for row in external_finalization["schemas"]
    )
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def build_files() -> tuple[dict[Path, bytes], list[str]]:
    policy = load(POLICY)
    generated_at = policy["generated_at"]
    evidence, evidence_errors = evidence_manifest(generated_at)
    status, status_errors = implementation_status(generated_at)
    external_finalization, schema_paths, external_errors = (
        external_finalization_projection(policy)
    )
    constraint_report = build_constraint_report(generated_at)
    constraint_body = render(constraint_report)
    model_cost = build_model_cost(generated_at)
    model_cost_body = render(model_cost)
    paid_governance = paid_publication.validate_governance_inputs()
    release_report, release_report_inputs, release_report_errors = (
        build_release_report(
            generated_at,
            constraint_report,
            constraint_body,
            model_cost,
            model_cost_body,
        )
    )
    release_report_body = render(release_report)
    traceability_accounted_for = (
        bool(status["requirements_accounted_for"]) and not status_errors
    )
    state, state_errors = release_state(
        generated_at,
        evidence_ok=not evidence_errors,
        traceability_accounted_for=traceability_accounted_for,
        release_report_material=projected_material(
            "release-report.json", release_report_body
        ),
        release_report_ok=not release_report_errors,
        external_finalization=external_finalization,
    )
    errors = (
        evidence_errors
        + status_errors
        + external_errors
        + list(paid_governance.errors)
        + release_report_errors
        + state_errors
    )

    input_paths = [
        POLICY,
        GATES,
        EXTERNAL_FINALIZATION_CONTRACT,
        FINALIZER,
        RELEASE_OBSERVATION_CONTROLLER,
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
        *paid_governance.materials,
        *schema_paths,
        *release_report_inputs,
    ]
    for enrichment in (
        HISTORICAL_MODEL_PUBLICATION,
        PAID_MODEL_RUN,
        PAID_MODEL_PUBLICATION,
    ):
        if enrichment.is_file() and not enrichment.is_symlink():
            input_paths.append(enrichment)
    for row in model_cost.get("paid_run_governance_materials", []):
        relative = row.get("path")
        if isinstance(relative, str):
            path = ROOT / relative
            if path.is_file() and not path.is_symlink():
                input_paths.append(path)
    inputs = [
        material(path)
        for path in dict.fromkeys(input_paths)
        if path.is_file()
    ]
    materials_digest = digest_bytes(
        "".join(f"{row['path']}:{row['sha256']}\n" for row in inputs).encode(
            "utf-8"
        )
    )
    provenance = {
        "builder": {
            "command": "python3 scripts/build_release_assurance.py",
            "name": "build_release_assurance.py",
            "version": "1.1.0",
        },
        "external_finalization": external_finalization,
        "generated_at": generated_at,
        "materials": inputs,
        "materials_digest": f"sha256:{materials_digest}",
        "paid_model_governance": {
            "authored_run": (
                material(PAID_MODEL_RUN)
                if PAID_MODEL_RUN.is_file()
                and not PAID_MODEL_RUN.is_symlink()
                else None
            ),
            "inputs": [
                material(path)
                for path in paid_governance.materials
                if path.is_file() and not path.is_symlink()
            ],
            "public_projection": (
                material(PAID_MODEL_PUBLICATION)
                if PAID_MODEL_PUBLICATION.is_file()
                and not PAID_MODEL_PUBLICATION.is_symlink()
                else None
            ),
            "release_gate": model_cost.get("paid_run_gate"),
            "status": (
                "validated-observed-run"
                if model_cost.get("release_effect") == "candidate"
                else "blocked-awaiting-valid-observed-run"
            ),
        },
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
        "external_finalization": {
            **external_finalization,
            "evidence_storage": (
                "All authorization, deployed-attempt and finalization receipts "
                "are regular files outside the frozen repository. Each output "
                "is write-once; verification reconstructs it from the same "
                "external evidence without changing the checkout or archive."
            ),
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
        Path("README.md"): build_readme(external_finalization),
        Path("controlling-requirements.md"): TRACEABILITY_SOURCE.read_bytes(),
        Path(
            "controlling-requirements.sha256"
        ): TRACEABILITY_SOURCE_DIGEST.read_bytes(),
        Path("constraint-report.json"): constraint_body,
        Path("claude-observed-access-test.json"): render(
            build_claude_access_test(generated_at)
        ),
        Path("evidence-manifest.json"): render(evidence),
        Path(
            "external-finalization-contract.json"
        ): EXTERNAL_FINALIZATION_CONTRACT.read_bytes(),
        Path("implementation-status.json"): render(status),
        Path("implementation-status.md"): build_status_markdown(status, state),
        Path("implementation-traceability.json"): TRACEABILITY.read_bytes(),
        Path("gap-register.json"): GAP_REGISTER.read_bytes(),
        Path(
            "github-operation-environment.json"
        ): GITHUB_OPERATION_ENVIRONMENT.read_bytes(),
        Path(
            "helper-crash-stop-receipt.json"
        ): HELPER_CRASH_STOP_RECEIPT.read_bytes(),
        Path("model-cost-report.json"): model_cost_body,
        Path("provenance.json"): render(provenance),
        Path("release-policy.json"): POLICY.read_bytes(),
        Path("release-report.json"): release_report_body,
        Path("release-gates.json"): render(
            {
                "gates": state["gates"],
                "generated_at": generated_at,
                "schema": load(GATES).get("schema"),
            }
        ),
        Path("release-state.json"): render(state),
        Path("reproduction.json"): render(reproduction),
        Path("rights.spdx.json"): render(build_spdx(generated_at, materials_digest)),
        Path("sbom.cdx.json"): render(build_sbom(generated_at, materials_digest)),
    }
    for row in external_finalization["schemas"]:
        source_path = ROOT / row["path"]
        files[Path(row["projected_path"])] = source_path.read_bytes()
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
