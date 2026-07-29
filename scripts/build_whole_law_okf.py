#!/usr/bin/env python3
"""Build the UK Whole-Law OKF federation from governed research inputs.

The research package is immutable evidence. This builder projects it into an
OKF 0.2 Markdown publication, federation descriptor, source-family catalogue,
coverage/constraint ledgers and standards artefacts without changing the
original files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

import rdflib
from pyld import jsonld

import build_legislation_okf as legislation_builder

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "whole-law"
RESEARCH = ROOT / "research" / "whole-law-okf-research"
OUTPUT = ROOT / "bundle" / "whole-law"
LEGISLATION_DESCRIPTOR = ROOT / "bundle" / "okf-explorer.json"
GENERATED_AT = "2026-07-25T22:54:00Z"
PUBLIC = "https://chris-page-gov.github.io/okf-uk-legislation"
NAMESPACE = f"{PUBLIC}/profile/whole-law/v1#"
OGL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"

RESEARCH_EXPORTS = {
    "source-register.json",
    "source-register.csv",
    "legal-source-taxonomy.json",
    "persona-task-matrix.json",
    "persona-task-matrix.csv",
    "ontology-crosswalk.json",
    "architecture-adrs.json",
    "gap-register.json",
    "adversarial-audit.json",
    "whole-law-evaluation-plan.json",
    "whole-law-evaluation-questions.json",
    "answer-schema-proposal.json",
    "coverage-ledger.schema.json",
    "coverage-ledger.example.json",
    "migration-backlog.json",
    "traceability.json",
    "integrity.json",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def render_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def render_canonical_turtle(document: dict[str, Any]) -> bytes:
    """Render the JSON-LD dataset as deterministic canonical N-Triples.

    RDFC-1.0/URDNA2015 emits N-Quads.  This descriptor uses only the RDF
    default graph, so its normalized statements are also valid N-Triples and
    therefore valid Turtle.  Parsing the result as Turtle makes that
    default-graph constraint fail closed if the semantic model later changes.
    """

    normalized = jsonld.normalize(
        document,
        {
            "algorithm": "URDNA2015",
            "format": "application/n-quads",
        },
    )
    try:
        rdflib.Graph().parse(data=normalized, format="turtle")
    except Exception as exc:
        raise ValueError(
            "canonical semantic descriptor is not a Turtle-compatible "
            "default-graph serialization"
        ) from exc
    return normalized.encode("utf-8")


def slugify(value: str) -> str:
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-") or "item"


def actor_source(resource: str, title: str) -> list[dict[str, str]]:
    return [{"id": "research-source", "resource": resource, "title": title}]


def concept(
    type_name: str,
    title: str,
    description: str,
    resource: str,
    tags: Iterable[str],
    body: str,
    *,
    status: str = "draft",
    stale_after: str | None = None,
) -> str:
    values: list[tuple[str, Any]] = [
        ("type", type_name),
        ("title", title),
        ("description", description),
        ("generated", {"by": "process:whole-law-okf-builder", "at": GENERATED_AT}),
        ("status", status),
        ("sources", actor_source(resource, title)),
        ("tags", sorted(set(tags))),
    ]
    if stale_after:
        values.append(("stale_after", stale_after))
    frontmatter = "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}"
        for key, value in values
    )
    return f"---\n{frontmatter}\n---\n\n# {title}\n\n{description}\n\n{body.strip()}\n"


def normalized_access(status: str) -> str:
    value = status.lower()
    if "verified working" in value:
        return "available"
    if "authenticated" in value or "restricted" in value:
        return "restricted"
    if "unavailable" in value or "deprecated" in value:
        return "unavailable"
    if "documented" in value or "inferred" in value or "untested" in value:
        return "planned"
    return "unknown"


def source_family_status(source_class_id: str, source_records: list[dict[str, Any]]) -> str:
    records = [
        row for row in source_records
        if source_class_id in row.get("source_classes", [])
    ]
    states = {
        normalized_access(method.get("status", ""))
        for row in records
        for method in row.get("access_methods", [])
    }
    if source_class_id in {"SC01", "SC02"}:
        return "available"
    if source_class_id in {"SC03", "SC04", "SC05", "SC06", "SC07"}:
        return "partial"
    if states and states <= {"restricted", "unavailable"}:
        return "restricted" if "restricted" in states else "unavailable"
    if "available" in states:
        return "partial"
    return "planned"


def build_constraints(source_register: dict[str, Any]) -> dict[str, Any]:
    constraints: list[dict[str, str]] = []
    serial = 1
    for source in source_register["records"]:
        source_id = source["id"]
        fair_use = str(source.get("fair_use_rate_limit_robots", "")).strip()
        if fair_use:
            constraints.append({
                "id": f"CON-{serial:03d}",
                "source_id": source_id,
                "kind": "fair-use",
                "trigger": fair_use,
                "effect": "Bulk acquisition must use source-aware pacing, caching and resumable requests; functionality remains represented.",
                "mitigation": "Use frozen envelopes, conditional requests, filtered feeds and source-specific schedules.",
                "owner": "UK Whole-Law OKF maintainer",
                "escalation_state": "mitigated",
            })
            serial += 1
        licence = str(source.get("licence_and_reuse", "")).strip()
        if licence:
            constraints.append({
                "id": f"CON-{serial:03d}",
                "source_id": source_id,
                "kind": "licence",
                "trigger": licence,
                "effect": "Rights and permitted redistribution can vary by item and manifestation.",
                "mitigation": "Retain item-level rights; publish metadata and links when redistribution rights are not established.",
                "owner": "UK Whole-Law OKF rights review",
                "escalation_state": "recorded",
            })
            serial += 1
        statuses = {
            normalized_access(method.get("status", ""))
            for method in source.get("access_methods", [])
        }
        if "restricted" in statuses:
            constraints.append({
                "id": f"CON-{serial:03d}",
                "source_id": source_id,
                "kind": "authentication",
                "trigger": "At least one researched route is authenticated or otherwise restricted.",
                "effect": "The public prototype cannot acquire restricted content without separately supplied authority.",
                "mitigation": "Publish adapter, coverage and access metadata; do not bypass authentication.",
                "owner": "Source owner and UK Whole-Law OKF maintainer",
                "escalation_state": "escalated",
            })
            serial += 1
        if "unavailable" in statuses:
            constraints.append({
                "id": f"CON-{serial:03d}",
                "source_id": source_id,
                "kind": "availability",
                "trigger": "At least one researched route was unavailable on the recorded test date.",
                "effect": "Live verification and acquisition cannot be asserted for that route.",
                "mitigation": "Retain the dated observation, use documented alternatives and re-test on schedule.",
                "owner": "UK Whole-Law OKF source monitoring",
                "escalation_state": "recorded",
            })
            serial += 1
    constraints.append({
        "id": f"CON-{serial:03d}",
        "source_id": "PUBLICATION",
        "kind": "hosting",
        "trigger": "GitHub Pages serves .yamlld as application/octet-stream.",
        "effect": "YAML-LD document conformance is testable, but strict HTTP media-type conformance cannot be claimed.",
        "mitigation": "Publish JSON-LD and release downloads; content-sniff .yamlld in Explorer; configure application/ld+yaml on the later permanent host.",
        "owner": "UK Whole-Law OKF publication",
        "escalation_state": "accepted-prototype-risk",
    })
    return {
        "schema": "okf-source-constraint-ledger.v1",
        "generated_at": GENERATED_AT,
        "constraints": constraints,
    }


def source_family_rows(
    taxonomy: dict[str, Any],
    source_register: dict[str, Any],
) -> list[dict[str, Any]]:
    sources = source_register["records"]
    result = []
    for row in taxonomy["classes"]:
        source_ids = [
            source["id"]
            for source in sources
            if row["id"] in source.get("source_classes", [])
        ]
        result.append({
            "id": row["id"],
            "title": row["label"],
            "authority_class": row["primary_authority_class"],
            "coverage_status": source_family_status(row["id"], sources),
            "source_ids": source_ids,
            "source_count": len(source_ids),
            "implemented_bundle": (
                f"{PUBLIC}/okf-explorer.json"
                if row["id"] in {"SC01", "SC02", "SC03", "SC04", "SC05", "SC06", "SC07"}
                else None
            ),
            "definition": row["definition_and_legal_force"],
            "minimum_provenance": row["minimum_provenance"],
            "related_source_classes": row.get("relationships_to_other_classes", []),
        })
    return result


def relationship_summary() -> dict[str, Any]:
    source = load(ROOT / "bundle" / "data" / "relationship-summary.json")
    legislation = load(LEGISLATION_DESCRIPTOR)
    effects = load(ROOT / "bundle" / "data" / "effects" / "manifest.json")
    effects_reconciliation = load(
        ROOT / "bundle" / "data" / "effects" / "reconciliation.json"
    )
    governed_v3 = legislation_builder.load_governed_model_enrichment_v3()
    if any(
        row.get("datapack") == "codex-assisted-v2"
        for row in source.get("relationships", [])
    ):
        raise ValueError(
            "active relationship summary still contains historical v2 rows"
        )
    published_v3 = sum(
        int(row["count"])
        for row in source.get("relationships", [])
        if row.get("datapack") == "codex-assisted-v3"
    )
    if published_v3 != governed_v3["counts"]["assertions"]:
        raise ValueError(
            "active relationship summary does not reconcile to accepted v3"
        )
    predicates: Counter[str] = Counter()
    authorities: Counter[str] = Counter()
    freshness: Counter[str] = Counter()
    authority_map = {
        "official-source": "official",
        "derived-non-official": "derived",
        "source-derived": "derived",
        "model-assisted": "model-assisted",
        "human-reviewed": "derived",
    }

    def parsed(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )

    def rendered(value: datetime) -> str:
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )

    core_observed = str(legislation["generated_at"])
    effects_observed = str(effects["generated_at"])
    enrichment_observed = str(governed_v3["manifest"]["generated_at"])
    v3_stale_after = (
        min(str(row["stale_after"]) for row in governed_v3["rows"])
        if governed_v3["rows"]
        else rendered(parsed(enrichment_observed) + timedelta(days=31))
    )
    datapack_policy = {
        "core": {
            "assertion_contract": "okf-core-relationship-row.v1",
            "observed_at": core_observed,
            "stale_after": rendered(parsed(core_observed) + timedelta(days=31)),
            "refresh_window": "P31D",
            "notes": (
                "Legacy compact core rows are a versioned projection. "
                "Snapshot currency is not a claim that every provision is current law."
            ),
        },
        "legislation-effects": {
            "assertion_contract": "okf-relationship-assertion.v2",
            "observed_at": effects_observed,
            "stale_after": rendered(parsed(effects_observed) + timedelta(days=7)),
            "refresh_window": "P7D",
            "notes": (
                "Only assertions materialised from successful frozen official routes "
                "are counted; inaccessible reconciliation routes are reported separately."
            ),
        },
        "codex-assisted-v3": {
            "assertion_contract": "okf-relationship-assertion.v2",
            "observed_at": enrichment_observed,
            "stale_after": v3_stale_after,
            "refresh_window": "governed-v3-assertion-window",
            "notes": (
                "Only independently accepted topic, concept and entity-link "
                "assertions are active. Candidate and historical v2 rows are excluded."
            ),
        },
    }
    generated = parsed(GENERATED_AT)
    by_datapack: dict[str, dict[str, Any]] = {}
    for row in source["relationships"]:
        count = int(row["count"])
        datapack = str(row["datapack"])
        predicates[row["predicate"]] += count
        authorities[authority_map.get(row["authority"], "derived")] += count
        policy = datapack_policy.get(datapack)
        state = (
            "unknown"
            if policy is None
            else (
                "stale"
                if generated > parsed(str(policy["stale_after"]))
                else "current"
            )
        )
        freshness[state] += count
        summary = by_datapack.setdefault(
            datapack,
            {
                **(
                    policy
                    if policy is not None
                    else {
                        "assertion_contract": "unknown",
                        "observed_at": None,
                        "stale_after": None,
                        "refresh_window": None,
                        "notes": "No freshness policy is registered for this datapack.",
                    }
                ),
                "count": 0,
                "freshness": state,
            },
        )
        summary["count"] += count
    total = int(source["combined_total"])
    return {
        "scope": "federated-data-plane",
        "total": total,
        "by_predicate": dict(sorted(predicates.items())),
        "by_authority": {
            "official": authorities["official"],
            "derived": authorities["derived"],
            "model-assisted": authorities["model-assisted"],
        },
        "by_freshness": {
            "current": freshness["current"],
            "stale": freshness["stale"],
            "unknown": freshness["unknown"],
        },
        "by_datapack": dict(sorted(by_datapack.items())),
        "freshness_semantics": (
            "`current` means the frozen datapack is inside its declared refresh "
            "window. It does not mean that every legal provision is in force, "
            "unamended or suitable for reliance without live verification."
        ),
        "reconciliation_routes": effects_reconciliation["states"],
        "observed_at": GENERATED_AT,
        "snapshot": "whole-law-2026-07-25",
    }


def descriptor(
    source_register: dict[str, Any],
    taxonomy: dict[str, Any],
    families: list[dict[str, Any]],
    relations: dict[str, Any],
) -> dict[str, Any]:
    legislation = load(LEGISLATION_DESCRIPTOR)
    work_count = int(legislation["counts"]["works"])
    combined_relationships = int(
        legislation["counts"]["relationships_with_external_datapacks"]
    )
    child = {
        "id": "uk-legislation",
        "title": legislation["title"],
        "description": legislation["description"],
        "role": "legislation-source-family",
        "status": "available",
        # Descriptor-relative identity keeps local previews, branch deploys and
        # the canonical Pages deployment on the same data plane.  Canonical
        # public/raw routes remain explicit fallbacks below.
        "descriptor": "../okf-explorer.json",
        "semantic_descriptor": "../okf-bundle.yamlld",
        "authority": {
            "class": "official",
            "label": "Official publication identities and source-derived legal effects",
            "source": "https://www.legislation.gov.uk/",
        },
        "coverage": {
            "status": "available",
            "applicable": work_count,
            "represented": work_count,
            "assertions": combined_relationships,
            "percent": 100,
            "as_of": "2026-07-25",
            "notes": [
                "The work index is complete against its recorded official enumeration.",
                "Full text, effects and source-family coverage remain explicitly partial.",
            ],
        },
        "freshness": {
            "state": "current",
            "observed_at": legislation["generated_at"],
            "snapshot": legislation.get(
                "snapshot",
                "legislation-work-index-2026-07-11T18:00:00Z",
            ),
            "stale_after": "2026-08-11T18:00:00Z",
        },
        "discovery": {
            "repository": "https://github.com/chris-page-gov/okf-uk-legislation",
            "documentation": f"{PUBLIC}/",
            "raw_subpath": "bundle",
            "release_archive": "https://github.com/chris-page-gov/okf-uk-legislation/releases",
            "semantic_descriptor": f"{PUBLIC}/okf-bundle.yamlld",
            "routes": [
                {
                    "kind": "descriptor-relative",
                    "purpose": "descriptor",
                    "priority": 0,
                    "url": "../okf-explorer.json",
                },
                {
                    "kind": "published",
                    "purpose": "descriptor",
                    "priority": 10,
                    "url": legislation["@id"],
                },
                {
                    "kind": "raw",
                    "purpose": "descriptor",
                    "priority": 20,
                    "url": (
                        "https://raw.githubusercontent.com/chris-page-gov/"
                        "okf-uk-legislation/main/bundle/okf-explorer.json"
                    ),
                },
            ],
        },
        "counts": {
            "works": work_count,
            "relationships": combined_relationships,
            "official_effect_relationships": int(
                legislation["counts"].get("official_effect_relationships", 0)
            ),
            "historical_model_assisted_relationships_v2": int(
                legislation["counts"].get(
                    "historical_model_assisted_relationships_v2",
                    0,
                )
            ),
            "model_assisted_relationships_v3": int(
                legislation["counts"]["model_assisted_relationships_v3"]
            ),
            "model_assisted_topic_relationships_v3": int(
                legislation["counts"][
                    "model_assisted_topic_relationships_v3"
                ]
            ),
            "model_assisted_concept_relationships_v3": int(
                legislation["counts"][
                    "model_assisted_concept_relationships_v3"
                ]
            ),
            "model_assisted_entity_relationships_v3": int(
                legislation["counts"][
                    "model_assisted_entity_relationships_v3"
                ]
            ),
        },
    }
    return {
        "@context": f"{PUBLIC}/whole-law/ontology/context.jsonld",
        "@id": f"{PUBLIC}/whole-law/okf-explorer.json",
        "schema": "okf-explorer-federation.v1",
        "kind": "okf-federation",
        "okf_version": "0.2",
        "title": "UK Whole-Law OKF",
        "description": "A federated, evidence-led map of authoritative and supporting UK legal sources.",
        "version": "0.3.0",
        "status": "candidate",
        "generated_at": GENERATED_AT,
        "snapshot": "whole-law-2026-07-25",
        "publisher": "https://github.com/chris-page-gov",
        "license": OGL,
        "profile": "https://chris-page-gov.github.io/okf-explorer/profile/federation/v1/",
        "semantic_descriptor": f"{PUBLIC}/whole-law/okf-bundle.yamlld",
        "discovery": {
            "repository": "https://github.com/chris-page-gov/okf-uk-legislation",
            "documentation": f"{PUBLIC}/whole-law/",
            "raw_subpath": "bundle/whole-law",
            "release_archive": "https://github.com/chris-page-gov/okf-uk-legislation/releases",
            "semantic_descriptor": f"{PUBLIC}/whole-law/okf-bundle.yamlld",
            "routes": [
                {
                    "kind": "published",
                    "purpose": "descriptor",
                    "priority": 10,
                    "url": f"{PUBLIC}/whole-law/okf-explorer.json",
                },
                {
                    "kind": "raw",
                    "purpose": "descriptor",
                    "priority": 20,
                    "url": (
                        "https://raw.githubusercontent.com/chris-page-gov/"
                        "okf-uk-legislation/main/bundle/whole-law/okf-explorer.json"
                    ),
                },
                {
                    "kind": "published",
                    "purpose": "documentation",
                    "priority": 30,
                    "url": f"{PUBLIC}/whole-law/docs/",
                },
                {
                    "kind": "release",
                    "purpose": "archive",
                    "priority": 40,
                    "url": "https://github.com/chris-page-gov/okf-uk-legislation/releases",
                },
            ],
        },
        "entrypoints": {
            "viewer": "https://chris-page-gov.github.io/okf-explorer/",
            "markdown_index": "index.md",
            "source_register": "data/source-register.json",
            "source_classes": "data/legal-source-taxonomy.json",
            "coverage": "data/coverage.json",
            "constraints": "data/source-constraint-ledger.json",
            "relationship_summary": "data/relationship-summary.json",
            "standards": "ontology/standards.json",
            "ontology": "ontology/index.md",
            "shapes": "ontology/shapes.ttl",
            "semantic_turtle": "okf-bundle.ttl",
            "semantic_conformance": "assurance/semantic-conformance.json",
            "evaluation": "evaluation/release-questions.json",
            "evaluation_coverage": "evaluation/coverage.json",
            "official_effects": "../data/effects/manifest.json",
            "model_enrichment_v3": "../data/enrichment-v3/manifest.json",
            "model_enrichment_v3_accepted_manifest": (
                "../enrichment/codex-assisted-v3/accepted-manifest.json"
            ),
            "model_enrichment_v3_coverage": (
                "../enrichment/codex-assisted-v3/coverage.json"
            ),
            "model_enrichment_v3_independent_audit": (
                "assurance/enrichment-v3-independent-audit-20260726.json"
            ),
            "model_enrichment_v3_reviewer": (
                "assurance/enrichment-v3-reviewer-task-receipt.json"
            ),
            "model_enrichment_v2_historical": (
                "../enrichment/codex-assisted-v2.json"
            ),
            "integrity": "integrity.json",
            "docs": "docs/index.md",
        },
        "counts": {
            "children": 1,
            "available": 1,
            "partial": 0,
            "restricted": 0,
            "unavailable": 0,
            "planned": 0,
            "source_records": len(source_register["records"]),
            "source_classes": len(taxonomy["classes"]),
            "access_methods": sum(len(row.get("access_methods", [])) for row in source_register["records"]),
            "personas": 38,
            "task_families": 20,
        },
        "children": [child],
        "bundles": [child],
        "relationship_summary": relations,
        "source_families": families,
        "alternate_access": [
            {"kind": "pages", "url": f"{PUBLIC}/whole-law/okf-explorer.json"},
            {"kind": "repository", "url": "https://github.com/chris-page-gov/okf-uk-legislation/tree/main/bundle/whole-law"},
            {"kind": "raw", "url": "https://raw.githubusercontent.com/chris-page-gov/okf-uk-legislation/main/bundle/whole-law/okf-explorer.json"},
            {"kind": "archive", "url": "https://github.com/chris-page-gov/okf-uk-legislation/archive/refs/heads/main.tar.gz"},
            {"kind": "jsonld-fallback", "url": f"{PUBLIC}/whole-law/okf-bundle.jsonld"},
            {"kind": "turtle", "url": f"{PUBLIC}/whole-law/okf-bundle.ttl"},
        ],
        "extensions": {
            "okf-whole-law.v1": {
                "authority_model_required": True,
                "coverage_ledger_required": True,
                "source_native_identifiers": True,
                "unknown_or_restricted_sources_are_not_omitted": True,
            },
            "okf-explorer-analysis.v1": {
                "mode": "external",
                "entrypoint": "coverage",
            },
        },
        "notices": [
            "Only the UK Legislation child bundle is currently loadable; the 36 legal-source classes are governed federation metadata, not fabricated child bundles.",
            "Official effects cover the declared seed snapshot; independently accepted v3 topics, concepts and entity links are non-official discovery metadata.",
            "GitHub Pages serves YAML-LD as application/octet-stream; JSON-LD is the strict transport fallback.",
        ],
    }


def csvw_metadata(csv_name: str, columns: list[str]) -> dict[str, Any]:
    return {
        "@context": "http://www.w3.org/ns/csvw",
        "url": csv_name,
        "tableSchema": {
            "columns": [{"name": name, "titles": name} for name in columns],
        },
    }


def source_markdown(source: dict[str, Any]) -> str:
    methods = "\n".join(
        f"- `{method.get('status', 'unknown')}` [{method.get('kind', 'access')}]"
        f"({method.get('url', '')}) — tested {method.get('tested_at', 'not recorded')}"
        for method in source.get("access_methods", [])
    ) or "- No access method recorded."
    classes = ", ".join(source.get("source_classes", [])) or "none recorded"
    jurisdictions = ", ".join(source.get("jurisdictions", [])) or "not recorded"
    body = f"""## Authority and coverage

