#!/usr/bin/env python3
"""Independent verifier for Whole-Law corpus-navigation evaluation answers.

This module deliberately does not import the answer generator.  It reconstructs
the expected source facts from the immutable research register and the sealed
source-access envelopes, then checks answers produced through the published OKF
descriptor/data path.

The verified scope is factual corpus navigation and evidence disclosure.  It is
not legal analysis, legal advice, qualified-practitioner review, or verification
of the underlying legal tasks retained as persona/task context.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

try:  # The release environment pins jsonschema; unit imports remain portable.
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - exercised only outside the release venv
    Draft202012Validator = None
    FormatChecker = None


VERIFIER_NAME = "whole-law-independent-corpus-fact-verifier"
VERIFIER_VERSION = "1.0.0"
EVALUATION_SCOPE = "corpus-navigation-metadata"
LEGAL_TASK_STATUS = "not-evaluated-requires-qualified-domain-review"
LIMITATION_MARKER = (
    "This answer verifies corpus-navigation metadata only; it does not answer "
    "the underlying legal task or provide legal advice."
)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def source_fact(row: dict[str, Any]) -> dict[str, Any]:
    """Return the exact factual fields independently checked for a source."""

    return {
        "id": row["id"],
        "title": row["title"],
        "owning_institution": row["owning_institution"],
        "jurisdictions": sorted(row.get("jurisdictions", [])),
        "authority_classes": sorted(row.get("authority_classes", [])),
        "source_classes": sorted(row.get("source_classes", [])),
        "coverage_status": row.get("coverage_status"),
        "access_test_date": row.get("access_test_date"),
    }


def envelope_observation(
    envelope: dict[str, Any],
    member_path: str,
    member_sha256: str,
) -> dict[str, Any]:
    """Normalize only fields present in an immutable acquisition envelope."""

    response = envelope.get("response", {})
    response_body = response.get("body")
    response_body = response_body if isinstance(response_body, dict) else {}
    fingerprint = response.get("schema_fingerprint")
    fingerprint = fingerprint if isinstance(fingerprint, dict) else {}
    request = envelope.get("request", {})
    assessment = envelope.get("access_assessment", {})
    return {
        "method_id": envelope.get("method_id"),
        "source_id": envelope.get("source", {}).get("id"),
        "url": request.get("url"),
        "final_url": response.get("final_url"),
        "observed_at": response.get("observed_at"),
        "observed_access_state": assessment.get("observed_access_state"),
        "http_status": response.get("status"),
        "media_type": response.get("media_type"),
        "body_sha256": response_body.get("sha256"),
        "schema_fingerprint_sha256": fingerprint.get("fingerprint_sha256"),
        "evidence_member": member_path,
        "evidence_member_sha256": member_sha256,
    }


def archived_observations(
    archived_files: dict[str, bytes],
) -> dict[str, list[dict[str, Any]]]:
    """Reconstruct source observations directly from verified archive members."""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for member_path, body in sorted(archived_files.items()):
        if not (
            member_path.startswith("methods/")
            and member_path.endswith("/envelope.json")
        ):
            continue
        try:
            envelope = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"invalid archived source envelope {member_path}: {exc}"
            ) from exc
        if envelope.get("schema") != "okf-source-access-envelope.v1":
            raise ValueError(
                f"unexpected archived source envelope schema: {member_path}"
            )
        observation = envelope_observation(
            envelope,
            member_path,
            sha256_bytes(body),
        )
        source_id = observation["source_id"]
        if not isinstance(source_id, str) or not source_id:
            raise ValueError(
                f"archived envelope has no source identifier: {member_path}"
            )
        grouped[source_id].append(observation)
    for rows in grouped.values():
        rows.sort(key=lambda row: str(row["method_id"]))
    return dict(sorted(grouped.items()))


def _shape_failures(answer: Any) -> list[str]:
    """Fail-closed fallback shape checks independent of jsonschema."""

    if not isinstance(answer, dict):
        return ["answer-not-object"]
    required = {
        "question_id",
        "evaluation_scope",
        "underlying_legal_task_status",
        "corpus_snapshot",
        "propositions",
        "citations",
        "temporal_context",
        "limitations",
        "independent_verification",
    }
    failures = []
    if not required <= set(answer):
        failures.append("required-answer-fields-missing")
    if answer.get("evaluation_scope") != EVALUATION_SCOPE:
        failures.append("evaluation-scope-mismatch")
    if answer.get("underlying_legal_task_status") != LEGAL_TASK_STATUS:
        failures.append("underlying-legal-task-boundary-missing")
    if not isinstance(answer.get("propositions"), list) or not answer.get(
        "propositions"
    ):
        failures.append("propositions-empty")
    if not isinstance(answer.get("citations"), list) or not answer.get(
        "citations"
    ):
        failures.append("citations-empty")
    if not isinstance(answer.get("limitations"), list) or not answer.get(
        "limitations"
    ):
        failures.append("limitations-empty")
    return failures


def schema_failures(
    answer: dict[str, Any],
    answer_schema: dict[str, Any],
) -> tuple[list[str], str]:
    failures = _shape_failures(answer)
    if Draft202012Validator is None:
        return sorted(set(failures)), "built-in-fail-closed-shape-validator"
    validator = Draft202012Validator(
        answer_schema,
        format_checker=FormatChecker(),
    )
    failures.extend(
        f"jsonschema:{'/'.join(str(value) for value in error.absolute_path)}:"
        f"{error.validator}"
        for error in validator.iter_errors(answer)
    )
    return sorted(set(failures)), "jsonschema-draft-2020-12"


def _citation_bytes(
    citation: dict[str, Any],
    snapshot: dict[str, bytes],
    archived_files: dict[str, bytes],
) -> bytes | None:
    scope = citation.get("evidence_scope")
    if scope == "repository-file":
        return snapshot.get(str(citation.get("evidence_path")))
    if scope == "archive-member":
        # An archive-member citation has two integrity bindings: the sealed
        # archive named by evidence_path and the member named by
        # evidence_member.  Checking only the extracted member would allow a
        # citation to point at an unrelated or non-existent archive while
        # retaining a valid member hash.
        archive_path = str(citation.get("evidence_path"))
        if archive_path not in snapshot:
            return None
        return archived_files.get(str(citation.get("evidence_member")))
    return None


def verify_answer(
    question: dict[str, Any],
    answer: dict[str, Any],
    *,
    source_records: dict[str, dict[str, Any]],
    direct_observations: dict[str, list[dict[str, Any]]],
    snapshot: dict[str, bytes],
    archived_files: dict[str, bytes],
    answer_schema: dict[str, Any],
) -> dict[str, Any]:
    """Verify one answer using independently reconstructed direct evidence."""

    failures, schema_engine = schema_failures(answer, answer_schema)
    checks: dict[str, bool] = {}

    checks["question_identity"] = (
        answer.get("question_id") == question.get("id")
    )
    checks["corpus_snapshot"] = (
        answer.get("corpus_snapshot") == question.get("corpus_snapshot")
        and answer.get("temporal_context", {}).get("snapshot")
        == question.get("corpus_snapshot")
    )
    checks["scope_boundary"] = (
        answer.get("evaluation_scope") == EVALUATION_SCOPE
        and answer.get("underlying_legal_task_status") == LEGAL_TASK_STATUS
        and LIMITATION_MARKER in answer.get("limitations", [])
    )

    propositions = {
        row.get("id"): row
        for row in answer.get("propositions", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    required_source_ids = sorted(question.get("required_source_ids", []))
    checks["required_source_set"] = (
        propositions.get("required-source-set", {}).get("value")
        == required_source_ids
    )
    checks["source_metadata"] = all(
        source_id in source_records
        and propositions.get(f"source-{source_id}", {}).get("value")
        == source_fact(source_records[source_id])
        for source_id in required_source_ids
    )
    checks["direct_access_evidence"] = all(
        propositions.get(f"access-{source_id}", {}).get("value")
        == direct_observations.get(source_id, [])
        for source_id in required_source_ids
    )

    citations = {
        row.get("id"): row
        for row in answer.get("citations", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    referenced_citations = {
        citation_id
        for proposition in propositions.values()
        for citation_id in proposition.get("citation_ids", [])
        if isinstance(citation_id, str)
    }
    citations_resolve = bool(referenced_citations) and referenced_citations <= set(
        citations
    )
    citation_hashes_match = citations_resolve
    for citation_id in sorted(referenced_citations):
        citation = citations.get(citation_id)
        if citation is None:
            citations_resolve = False
            citation_hashes_match = False
            continue
        body = _citation_bytes(citation, snapshot, archived_files)
        if body is None:
            citations_resolve = False
            citation_hashes_match = False
            continue
        if sha256_bytes(body) != citation.get("evidence_hash"):
            citation_hashes_match = False
    checks["citations_resolve"] = citations_resolve
    checks["citation_hashes"] = citation_hashes_match

    expected_propositions = {
        row.get("id"): row
        for row in question.get("expected_propositions", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    checks["declared_gold_match"] = all(
        propositions.get(identifier, {}).get("value") == row.get("value")
        for identifier, row in expected_propositions.items()
    ) and set(expected_propositions) <= set(propositions)

    for name, passed in checks.items():
        if not passed:
            failures.append(name.replace("_", "-"))
    failures = sorted(set(failures))
    score_components = {
        "schema_and_identity": not any(
            value.startswith("jsonschema:")
            or value in {
                "answer-not-object",
                "required-answer-fields-missing",
                "question-identity",
            }
            for value in failures
        ),
        "snapshot_and_scope": checks["corpus_snapshot"]
        and checks["scope_boundary"],
        "source_discovery": checks["required_source_set"]
        and checks["source_metadata"],
        "direct_evidence": checks["direct_access_evidence"],
        "citations_and_gold": checks["citations_resolve"]
        and checks["citation_hashes"]
        and checks["declared_gold_match"],
    }
    numeric_score = 20 * sum(score_components.values())
    hard_failures = failures
    return {
        "question_id": question.get("id"),
        "status": "passed" if not hard_failures else "failed",
        "score": numeric_score,
        "checks": checks,
        "score_components": score_components,
        "schema_engine": schema_engine,
        "hard_failures": hard_failures,
        "review": {
            "kind": "independent-deterministic-internal-verification",
            "verifier": VERIFIER_NAME,
            "version": VERIFIER_VERSION,
            "model_assisted": False,
            "qualified_legal_review": False,
            "scope": EVALUATION_SCOPE,
        },
    }


def verify_answers(
    questions: list[dict[str, Any]],
    answers: list[dict[str, Any]],
    *,
    register: dict[str, Any],
    archived_files: dict[str, bytes],
    snapshot: dict[str, bytes],
    answer_schema: dict[str, Any],
) -> dict[str, Any]:
    """Verify a complete answer set and return an auditable receipt."""

    source_records = {
        row["id"]: row
        for row in register.get("records", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    direct_observations = archived_observations(archived_files)
    answer_by_id = {
        row.get("question_id"): row
        for row in answers
        if isinstance(row, dict) and isinstance(row.get("question_id"), str)
    }
    question_ids = [row.get("id") for row in questions]
    duplicate_answer_ids = sorted(
        identifier
        for identifier in set(answer_by_id)
        if sum(
            row.get("question_id") == identifier
            for row in answers
            if isinstance(row, dict)
        )
        > 1
    )
    rows = []
    for question in questions:
        answer = answer_by_id.get(question.get("id"))
        if answer is None:
            rows.append(
                {
                    "question_id": question.get("id"),
                    "status": "failed",
                    "score": 0,
                    "checks": {},
                    "score_components": {},
                    "schema_engine": (
                        "jsonschema-draft-2020-12"
                        if Draft202012Validator is not None
                        else "built-in-fail-closed-shape-validator"
                    ),
                    "hard_failures": ["answer-missing"],
                    "review": {
                        "kind": "independent-deterministic-internal-verification",
                        "verifier": VERIFIER_NAME,
                        "version": VERIFIER_VERSION,
                        "model_assisted": False,
                        "qualified_legal_review": False,
                        "scope": EVALUATION_SCOPE,
                    },
                }
            )
            continue
        rows.append(
            verify_answer(
                question,
                answer,
                source_records=source_records,
                direct_observations=direct_observations,
                snapshot=snapshot,
                archived_files=archived_files,
                answer_schema=answer_schema,
            )
        )
    hard_failures = [
        {
            "question_id": row["question_id"],
            "failures": row["hard_failures"],
        }
        for row in rows
        if row["hard_failures"]
    ]
    extra_answer_ids = sorted(set(answer_by_id) - set(question_ids))
    if duplicate_answer_ids:
        hard_failures.append(
            {
                "question_id": None,
                "failures": [
                    f"duplicate-answer-ids:{','.join(duplicate_answer_ids)}"
                ],
            }
        )
    if extra_answer_ids:
        hard_failures.append(
            {
                "question_id": None,
                "failures": [f"extra-answer-ids:{','.join(extra_answer_ids)}"],
            }
        )
    return {
        "schema": "okf-evaluation-independent-verification.v1",
        "evaluation_scope": EVALUATION_SCOPE,
        "review_method": {
            "kind": "independent-deterministic-internal-verification",
            "verifier": VERIFIER_NAME,
            "version": VERIFIER_VERSION,
            "model_assisted": False,
            "qualified_legal_review": False,
            "independence": (
                "The verifier reconstructs facts from the research register "
                "and sealed acquisition envelopes and does not import the "
                "published-path answer generator."
            ),
        },
        "questions_expected": len(questions),
        "answers_received": len(answers),
        "answers_verified": sum(row["status"] == "passed" for row in rows),
        "schema_valid_answers": sum(
            not any(
                failure.startswith("jsonschema:")
                or failure in {
                    "answer-not-object",
                    "required-answer-fields-missing",
                }
                for failure in row["hard_failures"]
            )
            for row in rows
        ),
        "resolvable_citation_answers": sum(
            row["checks"].get("citations_resolve", False)
            and row["checks"].get("citation_hashes", False)
            for row in rows
        ),
        "hard_failure_count": len(hard_failures),
        "hard_failures": hard_failures,
        "results": rows,
        "status": "passed" if not hard_failures else "failed",
        "assurance_boundary": (
            "This verifies snapshot-bound corpus-navigation facts and evidence "
            "paths. It does not verify the underlying legal task, legal "
            "correctness, or provide qualified-practitioner assurance."
        ),
    }
