#!/usr/bin/env python3
"""Pure governance helpers for model-enrichment cache keys and cost limits.

This module performs no network access, reads no environment variables and
never handles API credentials.  It gives a future paid runner deterministic
request identities and exact decimal budget arithmetic without implementing
that runner.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping, Sequence


MILLION = Decimal(1_000_000)
DEFAULT_CAP_USD = Decimal("250")
RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
FORBIDDEN_REQUEST_KEY_FORMS = frozenset(
    {
        "api_key",
        "apikey",
        "auth",
        "auth_token",
        "authtoken",
        "authorization",
        "bearer",
        "bearer_token",
        "bearertoken",
        "client_secret",
        "clientsecret",
        "cookie",
        "credential",
        "credentials",
        "header",
        "headers",
        "http_headers",
        "httpheaders",
        "openai_api_key",
        "openaiapikey",
        "password",
        "private_key",
        "privatekey",
        "secret",
        "set_cookie",
        "setcookie",
        "token",
        "x_api_key",
        "xapikey",
    }
)
ALLOWED_REQUEST_PARAMETER_KEYS = frozenset(
    {
        "reasoning",
        "seed",
        "service_tier",
        "store",
        "temperature",
        "top_p",
        "truncation",
    }
)
ALLOWED_REASONING_PARAMETER_KEYS = frozenset({"effort", "summary"})
ALLOWED_REASONING_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh"}
)
ALLOWED_REASONING_SUMMARIES = frozenset({"auto", "concise", "detailed"})
ALLOWED_SERVICE_TIERS = frozenset({"auto", "default", "flex", "priority"})
KIND_PREDICATES = {
    "topic": "classified as",
    "concept": "about concept",
    "entity": "mentions entity",
}
REVIEW_REASON_VERDICTS = {
    "accepted-supported": "accept",
    "candidate-not-in-controlled-vocabulary": "reject",
    "duplicate-existing-assertion": "reject",
    "evidence-does-not-entail-target": "reject",
    "evidence-span-not-found": "reject",
    "high-risk-requires-strongest-model": "escalate",
    "insufficient-frozen-evidence": "reject",
    "official-authority-boundary": "reject",
    "reviewer-uncertain": "escalate",
}
TERMINAL_OUTCOMES = (
    "accepted",
    "already-supported",
    "budget-stopped",
    "escalation-rejected",
    "generator-schema-rejected",
    "input-invalid",
    "insufficient-frozen-evidence",
    "no-supported-new-assertion",
    "review-rejected",
)
UNSUPPORTED_STRUCTURED_OUTPUT_COMPOSITION_KEYWORDS = frozenset(
    {
        "allOf",
        "dependentRequired",
        "dependentSchemas",
        "else",
        "if",
        "not",
        "then",
    }
)


def _assert_json_value(value: Any, path: str = "$") -> None:
    """Reject Python-only values that ``json.dumps`` silently coerces."""

    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError(f"non-finite JSON number at {path}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _assert_json_value(child, f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError(f"JSON object key must be a string at {path}")
            _assert_json_value(child, f"{path}.{key}")
        return
    raise ValueError(
        f"value at {path} is not a JSON value: {type(value).__name__}"
    )


def canonical_json(value: Any) -> bytes:
    """Return the governed UTF-8 canonical JSON representation."""

    _assert_json_value(value)
    try:
        rendered = (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )
        encoded = rendered.encode("utf-8")
        # A round trip proves that the emitted bytes are valid JSON rather
        # than merely a Python serialization accepted by ``json.dumps``.
        json.loads(encoded)
    except (UnicodeEncodeError, ValueError, TypeError) as exc:
        raise ValueError(f"value cannot be encoded as canonical JSON: {exc}") from exc
    return encoded


def _normalized_key_forms(key: str) -> set[str]:
    casefolded = key.casefold()
    snake = re.sub(r"[^a-z0-9]+", "_", casefolded).strip("_")
    compact = re.sub(r"[^a-z0-9]+", "", casefolded)
    return {casefolded, snake, compact}


def _credential_shaped_key(key: str) -> bool:
    forms = _normalized_key_forms(key)
    if forms & FORBIDDEN_REQUEST_KEY_FORMS:
        return True
    snake = next((form for form in forms if "_" in form), "")
    compact = min(forms, key=len)
    forbidden_suffixes = (
        "_api_key",
        "_auth_token",
        "_access_token",
        "_bearer_token",
        "_client_secret",
        "_cookie",
        "_header",
        "_headers",
        "_private_key",
        "_password",
        "_secret",
        "_credentials",
    )
    compact_suffixes = tuple(
        suffix.replace("_", "") for suffix in forbidden_suffixes
    )
    return snake.endswith(forbidden_suffixes) or compact.endswith(
        compact_suffixes
    )


def _assert_no_secret_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError(f"request key must be a string at {path}")
            if _credential_shaped_key(key):
                raise ValueError(
                    f"credential-shaped key is forbidden in cache identity: "
                    f"{path}.{key}"
                )
            _assert_no_secret_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_secret_keys(child, f"{path}[{index}]")


def validate_material_reference(
    material: Mapping[str, Any],
    *,
    repository_root: Path | None = None,
    require_regular_file: bool = False,
) -> Path | None:
    """Reject escaping material paths and optionally verify exact file bytes."""

    path_value = material.get("path")
    digest = material.get("sha256")
    if not isinstance(path_value, str) or not path_value:
        raise ValueError("material path must be a non-empty repository path")
    if (
        "\\" in path_value
        or "\x00" in path_value
        or re.match(r"^[a-zA-Z]:", path_value)
        or any(part in {"", ".", ".."} for part in path_value.split("/"))
    ):
        raise ValueError(f"material path is not portable: {path_value!r}")
    relative = PurePosixPath(path_value)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError(f"material path escapes repository: {path_value!r}")
    if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
        raise ValueError(f"material digest is not SHA-256: {path_value!r}")
    if repository_root is None:
        if require_regular_file:
            raise ValueError(
                "repository_root is required to verify a material file"
            )
        return None

    root = repository_root.resolve(strict=True)
    candidate = root.joinpath(*relative.parts)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(
                f"material path contains a symlink: {path_value}"
            )
    resolved = candidate.resolve(strict=require_regular_file)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"material path escapes repository: {path_value!r}") from exc
    if require_regular_file:
        if not resolved.is_file():
            raise ValueError(
                f"material path is not a regular non-symlink file: {path_value}"
            )
        observed = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if observed != digest:
            raise ValueError(f"material file digest mismatch: {path_value}")
    return resolved


def validate_request_parameters(parameters: Mapping[str, Any]) -> None:
    """Validate the complete allowlisted, header-free request parameter set."""

    if not isinstance(parameters, Mapping):
        raise ValueError("request parameters must be an object")
    _assert_json_value(parameters, "$.parameters")
    _assert_no_secret_keys(parameters, "$.parameters")
    extras = sorted(set(parameters) - ALLOWED_REQUEST_PARAMETER_KEYS)
    if extras:
        raise ValueError(f"request parameters are not allowlisted: {extras}")

    reasoning = parameters.get("reasoning")
    if reasoning is not None:
        if not isinstance(reasoning, Mapping):
            raise ValueError("reasoning parameter must be an object")
        reasoning_extras = sorted(
            set(reasoning) - ALLOWED_REASONING_PARAMETER_KEYS
        )
        if reasoning_extras:
            raise ValueError(
                f"reasoning parameters are not allowlisted: {reasoning_extras}"
            )
        effort = reasoning.get("effort")
        if effort is not None and effort not in ALLOWED_REASONING_EFFORTS:
            raise ValueError(f"unsupported reasoning effort: {effort!r}")
        summary = reasoning.get("summary")
        if summary is not None and summary not in ALLOWED_REASONING_SUMMARIES:
            raise ValueError(f"unsupported reasoning summary: {summary!r}")

    for name in ("temperature", "top_p"):
        value = parameters.get(name)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value < 0
            or value > (2 if name == "temperature" else 1)
        ):
            raise ValueError(f"{name} is outside the governed range")
    seed = parameters.get("seed")
    if seed is not None and (
        isinstance(seed, bool) or not isinstance(seed, int)
    ):
        raise ValueError("seed must be an integer")
    if "store" in parameters and parameters["store"] is not False:
        raise ValueError("store must be false")
    service_tier = parameters.get("service_tier")
    if service_tier is not None and service_tier not in ALLOWED_SERVICE_TIERS:
        raise ValueError(f"unsupported service tier: {service_tier!r}")
    truncation = parameters.get("truncation")
    if truncation is not None and truncation != "disabled":
        raise ValueError("truncation must be disabled")


def request_cache_key(identity: Mapping[str, Any]) -> str:
    """Return a credential-free content address for an exact model request."""

    required = {
        "provider",
        "endpoint",
        "requested_model",
        "prompt_sha256",
        "response_schema_sha256",
        "parameters",
        "input_sha256",
        "max_output_tokens",
    }
    missing = sorted(required - set(identity))
    extras = sorted(set(identity) - required)
    if missing or extras:
        raise ValueError(
            f"request identity mismatch: missing={missing}, extras={extras}"
        )
    if identity.get("provider") != "OpenAI":
        raise ValueError("request provider must be OpenAI")
    if identity.get("endpoint") != RESPONSES_ENDPOINT:
        raise ValueError("request endpoint must be the governed Responses API")
    requested_model = identity.get("requested_model")
    if not isinstance(requested_model, str) or not requested_model.strip():
        raise ValueError("requested_model must be a non-empty exact model ID")
    for field in (
        "prompt_sha256",
        "response_schema_sha256",
        "input_sha256",
    ):
        value = identity.get(field)
        if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
            raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    max_output_tokens = identity.get("max_output_tokens")
    if (
        isinstance(max_output_tokens, bool)
        or not isinstance(max_output_tokens, int)
        or max_output_tokens < 1
    ):
        raise ValueError("max_output_tokens must be a positive integer")
    validate_request_parameters(identity.get("parameters"))
    _assert_no_secret_keys(identity)
    body = canonical_json(dict(identity))
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


def assert_structured_output_schema_subset(schema: Mapping[str, Any]) -> None:
    """Reject composition keywords unsupported by OpenAI strict outputs.

    This deliberately checks the API-facing schemas without making a
    capability claim for any particular configured model. Model admission
    still requires a paid, append-only capability probe.
    """

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if key in UNSUPPORTED_STRUCTURED_OUTPUT_COMPOSITION_KEYWORDS:
                    raise ValueError(
                        "unsupported strict structured-output keyword "
                        f"{key!r} at {path}"
                    )
                visit(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(schema, "$")


def validate_candidate_record_state(record: Mapping[str, Any]) -> None:
    """Enforce cross-field candidate invariants after strict parsing."""

    decision = record.get("decision")
    assertions = record.get("assertions")
    abstention_reason = record.get("abstention_reason")
    if not isinstance(assertions, list):
        raise ValueError("candidate assertions must be an array")
    if decision == "assert":
        if not assertions or abstention_reason is not None:
            raise ValueError(
                "assert decisions require assertions and no abstention reason"
            )
        return
    if decision == "abstain":
        if assertions or not isinstance(abstention_reason, str):
            raise ValueError(
                "abstain decisions require no assertions and a reason"
            )
        return
    raise ValueError(f"unsupported candidate decision: {decision!r}")


def validate_candidate_assertions(
    record: Mapping[str, Any],
    evidence_fields: Mapping[str, Mapping[str, Any] | str],
    *,
    frozen_projection: Mapping[str, Any] | None = None,
    known_collision_family: bool = False,
) -> None:
    """Validate assertion semantics and exact spans against frozen evidence.

    ``evidence_fields`` maps each permitted source field to either its exact
    text or an object containing ``text``, ``source_sha256`` and optionally
    ``source_uri``. The object form is required when the source digest covers a
    containing source document rather than the field text alone.
    """

    validate_candidate_record_state(record)
    assertions = record["assertions"]
    record_risk_flags = record.get("risk_flags")
    if not isinstance(record_risk_flags, list):
        raise ValueError("candidate record risk_flags must be an array")
    distinct_topics = {
        assertion.get("target_id")
        for assertion in assertions
        if isinstance(assertion, Mapping)
        and assertion.get("kind") == "topic"
    }
    record_required_flags: set[str] = set()
    if len(distinct_topics) > 1:
        record_required_flags.add("multi-topic")
    if known_collision_family:
        record_required_flags.add("known-collision-family")
    if isinstance(frozen_projection, Mapping):
        title = frozen_projection.get("title")
        if (
            isinstance(title, Mapping)
            and title.get("kind") == "uri-fallback"
        ):
            record_required_flags.add("uri-fallback-title")
        source_metadata = frozen_projection.get("source_metadata")
        jurisdiction = (
            source_metadata.get("jurisdiction")
            if isinstance(source_metadata, Mapping)
            else None
        )
        if (
            jurisdiction is None
            or jurisdiction == ""
            or (
                isinstance(jurisdiction, list)
                and len(
                    {
                        str(value).strip()
                        for value in jurisdiction
                        if str(value).strip()
                    }
                )
                != 1
            )
        ):
            record_required_flags.add("jurisdiction-ambiguity")
    if not record_required_flags.issubset(set(record_risk_flags)):
        missing = sorted(record_required_flags - set(record_risk_flags))
        raise ValueError(
            f"candidate record omits derived risk flags: {missing}"
        )
    assertion_digests: set[str] = set()
    for assertion_index, assertion in enumerate(assertions):
        if not isinstance(assertion, Mapping):
            raise ValueError(
                f"candidate assertion {assertion_index} must be an object"
            )
        assertion_digest = hashlib.sha256(
            canonical_json(dict(assertion))
        ).hexdigest()
        if assertion_digest in assertion_digests:
            raise ValueError("candidate contains a duplicate assertion")
        assertion_digests.add(assertion_digest)
        kind = assertion.get("kind")
        predicate = assertion.get("predicate")
        expected_predicate = KIND_PREDICATES.get(kind)
        if predicate != expected_predicate:
            raise ValueError(
                f"candidate assertion {assertion_index} kind {kind!r} "
                f"requires predicate {expected_predicate!r}"
            )
        target_id = assertion.get("target_id")
        expected_prefix = f"{kind}/"
        if (
            not isinstance(target_id, str)
            or not target_id.startswith(expected_prefix)
            or len(target_id) <= len(expected_prefix)
            or target_id.startswith(("http://", "https://"))
            or ".." in target_id.split("/")
            or any(
                not (
                    character.islower()
                    or character.isdigit()
                    or character in "-._/"
                )
                for character in target_id
            )
        ):
            raise ValueError(
                f"candidate assertion {assertion_index} target is outside "
                f"the controlled {expected_prefix} namespace"
            )
        risk_flags = assertion.get("risk_flags")
        if not isinstance(risk_flags, list):
            raise ValueError(
                f"candidate assertion {assertion_index} risk flags must be "
                "an array"
            )
        required_flags = set(record_required_flags)
        required_kind_flag = {
            "concept": "concept-link",
            "entity": "entity-link",
        }.get(kind)
        if required_kind_flag is not None:
            required_flags.add(required_kind_flag)
        confidence = assertion.get("confidence")
        if (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and confidence < 0.95
        ):
            required_flags.add("low-confidence")
        evidence_rows = assertion.get("evidence")
        if isinstance(evidence_rows, list) and any(
            isinstance(evidence, Mapping)
            and evidence.get("source_field") != "title"
            for evidence in evidence_rows
        ):
            required_flags.add("non-title-evidence")
        target_tokens = set(
            str(target_id).lower().replace("_", "-").split("/")
        )
        if any(
            token.startswith(
                (
                    "official-",
                    "authoritative-",
                    "government-",
                    "gov-uk",
                    "legislation-gov-uk",
                )
            )
            for token in target_tokens
        ):
            required_flags.add("official-looking-target")
        evidence_text = " ".join(
            str(evidence.get("quote", ""))
            for evidence in evidence_rows or []
            if isinstance(evidence, Mapping)
        ).casefold()
        if any(
            marker in evidence_text
            for marker in (
                "commencement",
                "expires",
                "expiry",
                "revocation",
                "temporary",
                "transitional",
            )
        ):
            required_flags.add("temporal-ambiguity")
        if not required_flags.issubset(set(risk_flags)):
            missing = sorted(required_flags - set(risk_flags))
            raise ValueError(
                f"candidate assertion {assertion_index} omits derived risk "
                f"flags: {missing}"
            )
        if not set(risk_flags).issubset(record_risk_flags):
            raise ValueError(
                f"candidate assertion {assertion_index} risk flags are not "
                "propagated to the record"
            )
        if not isinstance(evidence_rows, list) or not evidence_rows:
            raise ValueError(
                f"candidate assertion {assertion_index} has no evidence"
            )
        evidence_digests: set[str] = set()
        for evidence_index, evidence in enumerate(evidence_rows):
            if not isinstance(evidence, Mapping):
                raise ValueError(
                    f"candidate evidence {assertion_index}:{evidence_index} "
                    "must be an object"
                )
            evidence_digest = hashlib.sha256(
                canonical_json(dict(evidence))
            ).hexdigest()
            if evidence_digest in evidence_digests:
                raise ValueError(
                    f"candidate assertion {assertion_index} contains "
                    "duplicate evidence"
                )
            evidence_digests.add(evidence_digest)
            source_field = evidence.get("source_field")
            if source_field not in evidence_fields:
                raise ValueError(
                    f"candidate evidence {assertion_index}:{evidence_index} "
                    f"uses unavailable field {source_field!r}"
                )
            frozen = evidence_fields[source_field]
            if isinstance(frozen, str):
                text = frozen
                expected_sha256 = hashlib.sha256(
                    text.encode("utf-8")
                ).hexdigest()
                expected_uri = None
            elif isinstance(frozen, Mapping):
                text = frozen.get("text")
                expected_sha256 = frozen.get("source_sha256")
                expected_uri = frozen.get("source_uri")
                if not isinstance(text, str):
                    raise ValueError(
                        f"frozen evidence field {source_field!r} has no text"
                    )
                if (
                    not isinstance(expected_sha256, str)
                    or SHA256_RE.fullmatch(expected_sha256) is None
                ):
                    raise ValueError(
                        f"frozen evidence field {source_field!r} has no "
                        "lowercase source SHA-256"
                    )
            else:
                raise ValueError(
                    f"frozen evidence field {source_field!r} is invalid"
                )
            start = evidence.get("start")
            end = evidence.get("end")
            if (
                isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, int)
                or not isinstance(end, int)
                or start < 0
                or end <= start
                or end > len(text)
            ):
                raise ValueError(
                    f"candidate evidence {assertion_index}:{evidence_index} "
                    "has an invalid exact span"
                )
            if evidence.get("quote") != text[start:end]:
                raise ValueError(
                    f"candidate evidence {assertion_index}:{evidence_index} "
                    "quote does not match the frozen exact span"
                )
            if evidence.get("source_sha256") != expected_sha256:
                raise ValueError(
                    f"candidate evidence {assertion_index}:{evidence_index} "
                    "source digest does not match frozen evidence"
                )
            if (
                expected_uri is not None
                and evidence.get("source_uri") != expected_uri
            ):
                raise ValueError(
                    f"candidate evidence {assertion_index}:{evidence_index} "
                    "source URI does not match frozen evidence"
                )


def validate_review_record(
    candidate_record: Mapping[str, Any],
    review_record: Mapping[str, Any],
) -> None:
    """Require a coherent reviewer verdict for every candidate assertion."""

    validate_candidate_record_state(candidate_record)
    for field in ("record_id", "input_sha256"):
        if review_record.get(field) != candidate_record.get(field):
            raise ValueError(f"review {field} does not match candidate")
    expected_candidate_sha256 = hashlib.sha256(
        canonical_json(dict(candidate_record))
    ).hexdigest()
    if review_record.get("candidate_record_sha256") != expected_candidate_sha256:
        raise ValueError(
            "review candidate_record_sha256 does not match canonical candidate"
        )
    assertions = candidate_record.get("assertions")
    decisions = review_record.get("decisions")
    if not isinstance(assertions, list) or not isinstance(decisions, list):
        raise ValueError("candidate assertions and review decisions are arrays")
    expected_indexes = list(range(len(assertions)))
    observed_indexes = [decision.get("candidate_index") for decision in decisions]
    if observed_indexes != expected_indexes:
        raise ValueError(
            "review decisions must cover every candidate index exactly once "
            "in ascending order"
        )

    for index, decision in enumerate(decisions):
        if not isinstance(decision, Mapping):
            raise ValueError(f"review decision {index} must be an object")
        verdict = decision.get("verdict")
        reason = decision.get("reason_code")
        expected_verdict = REVIEW_REASON_VERDICTS.get(reason)
        if verdict != expected_verdict:
            raise ValueError(
                f"review reason {reason!r} requires verdict "
                f"{expected_verdict!r}"
            )
        evidence_supported = decision.get("evidence_supported")
        semantic_supported = decision.get("semantic_supported")
        if not isinstance(evidence_supported, bool) or not isinstance(
            semantic_supported, bool
        ):
            raise ValueError(f"review decision {index} support must be boolean")
        if verdict == "accept" and not (
            evidence_supported and semantic_supported
        ):
            raise ValueError(
                f"accepted review decision {index} requires both supports"
            )
        if reason == "evidence-span-not-found" and evidence_supported:
            raise ValueError("missing evidence span cannot be evidence-supported")
        if reason == "evidence-does-not-entail-target" and semantic_supported:
            raise ValueError(
                "non-entailing evidence cannot be semantically supported"
            )
        if reason in {
            "candidate-not-in-controlled-vocabulary",
            "insufficient-frozen-evidence",
        } and (evidence_supported and semantic_supported):
            raise ValueError(
                f"review reason {reason!r} contradicts full support"
            )
        risk_flags = decision.get("risk_flags")
        if not isinstance(risk_flags, list):
            raise ValueError(
                f"review decision {index} risk_flags must be an array"
            )
        required_risk_flags: set[str] = set()
        if reason == "evidence-span-not-found":
            required_risk_flags.add("evidence-field-mismatch")
        if reason == "evidence-does-not-entail-target":
            required_risk_flags.add("semantic-disagreement")
        if reason == "reviewer-uncertain":
            required_risk_flags.add("reviewer-uncertainty")
        if not required_risk_flags.issubset(set(risk_flags)):
            missing = sorted(required_risk_flags - set(risk_flags))
            raise ValueError(
                f"review decision {index} omits derived risk flags: {missing}"
            )
        if verdict == "escalate" and (
            not risk_flags
        ):
            raise ValueError("escalation requires at least one risk flag")


def validate_selection_receipt(receipt: Mapping[str, Any]) -> None:
    """Validate qualification, cheapest selection and exact-model roles."""

    thresholds = receipt.get("thresholds")
    candidates = receipt.get("candidates")
    if not isinstance(thresholds, Mapping) or not isinstance(candidates, list):
        raise ValueError("selection thresholds and candidates are required")
    required_thresholds = {
        "structured_output_schema_validity",
        "precision",
        "evidence_support",
    }
    if set(thresholds) != required_thresholds:
        raise ValueError("selection threshold fields are not exact")
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in thresholds.values()
    ):
        raise ValueError("selection thresholds must be numeric")

    returned_models: set[str] = set()
    qualified_models: set[str] = set()
    qualifying: list[tuple[Decimal, str]] = []
    requested_models: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise ValueError(f"selection candidate {index} must be an object")
        requested = candidate.get("requested_model")
        if not isinstance(requested, str) or not requested:
            raise ValueError(f"selection candidate {index} has no model")
        if requested in requested_models:
            raise ValueError(f"duplicate requested model in selection: {requested}")
        requested_models.add(requested)
        available = (
            candidate.get("availability") == "available-structured-output"
        )
        returned = candidate.get("returned_model")
        metrics = [
            candidate.get("structured_output_schema_validity"),
            candidate.get("precision"),
            candidate.get("evidence_support"),
        ]
        projected = candidate.get("projected_total_cost_usd")
        if available:
            if not isinstance(returned, str) or not returned:
                raise ValueError(
                    f"available selection candidate {index} lacks exact model"
                )
            if returned in returned_models:
                raise ValueError(
                    f"duplicate returned model in selection: {returned}"
                )
            returned_models.add(returned)
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                for value in metrics
            ):
                raise ValueError(
                    f"available selection candidate {index} lacks metrics"
                )
            if (
                isinstance(projected, bool)
                or not isinstance(projected, (int, float))
                or decimal_usd(projected) < 0
            ):
                raise ValueError(
                    f"available selection candidate {index} lacks cost"
                )
        else:
            if returned is not None or any(value is not None for value in metrics):
                raise ValueError(
                    f"unavailable selection candidate {index} has observations"
                )
            if projected is not None:
                raise ValueError(
                    f"unavailable selection candidate {index} has projected cost"
                )

        computed_qualified = bool(
            available
            and metrics[0] >= thresholds[
                "structured_output_schema_validity"
            ]
            and metrics[1] >= thresholds["precision"]
            and metrics[2] >= thresholds["evidence_support"]
        )
        if candidate.get("qualified") is not computed_qualified:
            raise ValueError(
                f"selection candidate {index} qualified flag is inconsistent"
            )
        if computed_qualified:
            measured = decimal_usd(candidate.get("calibration_cost_usd"))
            total_cost = measured + decimal_usd(projected)
            qualifying.append((total_cost, returned))
            qualified_models.add(returned)

    if not qualifying:
        raise ValueError("selection has no qualifying generator candidate")
    selected = receipt.get("selected_generator_model")
    minimum_cost = min(cost for cost, _ in qualifying)
    minimum_models = sorted(
        model for cost, model in qualifying if cost == minimum_cost
    )
    if selected != minimum_models[0]:
        raise ValueError(
            "selected generator is not the deterministic cheapest qualifier"
        )
    reviewer = receipt.get("reviewer_model")
    strongest = receipt.get("strongest_model")
    if reviewer not in qualified_models:
        raise ValueError("reviewer role must use an observed qualifying model")
    if strongest not in returned_models:
        raise ValueError(
            "strongest role must use an observed available model"
        )
    designation = receipt.get("strongest_designation")
    if not isinstance(designation, Mapping):
        raise ValueError("strongest role lacks hash-bound designation evidence")
    validate_material_reference(designation)
    if designation.get("designated_model") != strongest:
        raise ValueError("strongest designation model does not match role")
    for field in (
        "capability_ordering_policy_sha256",
        "official_model_evidence_sha256",
    ):
        value = designation.get(field)
        if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
            raise ValueError(f"strongest designation lacks {field}")
    validate_model_role_separation(
        generator_exact_model_id=selected,
        reviewer_exact_model_id=reviewer,
        strongest_exact_model_id=strongest,
    )
    if receipt.get("role_separation_satisfied") is not True:
        raise ValueError("selection role-separation receipt is not true")


def validate_model_role_separation(
    *,
    generator_exact_model_id: str,
    reviewer_exact_model_id: str,
    strongest_exact_model_id: str,
) -> None:
    """Enforce the governed generator/reviewer/escalation separation."""

    roles = {
        "generator": generator_exact_model_id,
        "reviewer": reviewer_exact_model_id,
        "strongest": strongest_exact_model_id,
    }
    for role, model_id in roles.items():
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError(f"{role} exact model ID must be non-empty")
    if generator_exact_model_id == reviewer_exact_model_id:
        raise ValueError("reviewer exact model ID must differ from generator")
    if generator_exact_model_id == strongest_exact_model_id:
        raise ValueError("strongest exact model ID must differ from generator")


def decimal_usd(value: Decimal | int | str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"USD value must be numeric: {value}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"USD value must be numeric: {value}") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"USD value must be finite and non-negative: {value}")
    return result


def request_upper_bound_usd(
    *,
    uncached_input_tokens: int,
    cached_input_tokens: int,
    max_output_tokens: int,
    input_usd_per_million: Decimal | int | str,
    cached_input_usd_per_million: Decimal | int | str,
    output_usd_per_million: Decimal | int | str,
) -> Decimal:
    """Calculate the exact advertised-price upper bound for one request."""

    tokens = (
        uncached_input_tokens,
        cached_input_tokens,
        max_output_tokens,
    )
    if any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        for value in tokens
    ):
        raise ValueError("token counts must be non-negative integers")
    if max_output_tokens == 0:
        raise ValueError("max_output_tokens must be greater than zero")
    input_rate = decimal_usd(input_usd_per_million)
    cached_rate = decimal_usd(cached_input_usd_per_million)
    output_rate = decimal_usd(output_usd_per_million)
    return (
        Decimal(uncached_input_tokens) * input_rate
        + Decimal(cached_input_tokens) * cached_rate
        + Decimal(max_output_tokens) * output_rate
    ) / MILLION


def reservation_permitted(
    *,
    spent_usd: Decimal | int | str,
    reserved_usd: Decimal | int | str,
    next_request_upper_bound_usd: Decimal | int | str,
    cap_usd: Decimal | int | str = DEFAULT_CAP_USD,
) -> bool:
    """Return whether an atomic reservation remains within the hard cap."""

    spent = decimal_usd(spent_usd)
    reserved = decimal_usd(reserved_usd)
    next_request = decimal_usd(next_request_upper_bound_usd)
    cap = decimal_usd(cap_usd)
    return spent + reserved + next_request <= cap


def remaining_after_reservation_usd(
    *,
    spent_usd: Decimal | int | str,
    reserved_usd: Decimal | int | str,
    next_request_upper_bound_usd: Decimal | int | str,
    cap_usd: Decimal | int | str = DEFAULT_CAP_USD,
) -> Decimal:
    """Return remaining budget, failing rather than representing overspend."""

    spent = decimal_usd(spent_usd)
    reserved = decimal_usd(reserved_usd)
    next_request = decimal_usd(next_request_upper_bound_usd)
    cap = decimal_usd(cap_usd)
    remaining = cap - spent - reserved - next_request
    if remaining < 0:
        raise ValueError("model request reservation would exceed hard cap")
    return remaining


def validate_cost_cap_receipt(receipt: Mapping[str, Any]) -> None:
    """Enforce the receipt arithmetic that JSON Schema cannot express."""

    cap = decimal_usd(receipt.get("cap_usd"))
    spent = decimal_usd(receipt.get("spent_usd"))
    reserved = decimal_usd(receipt.get("reserved_usd"))
    next_request = decimal_usd(receipt.get("next_request_upper_bound_usd"))
    projected = decimal_usd(receipt.get("projected_total_usd"))
    remaining = decimal_usd(receipt.get("remaining_usd"))
    reservations = receipt.get("reservations")
    if not isinstance(reservations, list):
        raise ValueError("cost-cap reservations must be an array")

    reservation_ids: set[str] = set()
    attempt_ids: set[str] = set()
    active_reservations = Decimal(0)
    for index, row in enumerate(reservations):
        if not isinstance(row, Mapping):
            raise ValueError(f"cost reservation {index} must be an object")
        reservation_id = row.get("reservation_id")
        attempt_id = row.get("attempt_id")
        if reservation_id in reservation_ids:
            raise ValueError(f"duplicate reservation ID: {reservation_id}")
        if attempt_id in attempt_ids:
            raise ValueError(f"duplicate reserved attempt ID: {attempt_id}")
        reservation_ids.add(reservation_id)
        attempt_ids.add(attempt_id)
        if row.get("state") == "reserved":
            active_reservations += decimal_usd(row.get("upper_bound_usd"))
    if active_reservations != reserved:
        raise ValueError(
            "reserved_usd does not equal active reservation upper bounds"
        )

    request_total = spent + reserved + next_request
    expected_remaining = max(cap - request_total, Decimal(0))
    if remaining != expected_remaining:
        raise ValueError("cost-cap remaining_usd is arithmetically inconsistent")
    if projected < request_total:
        raise ValueError("projected total is below committed request cost")
    mode = receipt.get("mode")
    expected_permitted = request_total <= cap
    if mode == "preflight":
        expected_permitted = expected_permitted and projected <= cap
    elif mode == "final-reconciliation":
        if reserved != 0 or next_request != 0 or active_reservations != 0:
            raise ValueError(
                "final reconciliation must close every request reservation"
            )
        expected_permitted = False
    if receipt.get("permitted") is not expected_permitted:
        raise ValueError("cost-cap permitted flag violates the hard-cap invariant")
    if mode == "hard-stop" and expected_permitted:
        raise ValueError("hard-stop receipt cannot permit another request")


def _validate_terminal_outcome_row(row: Mapping[str, Any]) -> None:
    outcome = row.get("outcome")
    if outcome not in TERMINAL_OUTCOMES:
        raise ValueError(f"unsupported terminal outcome: {outcome!r}")
    counts = {}
    for field in (
        "candidate_assertions",
        "accepted_assertions",
        "review_rejections",
        "escalations",
    ):
        value = row.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"terminal outcome {field} is not a count")
        counts[field] = value
    risk_flags = row.get("risk_flags")
    if not isinstance(risk_flags, list) or any(
        not isinstance(flag, str) or not flag for flag in risk_flags
    ):
        raise ValueError("terminal outcome risk_flags must be an array of flags")
    if outcome == "accepted":
        if counts["accepted_assertions"] < 1:
            raise ValueError("accepted outcome has no accepted assertion")
        if counts["candidate_assertions"] < 1:
            raise ValueError("accepted outcome has no candidate assertion")
        if row.get("deterministic_validation") != "passed":
            raise ValueError("accepted outcome requires deterministic validation")
        if risk_flags and counts["escalations"] < 1:
            raise ValueError(
                "accepted high-risk outcome requires strongest-model escalation"
            )
    elif counts["accepted_assertions"] != 0:
        raise ValueError("non-accepted outcome has accepted assertions")
    if counts["accepted_assertions"] > counts["candidate_assertions"]:
        raise ValueError("accepted assertions exceed candidate assertions")
    if outcome in {
        "already-supported",
        "budget-stopped",
        "input-invalid",
        "insufficient-frozen-evidence",
    }:
        if any(counts.values()):
            raise ValueError(
                f"{outcome} outcome cannot contain model assertion activity"
            )
        if row.get("deterministic_validation") != "not-applicable":
            raise ValueError(
                f"{outcome} outcome requires not-applicable validation"
            )
        if risk_flags:
            raise ValueError(f"{outcome} outcome cannot contain risk flags")
    if outcome == "generator-schema-rejected":
        if any(counts.values()):
            raise ValueError(
                "generator-schema-rejected outcome cannot contain assertions"
            )
        if row.get("deterministic_validation") == "passed":
            raise ValueError(
                "generator-schema-rejected outcome cannot pass validation"
            )
    if outcome == "review-rejected":
        if (
            counts["candidate_assertions"] < 1
            or counts["review_rejections"] < 1
        ):
            raise ValueError(
                "review-rejected outcome requires candidate and rejection"
            )
        if counts["escalations"] != 0:
            raise ValueError(
                "review-rejected outcome cannot also report escalation"
            )
    if outcome == "escalation-rejected":
        if (
            counts["candidate_assertions"] < 1
            or counts["escalations"] < 1
        ):
            raise ValueError(
                "escalation-rejected outcome requires candidate and escalation"
            )
    if outcome == "no-supported-new-assertion" and (
        counts["review_rejections"] or counts["escalations"]
    ):
        raise ValueError(
            "no-supported-new-assertion cannot report rejection or escalation"
        )
    evidence = row.get("outcome_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("terminal outcome has no immutable evidence")


def compute_terminal_outcome_roots(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    """Compute the ordered identity and canonical terminal-content roots."""

    identity_digest = hashlib.sha256()
    content_digest = hashlib.sha256()
    for expected_ordinal, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(
                f"terminal outcome row {expected_ordinal} must be an object"
            )
        if row.get("ordinal") != expected_ordinal:
            raise ValueError(
                "terminal outcome ordinals must be contiguous from zero"
            )
        record_id = row.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            raise ValueError(f"terminal outcome row {expected_ordinal} has no ID")
        _validate_terminal_outcome_row(row)
        identity_digest.update(record_id.encode("utf-8") + b"\n")
        content_digest.update(canonical_json(dict(row)))
    return {
        "ordered_identity_sha256": identity_digest.hexdigest(),
        "terminal_outcome_content_root_sha256": content_digest.hexdigest(),
    }


def validate_terminal_outcome_manifest(
    manifest: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    repository_root: Path | None = None,
    require_material_files: bool = False,
) -> None:
    """Validate uniqueness, denominator, chunk coverage and content roots."""

    if manifest.get("complete_denominator") is not True:
        raise ValueError("terminal manifest is not a complete denominator")
    counts = manifest.get("counts")
    input_row = manifest.get("input")
    roots = manifest.get("roots")
    chunks = manifest.get("chunks")
    if not all(
        isinstance(value, Mapping)
        for value in (counts, input_row, roots)
    ) or not isinstance(chunks, list):
        raise ValueError("terminal manifest structures are missing")

    record_ids = [row.get("record_id") for row in rows]
    if len(set(record_ids)) != len(record_ids):
        raise ValueError("terminal outcomes contain duplicate record IDs")
    run_ids = {row.get("run_id") for row in rows}
    if run_ids != {manifest.get("run_id")}:
        raise ValueError("terminal outcome rows do not share manifest run ID")
    validate_material_reference(
        manifest.get("row_schema", {}),
        repository_root=repository_root,
        require_regular_file=require_material_files,
    )
    for row in rows:
        for material in row.get("outcome_evidence", []):
            validate_material_reference(
                material,
                repository_root=repository_root,
                require_regular_file=require_material_files,
            )
    computed_roots = compute_terminal_outcome_roots(rows)
    if roots.get("ordered_identity_sha256") != computed_roots[
        "ordered_identity_sha256"
    ]:
        raise ValueError("terminal ordered identity root does not match rows")
    if roots.get("terminal_outcome_content_root_sha256") != computed_roots[
        "terminal_outcome_content_root_sha256"
    ]:
        raise ValueError("terminal content root does not match rows")
    if roots.get("ordered_identity_sha256") != input_row.get(
        "ordered_identity_sha256"
    ):
        raise ValueError("terminal identity root is not bound to input")
    if roots.get("ordered_input_projection_sha256") != input_row.get(
        "ordered_input_projection_sha256"
    ):
        raise ValueError("terminal input-projection root is not bound to input")

    denominator = input_row.get("eligible_records")
    expected_count = len(rows)
    if any(
        value != expected_count
        for value in (
            denominator,
            counts.get("eligible_records"),
            counts.get("terminal_outcomes"),
            counts.get("unique_record_ids"),
        )
    ):
        raise ValueError("terminal outcomes do not cover the full denominator")
    outcome_counts = Counter(row.get("outcome") for row in rows)
    declared_counts = counts.get("outcome_counts")
    if not isinstance(declared_counts, Mapping) or {
        name: outcome_counts.get(name, 0) for name in TERMINAL_OUTCOMES
    } != dict(declared_counts):
        raise ValueError("terminal manifest outcome counts do not match rows")

    next_ordinal = 0
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, Mapping):
            raise ValueError(f"terminal chunk {index} must be an object")
        validate_material_reference(
            chunk,
            repository_root=repository_root,
            require_regular_file=require_material_files,
        )
        chunk_count = chunk.get("records")
        chunk_start = chunk.get("ordinal_start")
        chunk_end = chunk.get("ordinal_end")
        if (
            isinstance(chunk_count, bool)
            or not isinstance(chunk_count, int)
            or chunk_count < 1
            or chunk_start != next_ordinal
            or chunk_end != chunk_start + chunk_count - 1
        ):
            raise ValueError("terminal chunks are not contiguous and exact")
        body = b"".join(
            canonical_json(dict(row))
            for row in rows[chunk_start : chunk_end + 1]
        )
        digest = hashlib.sha256(body).hexdigest()
        if chunk.get("content_root_sha256") != digest:
            raise ValueError(f"terminal chunk {index} content root is incorrect")
        if chunk.get("sha256") != digest:
            raise ValueError(
                f"terminal chunk {index} byte digest is not canonical NDJSON"
            )
        next_ordinal = chunk_end + 1
    if next_ordinal != expected_count:
        raise ValueError("terminal chunks do not cover every outcome row")


def validate_run_receipt(
    run: Mapping[str, Any],
    terminal_manifest: Mapping[str, Any],
    terminal_rows: Sequence[Mapping[str, Any]],
    *,
    repository_root: Path | None = None,
    require_material_files: bool = False,
) -> None:
    """Reconcile a final run with its exact roles and terminal denominator."""

    validate_terminal_outcome_manifest(
        terminal_manifest,
        terminal_rows,
        repository_root=repository_root,
        require_material_files=require_material_files,
    )
    run_id = run.get("run_id")
    if terminal_manifest.get("run_id") != run_id:
        raise ValueError("run and terminal manifest IDs differ")
    input_row = run.get("input")
    counts = run.get("counts")
    roles = run.get("roles")
    governance = run.get("governance")
    artifacts = run.get("artifacts")
    if not all(
        isinstance(value, Mapping)
        for value in (input_row, counts, roles, governance, artifacts)
    ):
        raise ValueError("run reconciliation structures are missing")
    for material in governance.values():
        validate_material_reference(
            material,
            repository_root=repository_root,
            require_regular_file=require_material_files,
        )
    for material in artifacts.values():
        validate_material_reference(
            material,
            repository_root=repository_root,
            require_regular_file=require_material_files,
        )

    manifest_input = terminal_manifest.get("input")
    input_pairs = (
        ("snapshot_id", "snapshot_id"),
        ("manifest_sha256", "source_manifest_sha256"),
        ("semantic_root_sha256", "source_semantic_root_sha256"),
        ("ordered_identity_sha256", "ordered_identity_sha256"),
        ("ordered_input_projection_sha256", "ordered_input_projection_sha256"),
        ("eligible_records", "eligible_records"),
    )
    for run_field, manifest_field in input_pairs:
        if input_row.get(run_field) != manifest_input.get(manifest_field):
            raise ValueError(
                f"run input {run_field} is not bound to terminal manifest"
            )

    generator = roles.get("generator")
    reviewer = roles.get("reviewer")
    strongest = roles.get("strongest")
    if not all(
        isinstance(value, Mapping)
        for value in (generator, reviewer, strongest)
    ):
        raise ValueError("run role receipts are missing")
    validate_model_role_separation(
        generator_exact_model_id=generator.get("returned_model"),
        reviewer_exact_model_id=reviewer.get("returned_model"),
        strongest_exact_model_id=strongest.get("returned_model"),
    )
    candidate_schema = governance.get("candidate_schema")
    review_schema = governance.get("review_schema")
    if not isinstance(candidate_schema, Mapping) or not isinstance(
        review_schema, Mapping
    ):
        raise ValueError("run response-schema bindings are missing")
    if generator.get("response_schema_sha256") != candidate_schema.get(
        "sha256"
    ):
        raise ValueError("generator is not bound to candidate schema")
    for role_name, role in (("reviewer", reviewer), ("strongest", strongest)):
        if role.get("response_schema_sha256") != review_schema.get("sha256"):
            raise ValueError(f"{role_name} is not bound to review schema")

    eligible = len(terminal_rows)
    records_with_candidates = sum(
        row["candidate_assertions"] > 0 for row in terminal_rows
    )
    expected_counts = {
        "eligible_records": eligible,
        "terminal_record_outcomes": eligible,
        "records_with_candidates": records_with_candidates,
        "records_without_candidates": eligible - records_with_candidates,
        "accepted_assertions": sum(
            row["accepted_assertions"] for row in terminal_rows
        ),
        "review_rejections": sum(
            row["review_rejections"] for row in terminal_rows
        ),
        "escalations": sum(row["escalations"] for row in terminal_rows),
    }
    if dict(counts) != expected_counts:
        raise ValueError("run counts do not reconcile to terminal outcomes")
    terminal_material = artifacts.get("terminal_outcome_manifest")
    if not isinstance(terminal_material, Mapping):
        raise ValueError("run does not bind its terminal-outcome manifest")
