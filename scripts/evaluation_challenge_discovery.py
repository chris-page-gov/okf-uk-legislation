#!/usr/bin/env python3
"""Deterministic challenge discovery for corpus-navigation evaluation.

The release-evaluation runner deliberately keeps this protocol separate from
the answer generator.  It derives domain-separated seeds from immutable corpus
inputs, discovers mutation surfaces from each answer's actual structure, and
classifies the independent verifier's diagnostics into a stable taxonomy.

This module does not evaluate legal propositions.  Its only subject is the
fail-closed behaviour of the corpus-navigation answer/verifier contract.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


PROTOCOL_NAME = "okf-corpus-navigation-challenge-discovery"
PROTOCOL_VERSION = "2.0.0"
PASS_SCHEMA = "okf-evaluation-held-out-challenge-pass.v2"
CALIBRATION_SCHEMA = "okf-evaluation-challenge-calibration.v2"

FAILURE_TAXONOMY = {
    "schema-contract": {
        "severity": "non-critical-detected-defence",
        "description": "The answer no longer satisfies the closed JSON Schema contract.",
    },
    "answer-identity": {
        "severity": "non-critical-detected-defence",
        "description": "The answer is no longer bound to the selected question.",
    },
    "snapshot-integrity": {
        "severity": "non-critical-detected-defence",
        "description": "The corpus or temporal snapshot binding changed.",
    },
    "scope-boundary": {
        "severity": "non-critical-detected-defence",
        "description": "The corpus-navigation/legal-task assurance boundary changed.",
    },
    "source-set-integrity": {
        "severity": "non-critical-detected-defence",
        "description": "The exact required source set changed.",
    },
    "source-metadata-integrity": {
        "severity": "non-critical-detected-defence",
        "description": "A source-native metadata proposition changed.",
    },
    "access-evidence-integrity": {
        "severity": "non-critical-detected-defence",
        "description": "A frozen route-observation proposition changed.",
    },
    "citation-integrity": {
        "severity": "non-critical-detected-defence",
        "description": "A citation reference, path, scope, URL or digest changed.",
    },
    "proposition-integrity": {
        "severity": "non-critical-detected-defence",
        "description": "An expected proposition or its declared gold value changed.",
    },
    "unclassified-diagnostic": {
        "severity": "critical-protocol-failure",
        "description": "The verifier emitted a diagnostic outside the pinned taxonomy.",
    },
}


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def derive_seed_commitment(
    pass_id: str,
    immutable_context: dict[str, str],
) -> dict[str, Any]:
    """Derive a reproducible, domain-separated seed without answer output.

    The context is limited to immutable corpus/evidence/verifier commitments.
    Generated answers, mutation results and previous pass results are excluded,
    so neither the answer generator nor an earlier challenge outcome chooses a
    later pass's seed.
    """

    if not pass_id or not immutable_context:
        raise ValueError("challenge seed requires a pass id and immutable context")
    invalid = [
        key
        for key, value in immutable_context.items()
        if not isinstance(key, str)
        or not key
        or not isinstance(value, str)
        or not value
    ]
    if invalid:
        raise ValueError(f"invalid challenge seed context keys: {sorted(invalid)}")
    material = {
        "protocol": PROTOCOL_NAME,
        "protocol_version": PROTOCOL_VERSION,
        "domain": "held-out-challenge-seed",
        "pass_id": pass_id,
        "immutable_context": dict(sorted(immutable_context.items())),
    }
    seed = sha256_bytes(canonical_json(material))
    return {
        "method": "sha256-domain-separated-immutable-input-commitment",
        "pass_id": pass_id,
        "protocol": PROTOCOL_NAME,
        "protocol_version": PROTOCOL_VERSION,
        "immutable_context": material["immutable_context"],
        "seed_sha256": seed,
        "answer_outputs_excluded": True,
        "previous_pass_results_excluded": True,
        "secret_or_random_seed": False,
    }


def _rank(seed: str, value: Any) -> str:
    return sha256_bytes(seed.encode("ascii") + b"\0" + canonical_json(value))


def _spec(
    operator: str,
    surface: str,
    target_categories: list[str],
    operation: dict[str, Any],
) -> dict[str, Any]:
    identity = {
        "operator": operator,
        "surface": surface,
        "target_categories": sorted(target_categories),
        "operation": operation,
    }
    return {
        "id": f"mutation-{sha256_bytes(canonical_json(identity))[:16]}",
        **identity,
    }


def discover_mutation_specs(
    answer: dict[str, Any],
    *,
    limitation_marker: str,
) -> list[dict[str, Any]]:
    """Discover mutation candidates from the supplied answer structure.

    Candidate paths and values come from the answer under test.  The protocol
    does not replay a single fixed mutation list against every row.
    """

    specs: list[dict[str, Any]] = []

    for field in (
        "citations",
        "propositions",
        "temporal_context",
        "limitations",
        "independent_verification",
    ):
        if field in answer:
            specs.append(
                _spec(
                    "delete-required-field",
                    field,
                    ["schema-contract"],
                    {"kind": "delete", "path": [field]},
                )
            )

    scalar_replacements = (
        (
            "question_id",
            "replace-question-identity",
            "answer-identity",
            "challenge-question-not-in-suite",
        ),
        (
            "corpus_snapshot",
            "replace-corpus-snapshot",
            "snapshot-integrity",
            "challenge-snapshot-not-in-corpus",
        ),
        (
            "evaluation_scope",
            "replace-evaluation-scope",
            "scope-boundary",
            "legal-answer",
        ),
        (
            "underlying_legal_task_status",
            "replace-legal-task-status",
            "scope-boundary",
            "evaluated-without-qualified-review",
        ),
    )
    for field, operator, category, replacement in scalar_replacements:
        if field in answer:
            specs.append(
                _spec(
                    operator,
                    field,
                    [category],
                    {
                        "kind": "replace",
                        "path": [field],
                        "value": replacement,
                    },
                )
            )

    temporal = answer.get("temporal_context")
    if isinstance(temporal, dict) and "snapshot" in temporal:
        specs.append(
            _spec(
                "replace-temporal-snapshot",
                "temporal_context.snapshot",
                ["snapshot-integrity"],
                {
                    "kind": "replace",
                    "path": ["temporal_context", "snapshot"],
                    "value": "challenge-temporal-snapshot",
                },
            )
        )

    limitations = answer.get("limitations")
    if (
        isinstance(limitations, list)
        and limitation_marker in limitations
    ):
        specs.append(
            _spec(
                "remove-scope-limitation",
                "limitations",
                ["scope-boundary"],
                {
                    "kind": "remove-value",
                    "path": ["limitations"],
                    "value": limitation_marker,
                },
            )
        )

    propositions = answer.get("propositions")
    if isinstance(propositions, list):
        for index, proposition in enumerate(propositions):
            if not isinstance(proposition, dict):
                continue
            proposition_id = proposition.get("id")
            surface = f"propositions[{index}]"
            specs.append(
                _spec(
                    "delete-discovered-proposition",
                    surface,
                    ["proposition-integrity", "schema-contract"],
                    {
                        "kind": "delete",
                        "path": ["propositions", index],
                    },
                )
            )
            if proposition_id == "required-source-set":
                specs.append(
                    _spec(
                        "replace-required-source-set",
                        f"{surface}.value",
                        ["source-set-integrity", "proposition-integrity"],
                        {
                            "kind": "replace",
                            "path": ["propositions", index, "value"],
                            "value": ["SRC-CHALLENGE-UNKNOWN"],
                        },
                    )
                )
            elif isinstance(proposition_id, str) and proposition_id.startswith(
                "source-"
            ):
                value = proposition.get("value")
                if isinstance(value, dict):
                    for field in sorted(value):
                        original = value[field]
                        if isinstance(original, str):
                            replacement: Any = f"{original} [challenge]"
                        elif isinstance(original, list):
                            replacement = [*original, "challenge-value"]
                        elif original is None:
                            replacement = "challenge-value"
                        else:
                            continue
                        specs.append(
                            _spec(
                                "alter-discovered-source-field",
                                f"{surface}.value.{field}",
                                [
                                    "source-metadata-integrity",
                                    "proposition-integrity",
                                ],
                                {
                                    "kind": "replace",
                                    "path": [
                                        "propositions",
                                        index,
                                        "value",
                                        field,
                                    ],
                                    "value": replacement,
                                },
                            )
                        )
            elif isinstance(proposition_id, str) and proposition_id.startswith(
                "access-"
            ):
                value = proposition.get("value")
                if isinstance(value, list):
                    replacement = value[1:] if value else [{"challenge": True}]
                    specs.append(
                        _spec(
                            "alter-discovered-access-observations",
                            f"{surface}.value",
                            [
                                "access-evidence-integrity",
                                "proposition-integrity",
                            ],
                            {
                                "kind": "replace",
                                "path": ["propositions", index, "value"],
                                "value": replacement,
                            },
                        )
                    )
            citation_ids = proposition.get("citation_ids")
            if isinstance(citation_ids, list) and citation_ids:
                specs.append(
                    _spec(
                        "replace-discovered-citation-reference",
                        f"{surface}.citation_ids",
                        ["citation-integrity", "proposition-integrity"],
                        {
                            "kind": "replace",
                            "path": ["propositions", index, "citation_ids"],
                            "value": ["citation-challenge-missing"],
                        },
                    )
                )

    citations = answer.get("citations")
    if isinstance(citations, list):
        for index, citation in enumerate(citations):
            if not isinstance(citation, dict):
                continue
            surface = f"citations[{index}]"
            specs.append(
                _spec(
                    "delete-discovered-citation",
                    surface,
                    ["citation-integrity", "schema-contract"],
                    {
                        "kind": "delete",
                        "path": ["citations", index],
                    },
                )
            )
            if "evidence_hash" in citation:
                specs.append(
                    _spec(
                        "corrupt-discovered-evidence-hash",
                        f"{surface}.evidence_hash",
                        ["citation-integrity"],
                        {
                            "kind": "replace",
                            "path": ["citations", index, "evidence_hash"],
                            "value": "0" * 64,
                        },
                    )
                )
            for field in ("evidence_path", "evidence_member"):
                if field in citation:
                    specs.append(
                        _spec(
                            "replace-discovered-evidence-location",
                            f"{surface}.{field}",
                            ["citation-integrity"],
                            {
                                "kind": "replace",
                                "path": ["citations", index, field],
                                "value": "challenge/missing-evidence.json",
                            },
                        )
                    )
            if "evidence_scope" in citation:
                specs.append(
                    _spec(
                        "replace-discovered-evidence-scope",
                        f"{surface}.evidence_scope",
                        ["citation-integrity", "schema-contract"],
                        {
                            "kind": "replace",
                            "path": ["citations", index, "evidence_scope"],
                            "value": "untrusted-network",
                        },
                    )
                )
            if isinstance(citation.get("url"), str):
                specs.append(
                    _spec(
                        "downgrade-discovered-citation-url",
                        f"{surface}.url",
                        ["citation-integrity", "schema-contract"],
                        {
                            "kind": "replace",
                            "path": ["citations", index, "url"],
                            "value": "http://challenge.invalid/evidence",
                        },
                    )
                )

    specs.append(
        _spec(
            "add-undeclared-top-level-field",
            "challenge_extra",
            ["schema-contract"],
            {
                "kind": "replace",
                "path": ["challenge_extra"],
                "value": True,
            },
        )
    )
    unique = {spec["id"]: spec for spec in specs}
    return [unique[identifier] for identifier in sorted(unique)]


def select_mutation_specs(
    answer: dict[str, Any],
    *,
    seed: str,
    limitation_marker: str,
    case_budget: int,
) -> list[dict[str, Any]]:
    """Choose a seed-specific, category-covering property-test portfolio."""

    if case_budget <= 0:
        raise ValueError("challenge case budget must be positive")
    candidates = discover_mutation_specs(
        answer,
        limitation_marker=limitation_marker,
    )
    ranked = sorted(candidates, key=lambda row: _rank(seed, row))
    selected: dict[str, dict[str, Any]] = {}
    categories = sorted(
        {
            category
            for row in candidates
            for category in row["target_categories"]
            if category != "schema-contract"
        }
    )
    for category in categories:
        candidate = next(
            (
                row
                for row in ranked
                if category in row["target_categories"]
            ),
            None,
        )
        if candidate is not None:
            selected[candidate["id"]] = candidate
    for row in ranked:
        if len(selected) >= case_budget:
            break
        selected[row["id"]] = row
    return sorted(selected.values(), key=lambda row: _rank(seed, row))


def apply_mutation(
    answer: dict[str, Any],
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Apply one serializable mutation specification to a deep copy."""

    mutated = copy.deepcopy(answer)
    operation = spec["operation"]
    path = operation["path"]
    if not isinstance(path, list) or not path:
        raise ValueError("mutation path must be a non-empty list")
    parent: Any = mutated
    for component in path[:-1]:
        parent = parent[component]
    leaf = path[-1]
    kind = operation["kind"]
    if kind == "delete":
        if isinstance(parent, list):
            del parent[leaf]
        else:
            del parent[leaf]
    elif kind == "replace":
        parent[leaf] = copy.deepcopy(operation["value"])
    elif kind == "remove-value":
        parent[leaf] = [
            value
            for value in parent[leaf]
            if value != operation["value"]
        ]
    else:
        raise ValueError(f"unsupported mutation kind: {kind}")
    return mutated


