#!/usr/bin/env python3
"""Build the corpus-bound Whole-Law OKF release evaluation.

The research questions and the original legislation questions remain historical
non-gold baselines. This generator creates complete structural coverage across
the researched personas, tasks and source classes without falsely claiming
independent legal verification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research" / "whole-law-okf-research"
OUTPUT = ROOT / "whole-law" / "evaluation"
GENERATED_AT = "2026-07-25T22:00:00Z"
CORPUS_SNAPSHOT = "whole-law-2026-07-25+legislation-2026-07-11T18:00:00Z"
TEMPORAL_TASKS = {"T02", "T03", "T05", "T06", "T07", "T13"}
ACCESS_STATES = {"available", "partial", "restricted", "unavailable", "planned"}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def access_state(source: dict[str, Any]) -> str:
    states = source_access_states(source)
    if "available" in states:
        return "available"
    if "partial" in states:
        return "partial"
    if "restricted" in states:
        return "restricted"
    if "unavailable" in states:
        return "unavailable"
    return "planned"


def source_access_states(source: dict[str, Any]) -> set[str]:
    mapping = {
        "verified working": "available",
        "documented but not tested": "partial",
        "authenticated or restricted": "restricted",
        "unavailable": "unavailable",
    }
    states = {
        mapping[row["status"]]
        for row in source.get("access_methods", [])
        if row.get("status") in mapping
    }
    return states or {"planned"}


def source_url(source: dict[str, Any]) -> str | None:
    samples = source.get("sample_work_and_passage_urls", [])
    if samples:
        return samples[0]
    methods = source.get("access_methods", [])
    return methods[0]["url"] if methods else None


def temporal_difficulty(task_id: str) -> str:
    return (
        "live-reconciliation-or-point-in-time"
        if task_id in TEMPORAL_TASKS
        else "snapshot-bounded"
    )


def combinations_digest(values: set[tuple[str, ...]]) -> str:
    return hashlib.sha256(
        render([list(value) for value in sorted(values)]).encode("utf-8")
    ).hexdigest()


def coverage_receipt(
    required: set[tuple[str, ...]],
    covered: set[tuple[str, ...]],
) -> dict[str, Any]:
    missing = required - covered
    return {
        "required": len(required),
        "covered": len(required & covered),
        "missing": [list(value) for value in sorted(missing)],
        "extra": len(covered - required),
        "required_sha256": combinations_digest(required),
        "covered_required_sha256": combinations_digest(required & covered),
        "passed": not missing,
    }


def source_strata(sources: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        "jurisdictions": sorted(
            {
                value
                for source in sources
                for value in source.get("jurisdictions", [])
            }
            or {"United Kingdom"}
        ),
        "access_states": sorted(
            {
                value
                for source in sources
                for value in source_access_states(source)
            }
        ),
        "authority_classes": sorted(
            {
                value
                for source in sources
                for value in source.get("authority_classes", [])
            }
            or {"unknown"}
        ),
    }


def question(
    identifier: str,
    persona: dict[str, Any],
    task: dict[str, Any],
    source_classes: list[str],
    sources: list[dict[str, Any]],
    mapping: dict[str, Any] | None,
    kind: str,
    access_override: str | None = None,
    sample_override: str | None = None,
) -> dict[str, Any]:
    primary = sources[0]
    class_labels = ", ".join(source_classes)
    sample = sample_override if sample_override is not None else source_url(primary)
    professional_escalation = bool(mapping and mapping.get("professional_escalation"))
    strata = source_strata(sources)
    if access_override:
        strata["access_states"] = [access_override]
    difficulty = temporal_difficulty(task["id"])
    risk = (
        "high-risk-three-way"
        if professional_escalation and task["id"] in TEMPORAL_TASKS
        else "pairwise-coverage"
    )
    prompt = (
        f"As {persona['label']}, perform “{task['label']}” using the "
        f"{CORPUS_SNAPSHOT} snapshot and source class(es) {class_labels}. "
        f"Start with {primary['title']}"
    )
    if sample:
        prompt += f" at {sample}"
    prompt += (
        ". Use source-native identifiers; distinguish binding, persuasive, "
        "derived and model-assisted material; state currency, access and "
        "coverage limitations; and cite every material proposition."
    )
    expected = [
        f"The response identifies the relevant {task['label'].lower()} outcome and its limits.",
        "Every source is identified by its source-native identifier and authority class.",
        "The answer states jurisdiction, relevant temporal context, access state and corpus snapshot.",
        "Any missing, restricted, stale or partial evidence is disclosed rather than inferred away.",
    ]
    if mapping:
        expected.append(mapping["definition_of_success"])
    return {
        "id": identifier,
        "kind": kind,
        "prompt": prompt,
        "persona_id": persona["id"],
        "persona_label": persona["label"],
        "task_id": task["id"],
        "task_label": task["label"],
        "source_class_ids": sorted(set(source_classes)),
        "required_source_ids": [row["id"] for row in sources],
        "sample_url": sample,
        "jurisdiction": primary.get("jurisdictions", ["United Kingdom"])[0],
        "access_state": access_override or access_state(primary),
        "authority_class": (
            (mapping or {}).get("required_authority_classes", [])
            or primary.get("authority_classes", [])
            or ["unknown"]
        )[0],
        "gold_status": "non-gold-baseline",
        "verification_status": "requires-independent-domain-review",
        "independent_verification": {
            "status": "not-performed",
            "reviewer_role": "qualified domain reviewer independent of suite generation",
            "evidence": [],
        },
        "corpus_snapshot": CORPUS_SNAPSHOT,
        "evidence_binding": {
            "source_register_path": (
                "../../research/whole-law-okf-research/source-register.json"
            ),
            "source_register_sha256": digest(RESEARCH / "source-register.json"),
            "source_record_ids": [row["id"] for row in sources],
            "frozen_access_evidence": "required-and-bound-by-release-execution",
            "corpus_snapshot": CORPUS_SNAPSHOT,
        },
        "strata": {
            **strata,
            "temporal_difficulty": difficulty,
        },
        "temporal_context": {
            "mode": task["default_currency_tolerance"],
            "snapshot": CORPUS_SNAPSHOT,
            "live_check_required": task["id"] in TEMPORAL_TASKS,
            "difficulty": difficulty,
        },
        "expected_proposition_status": (
            "structural-and-disclosure-requirements-only-not-legal-gold"
        ),
        "expected_propositions": expected,
        "near_miss_rules": (
            (mapping or {}).get("likely_failure_modes")
            or task.get("failure_modes", [])
        ),
        "citation_expectations": [
            "Direct canonical source or selected-passage URL",
            "Source-native identifier and publisher/owner",
            "Retrieval time and immutable evidence hash where available",
            "Pinpoint or smallest authoritative passage for each material proposition",
            "Authority, jurisdiction, version and access/coverage status",
        ],
        "hard_failures": [
            "invented authority or citation",
            "material proposition without a resolvable citation",
            "wrong jurisdiction or version",
            "derived/model-assisted assertion presented as official",
            "unsupported completeness claim",
            "concealed inaccessible or stale evidence",
        ],
        "coverage_stratum": risk,
        "high_risk_reason": (
            "professional escalation combined with a temporal task and source class"
            if risk == "high-risk-three-way"
            else None
        ),
        "professional_review_required": professional_escalation,
    }


def build_coverage_contract(
    questions: list[dict[str, Any]],
    matrix: dict[str, Any],
    taxonomy: dict[str, Any],
    register: dict[str, Any],
) -> dict[str, Any]:
    """Prove coverage against independent research applicability sets.

    Pair requirements come from the persona/task mappings and source register,
    not from whichever combinations happen to occur in the generated suite.
    This makes the coverage claim fail closed if a question or source binding
    is removed.
    """

    sources = {row["id"]: row for row in register["records"]}
    expected_dimensions: dict[str, set[str]] = {
        "personas": {row["id"] for row in matrix["personas"]},
        "tasks": {row["id"] for row in matrix["tasks"]},
        "source_classes": {row["id"] for row in taxonomy["classes"]},
        "jurisdictions": {
            value
            for row in register["records"]
            for value in row.get("jurisdictions", [])
        },
        "access_states": set(ACCESS_STATES),
        "authority_classes": {
            row["id"] for row in taxonomy["authority_classes"]
        },
        "temporal_difficulties": {
            temporal_difficulty(row["id"]) for row in matrix["tasks"]
        },
    }
    covered_dimensions: dict[str, set[str]] = {
        "personas": {row["persona_id"] for row in questions},
        "tasks": {row["task_id"] for row in questions},
        "source_classes": {
            value for row in questions for value in row["source_class_ids"]
        },
        "jurisdictions": {
            value for row in questions for value in row["strata"]["jurisdictions"]
        },
        "access_states": {
            value for row in questions for value in row["strata"]["access_states"]
        },
        "authority_classes": {
            value
            for row in questions
            for value in row["strata"]["authority_classes"]
        },
        "temporal_difficulties": {
            row["strata"]["temporal_difficulty"] for row in questions
        },
    }

    expected_pairs: dict[str, set[tuple[str, str]]] = {
        "persona_task": set(),
        "persona_source_class": set(),
        "task_source_class": set(),
        "source_class_jurisdiction": set(),
        "source_class_access_state": set(),
        "source_class_authority_class": set(),
        "jurisdiction_access_state": set(),
        "jurisdiction_authority_class": set(),
        "access_state_authority_class": set(),
        "task_temporal_difficulty": {
            (row["id"], temporal_difficulty(row["id"]))
            for row in matrix["tasks"]
        },
    }
    for mapping in matrix["mappings"]:
        persona_id = mapping["persona_id"]
        task_id = mapping["task_id"]
        expected_pairs["persona_task"].add((persona_id, task_id))
        for class_id in mapping["required_source_classes"]:
            expected_pairs["persona_source_class"].add((persona_id, class_id))
            expected_pairs["task_source_class"].add((task_id, class_id))
    for source in register["records"]:
        states = source_access_states(source)
        for class_id in source["source_classes"]:
            for jurisdiction in source.get("jurisdictions", []):
                expected_pairs["source_class_jurisdiction"].add(
                    (class_id, jurisdiction)
                )
            for state in states:
                expected_pairs["source_class_access_state"].add(
                    (class_id, state)
                )
            for authority in source.get("authority_classes", []):
                expected_pairs["source_class_authority_class"].add(
                    (class_id, authority)
                )
        for jurisdiction in source.get("jurisdictions", []):
            for state in states:
                expected_pairs["jurisdiction_access_state"].add(
                    (jurisdiction, state)
                )
            for authority in source.get("authority_classes", []):
                expected_pairs["jurisdiction_authority_class"].add(
                    (jurisdiction, authority)
                )
        for authority in source.get("authority_classes", []):
            for state in states:
                expected_pairs["access_state_authority_class"].add(
                    (state, authority)
                )
    # Planned is a deliberately explicit absence case rather than a property of
    # an already tested source record.
    for row in questions:
        if row["kind"] == "access-state" and row["access_state"] == "planned":
            for class_id in row["source_class_ids"]:
                expected_pairs["source_class_access_state"].add(
                    (class_id, "planned")
                )

    covered_pairs: dict[str, set[tuple[str, str]]] = {
        name: set() for name in expected_pairs
    }
    for row in questions:
        persona_id = row["persona_id"]
        task_id = row["task_id"]
        covered_pairs["persona_task"].add((persona_id, task_id))
        covered_pairs["task_temporal_difficulty"].add(
            (task_id, row["strata"]["temporal_difficulty"])
        )
        for class_id in row["source_class_ids"]:
            covered_pairs["persona_source_class"].add((persona_id, class_id))
            covered_pairs["task_source_class"].add((task_id, class_id))
        for source_id in row["required_source_ids"]:
            source = sources[source_id]
            states = (
                {row["access_state"]}
                if row["kind"] == "access-state"
                else source_access_states(source)
            )
            applicable_classes = set(source["source_classes"]) & set(
                row["source_class_ids"]
            )
            for class_id in applicable_classes:
                for jurisdiction in source.get("jurisdictions", []):
                    covered_pairs["source_class_jurisdiction"].add(
                        (class_id, jurisdiction)
                    )
                for state in states:
                    covered_pairs["source_class_access_state"].add(
                        (class_id, state)
                    )
                for authority in source.get("authority_classes", []):
                    covered_pairs["source_class_authority_class"].add(
                        (class_id, authority)
                    )
            for jurisdiction in source.get("jurisdictions", []):
                for state in states:
                    covered_pairs["jurisdiction_access_state"].add(
                        (jurisdiction, state)
                    )
                for authority in source.get("authority_classes", []):
                    covered_pairs["jurisdiction_authority_class"].add(
                        (jurisdiction, authority)
                    )
            for authority in source.get("authority_classes", []):
                for state in states:
                    covered_pairs["access_state_authority_class"].add(
                        (state, authority)
                    )

    expected_high_risk = {
        (mapping["persona_id"], mapping["task_id"], class_id)
        for mapping in matrix["mappings"]
        if mapping.get("professional_escalation")
        and mapping["task_id"] in TEMPORAL_TASKS
        for class_id in mapping["required_source_classes"]
    }
    covered_high_risk = {
        (row["persona_id"], row["task_id"], class_id)
        for row in questions
        if row["coverage_stratum"] == "high-risk-three-way"
        for class_id in row["source_class_ids"]
    }

    dimension_receipts = {
        name: {
            "required": len(required),
            "covered": len(required & covered_dimensions[name]),
            "missing": sorted(required - covered_dimensions[name]),
            "extra": len(covered_dimensions[name] - required),
            "required_sha256": combinations_digest(
                {(value,) for value in required}
            ),
            "covered_required_sha256": combinations_digest(
                {(value,) for value in required & covered_dimensions[name]}
            ),
            "passed": required <= covered_dimensions[name],
        }
        for name, required in expected_dimensions.items()
    }
    pair_receipts = {
        name: coverage_receipt(required, covered_pairs[name])
        for name, required in expected_pairs.items()
    }
    high_risk_receipt = coverage_receipt(
        expected_high_risk,
        covered_high_risk,
    )
    return {
        "method": (
            "Applicable pairs are derived independently from the researched "
            "persona/task mappings and source-register records. High-risk "
            "triples are every professional-escalation temporal mapping crossed "
            "with its required source classes."
        ),
        "dimensions": dimension_receipts,
        "pairwise": pair_receipts,
        "high_risk_three_way": high_risk_receipt,
        "complete": (
            all(row["passed"] for row in dimension_receipts.values())
            and all(row["passed"] for row in pair_receipts.values())
            and high_risk_receipt["passed"]
        ),
    }


def build() -> dict[Path, bytes]:
    matrix = load(RESEARCH / "persona-task-matrix.json")
    taxonomy = load(RESEARCH / "legal-source-taxonomy.json")
    register = load(RESEARCH / "source-register.json")
    research_questions = load(RESEARCH / "whole-law-evaluation-questions.json")
    legislation_questions = load(ROOT / "evaluation" / "legislation" / "questions.json")

    personas = {row["id"]: row for row in matrix["personas"]}
    tasks = {row["id"]: row for row in matrix["tasks"]}
    classes = {row["id"]: row for row in taxonomy["classes"]}
    sources = {row["id"]: row for row in register["records"]}
    by_class: dict[str, list[dict[str, Any]]] = {
        class_id: [
            row for row in register["records"]
            if class_id in row["source_classes"]
        ]
        for class_id in classes
    }

    questions = []
    for mapping in matrix["mappings"]:
        candidates = [
            sources[source_id]
            for source_id in mapping["candidate_source_ids"]
            if source_id in sources
        ]
        if not candidates:
            candidates = by_class[mapping["required_source_classes"][0]]
        questions.append(question(
            f"WLR-PT-{mapping['persona_id']}-{mapping['task_id']}",
            personas[mapping["persona_id"]],
            tasks[mapping["task_id"]],
            mapping["required_source_classes"],
            candidates,
            mapping,
            "persona-task",
        ))

    for class_id in sorted(classes):
        source_rows = by_class[class_id]
        candidate_personas = [
            row for row in matrix["personas"]
            if class_id in row["primary_source_classes"]
        ]
        persona = candidate_personas[0] if candidate_personas else personas["P12"]
        task_id = persona["task_ids"][0]
        questions.append(question(
            f"WLR-SC-{class_id}",
            persona,
            tasks[task_id],
            [class_id],
            source_rows,
            None,
            "source-class-coverage",
        ))

    status_mapping = {
        "available": "verified working",
        "partial": "documented but not tested",
        "restricted": "authenticated or restricted",
        "unavailable": "unavailable",
    }
    for access_label, research_status in status_mapping.items():
        source, method = next(
            (source, method)
            for source in register["records"]
            for method in source["access_methods"]
            if method["status"] == research_status
        )
        questions.append(question(
            f"WLR-ACCESS-{access_label.upper()}",
            personas["P12"],
            tasks["T17"],
            [source["source_classes"][0]],
            [source],
            None,
            "access-state",
            access_override=access_label,
            sample_override=method["url"],
        ))
    planned_source = register["records"][0]
    questions.append(question(
        "WLR-ACCESS-PLANNED",
        personas["P12"],
        tasks["T17"],
        [planned_source["source_classes"][0]],
        [planned_source],
        None,
        "access-state",
        access_override="planned",
        sample_override="",
    ))

    persona_counts = Counter(row["persona_id"] for row in questions)
    task_counts = Counter(row["task_id"] for row in questions)
    class_counts = Counter(
        class_id
        for row in questions
        for class_id in row["source_class_ids"]
    )
    jurisdiction_counts = Counter(
        value
        for row in questions
        for value in row["strata"]["jurisdictions"]
    )
    access_counts = Counter(
        value
        for row in questions
        for value in row["strata"]["access_states"]
    )
    authority_counts = Counter(
        value
        for row in questions
        for value in row["strata"]["authority_classes"]
    )
    temporal_counts = Counter(
        row["strata"]["temporal_difficulty"] for row in questions
    )
    coverage_contract = build_coverage_contract(
        questions,
        matrix,
        taxonomy,
        register,
    )
    coverage = {
        "schema": "okf-evaluation-coverage.v2",
        "generated_at": GENERATED_AT,
        "corpus_snapshot": CORPUS_SNAPSHOT,
        "question_count": len(questions),
        "expected": {
            "personas": len(personas),
            "tasks": len(tasks),
            "source_classes": len(classes),
        },
        "represented": {
            "personas": len(persona_counts),
            "tasks": len(task_counts),
            "source_classes": len(class_counts),
        },
        "counts": {
            "personas": dict(sorted(persona_counts.items())),
            "tasks": dict(sorted(task_counts.items())),
            "source_classes": dict(sorted(class_counts.items())),
            "jurisdictions": dict(sorted(jurisdiction_counts.items())),
            "access_states": dict(sorted(access_counts.items())),
            "authority_classes": dict(sorted(authority_counts.items())),
            "temporal_difficulties": dict(sorted(temporal_counts.items())),
            "strata": dict(sorted(Counter(row["coverage_stratum"] for row in questions).items())),
        },
        "coverage_contract": coverage_contract,
        "complete": (
            set(persona_counts) == set(personas)
            and set(task_counts) == set(tasks)
            and set(class_counts) == set(classes)
            and coverage_contract["complete"]
        ),
    }
    release = {
        "schema": "okf-evaluation.v2",
        "generated_at": GENERATED_AT,
        "corpus_snapshot": CORPUS_SNAPSHOT,
        "corpus_binding": {
            "legislation_snapshot": "legislation-work-index-2026-07-11T18:00:00Z",
            "whole_law_snapshot": "whole-law-2026-07-25",
            "source_register_sha256": digest(RESEARCH / "source-register.json"),
            "persona_task_matrix_sha256": digest(
                RESEARCH / "persona-task-matrix.json"
            ),
            "legal_source_taxonomy_sha256": digest(
                RESEARCH / "legal-source-taxonomy.json"
            ),
        },
        "gold_status": "non-gold-baseline",
        "release_gate_status": (
            "blocked-pending-independent-legal-and-deployed-access-assurance"
        ),
        "assurance_boundary": {
            "expected_propositions": (
                "structural and disclosure requirements, not verified legal answers"
            ),
            "independent_domain_review": "not performed",
            "qualified_practitioner_sign_off": "not performed",
            "held_out_answer_passes": 0,
            "legal_answer_score": None,
        },
        "questions": questions,
    }
    historical = {
        "schema": "okf-evaluation-historical-baselines.v1",
        "generated_at": GENERATED_AT,
        "baselines": [
            {
                "id": "legislation-100",
                "questions": len(legislation_questions["questions"]),
                "path": "../../evaluation/legislation/questions.json",
                "sha256": digest(ROOT / "evaluation" / "legislation" / "questions.json"),
                "gold_status": "non-gold-baseline",
                "immutable_source": True,
                "verification_status": "historical-structure-only",
            },
            {
                "id": "whole-law-research-360",
                "questions": len(research_questions["questions"]),
                "path": "../../research/whole-law-okf-research/whole-law-evaluation-questions.json",
                "sha256": digest(RESEARCH / "whole-law-evaluation-questions.json"),
                "gold_status": "non-gold-baseline",
                "immutable_source": True,
                "verification_status": "historical-structure-only",
            },
        ],
    }
    access_suite = {
        "schema": "okf-adversarial-access-suite.v2",
        "generated_at": GENERATED_AT,
        "corpus_snapshot": CORPUS_SNAPSHOT,
        "origin": "Claude 4.8 access journey, normalized into executable release requirements",
        "origin_evidence": [
            {
                "path": "../../research/Legislation-govuk Claude 4.8 run.docx",
                "sha256": digest(
                    ROOT / "research" / "Legislation-govuk Claude 4.8 run.docx"
                ),
                "role": "immutable original evaluation",
            },
            {
                "path": "../../research/claude-4.8-evaluation-transcript.md",
                "sha256": digest(
                    ROOT / "research" / "claude-4.8-evaluation-transcript.md"
                ),
                "role": "normalized text projection",
            },
        ],
        "assurance_boundary": (
            "The deterministic runner verifies local publication contracts and "
            "frozen evidence only. Public HTTP behaviour, compatibility-host "
            "redirects and Explorer browser behaviour require separate deployed "
            "journey receipts and remain blocked here."
        ),
        "scenarios": [
            {
                "id": "CLAUDE-ACCESS-01",
                "name": "Repository and canonical descriptor discovery",
                "expected": "Landing metadata declares repository, repository_subpath, descriptor, docs and alternate routes.",
                "local_contract": "descriptor-discovery",
                "external_receipt_required": "public-landing-and-descriptor-journey",
            },
            {
                "id": "CLAUDE-ACCESS-02",
                "name": "GitHub API exhaustion",
                "expected": "Pages, raw-content and archive/release routes remain usable without GitHub API access.",
                "local_contract": "non-api-alternate-routes",
                "external_receipt_required": "api-exhaustion-public-fallback-journey",
            },
            {
                "id": "CLAUDE-ACCESS-03",
                "name": "Raw-root path mismatch",
                "expected": "A raw 404 directs the client to repository_subpath; the client does not guess paths.",
                "local_contract": "declared-raw-subpaths",
                "external_receipt_required": "explorer-raw-404-behaviour",
            },
            {
                "id": "CLAUDE-ACCESS-04",
                "name": "Pages access",
                "expected": "Public Pages descriptor and documentation resolve without authentication.",
                "local_contract": "pages-routes-declared",
                "external_receipt_required": "unauthenticated-public-http-smoke",
            },
            {
                "id": "CLAUDE-ACCESS-05",
                "name": "YAML-LD MIME fallback",
                "expected": "Octet-stream YAML-LD is safely content-sniffed; JSON-LD is the strict transport fallback.",
                "local_contract": "yaml-ld-json-ld-fallback-declared",
                "external_receipt_required": "explorer-mime-fallback-browser-journey",
            },
            {
                "id": "CLAUDE-ACCESS-06",
                "name": "Static and live effect graph",
                "expected": "Official frozen effects and live reconciliation routes are distinct and expose coverage.",
                "local_contract": "effects-and-reconciliation-entrypoints",
                "external_receipt_required": "post-snapshot-live-reconciliation",
            },
            {
                "id": "CLAUDE-ACCESS-07",
                "name": "Stale compatibility URL",
                "expected": "Historical legislation, evaluation and documentation URLs resolve through moved descriptors or redirects.",
                "local_contract": None,
                "external_receipt_required": "compatibility-host-link-and-redirect-crawl",
            },
            {
                "id": "CLAUDE-ACCESS-08",
                "name": "Freshness and source-access cliff",
                "expected": "Snapshot, observation date, route state, truncation and inaccessible checks are visible.",
                "local_contract": "freshness-and-access-cliff-metadata",
                "external_receipt_required": "explorer-visible-freshness-browser-journey",
            },
        ],
    }
    answer_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "https://chris-page-gov.github.io/okf-uk-legislation/"
            "whole-law/evaluation/answer-schema.json"
        ),
        "title": "Whole-Law OKF evaluation answer v2",
        "type": "object",
        "required": [
            "question_id",
            "corpus_snapshot",
            "propositions",
            "citations",
            "temporal_context",
            "limitations",
            "independent_verification",
        ],
        "additionalProperties": False,
        "properties": {
            "question_id": {"type": "string", "minLength": 1},
            "corpus_snapshot": {"const": CORPUS_SNAPSHOT},
            "propositions": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "text", "citation_ids"],
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "text": {"type": "string", "minLength": 1},
                        "citation_ids": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
            "citations": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": [
                        "id",
                        "url",
                        "source_native_id",
                        "authority",
                        "jurisdiction",
                        "version",
                        "retrieved_at",
                        "evidence_hash",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "url": {
                            "type": "string",
                            "pattern": "^https://",
                        },
                        "source_native_id": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "authority": {"type": "string", "minLength": 1},
                        "jurisdiction": {"type": "string", "minLength": 1},
                        "version": {"type": "string", "minLength": 1},
                        "retrieved_at": {
                            "type": "string",
                            "format": "date-time",
                        },
                        "evidence_hash": {
                            "type": "string",
                            "pattern": "^[0-9a-f]{64}$",
                        },
                    },
                },
            },
            "temporal_context": {
                "type": "object",
                "required": ["snapshot", "as_of", "currency_limitations"],
                "properties": {
                    "snapshot": {"const": CORPUS_SNAPSHOT},
                    "as_of": {"type": "string", "format": "date-time"},
                    "currency_limitations": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
            "limitations": {"type": "array", "items": {"type": "string"}},
            "independent_verification": {
                "type": "object",
                "required": ["status", "reviewer", "evidence"],
                "properties": {
                    "status": {
                        "enum": [
                            "not-performed",
                            "independently-verified",
                            "rejected",
                        ]
                    },
                    "reviewer": {
                        "type": ["string", "null"],
                    },
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
    }
    readme = """# Whole-Law release evaluation