- Owner: {source.get('owning_institution', 'not recorded')}
- Authority: {', '.join(source.get('authority_classes', []))}
- Source classes: {classes}
- Jurisdictions: {jurisdictions}
- Coverage status: `{source.get('coverage_status', 'unknown')}`
- Denominator: {source.get('official_enumeration_or_denominator', 'not recorded')}

## Access

{methods}

## Rights and constraints

- Licence: {source.get('licence_and_reuse', 'not recorded')}
- Fair use/rate/robots: {source.get('fair_use_rate_limit_robots', 'not recorded')}

## Known limitations

{chr(10).join(f'- {item}' for item in source.get('known_omissions_or_inconsistencies', [])) or '- None recorded.'}
"""
    primary = next(
        (
            method["url"] for method in source.get("access_methods", [])
            if method.get("url")
        ),
        "https://github.com/chris-page-gov/okf-uk-legislation",
    )
    return concept(
        "Legal Source Record",
        source["title"],
        source.get("legal_force_or_role", "Governed legal source record."),
        primary,
        ["source", source["id"], *source.get("source_classes", [])],
        body,
        stale_after="2026-10-25",
    )


def class_markdown(row: dict[str, Any], families: dict[str, dict[str, Any]]) -> str:
    family = families[row["id"]]
    body = f"""## Implementation state

