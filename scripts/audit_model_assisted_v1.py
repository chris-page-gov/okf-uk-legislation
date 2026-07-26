#!/usr/bin/env python3
"""Independently audit and fail-close the legacy title-rule enrichment.

The v1 rule file is retained as immutable historical evidence.  This audit
reconstructs every assertion that the file would emit from the published work
titles, binds the reconstruction to stable digests, and applies a deliberately
generous precision ceiling: every assertion not in the exhaustively reviewed
false-positive populations is assumed correct.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "bundle"
RULE_PATH = ROOT / "enrichment" / "model-assisted-v1.json"
AUDIT_JSON_PATH = ROOT / "enrichment" / "model-assisted-v1-independent-audit.json"
AUDIT_MARKDOWN_PATH = ROOT / "enrichment" / "model-assisted-v1-independent-audit.md"

sys.path.insert(0, str(ROOT / "scripts"))
import build_legislation_okf as legislation  # noqa: E402

GENERATED_AT = "2026-07-25T23:25:42Z"
PRECISION_THRESHOLD = 0.95
EVIDENCE_SUPPORT_THRESHOLD = 0.95
EXPECTED_RULE_SHA256 = (
    "819030b842a6eedd88ddec35ac526c718689c7cd1a4577a9c64ef802a879d4dc"
)
EXPECTED_ENTITY_ASSERTIONS = 18_135
EXPECTED_ENTITY_POPULATION_SHA256 = (
    "d01009ea8e100a67d859c734e1a63f2586831592aa2367364699528b9156933e"
)
EXPECTED_RELATIONSHIP_POPULATION_SHA256 = (
    "c453f2318238e8cb9743cedae3cbec5e4eec36ff9ef7756e083f524fa49758af"
)
EXPECTED_TOPIC_ASSERTIONS = 562
EXPECTED_TOPIC_POPULATION_SHA256 = (
    "15d974945b43e1646ab3edfee042e3e1ff54841e21e44e9465b0d5631bbca4be"
)

# These label populations were reviewed exhaustively, not sampled.  In every
# occurrence the extracted string is a generic legal/service phrase, a
# truncated prefix, or a class rather than the named public body or office
# required by the v1 prompt.  The population alone is sufficient to put the
# most generous possible precision below the release threshold.
DEFINITE_FALSE_LABELS = {
    "The Public Service": (
        "Generic prefix in titles such as Public Service Pensions and Public "
        "Service Vehicles; it does not name a public body or office."
    ),
    "The Council": (
        "Truncated or generic prefix, predominantly from Council Tax titles; "
        "it does not identify a named council."
    ),
    "Public Service": (
        "Generic description of public service or a modifier of vehicles and "
        "pensions, not a named body or office."
    ),
    "War Service": (
        "A type or period of service used in pension and superannuation "
        "titles, not an organisation."
    ),
    "The Service": (
        "Truncated prefix in Service Police, Service Address and similar "
        "titles, not an identified organisation."
    ),
    "Remediable Service": (
        "A pension-remedy service-period concept, not an organisation."
    ),
    "National Service": (
        "A statutory service obligation or service period, not a named public "
        "body or office."
    ),
}

# Deterministic cross-suffix review: the three most frequent labels and two
# SHA-256-selected singleton labels for every suffix.  These decisions are
# corroborative; the release failure is established by the exhaustive
# false-population ceiling above, so ambiguous rows never count against v1.
STRATIFIED_DECISIONS: dict[str, tuple[str, str]] = {
    "The Council": ("false", "Generic/truncated prefix, chiefly Council Tax."),
    "London County Council": ("true", "Complete named local authority."),
    "The General Medical Council": ("true", "Complete named regulator."),
    "Auchterarder Town Council": ("true", "Complete named local authority."),
    "Salford City Council": ("true", "Complete named local authority."),
    "The Anglian Water Authority": ("true", "Complete named authority."),
    "High Authority": ("true", "Historical ECSC institution named in context."),
    "The Greater London Authority": ("true", "Complete named authority."),
    "The Lancaster Port Health Authority": ("true", "Complete named authority."),
    "South West Hampshire Health Authority": ("true", "Complete named authority."),
    "European Commission": ("true", "Complete named institution."),
    "United Nations Economic Commission": (
        "false",
        "Truncated before 'for Europe'; target does not identify the full body.",
    ),
    "The Commission": ("false", "Generic/truncated prefix."),
    "Twenty-Fourth Commission": (
        "false",
        "Ordinal modifier of a Commission Directive, not an organisation name.",
    ),
    "The Londonderry Development Commission": (
        "true",
        "Complete named commission.",
    ),
    "Local Government Board": ("true", "Complete historical named board."),
    "Construction Board": (
        "ambiguous",
        "May abbreviate a statutory training board; excluded from scoring.",
    ),
    "Management Board": ("false", "Generic board class or truncated phrase."),
    "The Welland River Board": ("true", "Complete named board."),
    "Wood Green Local Board": ("true", "Complete named local board."),
    "Works Agency": (
        "false",
        "Truncated from United Nations Relief and Works Agency.",
    ),
    "European Agency": (
        "false",
        "Truncated before the agency's functional name.",
    ),
    "Euratom Supply Agency": ("true", "Complete named agency."),
    "European Railway Agency": ("true", "Complete named agency."),
    "Appropriate Agency": ("false", "Generic statutory role, not a named agency."),
    "Post Office": ("true", "Complete named institution."),
    "The Post Office": ("true", "Complete named institution."),
    "The Office": ("false", "Truncated prefix, for example Office of Communications."),
    "State Forests Office": ("true", "Named office in the source-title context."),
    "Accountant General's Office": ("true", "Complete named office."),
    "The National Health Service": ("true", "Named public service/institution."),
    "The Public Service": ("false", "Generic or truncated service phrase."),
    "National Health Service": ("true", "Named public service/institution."),
    "Nationalealth Service": (
        "false",
        "Malformed source-title token; not a valid entity label.",
    ),
    "The Dundee Healthcare National Health Service": (
        "false",
        "Truncated before 'Trust'; not the complete organisation name.",
    ),
    "The First-tier Tribunal": ("true", "Complete named tribunal."),
    "The Lands Tribunal": ("true", "Complete named tribunal."),
    "Upper Tribunal": ("true", "Complete named tribunal."),
    "The Scottish Solicitors' Discipline Tribunal": (
        "true",
        "Complete named tribunal.",
    ),
    "The Consumer Credit Appeals Tribunal": (
        "true",
        "Complete named tribunal.",
    ),
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_digest(rows: Iterable[dict[str, Any]]) -> str:
    rendered = [
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for row in rows
    ]
    digest = hashlib.sha256()
    for row in sorted(rendered):
        digest.update(row.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_gzip_json(path: Path) -> Any:
    return json.loads(gzip.decompress(path.read_bytes()))


def iter_works(manifest: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for relative in manifest["chunks"]["datasets"]:
        yield from load_gzip_json(PACK / relative)


def compile_entity_pattern(suffixes: list[str]) -> re.Pattern[str]:
    escaped = [re.escape(value) for value in suffixes]
    return re.compile(
        rf"\b((?:[A-Z][\w’'&.-]*\s+){{1,6}}(?:{'|'.join(escaped)}))\b"
    )


def reconstruct(
    works: list[dict[str, Any]],
    rule_document: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    suffixes = [
        str(value)
        for value in rule_document["rules"].get("entity_suffixes", [])
        if value
    ]
    entity_pattern = compile_entity_pattern(suffixes)
    entities: list[dict[str, str]] = []
    topics: list[dict[str, str]] = []
    for work in works:
        route = str(work["route"])
        title = str(work["title"])
        lowered = title.lower()
        for match in sorted(
            {item.group(1).strip() for item in entity_pattern.finditer(title)}
        ):
            entities.append({"route": route, "label": match, "title": title})

        applied_topics = [
            label
            for label, pattern in legislation.TOPIC_RULES
            if re.search(pattern, lowered)
        ]
        for rule in rule_document["rules"].get("topic_keywords", []):
            topic = str(rule.get("topic", ""))
            keyword = str(rule.get("keyword", "")).lower().strip()
            if topic and keyword and keyword in lowered and topic not in applied_topics:
                applied_topics.append(topic)
                topics.append(
                    {
                        "route": route,
                        "topic": topic,
                        "keyword": keyword,
                        "title": title,
                    }
                )
        code = str(work.get("type_code", ""))
        if (
            code in legislation.EU_CODES
            and "European Union and retained EU law" not in applied_topics
        ):
            applied_topics.append("European Union and retained EU law")
    return entities, topics


def example_by_label(
    entity_rows: list[dict[str, str]],
) -> dict[str, dict[str, str]]:
    examples: dict[str, dict[str, str]] = {}
    for row in entity_rows:
        examples.setdefault(
            row["label"],
            {"route": row["route"], "title": row["title"]},
        )
    return examples


def stratified_review(
    entity_rows: list[dict[str, str]],
    suffixes: list[str],
) -> list[dict[str, Any]]:
    labels_by_suffix: dict[str, Counter[str]] = defaultdict(Counter)
    examples = example_by_label(entity_rows)
    for row in entity_rows:
        label = row["label"]
        suffix = next(value for value in suffixes if label.endswith(value))
        labels_by_suffix[suffix][label] += 1

    review: list[dict[str, Any]] = []
    for suffix in suffixes:
        counts = labels_by_suffix[suffix]
        dominant = [
            label
            for label, _count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0])
            )[:3]
        ]
        singleton_candidates = [
            label for label, count in counts.items() if count == 1
        ]
        tail = sorted(
            singleton_candidates,
            key=lambda label: hashlib.sha256(
                f"{suffix}\0{label}".encode("utf-8")
            ).hexdigest(),
        )[:2]
        for band, labels in (("dominant", dominant), ("tail-singleton", tail)):
            for label in labels:
                if label not in STRATIFIED_DECISIONS:
                    raise RuntimeError(
                        f"stratified decision is missing for {suffix}: {label}"
                    )
                verdict, rationale = STRATIFIED_DECISIONS[label]
                review.append(
                    {
                        "suffix": suffix,
                        "band": band,
                        "label": label,
                        "population_count": counts[label],
                        "example": examples[label],
                        "verdict": verdict,
                        "rationale": rationale,
                    }
                )
    return review


def build_audit() -> dict[str, Any]:
    rule_bytes = RULE_PATH.read_bytes()
    rule_sha256 = sha256_bytes(rule_bytes)
    if rule_sha256 != EXPECTED_RULE_SHA256:
        raise RuntimeError(
            "legacy v1 rule artifact changed: "
            f"expected {EXPECTED_RULE_SHA256}, got {rule_sha256}"
        )
    rule_document = json.loads(rule_bytes)
    manifest = load_json(PACK / "data" / "manifest.json")
    works = list(iter_works(manifest))
    entity_rows, topic_rows = reconstruct(works, rule_document)
    relationship_rows = [
        {"route": row["route"], "label": row["label"]}
        for row in entity_rows
    ]
    entity_digest = canonical_digest(entity_rows)
    relationship_digest = canonical_digest(relationship_rows)
    topic_digest = canonical_digest(topic_rows)
    expected = (
        (len(entity_rows), EXPECTED_ENTITY_ASSERTIONS, "entity assertion count"),
        (
            entity_digest,
            EXPECTED_ENTITY_POPULATION_SHA256,
            "entity assertion digest",
        ),
        (
            relationship_digest,
            EXPECTED_RELATIONSHIP_POPULATION_SHA256,
            "relationship assertion digest",
        ),
        (len(topic_rows), EXPECTED_TOPIC_ASSERTIONS, "topic assertion count"),
        (
            topic_digest,
            EXPECTED_TOPIC_POPULATION_SHA256,
            "topic assertion digest",
        ),
    )
    for actual, wanted, label in expected:
        if actual != wanted:
            raise RuntimeError(f"{label} changed: expected {wanted}, got {actual}")

    label_counts = Counter(row["label"] for row in entity_rows)
    suffixes = [
        str(value) for value in rule_document["rules"]["entity_suffixes"]
    ]
    suffix_counts = Counter(
        next(value for value in suffixes if row["label"].endswith(value))
        for row in entity_rows
    )
    false_populations = [
        {
            "label": label,
            "count": label_counts[label],
            "reason": reason,
            "example": example_by_label(entity_rows)[label],
        }
        for label, reason in DEFINITE_FALSE_LABELS.items()
    ]
    proven_false = sum(row["count"] for row in false_populations)
    maximum_possible_true = len(entity_rows) - proven_false
    precision_ceiling = maximum_possible_true / len(entity_rows)
    evidence_supported = sum(
        1
        for row in entity_rows
        if row["label"] in row["title"]
        and any(row["label"].endswith(value) for value in suffixes)
        and row["route"]
    )
    evidence_support = evidence_supported / len(entity_rows)
    reviewed = stratified_review(entity_rows, suffixes)
    review_counts = Counter(row["verdict"] for row in reviewed)

    return {
        "schema": "okf-independent-enrichment-audit.v1",
        "generated_at": GENERATED_AT,
        "subject": {
            "path": RULE_PATH.relative_to(ROOT).as_posix(),
            "sha256": rule_sha256,
            "schema": rule_document.get("schema"),
            "claimed_review_status": rule_document.get("review_status"),
            "preservation": "immutable-historical-evidence",
        },
        "scope": {
            "source": "published legislation work titles",
            "historical_entity_assertions": len(entity_rows),
            "historical_topic_assertions": len(topic_rows),
            "rule_suffixes": suffixes,
            "precision_threshold": PRECISION_THRESHOLD,
            "evidence_support_threshold": EVIDENCE_SUPPORT_THRESHOLD,
        },
        "reconstruction": {
            "entity_assertions": len(entity_rows),
            "entity_population_sha256": entity_digest,
            "relationship_population_sha256": relationship_digest,
            "topic_assertions": len(topic_rows),
            "topic_population_sha256": topic_digest,
            "exact_historical_relationship_match": True,
            "method": (
                "Re-executed the literal title regex and topic-keyword sequence "
                "from source titles; compared canonical route/label and "
                "route/topic populations with the pre-rejection publication."
            ),
        },
        "evidence_validity": {
            "supported": evidence_supported,
            "population": len(entity_rows),
            "rate": round(evidence_support, 9),
            "threshold": EVIDENCE_SUPPORT_THRESHOLD,
            "passed": evidence_support >= EVIDENCE_SUPPORT_THRESHOLD,
            "checks": [
                "source route is present",
                "entity label is an exact case-sensitive source-title substring",
                "entity label ends with one of the declared suffixes",
                "canonical reconstructed relationship population matches the historical publication",
            ],
            "interpretation": (
                "Literal support is complete, but literal occurrence does not "
                "establish that the extracted phrase denotes a named entity."
            ),
        },
        "precision_assessment": {
            "method": (
                "Exhaustive conservative upper bound. Seven indisputable "
                "false-positive label populations were reviewed in every "
                "occurrence. Every other assertion, including ambiguous rows, "
                "is assumed true to maximize v1's possible precision."
            ),
            "proven_false": proven_false,
            "maximum_possible_true": maximum_possible_true,
            "population": len(entity_rows),
            "precision_ceiling": round(precision_ceiling, 9),
            "threshold": PRECISION_THRESHOLD,
            "passed": precision_ceiling >= PRECISION_THRESHOLD,
            "false_populations": false_populations,
        },
        "population_profile": {
            "unique_labels": len(label_counts),
            "by_suffix": {
                suffix: {
                    "assertions": suffix_counts[suffix],
                    "unique_labels": len(
                        {
                            row["label"]
                            for row in entity_rows
                            if row["label"].endswith(suffix)
                        }
                    ),
                }
                for suffix in suffixes
            },
            "dominant_and_tail_stratified_review": {
                "selection": (
                    "For each suffix: three highest-frequency labels plus two "
                    "SHA-256-selected singleton labels."
                ),
                "reviewed": len(reviewed),
                "verdict_counts": dict(sorted(review_counts.items())),
                "rows": reviewed,
                "use_in_threshold": (
                    "Corroborative only; no extrapolation. The exhaustive "
                    "precision ceiling determines the release decision."
                ),
            },
        },
        "affected_outputs": {
            "entity_assertions_rejected": len(entity_rows),
            "topic_assertions_rejected": len(topic_rows),
            "total_v1_assertions_rejected": len(entity_rows) + len(topic_rows),
            "governed_v1_assertions_permitted": 0,
            "audited_v2_unchanged": True,
        },
        "decision": {
            "verdict": "rejected-fail-closed",
            "release_gate_passed": False,
            "reason": (
                f"Even granting every unproven row as correct, precision can "
                f"be no higher than {precision_ceiling:.4%}, below the "
                f"{PRECISION_THRESHOLD:.0%} release threshold."
            ),
            "required_policy": [
                "retain the original v1 rule artifact as historical evidence",
                "publish this hash-bound independent audit beside it",
                "apply none of the v1 entity-suffix or topic-keyword rules",
                "exclude all v1 assertions from core graph and governed-model totals",
                "do not change or reclassify independently audited v2 assertions",
            ],
        },
    }


def render_markdown(audit: dict[str, Any]) -> str:
    precision = audit["precision_assessment"]
    evidence = audit["evidence_validity"]
    affected = audit["affected_outputs"]
    lines = [
        "# Independent audit of `model-assisted-v1`",
        "",
        f"**Decision:** `{audit['decision']['verdict']}`",
        "",
        (
            f"The legacy rule file is preserved unchanged at "
            f"`{audit['subject']['path']}` with SHA-256 "
            f"`{audit['subject']['sha256']}`. Its self-labelled "
            f"`{audit['subject']['claimed_review_status']}` state is not "
            "accepted by this audit."
        ),
        "",
        "## Result",
        "",
        (
            f"All {evidence['supported']:,} of {evidence['population']:,} "
            f"reconstructed entity rows have literal title/suffix evidence "
            f"({evidence['rate']:.1%}). Literal matching is therefore "
            "reproducible, but it does not prove that the phrase names an entity."
        ),
        "",
        (
            f"Exhaustive review proves at least {precision['proven_false']:,} "
            f"false assertions. Even assuming every other row is correct, "
            f"precision is at most **{precision['precision_ceiling']:.4%}**, "
            f"below the {precision['threshold']:.0%} gate."
        ),
        "",
        (
            f"The fail-closed policy rejects {affected['entity_assertions_rejected']:,} "
            f"entity and {affected['topic_assertions_rejected']:,} topic "
            f"assertions ({affected['total_v1_assertions_rejected']:,} total). "
            "Audited v2 output is unchanged."
        ),
        "",
        "## Exhaustive false-positive populations",
        "",
        "| Label | Rows | Why it is not the required named entity |",
        "| --- | ---: | --- |",
    ]
    for row in precision["false_populations"]:
        lines.append(
            f"| `{row['label']}` | {row['count']:,} | {row['reason']} |"
        )
    lines.extend(
        [
            "",
            "## Suffix coverage",
            "",
            "| Suffix | Assertions | Unique labels |",
            "| --- | ---: | ---: |",
        ]
    )
    for suffix, row in audit["population_profile"]["by_suffix"].items():
        lines.append(
            f"| {suffix} | {row['assertions']:,} | {row['unique_labels']:,} |"
        )
    lines.extend(
        [
            "",
            "## Dominant and tail review",
            "",
            (
                "For every suffix, the three most frequent labels and two "
                "deterministically selected singleton labels were inspected. "
                "This cross-stratum review is corroborative and is not "
                "extrapolated; ambiguous rows are not counted as false."
            ),
            "",
            "| Suffix | Band | Label | Population | Verdict | Rationale |",
            "| --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for row in audit["population_profile"][
        "dominant_and_tail_stratified_review"
    ]["rows"]:
        lines.append(
            f"| {row['suffix']} | {row['band']} | `{row['label']}` | "
            f"{row['population_count']:,} | {row['verdict']} | "
            f"{row['rationale']} |"
        )
    lines.extend(
        [
            "",
            "## Enforcement",
            "",
            *[f"- {item}" for item in audit["decision"]["required_policy"]],
            "",
            "## Reproduction",
            "",
            "```sh",
            "python3 scripts/audit_model_assisted_v1.py --check",
            "```",
            "",
            (
                "The check reconstructs the bound populations and also fails "
                "if any rejected v1 entity or model-assisted topic assertion "
                "remains in the generated core bundle."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def current_rejected_output_counts() -> tuple[int, int]:
    manifest = load_json(PACK / "data" / "manifest.json")
    mentions = 0
    for relative in manifest["chunks"]["relationships"]:
        mentions += sum(
            1
            for row in load_gzip_json(PACK / relative)
            if row.get("kind") == "mentions entity"
            or row.get("evidence_type") == "model-assisted-entity-pattern"
        )
    assisted_topics = 0
    for work in iter_works(manifest):
        assisted_topics += len(
            work.get("semantic_enrichment", {}).get("model_assisted_topics", [])
        )
    return mentions, assisted_topics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    audit = build_audit()
    json_body = (
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    markdown_body = render_markdown(audit)
    if args.check:
        errors: list[str] = []
        for path, expected in (
            (AUDIT_JSON_PATH, json_body),
            (AUDIT_MARKDOWN_PATH, markdown_body),
        ):
            if not path.is_file():
                errors.append(f"missing audit artifact: {path.relative_to(ROOT)}")
            elif path.read_text(encoding="utf-8") != expected:
                errors.append(
                    f"audit artifact is stale: {path.relative_to(ROOT)}"
                )
        mentions, assisted_topics = current_rejected_output_counts()
        if mentions:
            errors.append(
                f"generated core still contains {mentions:,} rejected v1 entity assertions"
            )
        if assisted_topics:
            errors.append(
                f"generated works still contain {assisted_topics:,} rejected v1 topic assertions"
            )
        if errors:
            print("Legacy v1 independent audit check failed:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
        print(
            "Legacy v1 independent audit check passed: "
            f"{EXPECTED_ENTITY_ASSERTIONS:,} entity and "
            f"{EXPECTED_TOPIC_ASSERTIONS:,} topic assertions rejected; "
            "0 published in core"
        )
        return 0
    AUDIT_JSON_PATH.write_text(json_body, encoding="utf-8")
    AUDIT_MARKDOWN_PATH.write_text(markdown_body, encoding="utf-8")
    mentions, assisted_topics = current_rejected_output_counts()
    print(
        f"wrote independent v1 audit; current generated core contains "
        f"{mentions:,} legacy entity and {assisted_topics:,} legacy topic "
        "assertions pending fail-closed rebuild"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