This directory contains the corpus-bound `okf-evaluation.v2` release suite.
It covers all 38 researched personas, 20 task families and 36 legal-source
classes, every applicable pair derived from the research mappings/source
register, and every high-risk persona–task–source-class triple. The original
100 legislation questions and the 360 research questions remain preserved as
historical non-gold baselines with checked hashes.

Every current question is deliberately labelled `non-gold-baseline`.
Independent source-evidence and qualified domain review have not yet occurred,
so its expected propositions are structural/disclosure requirements rather
than verified legal propositions. Structural completeness must not be
presented as legal correctness. The release gate remains blocked until
propositions, near misses, citations and temporal expectations have independent
evidence verification.

`claude-access-suite.json` records the adversarial discovery and access journey.
The local runner executes its deterministic publication contracts. Public HTTP,
compatibility-host and browser behaviour require separate receipts and remain
blocked in the local result; neither result may rewrite this suite.

## Execute the release checks

Run:

```bash
python3 scripts/run_release_evaluation.py
python3 scripts/run_release_evaluation.py --check
```

The runner checks the retained 100-question legislation suite and the
Whole-Law release suite against its declared corpus, source
catalogue and immutable acquisition envelopes. It writes a content-addressed,
write-once result beneath `executions/`, including exact structural scores,
pair/high-risk coverage receipts, hard failures, access blocks, timings, input
hashes, the named Claude local-contract journey and the comparison with the
frozen direct-source access baseline.