- Coverage: `{family['coverage_status']}`
- Source records: {family['source_count']}
- Authority class: `{row['primary_authority_class']}`
- Implemented bundle: {family['implemented_bundle'] or 'none; metadata-only federation record'}

## Minimum provenance

{row['minimum_provenance']}

## Related classes

{', '.join(row.get('relationships_to_other_classes', [])) or 'None recorded.'}
"""
    return concept(
        "Legal Source Class",
        row["label"],
        row["definition_and_legal_force"],
        f"{PUBLIC}/whole-law/data/legal-source-taxonomy.json",
        ["source-class", row["id"], row["primary_authority_class"]],
        body,
    )


def persona_markdown(row: dict[str, Any]) -> str:
    body = f"""## Risk

{row['risk_profile']}

## Task families

{', '.join(row.get('task_ids', []))}

## Primary source classes

{', '.join(row.get('primary_source_classes', []))}
"""
    return concept(
        "Research Persona",
        row["label"],
        row["description"],
        f"{PUBLIC}/whole-law/data/persona-task-matrix.json",
        ["persona", row["id"], row["group"]],
        body,
    )


def task_markdown(row: dict[str, Any]) -> str:
    body = f"""## Required authority

{', '.join(row.get('required_authority', []))}

## Evidence

{row['acceptable_evidence']}