def classify_diagnostic(diagnostic: str) -> str:
    """Classify one independent-verifier failure without using mutation intent."""

    value = str(diagnostic)
    lowered = value.lower()
    if (
        "question-identity" in lowered
        or "question_id" in lowered
        or "question-id" in lowered
    ):
        return "answer-identity"
    if (
        "corpus-snapshot" in lowered
        or "corpus_snapshot" in lowered
        or "temporal_context/snapshot" in lowered
    ):
        return "snapshot-integrity"
    if any(
        token in lowered
        for token in (
            "scope-boundary",
            "evaluation-scope",
            "evaluation_scope",
            "underlying-legal-task",
            "underlying_legal_task",
            "limitations",
        )
    ):
        return "scope-boundary"
    if "required-source-set" in lowered:
        return "source-set-integrity"
    if "source-metadata" in lowered:
        return "source-metadata-integrity"
    if "direct-access-evidence" in lowered or "access-evidence" in lowered:
        return "access-evidence-integrity"
    if any(
        token in lowered
        for token in (
            "citation",
            "citations",
            "evidence_hash",
            "evidence_path",
            "evidence_member",
            "evidence_scope",
        )
    ):
        return "citation-integrity"
    if any(
        token in lowered
        for token in (
            "declared-gold-match",
            "proposition",
            "propositions",
        )
    ):
        return "proposition-integrity"
    if value.startswith("jsonschema:") or value in {
        "answer-not-object",
        "required-answer-fields-missing",
    }:
        return "schema-contract"
    return "unclassified-diagnostic"


def classify_diagnostics(diagnostics: list[str]) -> list[dict[str, str]]:
    return [
        {
            "diagnostic": diagnostic,
            "category": classify_diagnostic(diagnostic),
            "severity": FAILURE_TAXONOMY[
                classify_diagnostic(diagnostic)
            ]["severity"],
        }
        for diagnostic in sorted(set(diagnostics))
    ]