This is structural and evidence-path assurance. It does not generate legal
answers and will not report a legal-answer score, promote a non-gold question,
claim deployed browser results, or claim the locked 85/100 threshold. Those
gates remain blocked until a bound answer corpus has independent source
verification and qualified domain review and separate deployed journey
receipts exist.
"""
    return {
        Path("release-questions.json"): render(release).encode("utf-8"),
        Path("coverage.json"): render(coverage).encode("utf-8"),
        Path("historical-baselines.json"): render(historical).encode("utf-8"),
        Path("claude-access-suite.json"): render(access_suite).encode("utf-8"),
        Path("answer-schema.json"): render(answer_schema).encode("utf-8"),
        Path("README.md"): readme.encode("utf-8"),
    }


def check_files(files: dict[Path, bytes]) -> list[str]:
    expected = set(files)
    actual = {
        path.relative_to(OUTPUT)
        for path in OUTPUT.rglob("*")
        if path.is_file()
        and path.relative_to(OUTPUT).parts[0] != "executions"
    } if OUTPUT.is_dir() else set()
    errors = []
    for path in sorted(actual | expected):
        if path not in expected:
            errors.append(f"unexpected: {path}")
        elif path not in actual:
            errors.append(f"missing: {path}")
        elif (OUTPUT / path).read_bytes() != files[path]:
            errors.append(f"out of date: {path}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = build()
    if args.check:
        errors = check_files(files)
        if errors:
            print("Whole-Law evaluation is not synchronized:")
            for error in errors[:100]:
                print(f"- {error}")
            return 1
        coverage = load(OUTPUT / "coverage.json")
        print(
            "Whole-Law evaluation synchronized: "
            f"{coverage['question_count']} questions; complete persona/task/source coverage"
        )
        return 0
    OUTPUT.mkdir(parents=True, exist_ok=True)
    unexpected = {
        path.relative_to(OUTPUT)
        for path in OUTPUT.rglob("*")
        if path.is_file()
        and path.relative_to(OUTPUT).parts[0] != "executions"
    } - set(files)
    if unexpected:
        raise SystemExit(
            "Refusing to delete unexpected evaluation files: "
            + ", ".join(str(path) for path in sorted(unexpected))
        )
    for relative, body in files.items():
        path = OUTPUT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    coverage = load(OUTPUT / "coverage.json")
    if not coverage["complete"]:
        raise SystemExit("Evaluation coverage is incomplete")
    print(
        "Built Whole-Law evaluation: "
        f"{coverage['question_count']} questions; complete persona/task/source coverage"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