## Currency

{row['default_currency_tolerance']}

## Definition of success

{row['success']}

## Failure modes

{chr(10).join(f'- {item}' for item in row.get('failure_modes', []))}
"""
    return concept(
        "Legal Research Task",
        row["label"],
        row["description"],
        f"{PUBLIC}/whole-law/data/persona-task-matrix.json",
        ["task", row["id"]],
        body,
    )


def index_page(title: str, rows: Iterable[tuple[str, str, str]]) -> str:
    links = "\n".join(f"- [{label}]({path}) — {note}" for path, label, note in rows)
    return f"# {title}\n\n{links}\n"


def build_files() -> dict[Path, bytes]:
    source_register = load(RESEARCH / "source-register.json")
    taxonomy = load(RESEARCH / "legal-source-taxonomy.json")
    personas = load(RESEARCH / "persona-task-matrix.json")
    families = source_family_rows(taxonomy, source_register)
    family_by_id = {row["id"]: row for row in families}
    constraints = build_constraints(source_register)
    relations = relationship_summary()
    desc = descriptor(source_register, taxonomy, families, relations)
    execution_rows: list[dict[str, Any]] = []
    execution_root = SOURCE / "evaluation" / "executions"
    if execution_root.is_dir():
        for results_path in sorted(execution_root.glob("*/results.json")):
            run_id = results_path.parent.name
            report_path = results_path.parent / "report.md"
            integrity_path = results_path.parent / "integrity.json"
            if not report_path.is_file() or not integrity_path.is_file():
                raise ValueError(
                    f"evaluation execution {run_id} is missing its report or integrity receipt"
                )
            results = load(results_path)
            if results.get("run_id") != run_id:
                raise ValueError(
                    f"evaluation execution directory {run_id} does not match its run_id"
                )
            execution_rows.append(
                {
                    "run_id": run_id,
                    "executed_at": results["executed_at"],
                    "corpus_binding_sha256": results["corpus_binding_sha256"],
                    "decision": results["analysis"]["release_decision"],
                    "results": f"{run_id}/results.json",
                    "report": f"{run_id}/report.md",
                    "integrity": f"{run_id}/integrity.json",
                }
            )
    execution_rows.sort(key=lambda row: (row["executed_at"], row["run_id"]))
    latest_execution = execution_rows[-1] if execution_rows else None
    desc["entrypoints"]["evaluation_executions"] = "evaluation/executions/index.json"

    coverage = {
        "schema": "okf-whole-law-coverage.v1",
        "generated_at": GENERATED_AT,
        "denominator": {
            "source_records": len(source_register["records"]),
            "source_classes": len(taxonomy["classes"]),
            "access_methods": sum(len(row.get("access_methods", [])) for row in source_register["records"]),
        },
        "source_family_status": dict(Counter(row["coverage_status"] for row in families)),
        "families": families,
        "claim": "The register covers all researched source records/classes; it does not claim complete ingestion of every legal corpus.",
    }
    source_register_bytes = render_json(source_register)
    source_register_sha256 = sha256_bytes(source_register_bytes.encode("utf-8"))
    access_method_count = sum(
        len(row.get("access_methods", [])) for row in source_register["records"]
    )

    semantic = {
        "@context": load(SOURCE / "ontology" / "context.jsonld")["@context"],
        "@id": f"{PUBLIC}/whole-law/",
        "@type": "okflaw:Federation",
        "okf_version": "0.2",
        "title": desc["title"],
        "description": desc["description"],
        "version": desc["version"],
        "status": desc["status"],
        "issued": "2026-07-25",
        "descriptor": {"@id": desc["@id"]},
        "childBundle": [
            {"@id": urljoin(desc["@id"], bundle["descriptor"])}
            for bundle in desc["bundles"]
        ],
        "sourceRegister": {
            "@id": f"{PUBLIC}/whole-law/data/source-register.json",
            "@type": "okflaw:SourceRegister",
            "title": "UK Whole-Law governed source register",
            "identifier": "whole-law-source-register-2026-07-25",
            "registerSchema": source_register["schema"],
            "recordCount": len(source_register["records"]),
            "sourceClassCount": len(taxonomy["classes"]),
            "accessMethodCount": access_method_count,
            "accessTestDate": source_register["access_test_date"],
            "sourceHash": f"sha256:{source_register_sha256}",
        },
        "generatedAt": GENERATED_AT,
        "license": {"@id": OGL},
    }

    files: dict[Path, bytes] = {}

    def put(path: str | Path, value: str | bytes) -> None:
        files[Path(path)] = value.encode("utf-8") if isinstance(value, str) else value

    for source_path in SOURCE.rglob("*"):
        if source_path.is_file():
            relative = source_path.relative_to(SOURCE)
            put(relative, source_path.read_bytes())
    put(
        "assurance/enrichment-v3-reviewer-task-receipt.json",
        legislation_builder.MODEL_ENRICHMENT_V3_REVIEWER_PATH.read_bytes(),
    )

    put("okf-explorer.json", render_json(desc))
    put("okf-bundle.jsonld", render_json(semantic))
    put("okf-bundle.ttl", render_canonical_turtle(semantic))
    put("data/source-register.json", source_register_bytes)
    put("data/legal-source-taxonomy.json", render_json(taxonomy))
    put("data/persona-task-matrix.json", render_json(personas))
    put("data/coverage.json", render_json(coverage))
    put("data/source-constraint-ledger.json", render_json(constraints))
    put("data/relationship-summary.json", render_json(relations))

    for name in sorted(RESEARCH_EXPORTS):
        path = RESEARCH / name
        if path.is_file():
            put(Path("research") / name, path.read_bytes())

    with (RESEARCH / "source-register.csv").open(newline="", encoding="utf-8") as handle:
        source_columns = next(csv.reader(handle))
    put("data/source-register.csv", (RESEARCH / "source-register.csv").read_bytes())
    put("data/source-register.csv-metadata.json", render_json(csvw_metadata("source-register.csv", source_columns)))
    with (RESEARCH / "persona-task-matrix.csv").open(newline="", encoding="utf-8") as handle:
        persona_columns = next(csv.reader(handle))
    put("data/persona-task-matrix.csv", (RESEARCH / "persona-task-matrix.csv").read_bytes())
    put("data/persona-task-matrix.csv-metadata.json", render_json(csvw_metadata("persona-task-matrix.csv", persona_columns)))

    source_links = []
    for row in source_register["records"]:
        filename = f"{row['id'].lower()}-{slugify(row['title'])}.md"
        put(Path("sources") / filename, source_markdown(row))
        source_links.append((filename, f"{row['id']} — {row['title']}", row.get("coverage_status", "unknown")))
    put("sources/index.md", index_page("Whole-Law source catalogue", source_links))

    class_links = []
    for row in taxonomy["classes"]:
        filename = f"{row['id'].lower()}-{slugify(row['label'])}.md"
        put(Path("source-classes") / filename, class_markdown(row, family_by_id))
        class_links.append((filename, f"{row['id']} — {row['label']}", family_by_id[row["id"]]["coverage_status"]))
    put("source-classes/index.md", index_page("Legal-source classes", class_links))

    persona_links = []
    for row in personas["personas"]:
        filename = f"{row['id'].lower()}-{slugify(row['label'])}.md"
        put(Path("personas") / filename, persona_markdown(row))
        persona_links.append((filename, f"{row['id']} — {row['label']}", row["group"]))
    put("personas/index.md", index_page("Whole-Law research personas", persona_links))

    task_links = []
    for row in personas["tasks"]:
        filename = f"{row['id'].lower()}-{slugify(row['label'])}.md"
        put(Path("tasks") / filename, task_markdown(row))
        task_links.append((filename, f"{row['id']} — {row['label']}", ", ".join(row["required_authority"])))
    put("tasks/index.md", index_page("Whole-Law research tasks", task_links))

    put("coverage/index.md", """# Coverage and source constraints

The federation distinguishes a source record being catalogued from a corpus
being ingested or complete. Exact denominators and access states are available
in [coverage.json](../data/coverage.json); legal, fair-use, authentication,
availability and hosting constraints are in
[source-constraint-ledger.json](../data/source-constraint-ledger.json).

Restricted or unavailable sources remain visible. Their content is not
fabricated and authentication is not bypassed.
""")
    latest_execution_markdown = (
        f"- [Latest executed assurance report]"
        f"(executions/{latest_execution['report']}) — "
        f"`{latest_execution['decision']}`\n"
        if latest_execution
        else "- No release evaluation execution has been recorded.\n"
    )
    put("evaluation/index.md", f"""# Whole-Law evaluation

The original 100-question legislation suite and the 360-question research
suite are retained as non-gold baselines. The release suite adds corpus
binding, coverage strata, evidence and independent verification state.

{latest_execution_markdown}
- [Release questions](release-questions.json)
- [Coverage](coverage.json)
- [Historical baselines](historical-baselines.json)
- [Answer schema](answer-schema.json)
- [Claude access journey](claude-access-suite.json)
- [All immutable evaluation executions](executions/index.json)

## Canonical publication access

| Repository | Canonical descriptor | Declared `raw_subpath` | Release/archive fallback |
|---|---|---|---|
| [GitHub](https://github.com/chris-page-gov/okf-uk-legislation) | [federation descriptor](https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-explorer.json) | `bundle/whole-law` | [immutable releases](https://github.com/chris-page-gov/okf-uk-legislation/releases) |

- [legislation.gov.uk](https://www.legislation.gov.uk/)
- [Official legislation data/API documentation](https://legislation.github.io/data-documentation/)
- [Official data.gov.uk API documentation](https://guidance.data.gov.uk/get_data/api_documentation/)
- [GOV.UK CKAN example descriptor](https://chris-page-gov.github.io/ai-engineering-lab-hackathon-london-2026/gov-ckan/okf-explorer.json)
- [Preserved OKF Bundle Wiki authoring guide](https://chris-page-gov.github.io/ai-infrastructure-wiki/docs/okf-bundle-authoring.md)
""")
    latest_execution_html = (
        "<li><a href=\"executions/"
        + html.escape(latest_execution["report"])
        + "\">Latest executed assurance report</a> — "
        + html.escape(latest_execution["decision"])
        + "</li>"
        if latest_execution
        else "<li>No release evaluation execution has been recorded.</li>"
    )
    put("evaluation/index.html", f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Whole-Law evaluation</title>
<main><h1>Whole-Law evaluation</h1><ul>
{latest_execution_html}
<li><a href="release-questions.json">Release questions</a></li>
<li><a href="coverage.json">Coverage</a></li>
<li><a href="historical-baselines.json">Historical baselines</a></li>
<li><a href="answer-schema.json">Answer schema</a></li>
<li><a href="claude-access-suite.json">Claude access suite</a></li>
<li><a href="executions/index.json">All immutable evaluation executions</a></li>
</ul>
<h2>Canonical publication access</h2><ul>
<li><a href="https://github.com/chris-page-gov/okf-uk-legislation">Repository</a></li>
<li><a href="https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-explorer.json">Canonical federation descriptor</a></li>
<li>Declared raw subpath: <code>bundle/whole-law</code></li>
<li><a href="https://github.com/chris-page-gov/okf-uk-legislation/releases">Release/archive fallback</a></li>
</ul>
<h2>Official sources and examples</h2><ul>
<li><a href="https://www.legislation.gov.uk/">legislation.gov.uk</a></li>
<li><a href="https://legislation.github.io/data-documentation/">Official legislation data/API documentation</a></li>
<li><a href="https://guidance.data.gov.uk/get_data/api_documentation/">Official data.gov.uk API documentation</a></li>
<li><a href="https://chris-page-gov.github.io/ai-engineering-lab-hackathon-london-2026/gov-ckan/okf-explorer.json">GOV.UK CKAN example descriptor</a></li>
<li><a href="https://chris-page-gov.github.io/ai-infrastructure-wiki/docs/okf-bundle-authoring.md">Preserved OKF Bundle Wiki authoring guide</a></li>
</ul></main></html>
""")
    put(
        "evaluation/executions/index.json",
        render_json(
            {
                "schema": "okf-evaluation-execution-index.v1",
                "generated_at": GENERATED_AT,
                "execution_count": len(execution_rows),
                "latest_run_id": (
                    latest_execution["run_id"] if latest_execution else None
                ),
                "executions": execution_rows,
            }
        ),
    )
    put("evaluation/questions.json", (SOURCE / "evaluation" / "release-questions.json").read_bytes())
    put(
        "evaluation/historical/research-360-questions.json",
        (RESEARCH / "whole-law-evaluation-questions.json").read_bytes(),
    )
    put(
        "evaluation/historical/research-evaluation-plan.json",
        (RESEARCH / "whole-law-evaluation-plan.json").read_bytes(),
    )
    put(
        "evaluation/historical/answer-schema-proposal.json",
        (RESEARCH / "answer-schema-proposal.json").read_bytes(),
    )
    put("docs/index.md", """# UK Whole-Law OKF documentation

- [Getting started](getting-started.md)
- [Authority, evidence and legal-use boundaries](authority-and-evidence.md)
- [Sources, access and coverage](sources-and-coverage.md)
- [Standards and validation](standards-and-validation.md)
- [Maintenance and recovery](maintenance.md)
- [Role guides](../../docs/roles/)

## Canonical access

| Repository | Canonical descriptor | Declared `raw_subpath` | Release/archive fallback |
|---|---|---|---|
| [GitHub](https://github.com/chris-page-gov/okf-uk-legislation) | [federation descriptor](https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-explorer.json) | `bundle/whole-law` | [immutable releases](https://github.com/chris-page-gov/okf-uk-legislation/releases) |

## Semantic representations

- [Authored YAML-LD](https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-bundle.yamlld)
- [Generated JSON-LD](https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-bundle.jsonld)
- [Canonical Turtle](https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-bundle.ttl)

## Official sources and examples

- [legislation.gov.uk](https://www.legislation.gov.uk/)
- [Official legislation data/API documentation](https://legislation.github.io/data-documentation/)
- [Official data.gov.uk API documentation](https://guidance.data.gov.uk/get_data/api_documentation/)
- [GOV.UK CKAN example descriptor](https://chris-page-gov.github.io/ai-engineering-lab-hackathon-london-2026/gov-ckan/okf-explorer.json)
- [Preserved OKF Bundle Wiki authoring guide](https://chris-page-gov.github.io/ai-infrastructure-wiki/docs/okf-bundle-authoring.md)
""")
    put("docs/index.html", """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>UK Whole-Law OKF documentation</title>
<main><h1>UK Whole-Law OKF documentation</h1><ul>
<li><a href="getting-started.md">Getting started</a></li>
<li><a href="authority-and-evidence.md">Authority and evidence</a></li>
<li><a href="sources-and-coverage.md">Sources and coverage</a></li>
<li><a href="standards-and-validation.md">Standards and validation</a></li>
<li><a href="maintenance.md">Maintenance and recovery</a></li>
<li><a href="../evaluation/">Evaluation</a></li>
<li><a href="../../docs/roles/">Role guides</a></li>
</ul>
<h2>Canonical access</h2><ul>
<li><a href="https://github.com/chris-page-gov/okf-uk-legislation">Repository</a></li>
<li><a href="https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-explorer.json">Canonical federation descriptor</a></li>
<li>Declared raw subpath: <code>bundle/whole-law</code></li>
<li><a href="https://github.com/chris-page-gov/okf-uk-legislation/releases">Release/archive fallback</a></li>
</ul>
<h2>Semantic representations</h2><ul>
<li><a href="../okf-bundle.yamlld">Authored YAML-LD</a></li>
<li><a href="../okf-bundle.jsonld">Generated JSON-LD</a></li>
<li><a href="../okf-bundle.ttl">Canonical Turtle</a></li>
</ul>
<h2>Official sources and examples</h2><ul>
<li><a href="https://www.legislation.gov.uk/">legislation.gov.uk</a></li>
<li><a href="https://legislation.github.io/data-documentation/">Official legislation data/API documentation</a></li>
<li><a href="https://guidance.data.gov.uk/get_data/api_documentation/">Official data.gov.uk API documentation</a></li>
<li><a href="https://chris-page-gov.github.io/ai-engineering-lab-hackathon-london-2026/gov-ckan/okf-explorer.json">GOV.UK CKAN example descriptor</a></li>
<li><a href="https://chris-page-gov.github.io/ai-infrastructure-wiki/docs/okf-bundle-authoring.md">Preserved OKF Bundle Wiki authoring guide</a></li>
</ul></main></html>
""")
    put("docs/getting-started.md", f"""# Getting started

Open the federation in OKF Explorer with:

`https://chris-page-gov.github.io/okf-explorer/?bundle=https%3A%2F%2Fchris-page-gov.github.io%2Fokf-uk-legislation%2Fwhole-law%2Fokf-explorer.json&view=reader#overview`

The descriptor declares its repository, raw subpath, archive, JSON-LD and
Turtle alternatives, and source-family coverage so agents do not need to
guess paths.

Canonical descriptor:
`{PUBLIC}/whole-law/okf-explorer.json`. Its declared raw subpath is
`bundle/whole-law`; its archive fallback is
`https://github.com/chris-page-gov/okf-uk-legislation/releases`.

Semantic representations:

- `{PUBLIC}/whole-law/okf-bundle.yamlld`
- `{PUBLIC}/whole-law/okf-bundle.jsonld`
- `{PUBLIC}/whole-law/okf-bundle.ttl`
""")
    put("docs/authority-and-evidence.md", """# Authority, evidence and legal-use boundaries

Authority class, jurisdiction, temporal state and source-native identifier are
mandatory research context. A topical match is not necessarily controlling
authority. Model-assisted topics and entities are discovery metadata, never
official classification or legal advice.

Material propositions require selected passages and retrieval/version context.
Consequential legal use requires qualified review.
""")
    put("docs/sources-and-coverage.md", """# Sources, access and coverage

The source register records 72 authoritative-source records across 36 legal
source classes. A recorded source is not automatically an ingested or complete
corpus. Coverage, access method and denominator are reported separately.

Unavailable and restricted routes remain visible. The public prototype does
not bypass authentication and does not infer absence from database absence.
""")
    put("docs/standards-and-validation.md", """# Standards and validation

## Versioned profile

The machine-readable [standards applicability
register](../ontology/standards.json) distinguishes `normative`, `projection`,
`source-native`, `conditional`, `reference-only` and `not-applicable` use. The
core pins are:

- OKF 0.2 at repository revision
  `3fcbb9f828c2f23d109c855ee403c3a4c81f3a96`;
- YAML 1.2.2;
- the 23 July 2026 YAML-LD 1.0 Working Draft;
- `yaml-ld==1.1.22`, with the local standards checkout and test-manifest
  revisions recorded in the register;
- JSON-LD 1.1/API/Framing with `PyLD==2.0.4`;
- RDF 1.1, RDF Dataset Canonicalization 1.0, SHACL 1.0, JSON Schema
  2020-12 and CSVW.

The repository-controlled namespace is
`https://chris-page-gov.github.io/okf-uk-legislation/profile/whole-law/v1#`.
It is intentionally versioned and does not claim an unregistered `w3id.org`
identifier. A later permanent government-domain migration is a separate,
documented compatibility decision.

## Authored and generated representations

`okf-bundle.yamlld` is the authored semantic publication. The builder emits
`okf-bundle.jsonld` and canonical N-Triples-compatible
`okf-bundle.ttl` from the same governed values. Validation exercises YAML-LD
expansion, JSON-LD compaction, flattening and framing, RDF conversion,
RDF-to-JSON-LD-to-RDF round-trip, three-way graph isomorphism and canonical
dataset-digest equivalence. SHACL validates all three complete semantic
descriptor graphs and the example/entity contract. The semantic descriptor
contains the Federation and its hash-bound SourceRegister contract node; it
does not materialise the 365,786 catalogued legal works as RDF. The
[deterministic conformance receipt](../assurance/semantic-conformance.json)
separately records exhaustive JSON Schema validation of every compact core and
provider relationship row.

These checks establish conformance of this publication to its declared basic
profile. They do not claim that the selected third-party processor passes
every upstream processor test. The upstream YAML-LD, JSON-LD API and Framing
test suites remain processor-level dependencies; their exact revisions and
the subset exercised here are retained as release evidence.

## Legal and catalogue projections

ELI, ELI-DL/ELI-I, ECLI, Akoma Ntoso/LegalDocML, CLML, LRM/WEMI, PROV-O,
Dublin Core Terms, DCAT 3/DCAT-AP, SKOS, OWL-Time, Web Annotation, CiTO,
ODRL, DQV and Schema.org Legislation are applied only in the roles declared by
the register. Conditional mappings are not emitted when source evidence does
not support them. LegalRuleML is conditional on reviewed rule extraction and
LKIF remains reference-only.

## Known transport exception

GitHub Pages currently serves `.yamlld` as `application/octet-stream`, not
`application/ld+yaml`. The document remains semantically conformant, but this
deployment is not described as transport-conformant. JSON-LD and release
downloads are universal fallbacks; Explorer may safely content-sniff a
declared `.yamlld` route. The exception remains open until a permanent host can
set the registered media type.
""")
    put("docs/maintenance.md", """# Maintenance and recovery

Refreshes create immutable attempts and provider datapacks. They never rewrite
historical evidence. A source-health failure changes the public access state;
the dated snapshot remains available without being described as current.

The release state is draft, candidate, validated, RC and published. RC
artefacts are promoted by digest without rebuilding.
""")
    put("index.html", f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>UK Whole-Law OKF</title>
<main><h1>UK Whole-Law OKF</h1>
<p>A federated, evidence-led map of authoritative and supporting UK legal sources.</p>
<h2>Published release</h2>
<dl>
<dt>Bundle release</dt><dd><a href="https://github.com/chris-page-gov/okf-uk-legislation/releases/tag/v0.3.0"><strong>v0.3.0</strong></a></dd>
<dt>Published</dt><dd>27 July 2026 at 15:40:30 UTC</dd>
<dt>OKF specification</dt><dd>OKF 0.2</dd>
<dt>Source-access snapshot</dt><dd>25 July 2026</dd>
<dt>Legislation child snapshot</dt><dd>11 July 2026 at 18:00 UTC</dd>
</dl>
<p>The immutable release retains pre-promotion <code>candidate</code> labels in some machine representations. The GitHub release record is the authoritative publication status. There is no Legislation/Whole-Law <code>v0.4.0</code> release.</p>
<ul>
<li><a href="https://chris-page-gov.github.io/okf-uk-legislation/whole-law/okf-explorer.json">Canonical Explorer descriptor</a></li>
<li><a href="okf-bundle.yamlld">YAML-LD</a></li>
<li><a href="okf-bundle.jsonld">JSON-LD</a></li>
<li><a href="okf-bundle.ttl">Turtle</a></li>
<li><a href="docs/">Documentation</a></li>
<li><a href="data/source-register.json">Source register</a></li>
<li><a href="https://github.com/chris-page-gov/okf-uk-legislation">Repository</a></li>
<li>Declared raw subpath: <code>bundle/whole-law</code></li>
<li><a href="https://github.com/chris-page-gov/okf-uk-legislation/releases">Release/archive fallback</a></li>
</ul>
<h2>Official sources and examples</h2><ul>
<li><a href="https://www.legislation.gov.uk/">legislation.gov.uk</a></li>
<li><a href="https://legislation.github.io/data-documentation/">Official legislation data/API documentation</a></li>
<li><a href="https://guidance.data.gov.uk/get_data/api_documentation/">Official data.gov.uk API documentation</a></li>
<li><a href="https://chris-page-gov.github.io/ai-engineering-lab-hackathon-london-2026/gov-ckan/okf-explorer.json">GOV.UK CKAN example descriptor</a></li>
<li><a href="https://chris-page-gov.github.io/ai-infrastructure-wiki/docs/okf-bundle-authoring.md">Preserved OKF Bundle Wiki authoring guide</a></li>
</ul>
<p>Coverage and authority state are explicit. This prototype is not legal advice.</p>
</main></html>
""")

    integrity_rows = []
    for path, body in sorted(files.items(), key=lambda item: item[0].as_posix()):
        integrity_rows.append({
            "path": path.as_posix(),
            "bytes": len(body),
            "sha256": sha256_bytes(body),
        })
    put("integrity.json", render_json({
        "schema": "okf-integrity-manifest.v1",
        "algorithm": "sha256",
        "generated_at": GENERATED_AT,
        "files": integrity_rows,
    }))
    return files


def check_files(files: dict[Path, bytes], output: Path) -> list[str]:
    errors = []
    expected = set(files)
    actual = {
        path.relative_to(output)
        for path in output.rglob("*")
        if path.is_file()
    } if output.exists() else set()
    for path in sorted(expected | actual):
        if path not in expected:
            errors.append(f"unexpected generated file: {path}")
        elif path not in actual:
            errors.append(f"missing generated file: {path}")
        elif (output / path).read_bytes() != files[path]:
            errors.append(f"out-of-date generated file: {path}")
    return errors


def write_files(files: dict[Path, bytes], output: Path) -> None:
    if output.exists():
        shutil.rmtree(output)
    for path, body in files.items():
        destination = output / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    files = build_files()
    if args.check:
        errors = check_files(files, output)
        if errors:
            print("Whole-Law OKF is not synchronized:")
            for error in errors[:100]:
                print(f"- {error}")
            return 1
        print(f"Whole-Law OKF synchronized: {len(files)} files")
        return 0
    write_files(files, output)
    try:
        display_output = output.relative_to(ROOT)
    except ValueError:
        display_output = output
    print(f"Wrote {len(files)} Whole-Law OKF files to {display_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
