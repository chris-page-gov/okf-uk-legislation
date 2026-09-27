#!/usr/bin/env python3
"""Build the bounded rich YAML-LD/JSON-LD relationship control plane.

The existing corpus, effects and enrichment artefacts remain the governed
assertion inputs.  This builder never rewrites those inputs.  For every input
assertion it deterministically emits one rich ``okf:RelationshipAssertion``
and one matching direct RDF triple into a bounded gzip JSON-LD shard.  The
YAML-LD/JSON-LD manifest keeps active, official, model-assisted and historical
planes separate and links every shard to its source material.
"""

from __future__ import annotations

import argparse
from collections import Counter
from functools import lru_cache
import gzip
import hashlib
import io
import json
import jsonschema
from pathlib import Path
import re
import sys
from typing import Any, Callable, Iterable, Iterator
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"
OUTPUT = BUNDLE / "data" / "semantic"
PUBLIC = "https://chris-page-gov.github.io/okf-uk-legislation"
OKF = f"{PUBLIC}/profile/whole-law/v1#"
PLANE_BASE = f"{PUBLIC}/id/relationship-plane/"
PROCESS_BASE = f"{PUBLIC}/id/process/"
SEMANTIC_NODE_BASE = f"{PUBLIC}/id/"
OGL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"
RDF_STATEMENT = "rdf:Statement"
RELATIONSHIP_ASSERTION = "okf:RelationshipAssertion"
GENERATED_AT = "2026-08-09T00:00:00Z"
SHARD_SIZE = 5_000
AUTHORITY_CLASSES = {
    "official",
    "derived",
    "model-assisted",
    "synthetic",
    "unclassified",
}
LIFECYCLES = {"active", "historical", "rejected"}
PLANE_AUTHORITY_CLASSES = {
    "core": {"official", "derived"},
    "official-effects": {"official"},
    "model-assisted-v3": {"model-assisted"},
    "model-assisted-v2-historical": {"model-assisted"},
    "model-assisted-v1-rejected": {"model-assisted"},
}
PLANE_LIFECYCLES = {
    "core": "active",
    "official-effects": "active",
    "model-assisted-v3": "active",
    "model-assisted-v2-historical": "historical",
    "model-assisted-v1-rejected": "rejected",
}

SOURCE_MANIFEST = BUNDLE / "data" / "manifest.json"
EFFECTS_MANIFEST = BUNDLE / "data" / "effects" / "manifest.json"
EFFECTS_ASSERTIONS = BUNDLE / "data" / "effects" / "assertions.json.gz"
V3_MANIFEST = BUNDLE / "enrichment" / "codex-assisted-v3" / "accepted-manifest.json"
V2_MANIFEST = BUNDLE / "data" / "enrichment" / "manifest.json"
V1_RULES = ROOT / "enrichment" / "model-assisted-v1.json"
V1_AUDIT = ROOT / "enrichment" / "model-assisted-v1-independent-audit.json"
ASSERTION_SCHEMA = ROOT / "whole-law" / "schemas" / "relationship-assertion-v3.schema.json"
SHARED_ASSERTION_SCHEMA = (
    ROOT / "whole-law" / "schemas" / "semantic-assertion.schema.json"
)

ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")
LOCAL_ROUTE = re.compile(r"^[a-z][a-z0-9-]*(?:/[A-Za-z0-9._~-]+)+$")
OFFICIAL_WORK_IRI = re.compile(
    r"^https://www\.legislation\.gov\.uk/id/([^/]+)/([^/]+)/([^/]+)$"
)

CONTEXT: dict[str, Any] = {
    "@version": 1.1,
    "@vocab": OKF,
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "okf": OKF,
    "prov": "http://www.w3.org/ns/prov#",
    "dcterms": "http://purl.org/dc/terms/",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "source": {"@id": "rdf:subject", "@type": "@id"},
    "target": {"@id": "rdf:object", "@type": "@id"},
    "predicate": {"@id": "rdf:predicate", "@type": "@id"},
    "source_iri": {"@id": "okf:sourceIri", "@type": "@id"},
    "target_iri": {"@id": "okf:targetIri", "@type": "@id"},
    "plane": {"@id": "okf:relationshipPlane", "@type": "@id"},
    "lifecycle": "okf:lifecycle",
    "shard": {"@id": "okf:shard", "@type": "@id", "@container": "@set"},
    "runtimeShard": {"@id": "okf:runtimeShard", "@type": "@id", "@container": "@set"},
    "sourceMaterial": {"@id": "prov:wasDerivedFrom", "@type": "@id"},
    "relationshipManifest": {"@id": "okf:relationshipManifest", "@type": "@id"},
    "relationshipManifestJson": {"@id": "okf:relationshipManifestJson", "@type": "@id"},
    "relationshipRuntimeManifest": {"@id": "okf:relationshipRuntimeManifest", "@type": "@id"},
    "observed_at": {"@id": "okf:observedAt", "@type": "xsd:dateTime"},
    "generated_at": {"@id": "prov:generatedAtTime", "@type": "xsd:dateTime"},
    "evidence": {"@id": "okf:evidence", "@type": "@json"},
    "rights": {"@id": "dcterms:rights", "@type": "@json"},
    "authority": {"@id": "okf:authority", "@type": "@json"},
    "source_assertion": {"@id": "okf:sourceAssertion", "@type": "@json"},
    "counts": {"@id": "okf:counts", "@type": "@json"},
}

PREDICATES: dict[str, dict[str, str]] = {
    "classified as": {
        "iri": f"{OKF}classifiedAs",
        "label": "classified as",
        "inverse_label": "classification of",
    },
    "has document type": {
        "iri": f"{OKF}hasDocumentType",
        "label": "has document type",
        "inverse_label": "document type of",
    },
    "mentions entity": {
        "iri": "https://schema.org/mentions",
        "label": "mentions entity",
        "inverse_label": "mentioned by",
    },
    "has discovery concept": {
        "iri": f"{OKF}hasDiscoveryConcept",
        "label": "has discovery concept",
        "inverse_label": "discovery concept of",
    },
}
PREDICATES_BY_IRI: dict[str, dict[str, str]] = {
    value["iri"]: value for value in PREDICATES.values()
}


class SemanticBuildError(RuntimeError):
    """Raised when a source plane cannot be projected without ambiguity."""


def load_json(path: Path) -> Any:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def render_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def render_compact_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def gzip_json(value: Any) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(
        filename="", mode="wb", fileobj=output, compresslevel=6, mtime=0
    ) as stream:
        stream.write(render_json(value))
    return output.getvalue()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@lru_cache(maxsize=None)
def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def root_relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def bundle_relative(path: Path) -> str:
    return path.relative_to(BUNDLE).as_posix()


def material(path: Path) -> dict[str, Any]:
    return {
        "path": root_relative(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def artifact_iri(path: Path) -> str:
    identity = sha256_bytes(bundle_relative(path).encode("utf-8"))
    return f"urn:okf:uk-legislation:artifact:sha256:{identity}"


def source_material_url(path: Path) -> str:
    return (
        "https://github.com/chris-page-gov/okf-uk-legislation/blob/main/"
        f"{root_relative(path)}"
    )


def slugify(value: str) -> str:
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-") or "item"


def chunks(rows: list[dict[str, Any]], size: int = SHARD_SIZE) -> Iterator[list[dict[str, Any]]]:
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def source_binding(path: Path) -> dict[str, Any]:
    return {"path": root_relative(path), "sha256": sha256_file(path)}


def work_route_registry() -> tuple[dict[str, str], dict[str, str], dict[str, Any]]:
    manifest = load_json(SOURCE_MANIFEST)
    locator_manifest_path = BUNDLE / "data" / "records" / "manifest.json"
    locator_manifest = load_json(locator_manifest_path)
    ordinal_routes: dict[int, str] = {}
    for collision in locator_manifest.get("route_collisions", []):
        ordinals = collision.get("ordinals", [])
        aliases = collision.get("aliases", [])
        if (
            not isinstance(ordinals, list)
            or not ordinals
            or not isinstance(aliases, list)
            or len(aliases) != len(ordinals) - 1
        ):
            raise SemanticBuildError("record locator collision contract is invalid")
        ordinal_routes[int(ordinals[0])] = str(collision["route"])
        for ordinal, alias in zip(ordinals[1:], aliases, strict=True):
            ordinal_routes[int(ordinal)] = str(alias)
    iri_to_route: dict[str, str] = {}
    route_to_iri: dict[str, str] = {}
    source_chunks = manifest.get("chunks", {}).get("datasets", [])
    if not isinstance(source_chunks, list) or not source_chunks:
        raise SemanticBuildError("work manifest has no dataset chunks")
    ordinal = 0
    for relative in source_chunks:
        path = BUNDLE / str(relative)
        rows = load_json(path)
        if not isinstance(rows, list):
            raise SemanticBuildError(f"work chunk is not an array: {path}")
        for row in rows:
            iri = str(row.get("id") or "")
            route = ordinal_routes.get(ordinal, str(row.get("route") or ""))
            if not ABSOLUTE_IRI.fullmatch(iri) or not LOCAL_ROUTE.fullmatch(route):
                raise SemanticBuildError(f"invalid work identity/route in {path}: {iri} / {route}")
            if iri in iri_to_route and iri_to_route[iri] != route:
                raise SemanticBuildError(f"work IRI maps to two routes: {iri}")
            if route in route_to_iri and route_to_iri[route] != iri:
                raise SemanticBuildError(f"work route maps to two IRIs: {route}")
            iri_to_route[iri] = route
            route_to_iri[route] = iri
            ordinal += 1
    return iri_to_route, route_to_iri, {
        "path": root_relative(SOURCE_MANIFEST),
        "sha256": sha256_file(SOURCE_MANIFEST),
        "records": len(iri_to_route),
        "route_index": root_relative(locator_manifest_path),
        "route_index_sha256": sha256_file(locator_manifest_path),
    }


def external_work_route(iri: str) -> str:
    match = OFFICIAL_WORK_IRI.fullmatch(iri)
    if not match:
        raise SemanticBuildError(f"no local route can be derived for work IRI: {iri}")
    return "external-legislation/" + "-".join(slugify(part) for part in match.groups())


def work_route(iri: str, work_routes: dict[str, str]) -> tuple[str, bool]:
    if iri in work_routes:
        return work_routes[iri], True
    return external_work_route(iri), False


def semantic_target(value: str, *, dimension: str | None = None, label: str | None = None) -> tuple[str, str, str]:
    if value.startswith(("topic/", "concept/", "entity/", "legislation-type/")):
        kind, slug = value.split("/", 1)
        return f"{SEMANTIC_NODE_BASE}{kind}/{slug}", value, kind
    if value.startswith(f"{OKF}topic-"):
        slug = value.split("#topic-", 1)[1]
        return value, f"topic/{slug}", "topic"
    if value.startswith(f"{OKF}concept-"):
        slug = value.split("#concept-", 1)[1]
        return value, f"concept/{slug}", "concept"
    if value.startswith(f"{OKF}entity-"):
        slug = value.split("#entity-", 1)[1]
        return value, f"entity/{slug}", "entity"
    if ABSOLUTE_IRI.fullmatch(value):
        kind = dimension or "entity"
        route = f"{kind}/{slugify(label or value)}"
        return value, route, kind
    raise SemanticBuildError(f"relationship target cannot be normalized: {value}")


def predicate_contract(source_predicate: str, row: dict[str, Any]) -> dict[str, str]:
    if source_predicate in PREDICATES:
        return dict(PREDICATES[source_predicate])
    prefix = "official effect: "
    if source_predicate.startswith(prefix):
        effect_type = str(row.get("source_native_type") or source_predicate[len(prefix) :]).strip().lower()
        effect_slug = slugify(effect_type)
        contract = {
            "iri": f"{OKF}officialEffect-{effect_slug}",
            "label": f"{effect_type} effect on",
            "inverse_label": f"affected by {effect_type} effect",
        }
        PREDICATES_BY_IRI[contract["iri"]] = contract
        return contract
    raise SemanticBuildError(f"unregistered relationship predicate: {source_predicate}")


def assertion_id(parts: Iterable[str], prefix: str) -> str:
    identity = "\0".join(parts).encode("utf-8")
    return f"urn:okf:{prefix}:sha256:{sha256_bytes(identity)}"


def canonical_value_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(encoded)


def evidence_with_route(
    value: Any,
    route: str,
    fallback_url: str,
    *,
    assertion_identifier: str,
    observed_at: str,
    source_field_default: str,
) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(rows):
        if isinstance(item, str):
            item = {"url": item}
        if not isinstance(item, dict):
            continue
        evidence = dict(item)
        evidence.setdefault("url", evidence.get("source_url") or fallback_url)
        evidence["source_route"] = route
        if not isinstance(evidence.get("url"), str) or not evidence["url"].startswith(("http://", "https://")):
            evidence["url"] = fallback_url
        evidence.setdefault("type", "source-record")
        evidence.setdefault("source_field", source_field_default)
        if "source_value" not in evidence:
            for candidate in (
                "value",
                "entry_title",
                "source_native_type",
                "literal_sha256",
                "url",
            ):
                if evidence.get(candidate) not in (None, ""):
                    evidence["source_value"] = evidence[candidate]
                    break
        evidence.setdefault(
            "source_value_sha256",
            canonical_value_sha256(evidence.get("source_value")),
        )
        if not re.fullmatch(
            r"[0-9a-f]{64}",
            str(evidence.get("source_value_sha256") or ""),
        ):
            evidence["source_value_sha256"] = canonical_value_sha256(
                evidence.get("source_value")
            )
        evidence.setdefault(
            "source_value_hash_canonicalization",
            "canonical-json-utf8",
        )
        evidence.setdefault("retrieved_at", observed_at)
        for iri_field, source_field_name, prefix in (
            ("normalization", "source_normalization", "normalization"),
            ("rule_id", "source_rule_id", "rule"),
        ):
            value = evidence.get(iri_field)
            if value not in (None, "") and not ABSOLUTE_IRI.fullmatch(
                str(value)
            ):
                evidence[source_field_name] = value
                evidence[iri_field] = (
                    f"{PROCESS_BASE}{prefix}-{slugify(str(value))}"
                )
        if not ABSOLUTE_IRI.fullmatch(str(evidence.get("@id") or "")):
            evidence["@id"] = assertion_id(
                (
                    assertion_identifier,
                    str(index),
                    str(evidence["url"]),
                    str(evidence["source_field"]),
                    str(evidence["source_value_sha256"]),
                ),
                "evidence",
            )
        result.append(evidence)
    if not result:
        source_value_sha256 = canonical_value_sha256(fallback_url)
        result.append(
            {
                "@id": assertion_id(
                    (
                        assertion_identifier,
                        "0",
                        fallback_url,
                        source_field_default,
                        source_value_sha256,
                    ),
                    "evidence",
                ),
                "url": fallback_url,
                "source_route": route,
                "type": "source-record",
                "source_field": source_field_default,
                "source_value": fallback_url,
                "source_value_sha256": source_value_sha256,
                "source_value_hash_canonicalization": "canonical-json-utf8",
                "retrieved_at": observed_at,
            }
        )
    return result


def rich_base(
    *,
    identifier: str,
    source: str,
    target: str,
    source_route: str,
    target_route: str,
    predicate: dict[str, str],
    assertion_status: str,
    assertion_scope: str,
    authority: dict[str, Any],
    derivation: str,
    observed_at: str,
    evidence: list[dict[str, Any]],
    rights: dict[str, Any],
    plane: str,
    lifecycle: str,
    active: bool,
    source_path: Path,
) -> dict[str, Any]:
    row = {
        "@id": identifier,
        "@type": [RDF_STATEMENT, RELATIONSHIP_ASSERTION],
        "schema": "okf-relationship-assertion.v3",
        "id": identifier,
        "source": source,
        "source_iri": source,
        "target": target,
        "target_iri": target,
        "source_route": source_route,
        "target_route": target_route,
        "predicate": predicate["iri"],
        "kind": predicate["label"],
        "label": predicate["label"],
        "inverse_label": predicate["inverse_label"],
        "direction": "source-to-target",
        "assertion_status": assertion_status,
        "assertion_scope": assertion_scope,
        "authority": authority,
        "derivation": derivation,
        "observed_at": observed_at,
        "evidence": evidence,
        "rights": rights,
        "plane": plane,
        "lifecycle": lifecycle,
        "active": active,
        "source_assertion": source_binding(source_path),
    }
    return row


def core_assertion(row: dict[str, Any], source_path: Path, work_routes: dict[str, str]) -> tuple[dict[str, Any], str]:
    source_route = str(row["source"])
    # Reverse lookup is passed as an attribute by the build loop to avoid
    # changing the frozen compact row shape.
    route_to_iri = core_assertion.route_to_iri  # type: ignore[attr-defined]
    if source_route not in route_to_iri:
        raise SemanticBuildError(f"unknown core source route: {source_route}")
    source = route_to_iri[source_route]
    target, target_route, target_kind = semantic_target(str(row["target"]))
    source_predicate = str(row.get("kind") or row.get("predicate") or "")
    predicate = predicate_contract(source_predicate, row)
    official = str(row.get("authority")) == "official-source"
    derivation_name = (
        "official-atom-metadata" if official else str(row.get("evidence_type") or "deterministic-title-rule")
    )
    identifier = assertion_id(
        (source, predicate["iri"], target, derivation_name),
        "core-relationship",
    )
    evidence_type = str(row.get("evidence_type") or "source-record")
    source_field = (
        "document_type"
        if official
        else "topics"
        if source_predicate == "classified as"
        else "semantic_entities"
        if source_predicate == "mentions entity"
        else "relationship"
    )
    evidence = [{
        "@id": assertion_id(
            (identifier, "0", source, source_field),
            "evidence",
        ),
        "url": source,
        "source_route": source_route,
        "type": evidence_type,
        "source_field": source_field,
        "source_artifact": root_relative(source_path),
        "source_sha256": sha256_file(source_path),
        "retrieved_at": str(row["observed_at"]),
    }]
    if isinstance(row.get("source_value"), str) and row["source_value"]:
        evidence[0]["source_value"] = row["source_value"]
        evidence[0]["source_value_sha256"] = canonical_value_sha256(
            row["source_value"]
        )
        evidence[0]["source_value_hash_canonicalization"] = (
            "canonical-json-utf8"
        )
    else:
        evidence[0]["source_value"] = target
        evidence[0]["source_value_sha256"] = canonical_value_sha256(target)
        evidence[0]["source_value_hash_canonicalization"] = (
            "canonical-json-utf8"
        )
    detailed_status = (
        "source-native-metadata" if official else "deterministic-derived"
    )
    detailed_scope = (
        "official legislation.gov.uk work-level document-type metadata"
        if official
        else "deterministic title-only discovery metadata; not official legal classification or legal advice"
    )
    rich = rich_base(
        identifier=identifier,
        source=source,
        target=target,
        source_route=source_route,
        target_route=target_route,
        predicate=predicate,
        assertion_status="official" if official else "inferred",
        assertion_scope="real-world",
        authority=(
            {"class": "official", "label": "legislation.gov.uk source metadata", "source": "https://www.legislation.gov.uk/"}
            if official
            else {"class": "derived", "label": "deterministic non-official title rule", "source": f"{PUBLIC}/methodology/"}
        ),
        derivation=f"{PROCESS_BASE}{slugify(derivation_name)}",
        observed_at=str(row["observed_at"]),
        evidence=evidence,
        rights={
            "source": OGL,
            "attribution": "Contains public sector information licensed under the Open Government Licence v3.0.",
            "assertion": "official source metadata" if official else "derived discovery metadata",
        },
        plane=f"{PLANE_BASE}core",
        lifecycle="active",
        active=True,
        source_path=source_path,
    )
    rich.update({
        "confidence": row.get("confidence", "unknown"),
        "source_assertion_status": detailed_status,
        "source_assertion_scope": detailed_scope,
        "freshness": row.get("freshness", "current"),
        "source_predicate": source_predicate,
        "source_evidence_type": evidence_type,
        "target_kind": target_kind,
    })
    if "target_label" in row:
        rich["target_label"] = row["target_label"]
    if not official:
        confidence_score = {
            "low": 0.5,
            "medium": 0.75,
            "high": 1.0,
        }.get(str(row.get("confidence") or "").lower(), 0.5)
        rich.update(
            {
                "rule": f"{PROCESS_BASE}deterministic-title-rule",
                "supporting_assertions": [evidence[0]["@id"]],
                "confidence_score": confidence_score,
                "derivation_activity": rich["derivation"],
            }
        )
    validate_rich_assertion(rich)
    return rich, target_kind


def core_relationship_rows(
    record: dict[str, Any],
    *,
    route: str,
    observed_at: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    assisted = set(
        record.get("semantic_enrichment", {}).get("model_assisted_topics", [])
    )
    for topic in record.get("topics", []):
        rows.append({
            "source": route,
            "target": f"topic/{slugify(str(topic))}",
            "target_label": str(topic),
            "kind": "classified as",
            "evidence_type": (
                "model-assisted-title-rule"
                if topic in assisted
                else "deterministic-title-rule"
            ),
            "confidence": "medium" if topic in assisted else "low",
            "authority": "derived-non-official",
            "observed_at": observed_at,
            "source_value": str(topic),
        })
    rows.append({
        "source": route,
        "target": f"legislation-type/{record['type_code']}",
        "target_label": str(record.get("document_type") or record["type_code"]),
        "kind": "has document type",
        "evidence_type": "official-atom-metadata",
        "confidence": "high",
        "authority": "official-source",
        "observed_at": observed_at,
        "source_value": str(record.get("document_type") or record["type_code"]),
    })
    for entity in record.get("semantic_entities", []):
        rows.append({
            "source": route,
            "target": f"entity/{slugify(str(entity))}",
            "target_label": str(entity),
            "kind": "mentions entity",
            "evidence_type": "model-assisted-entity-pattern",
            "confidence": "medium",
            "authority": "derived-non-official",
            "observed_at": observed_at,
            "source_value": str(entity),
        })
    return rows


def provider_assertion(
    row: dict[str, Any],
    source_path: Path,
    work_routes: dict[str, str],
    *,
    plane_name: str,
    active: bool,
) -> tuple[dict[str, Any], str]:
    original = dict(row)
    source = str(row.get("source") or "")
    if not ABSOLUTE_IRI.fullmatch(source):
        raise SemanticBuildError(f"provider assertion source is not absolute: {source}")
    source_route, source_in_snapshot = work_route(source, work_routes)
    dimension = str(row.get("dimension") or "") or None
    target, target_route, target_kind = semantic_target(
        str(row.get("target") or ""),
        dimension=dimension,
        label=str(row.get("rule_label") or row.get("target") or ""),
    )
    if target.startswith("https://www.legislation.gov.uk/id/"):
        target_route, _target_in_snapshot = work_route(target, work_routes)
        target_kind = "legal-work"
    source_predicate = str(row.get("predicate") or row.get("kind") or "")
    predicate = predicate_contract(source_predicate, row)
    identifier = str(row.get("id") or "")
    if not ABSOLUTE_IRI.fullmatch(identifier):
        identifier = assertion_id(
            (source, predicate["iri"], target, plane_name),
            f"{slugify(plane_name)}-relationship",
        )
    if plane_name == "official-effects":
        detailed_status = "source-native-official"
        detailed_scope = (
            "official legislation.gov.uk editorial effect from successful frozen acquisition routes; partial at whole-corpus level"
        )
        derivation = f"{PROCESS_BASE}source-native-official-atom-feed"
        canonical_status = "official"
    elif plane_name == "model-assisted-v3":
        detailed_status = "accepted-independent-review"
        detailed_scope = "governed model-assisted discovery metadata; not official legal classification, legal advice or qualified practitioner assurance"
        derivation = f"{PROCESS_BASE}codex-assisted-v3-independent-review"
        canonical_status = "model-derived"
    elif plane_name == "model-assisted-v2-historical":
        detailed_status = "historical-independently-audited-not-active"
        detailed_scope = "preserved v2 historical discovery metadata excluded from active relationship totals; not legal advice"
        derivation = f"{PROCESS_BASE}codex-assisted-v2-historical"
        canonical_status = "model-derived"
    else:
        raise SemanticBuildError(f"unknown provider plane: {plane_name}")
    source_authority = dict(row.get("authority") or {})
    authority = {
        key: source_authority.get(key) for key in ("class", "label", "source")
    }
    if not all(authority.values()):
        raise SemanticBuildError(f"provider assertion has no authority: {identifier}")
    observed_at = str(
        row.get("observed_at") or row.get("generated_at") or ""
    )
    evidence = evidence_with_route(
        row.get("evidence"),
        source_route,
        source,
        assertion_identifier=identifier,
        observed_at=observed_at,
        source_field_default=(
            "effect-entry"
            if plane_name == "official-effects"
            else str(row.get("dimension") or "source-record")
        ),
    )
    rights = dict(row.get("rights") or {"source": OGL})
    rights.setdefault("source", OGL)
    rights.setdefault(
        "assertion",
        "official source relationship metadata"
        if plane_name == "official-effects"
        else "governed model-assisted discovery metadata"
        if plane_name == "model-assisted-v3"
        else "historical model-assisted discovery metadata",
    )
    rich = rich_base(
        identifier=identifier,
        source=source,
        target=target,
        source_route=source_route,
        target_route=target_route,
        predicate=predicate,
        assertion_status=canonical_status,
        assertion_scope="real-world",
        authority=authority,
        derivation=derivation,
        observed_at=observed_at,
        evidence=evidence,
        rights=rights,
        plane=f"{PLANE_BASE}{plane_name}",
        lifecycle=(
            "historical"
            if plane_name == "model-assisted-v2-historical"
            else "active"
        ),
        active=active,
        source_path=source_path,
    )
    preserved = {
        key: value
        for key, value in original.items()
        if key not in rich and key not in {"schema", "source", "target", "predicate", "derivation", "evidence"}
    }
    rich.update(preserved)
    rich.update({
        "original_schema": row.get("schema"),
        "source_assertion_status": detailed_status,
        "source_assertion_scope": detailed_scope,
        "source_predicate": source_predicate,
        "source_derivation": row.get("derivation"),
        "source_in_catalogue_snapshot": source_in_snapshot,
        "target_kind": target_kind,
        "freshness": "historical" if not active else row.get("freshness", "unknown"),
    })
    if plane_name == "model-assisted-v2-historical":
        rich["source_review_status"] = row.get("review_status")
    if source_authority != authority:
        rich["source_authority"] = source_authority
    if canonical_status == "model-derived":
        confidence = row.get("confidence", 0.5)
        try:
            confidence_score = float(confidence)
        except (TypeError, ValueError):
            confidence_score = 0.5
        rich.update(
            {
                "confidence_score": min(1.0, max(0.0, confidence_score)),
                "derivation_activity": derivation,
                "review_status": str(
                    row.get("review_status") or detailed_status
                ),
            }
        )
    validate_rich_assertion(rich)
    return rich, target_kind


def validate_rich_assertion(row: dict[str, Any]) -> None:
    required = (
        "@id", "@type", "schema", "id", "source", "target",
        "source_route", "target_route", "predicate", "label",
        "kind", "inverse_label", "direction", "assertion_status",
        "assertion_scope", "authority", "derivation", "observed_at",
        "evidence", "rights", "plane", "lifecycle", "active",
    )
    missing = [key for key in required if row.get(key) in (None, "", [])]
    if missing:
        raise SemanticBuildError(f"rich assertion lacks {', '.join(missing)}: {row.get('id')}")
    for key in ("@id", "id", "source", "target", "predicate", "derivation", "plane"):
        if not ABSOLUTE_IRI.fullmatch(str(row[key])):
            raise SemanticBuildError(f"{key} is not an absolute IRI: {row[key]}")
    if row["@id"] != row["id"]:
        raise SemanticBuildError("assertion @id and id differ")
    for key in ("source_route", "target_route"):
        if not LOCAL_ROUTE.fullmatch(str(row[key])):
            raise SemanticBuildError(f"{key} is not a local route: {row[key]}")
    if row["direction"] != "source-to-target":
        raise SemanticBuildError("relationship direction is not source-to-target")
    if RDF_STATEMENT not in row["@type"] or RELATIONSHIP_ASSERTION not in row["@type"]:
        raise SemanticBuildError("assertion is not rdf:Statement + okf:RelationshipAssertion")
    authority = row["authority"]
    if not isinstance(authority, dict) or not all(authority.get(key) for key in ("class", "label", "source")):
        raise SemanticBuildError("relationship authority is incomplete")
    if authority.get("class") not in AUTHORITY_CLASSES:
        raise SemanticBuildError(
            f"relationship authority class differs: {row['id']}"
        )
    lifecycle = str(row["lifecycle"])
    if lifecycle not in LIFECYCLES:
        raise SemanticBuildError(
            f"relationship lifecycle differs: {row['id']}"
        )
    if bool(row["active"]) != (lifecycle == "active"):
        raise SemanticBuildError(
            f"relationship active/lifecycle axes differ: {row['id']}"
        )
    plane_name = str(row["plane"]).removeprefix(PLANE_BASE)
    if plane_name in PLANE_AUTHORITY_CLASSES:
        if authority["class"] not in PLANE_AUTHORITY_CLASSES[plane_name]:
            raise SemanticBuildError(
                "relationship authority is not declared by its plane: "
                f"{row['id']}"
            )
        if lifecycle != PLANE_LIFECYCLES[plane_name]:
            raise SemanticBuildError(
                f"relationship lifecycle differs from its plane: {row['id']}"
            )
    if not isinstance(row["evidence"], list) or not row["evidence"]:
        raise SemanticBuildError("relationship evidence is empty")
    for item in row["evidence"]:
        if not isinstance(item, dict) or not str(item.get("url", "")).startswith(("http://", "https://")) or not LOCAL_ROUTE.fullmatch(str(item.get("source_route") or "")):
            raise SemanticBuildError(f"relationship evidence is incomplete: {row['id']}")
    rights = row["rights"]
    if (
        not isinstance(rights, dict)
        or not str(rights.get("source", "")).startswith(("http://", "https://"))
        or not str(rights.get("assertion") or "").strip()
    ):
        raise SemanticBuildError(f"relationship rights are incomplete: {row['id']}")
    validate_shared_assertion(row)


@lru_cache(maxsize=1)
def shared_assertion_contract() -> dict[str, Any]:
    contract = load_json(SHARED_ASSERTION_SCHEMA)
    if contract.get("$id") != (
        "https://chris-page-gov.github.io/okf-explorer/"
        "profile/bundle-wiki/v1/semantic-assertion.schema.json"
    ):
        raise SemanticBuildError("pinned shared semantic assertion schema differs")
    return contract


@lru_cache(maxsize=1)
def shared_assertion_validator() -> jsonschema.Draft202012Validator:
    """Compile the pinned shared Draft 2020-12 assertion contract once."""

    contract = shared_assertion_contract()
    jsonschema.Draft202012Validator.check_schema(contract)
    return jsonschema.Draft202012Validator(
        contract,
        format_checker=jsonschema.FormatChecker(),
    )


def validate_shared_assertion(row: dict[str, Any]) -> None:
    """Exhaustively enforce the pinned shared assertion-schema contract."""

    contract = shared_assertion_contract()
    try:
        shared_assertion_validator().validate(row)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path)
        raise SemanticBuildError(
            "shared semantic assertion schema differs"
            + (f" at {location}" if location else "")
            + f": {exc.message} ({row.get('id')})"
        ) from exc
    required = set(contract.get("required", []))
    missing = sorted(key for key in required if row.get(key) in (None, "", []))
    if missing:
        raise SemanticBuildError(
            "shared semantic assertion fields are missing: "
            + ", ".join(missing)
        )
    status_values = set(
        contract["properties"]["assertion_status"]["enum"]
    )
    scope_values = set(contract["properties"]["assertion_scope"]["enum"])
    status = str(row["assertion_status"])
    scope = str(row["assertion_scope"])
    if status not in status_values or scope not in scope_values:
        raise SemanticBuildError(
            f"shared assertion status/scope differs: {status} / {scope}"
        )
    expected_authority = {
        "official": "official",
        "normalized": "derived",
        "inferred": "derived",
        "model-derived": "model-assisted",
    }[status]
    authority = row["authority"]
    if (
        not isinstance(authority, dict)
        or set(authority) != {"class", "label", "source"}
        or authority.get("class") != expected_authority
    ):
        raise SemanticBuildError(
            f"shared assertion authority differs for {status}: {row['id']}"
        )
    evidence_required = set(
        contract["$defs"]["evidence"]["required"]
    )
    for evidence in row["evidence"]:
        if not isinstance(evidence, dict):
            raise SemanticBuildError("shared assertion evidence is not an object")
        evidence_missing = sorted(
            key
            for key in evidence_required
            if evidence.get(key) in (None, "", [])
        )
        if evidence_missing:
            raise SemanticBuildError(
                "shared assertion evidence fields are missing: "
                + ", ".join(evidence_missing)
                + f" ({row['id']})"
            )
        if not ABSOLUTE_IRI.fullmatch(str(evidence["@id"])):
            raise SemanticBuildError("shared evidence @id is not absolute")
        if not re.fullmatch(r"[0-9a-f]{64}", str(evidence["source_value_sha256"])):
            raise SemanticBuildError("shared evidence value hash is invalid")
    if status == "inferred":
        conditional = (
            "rule",
            "supporting_assertions",
            "confidence_score",
            "derivation_activity",
        )
        if any(row.get(key) in (None, "", []) for key in conditional):
            raise SemanticBuildError(
                f"inferred assertion conditional fields are missing: {row['id']}"
            )
    if status == "model-derived":
        conditional = (
            "confidence_score",
            "derivation_activity",
            "review_status",
        )
        if any(row.get(key) in (None, "", []) for key in conditional):
            raise SemanticBuildError(
                "model-derived assertion conditional fields are missing: "
                f"{row['id']}"
            )
    confidence_score = row.get("confidence_score")
    if confidence_score is not None and (
        isinstance(confidence_score, bool)
        or not isinstance(confidence_score, (int, float))
        or not 0 <= confidence_score <= 1
    ):
        raise SemanticBuildError(
            f"shared assertion confidence score is invalid: {row['id']}"
        )


def shard_document(
    assertions: list[dict[str, Any]],
    *,
    output_path: Path,
    plane_name: str,
    active: bool,
    source_path: Path,
) -> dict[str, Any]:
    graph: list[dict[str, Any]] = []
    for assertion in assertions:
        graph.append({
            "@id": assertion["source"],
            "route": assertion["source_route"],
            assertion["predicate"]: {"@id": assertion["target"]},
        })
        graph.append(assertion)
    return {
        "@context": CONTEXT,
        "@id": artifact_iri(output_path),
        "@type": "okf:RelationshipAssertionShard",
        "schema": "okf-relationship-assertion-shard.v1",
        "generated_at": GENERATED_AT,
        "plane": f"{PLANE_BASE}{plane_name}",
        "lifecycle": "active" if active else "historical",
        "active": active,
        "sourceMaterial": {"@id": source_material_url(source_path)},
        "source_assertion": source_binding(source_path),
        "counts": {
            "assertions": len(assertions),
            "direct_triples": len(assertions),
            "reified_statements": len(assertions),
        },
        "@graph": graph,
    }


def validate_shard(document: dict[str, Any]) -> None:
    graph = document.get("@graph")
    counts = document.get("counts")
    if not isinstance(graph, list) or not isinstance(counts, dict):
        raise SemanticBuildError("semantic shard has no graph/counts")
    assertions = [row for row in graph if isinstance(row, dict) and row.get("schema") == "okf-relationship-assertion.v3"]
    direct_triples: Counter[tuple[str, str, str]] = Counter()
    for node in graph:
        if not isinstance(node, dict) or node.get("schema") == "okf-relationship-assertion.v3":
            continue
        source = node.get("@id")
        for key, value in node.items():
            if key in {"@id", "route"}:
                continue
            if isinstance(source, str) and isinstance(value, dict) and isinstance(value.get("@id"), str):
                direct_triples[(source, key, value["@id"])] += 1
    if len(assertions) != counts.get("assertions") or len(assertions) != counts.get("reified_statements") or sum(direct_triples.values()) != counts.get("direct_triples"):
        raise SemanticBuildError("semantic shard counts do not reconcile")
    expected: Counter[tuple[str, str, str]] = Counter()
    for row in assertions:
        validate_rich_assertion(row)
        if row["lifecycle"] != document.get("lifecycle"):
            raise SemanticBuildError(
                "semantic shard and assertion lifecycle differ"
            )
        expected[(row["source"], row["predicate"], row["target"])] += 1
    if direct_triples != expected:
        raise SemanticBuildError("direct triples and reified assertions differ")


def runtime_row(assertion: dict[str, Any]) -> dict[str, Any]:
    """Return the lossless local-route projection consumed by the Reader."""

    omitted = {
        "@id",
        "@type",
        "schema",
        "id",
        "source",
        "target",
        "source_iri",
        "target_iri",
        "source_route",
        "target_route",
        "predicate",
        "label",
        "inverse_label",
    }
    projected = {
        key: value for key, value in assertion.items() if key not in omitted
    }
    projected.update(
        {
            "schema": "okf-relationship-runtime-row.v1",
            "id": assertion["id"],
            "assertion_id": assertion["id"],
            "source": assertion["source_route"],
            "target": assertion["target_route"],
            "source_route": assertion["source_route"],
            "target_route": assertion["target_route"],
            "source_iri": assertion["source"],
            "target_iri": assertion["target"],
            "predicate": assertion["predicate"],
            "predicate_iri": assertion["predicate"],
            "kind": assertion["label"],
            "label": assertion["label"],
            "inverse_label": assertion["inverse_label"],
        }
    )
    validate_runtime_row(projected)
    return projected


def validate_runtime_row(row: dict[str, Any]) -> None:
    required = (
        "schema",
        "id",
        "assertion_id",
        "source",
        "target",
        "source_iri",
        "target_iri",
        "predicate",
        "predicate_iri",
        "kind",
        "label",
        "inverse_label",
        "direction",
        "assertion_status",
        "assertion_scope",
        "authority",
        "derivation",
        "observed_at",
        "evidence",
        "rights",
        "plane",
        "lifecycle",
        "active",
    )
    missing = [key for key in required if row.get(key) in (None, "", [])]
    if missing:
        raise SemanticBuildError(
            "runtime relationship lacks "
            + ", ".join(missing)
            + f": {row.get('id')}"
        )
    if row["schema"] != "okf-relationship-runtime-row.v1":
        raise SemanticBuildError("runtime relationship schema differs")
    if row["id"] != row["assertion_id"]:
        raise SemanticBuildError("runtime assertion identities differ")
    for key in (
        "id",
        "assertion_id",
        "source_iri",
        "target_iri",
        "predicate",
        "predicate_iri",
        "derivation",
        "plane",
    ):
        if not ABSOLUTE_IRI.fullmatch(str(row[key])):
            raise SemanticBuildError(
                f"runtime {key} is not an absolute IRI: {row[key]}"
            )
    if row["predicate"] != row["predicate_iri"]:
        raise SemanticBuildError("runtime predicate IRI aliases differ")
    if row["lifecycle"] not in LIFECYCLES:
        raise SemanticBuildError("runtime lifecycle differs")
    if bool(row["active"]) != (row["lifecycle"] == "active"):
        raise SemanticBuildError("runtime active/lifecycle axes differ")
    if row["authority"].get("class") not in AUTHORITY_CLASSES:
        raise SemanticBuildError("runtime authority class differs")
    for key in ("source", "target", "source_route", "target_route"):
        if not LOCAL_ROUTE.fullmatch(str(row[key])):
            raise SemanticBuildError(
                f"runtime {key} is not a local route: {row[key]}"
            )


def runtime_output_path(semantic_path: Path) -> Path:
    relative = semantic_path.relative_to(OUTPUT)
    name = relative.name
    if not name.startswith("assertions-") or not name.endswith(".jsonld.gz"):
        raise SemanticBuildError(
            f"semantic assertion shard has unexpected name: {semantic_path}"
        )
    runtime_name = (
        "relationships-" + name.removeprefix("assertions-").removesuffix(
            ".jsonld.gz"
        ) + ".json.gz"
    )
    return OUTPUT / "runtime" / relative.parent / runtime_name


def runtime_shard_material(
    path: Path,
    body: bytes,
    records: int,
) -> dict[str, Any]:
    return {
        "path": bundle_relative(path),
        "id": artifact_iri(path),
        "media_type": "application/json",
        "content_encoding": "gzip",
        "bytes": len(body),
        "sha256": sha256_bytes(body),
        "count": records,
        "records": records,
    }


def route_locator_plane_commitment(
    plane_name: str,
    incident: dict[str, set[str]],
) -> dict[str, Any]:
    assertion_ids = sorted(incident["assertion_ids"])
    chunk_paths = sorted(incident["chunks"])
    if not assertion_ids or not chunk_paths:
        raise SemanticBuildError(
            f"route locator commitment is empty for {plane_name}"
        )
    return {
        "name": plane_name,
        "assertions": len(assertion_ids),
        "assertion_ids_sha256": canonical_value_sha256(assertion_ids),
        "chunks": chunk_paths,
    }


def emit_route_locator(
    route_incidents: dict[str, dict[str, dict[str, set[str]]]],
    *,
    active_planes: set[str],
    known_planes: set[str],
    known_chunk_paths: set[str],
    check: bool,
    expected_paths: set[Path],
) -> tuple[dict[str, Any], int, dict[str, int]]:
    bucket_routes: dict[str, list[dict[str, Any]]] = {}
    totals: Counter[str] = Counter()
    maxima: Counter[str] = Counter()
    for route, incident_planes in sorted(route_incidents.items()):
        plane_rows: list[dict[str, Any]] = []
        all_chunks: set[str] = set()
        active_chunks: set[str] = set()
        active_incident_assertions = 0
        for plane_name, incident in sorted(incident_planes.items()):
            if plane_name not in known_planes:
                raise SemanticBuildError(
                    f"route locator references unknown plane: {plane_name}"
                )
            plane_row = route_locator_plane_commitment(
                plane_name,
                incident,
            )
            assertion_ids = sorted(incident["assertion_ids"])
            chunk_paths = plane_row["chunks"]
            unknown_paths = set(chunk_paths) - known_chunk_paths
            if unknown_paths:
                raise SemanticBuildError(
                    "route locator references unknown runtime chunks: "
                    + ", ".join(sorted(unknown_paths)[:5])
                )
            plane_rows.append(plane_row)
            all_chunks.update(chunk_paths)
            totals["plane_commitments"] += 1
            totals["incident_assertions"] += len(assertion_ids)
            totals["plane_chunk_references"] += len(chunk_paths)
            if plane_name in active_planes:
                active_chunks.update(chunk_paths)
                active_incident_assertions += len(assertion_ids)
                totals["active_incident_assertions"] += len(assertion_ids)
                totals["active_plane_chunk_references"] += len(chunk_paths)
        incident_assertions = sum(row["assertions"] for row in plane_rows)
        row = {
            "route": route,
            "chunks": sorted(all_chunks),
            "planes": plane_rows,
            "counts": {
                "planes": len(plane_rows),
                "incident_assertions": incident_assertions,
                "active_incident_assertions": active_incident_assertions,
                "chunk_references": len(all_chunks),
                "active_chunk_references": len(active_chunks),
            },
        }
        maxima["max_incident_assertions_per_route"] = max(
            maxima["max_incident_assertions_per_route"],
            incident_assertions,
        )
        maxima["max_active_incident_assertions_per_route"] = max(
            maxima["max_active_incident_assertions_per_route"],
            active_incident_assertions,
        )
        maxima["max_chunk_references_per_route"] = max(
            maxima["max_chunk_references_per_route"],
            len(all_chunks),
        )
        maxima["max_active_chunk_references_per_route"] = max(
            maxima["max_active_chunk_references_per_route"],
            len(active_chunks),
        )
        bucket = sha256_bytes(route.encode("utf-8"))[:2]
        bucket_routes.setdefault(bucket, []).append(row)

    bucket_materials: list[dict[str, Any]] = []
    for bucket, rows in sorted(bucket_routes.items()):
        path = (
            OUTPUT
            / "runtime"
            / "route-locator"
            / f"bucket-{bucket}.json.gz"
        )
        document = {
            "schema": "okf-rich-relationship-route-locator-bucket.v1",
            "generated_at": GENERATED_AT,
            "hash_algorithm": "sha256-utf8-first-byte-hex",
            "bucket": bucket,
            "routes": rows,
            "counts": {
                "routes": len(rows),
                "chunk_references": sum(len(row["chunks"]) for row in rows),
                "plane_commitments": sum(
                    len(row["planes"]) for row in rows
                ),
                "incident_assertions": sum(
                    row["counts"]["incident_assertions"] for row in rows
                ),
                "active_incident_assertions": sum(
                    row["counts"]["active_incident_assertions"]
                    for row in rows
                ),
            },
        }
        body = gzip_json(document)
        write_or_check(path, body, check=check)
        expected_paths.add(path)
        bucket_materials.append(
            {
                "bucket": bucket,
                "path": bundle_relative(path),
                "bytes": len(body),
                "sha256": sha256_bytes(body),
                "content_encoding": "gzip",
                "routes": len(rows),
                "chunk_references": document["counts"]["chunk_references"],
                "plane_commitments": document["counts"]["plane_commitments"],
                "incident_assertions": document["counts"]["incident_assertions"],
                "active_incident_assertions": document["counts"]["active_incident_assertions"],
            }
        )

    manifest_path = OUTPUT / "runtime" / "route-locator" / "manifest.json"
    manifest = {
        "schema": "okf-rich-relationship-route-locator.v1",
        "generated_at": GENERATED_AT,
        "hash_algorithm": "sha256-utf8-first-byte-hex",
        "bucket_path_template": (
            "data/semantic/runtime/route-locator/bucket-{prefix}.json.gz"
        ),
        "buckets": bucket_materials,
        "counts": {
            "routes": len(route_incidents),
            "buckets": len(bucket_materials),
            "chunk_references": sum(
                len(
                    {
                        path
                        for incident in planes.values()
                        for path in incident["chunks"]
                    }
                )
                for planes in route_incidents.values()
            ),
            **dict(sorted(totals.items())),
            **dict(sorted(maxima.items())),
        },
    }
    write_or_check(
        manifest_path,
        render_json(manifest),
        check=check,
    )
    expected_paths.add(manifest_path)
    return (
        {
            "path": bundle_relative(manifest_path),
            "id": artifact_iri(manifest_path),
            "routes": len(route_incidents),
            "buckets": len(bucket_materials),
            "sha256": sha256_bytes(render_json(manifest)),
            **dict(sorted(maxima.items())),
        },
        len(bucket_materials),
        dict(sorted(maxima.items())),
    )


def validate_runtime_manifest(document: dict[str, Any]) -> None:
    if document.get("schema") != "okf-rich-relationship-runtime-manifest.v1":
        raise SemanticBuildError("relationship runtime manifest schema differs")
    planes = document.get("planes")
    if not isinstance(planes, list) or not planes:
        raise SemanticBuildError("relationship runtime manifest has no planes")
    names = [str(plane.get("name") or "") for plane in planes]
    if not all(names) or len(names) != len(set(names)):
        raise SemanticBuildError("relationship runtime plane names are invalid")
    active_names = [
        str(plane["name"])
        for plane in planes
        if plane.get("lifecycle") == "active"
    ]
    if document.get("default_planes") != active_names:
        raise SemanticBuildError(
            "relationship runtime defaults do not equal active planes"
        )
    for plane in planes:
        lifecycle = str(plane.get("lifecycle") or "")
        if lifecycle not in LIFECYCLES:
            raise SemanticBuildError(
                f"relationship runtime plane lifecycle differs: {plane.get('name')}"
            )
        if bool(plane.get("active")) != (lifecycle == "active"):
            raise SemanticBuildError(
                "relationship runtime plane active/lifecycle axes differ: "
                f"{plane.get('name')}"
            )
        authority_classes = plane.get("authority_classes")
        if (
            not isinstance(authority_classes, list)
            or not authority_classes
            or not set(authority_classes).issubset(AUTHORITY_CLASSES)
        ):
            raise SemanticBuildError(
                "relationship runtime plane authority classes differ: "
                f"{plane.get('name')}"
            )
        chunks_value = plane.get("chunks")
        if not isinstance(chunks_value, list):
            raise SemanticBuildError(
                f"relationship runtime plane has no chunks: {plane.get('name')}"
            )
        if sum(int(row.get("count", -1)) for row in chunks_value) != int(
            plane.get("assertions", -1)
        ):
            raise SemanticBuildError(
                "relationship runtime plane chunks do not reconcile: "
                f"{plane.get('name')}"
            )
    totals = document.get("totals")
    if not isinstance(totals, dict):
        raise SemanticBuildError("relationship runtime totals are missing")
    lifecycle_totals = {
        lifecycle: sum(
            int(plane["assertions"])
            for plane in planes
            if plane["lifecycle"] == lifecycle
        )
        for lifecycle in LIFECYCLES
    }
    if (
        int(totals.get("active_assertions", -1))
        != lifecycle_totals["active"]
        or int(totals.get("historical_assertions", -1))
        != lifecycle_totals["historical"]
        or int(totals.get("rejected_assertions", -1))
        != lifecycle_totals["rejected"]
        or int(totals.get("all_assertions", -1))
        != sum(lifecycle_totals.values())
        or int(totals.get("chunks", -1))
        != sum(len(plane["chunks"]) for plane in planes)
    ):
        raise SemanticBuildError("relationship runtime totals do not reconcile")


def bind_root_reader_descriptor(
    runtime_manifest_body: bytes,
    *,
    check: bool,
) -> None:
    descriptor_path = BUNDLE / "okf-explorer.json"
    descriptor = load_json(descriptor_path)
    entrypoints = descriptor.setdefault("entrypoints", {})
    entrypoints.update(
        {
            "relationship_semantics": "data/semantic/manifest.yamlld",
            "relationship_semantics_jsonld": "data/semantic/manifest.jsonld",
            "relationship_runtime": "data/semantic/runtime-manifest.json",
            "predicate_registry": "data/semantic/predicate-registry.json",
            "iri_route_registry": "data/semantic/iri-route-registry.json",
        }
    )
    descriptor.setdefault("entrypoint_integrity", {})[
        "relationship_runtime"
    ] = {
        "path": "data/semantic/runtime-manifest.json",
        "bytes": len(runtime_manifest_body),
        "sha256": sha256_bytes(runtime_manifest_body),
        "content_encoding": "identity",
    }
    descriptor.setdefault("performance", {})[
        "route_relationship_hydration"
    ] = (
        "sha256-prefix rich relationship route locator; legacy FNV-1a "
        "adjacency retained as the compact-core fallback"
    )
    extension = descriptor.setdefault("extensions", {}).setdefault(
        "okf-rich-directed-relationships.v1", {}
    )
    extension.update(
        {
            "mode": "bounded-json-ld-shards-with-yaml-ld-control-plane",
            "entrypoint": "relationship_semantics",
            "jsonld_fallback": "relationship_semantics_jsonld",
            "runtime_entrypoint": "relationship_runtime",
            "direct_triple_policy": (
                "generated-with-evidence-bearing-reification"
            ),
            "authority_planes_preserved": True,
            "active_planes": [
                "core",
                "official-effects",
                "model-assisted-v3",
            ],
            "historical_planes": [
                "model-assisted-v2-historical",
                "model-assisted-v1-rejected",
            ],
        }
    )
    write_or_check(
        descriptor_path,
        render_compact_json(descriptor),
        check=check,
    )


def emit_shard_pair(
    assertions: list[dict[str, Any]],
    *,
    output_path: Path,
    plane_name: str,
    active: bool,
    source_path: Path,
    check: bool,
    expected_paths: set[Path],
    route_incidents: dict[str, dict[str, dict[str, set[str]]]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    document = shard_document(
        assertions,
        output_path=output_path,
        plane_name=plane_name,
        active=active,
        source_path=source_path,
    )
    validate_shard(document)
    body = gzip_json(document)
    write_or_check(output_path, body, check=check)
    expected_paths.add(output_path)

    runtime_path = runtime_output_path(output_path)
    runtime_rows = [runtime_row(assertion) for assertion in assertions]
    runtime_body = gzip_json(runtime_rows)
    write_or_check(runtime_path, runtime_body, check=check)
    expected_paths.add(runtime_path)
    runtime_relative = bundle_relative(runtime_path)
    for assertion in assertions:
        for route in {
            assertion["source_route"],
            assertion["target_route"],
        }:
            incident = (
                route_incidents.setdefault(route, {})
                .setdefault(
                    plane_name,
                    {"assertion_ids": set(), "chunks": set()},
                )
            )
            incident["assertion_ids"].add(assertion["id"])
            incident["chunks"].add(runtime_relative)
    return (
        shard_material(output_path, body, len(assertions)),
        runtime_shard_material(
            runtime_path,
            runtime_body,
            len(runtime_rows),
        ),
    )


def write_or_check(path: Path, body: bytes, *, check: bool) -> None:
    if check:
        if not path.is_file() or path.read_bytes() != body:
            raise SemanticBuildError(f"generated semantic output is missing or stale: {root_relative(path)}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(body)
    temporary.replace(path)


def shard_material(path: Path, body: bytes, records: int) -> dict[str, Any]:
    return {
        "path": bundle_relative(path),
        "id": artifact_iri(path),
        "media_type": "application/ld+json",
        "content_encoding": "gzip",
        "bytes": len(body),
        "sha256": sha256_bytes(body),
        "assertions": records,
        "direct_triples": records,
        "reified_statements": records,
    }


def emit_source_chunks(
    *,
    source_chunks: list[Path],
    output_directory: Path,
    plane_name: str,
    active: bool,
    work_routes: dict[str, str],
    normalizer: Callable[[dict[str, Any], Path, dict[str, str]], tuple[dict[str, Any], str]],
    check: bool,
    expected_paths: set[Path],
    seen_ids: set[str],
    route_registry: dict[str, dict[str, Any]],
    predicate_counts: Counter[tuple[str, str]],
    route_incidents: dict[str, dict[str, dict[str, set[str]]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    shard_rows: list[dict[str, Any]] = []
    runtime_shard_rows: list[dict[str, Any]] = []
    total = 0
    for index, source_path in enumerate(source_chunks):
        rows = load_json(source_path)
        if not isinstance(rows, list):
            raise SemanticBuildError(f"relationship input is not an array: {source_path}")
        normalized: list[dict[str, Any]] = []
        for row in rows:
            rich, target_kind = normalizer(row, source_path, work_routes)
            if rich["id"] in seen_ids:
                raise SemanticBuildError(f"duplicate assertion id: {rich['id']}")
            seen_ids.add(rich["id"])
            normalized.append(rich)
            predicate_counts[(plane_name, rich["predicate"])] += 1
            route_registry.setdefault(
                rich["target"],
                {
                    "iri": rich["target"],
                    "route": rich["target_route"],
                    "kind": target_kind,
                    "planes": [],
                },
            )
            target_entry = route_registry[rich["target"]]
            if target_entry["route"] != rich["target_route"]:
                raise SemanticBuildError(f"target IRI maps to two routes: {rich['target']}")
            if plane_name not in target_entry["planes"]:
                target_entry["planes"].append(plane_name)
            if not rich.get("source_in_catalogue_snapshot", True):
                route_registry.setdefault(
                    rich["source"],
                    {
                        "iri": rich["source"],
                        "route": rich["source_route"],
                        "kind": "external-legal-work",
                        "planes": [plane_name],
                    },
                )
        output_path = output_directory / (source_path.name.removesuffix(".json.gz") + ".jsonld.gz")
        semantic_material, runtime_material = emit_shard_pair(
            normalized,
            output_path=output_path,
            plane_name=plane_name,
            active=active,
            source_path=source_path,
            check=check,
            expected_paths=expected_paths,
            route_incidents=route_incidents,
        )
        shard_rows.append(semantic_material)
        runtime_shard_rows.append(runtime_material)
        total += len(normalized)
    return shard_rows, runtime_shard_rows, total


def emit_core_chunks(
    *,
    source_chunks: list[Path],
    generated_at: str,
    work_routes: dict[str, str],
    route_to_iri: dict[str, str],
    check: bool,
    expected_paths: set[Path],
    seen_ids: set[str],
    route_registry: dict[str, dict[str, Any]],
    predicate_counts: Counter[tuple[str, str]],
    route_incidents: dict[str, dict[str, dict[str, set[str]]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    output_chunks: list[dict[str, Any]] = []
    runtime_output_chunks: list[dict[str, Any]] = []
    total = 0
    for index, source_path in enumerate(source_chunks):
        records = load_json(source_path)
        if not isinstance(records, list):
            raise SemanticBuildError(f"work assertion source is not an array: {source_path}")
        normalized: list[dict[str, Any]] = []
        for record in records:
            source_iri = str(record.get("id") or "")
            source_route = work_routes.get(source_iri)
            if not source_route:
                raise SemanticBuildError(f"work has no validated route: {source_iri}")
            for compact in core_relationship_rows(
                record,
                route=source_route,
                observed_at=generated_at,
            ):
                rich, target_kind = core_assertion(compact, source_path, work_routes)
                if rich["id"] in seen_ids:
                    raise SemanticBuildError(f"duplicate assertion id: {rich['id']}")
                seen_ids.add(rich["id"])
                normalized.append(rich)
                predicate_counts[("core", rich["predicate"])] += 1
                entry = route_registry.setdefault(
                    rich["target"],
                    {
                        "iri": rich["target"],
                        "route": rich["target_route"],
                        "kind": target_kind,
                        "planes": [],
                    },
                )
                if entry["route"] != rich["target_route"]:
                    raise SemanticBuildError(
                        f"target IRI maps to two routes: {rich['target']}"
                    )
                if "core" not in entry["planes"]:
                    entry["planes"].append("core")
        output_path = (
            OUTPUT
            / "active"
            / "core"
            / f"assertions-{index:03d}.jsonld.gz"
        )
        semantic_material, runtime_material = emit_shard_pair(
            normalized,
            output_path=output_path,
            plane_name="core",
            active=True,
            source_path=source_path,
            check=check,
            expected_paths=expected_paths,
            route_incidents=route_incidents,
        )
        output_chunks.append(semantic_material)
        runtime_output_chunks.append(runtime_material)
        total += len(normalized)
    return output_chunks, runtime_output_chunks, total


def emit_effect_chunks(
    *,
    work_routes: dict[str, str],
    check: bool,
    expected_paths: set[Path],
    seen_ids: set[str],
    route_registry: dict[str, dict[str, Any]],
    predicate_counts: Counter[tuple[str, str]],
    route_incidents: dict[str, dict[str, dict[str, set[str]]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    source_rows = load_json(EFFECTS_ASSERTIONS)
    if not isinstance(source_rows, list):
        raise SemanticBuildError("official-effects assertion input is not an array")
    output_chunks: list[dict[str, Any]] = []
    runtime_output_chunks: list[dict[str, Any]] = []
    total = 0
    for index, source_chunk in enumerate(chunks(source_rows)):
        normalized: list[dict[str, Any]] = []
        for row in source_chunk:
            rich, target_kind = provider_assertion(
                row,
                EFFECTS_ASSERTIONS,
                work_routes,
                plane_name="official-effects",
                active=True,
            )
            if rich["id"] in seen_ids:
                raise SemanticBuildError(f"duplicate assertion id: {rich['id']}")
            seen_ids.add(rich["id"])
            normalized.append(rich)
            predicate_counts[("official-effects", rich["predicate"])] += 1
            for iri, route, kind in (
                (rich["target"], rich["target_route"], target_kind),
                *(
                    ((rich["source"], rich["source_route"], "external-legal-work"),)
                    if not rich["source_in_catalogue_snapshot"]
                    else ()
                ),
            ):
                entry = route_registry.setdefault(
                    iri,
                    {"iri": iri, "route": route, "kind": kind, "planes": []},
                )
                if entry["route"] != route:
                    raise SemanticBuildError(f"IRI maps to two routes: {iri}")
                if "official-effects" not in entry["planes"]:
                    entry["planes"].append("official-effects")
        output_path = OUTPUT / "active" / "official-effects" / f"assertions-{index:03d}.jsonld.gz"
        semantic_material, runtime_material = emit_shard_pair(
            normalized,
            output_path=output_path,
            plane_name="official-effects",
            active=True,
            source_path=EFFECTS_ASSERTIONS,
            check=check,
            expected_paths=expected_paths,
            route_incidents=route_incidents,
        )
        output_chunks.append(semantic_material)
        runtime_output_chunks.append(runtime_material)
        total += len(normalized)
    return output_chunks, runtime_output_chunks, total


def source_paths_from_manifest(manifest_path: Path, *, root_prefix: Path) -> list[Path]:
    manifest = load_json(manifest_path)
    source_chunks = manifest.get("chunks")
    if not isinstance(source_chunks, list) or not source_chunks:
        raise SemanticBuildError(f"manifest has no assertion chunks: {manifest_path}")
    paths: list[Path] = []
    for row in source_chunks:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise SemanticBuildError(f"invalid assertion chunk declaration: {manifest_path}")
        path = root_prefix / row["path"]
        if not path.is_file():
            raise SemanticBuildError(f"declared assertion chunk is absent: {path}")
        if row.get("sha256") != sha256_file(path) or row.get("bytes") != path.stat().st_size:
            raise SemanticBuildError(f"assertion chunk binding differs: {path}")
        paths.append(path)
    return paths


def build(*, check: bool = False) -> dict[str, Any]:
    work_routes, route_to_iri, work_registry = work_route_registry()
    core_assertion.route_to_iri = route_to_iri  # type: ignore[attr-defined]
    expected_paths: set[Path] = set()
    seen_ids: set[str] = set()
    route_registry: dict[str, dict[str, Any]] = {}
    predicate_counts: Counter[tuple[str, str]] = Counter()
    route_incidents: dict[str, dict[str, dict[str, set[str]]]] = {}

    context_path = OUTPUT / "context.jsonld"
    context_body = render_json({"@context": CONTEXT})
    write_or_check(context_path, context_body, check=check)
    expected_paths.add(context_path)

    core_manifest = load_json(SOURCE_MANIFEST)
    core_sources = [
        BUNDLE / str(path) for path in core_manifest["chunks"]["datasets"]
    ]
    core_shards, core_runtime_shards, core_count = emit_core_chunks(
        source_chunks=core_sources,
        generated_at=str(core_manifest["generated_at"]),
        work_routes=work_routes,
        route_to_iri=route_to_iri,
        check=check,
        expected_paths=expected_paths,
        seen_ids=seen_ids,
        route_registry=route_registry,
        predicate_counts=predicate_counts,
        route_incidents=route_incidents,
    )

    effect_shards, effect_runtime_shards, effect_count = emit_effect_chunks(
        work_routes=work_routes,
        check=check,
        expected_paths=expected_paths,
        seen_ids=seen_ids,
        route_registry=route_registry,
        predicate_counts=predicate_counts,
        route_incidents=route_incidents,
    )

    v3_sources = source_paths_from_manifest(V3_MANIFEST, root_prefix=ROOT)
    v3_shards, v3_runtime_shards, v3_count = emit_source_chunks(
        source_chunks=v3_sources,
        output_directory=OUTPUT / "active" / "model-assisted-v3",
        plane_name="model-assisted-v3",
        active=True,
        work_routes=work_routes,
        normalizer=lambda row, path, routes: provider_assertion(
            row, path, routes, plane_name="model-assisted-v3", active=True
        ),
        check=check,
        expected_paths=expected_paths,
        seen_ids=seen_ids,
        route_registry=route_registry,
        predicate_counts=predicate_counts,
        route_incidents=route_incidents,
    )

    v2_sources = source_paths_from_manifest(V2_MANIFEST, root_prefix=BUNDLE)
    v2_shards, v2_runtime_shards, v2_count = emit_source_chunks(
        source_chunks=v2_sources,
        output_directory=OUTPUT / "historical" / "model-assisted-v2",
        plane_name="model-assisted-v2-historical",
        active=False,
        work_routes=work_routes,
        normalizer=lambda row, path, routes: provider_assertion(
            row, path, routes, plane_name="model-assisted-v2-historical", active=False
        ),
        check=check,
        expected_paths=expected_paths,
        seen_ids=seen_ids,
        route_registry=route_registry,
        predicate_counts=predicate_counts,
        route_incidents=route_incidents,
    )

    effects_manifest = load_json(EFFECTS_MANIFEST)
    v3_manifest = load_json(V3_MANIFEST)
    v2_manifest = load_json(V2_MANIFEST)
    declared = {
        "core": int(core_manifest["counts"]["relationships"]),
        "official-effects": int(effects_manifest["counts"]["assertions"]),
        "model-assisted-v3": int(v3_manifest["counts"]["assertions"]),
        "model-assisted-v2-historical": int(v2_manifest["counts"]["assertions"]),
    }
    actual = {
        "core": core_count,
        "official-effects": effect_count,
        "model-assisted-v3": v3_count,
        "model-assisted-v2-historical": v2_count,
    }
    if actual != declared:
        raise SemanticBuildError(f"semantic plane counts differ from governed inputs: {actual} != {declared}")

    plane_specs = [
        {
            "name": "core",
            "active": True,
            "lifecycle": "active",
            "authority_classes": ["official", "derived"],
            "source_schema": "okf-legislation-work-record -> deterministic relationship assertion",
            "source_manifest": SOURCE_MANIFEST,
            "shards": core_shards,
            "runtime_shards": core_runtime_shards,
            "count": core_count,
            "notice": "Official document-type metadata and deterministic title discovery remain distinguishable on every assertion.",
        },
        {
            "name": "official-effects",
            "active": True,
            "lifecycle": "active",
            "authority_classes": ["official"],
            "source_schema": "okf-relationship-assertion.v2",
            "source_manifest": EFFECTS_MANIFEST,
            "shards": effect_shards,
            "runtime_shards": effect_runtime_shards,
            "count": effect_count,
            "notice": "Official source-native effects are partial to successful frozen routes and do not imply whole-corpus completeness.",
        },
        {
            "name": "model-assisted-v3",
            "active": True,
            "lifecycle": "active",
            "authority_classes": ["model-assisted"],
            "source_schema": "okf-enrichment-accepted-assertion-manifest.v3",
            "source_manifest": V3_MANIFEST,
            "shards": v3_shards,
            "runtime_shards": v3_runtime_shards,
            "count": v3_count,
            "notice": "Only independently accepted v3 discovery assertions are active; they are not official classification or legal advice.",
        },
        {
            "name": "model-assisted-v2-historical",
            "active": False,
            "lifecycle": "historical",
            "authority_classes": ["model-assisted"],
            "source_schema": "okf-provider-datapack.v1",
            "source_manifest": V2_MANIFEST,
            "shards": v2_shards,
            "runtime_shards": v2_runtime_shards,
            "count": v2_count,
            "notice": "The independently audited v2 snapshot is preserved as historical and excluded from active totals.",
        },
        {
            "name": "model-assisted-v1-rejected",
            "active": False,
            "lifecycle": "rejected",
            "authority_classes": ["model-assisted"],
            "source_schema": "okf-model-assisted-enrichment.v1",
            "source_manifest": V1_RULES,
            "source_materials": [material(V1_RULES), material(V1_AUDIT)],
            "shards": [],
            "runtime_shards": [],
            "count": 0,
            "notice": "The rejected v1 rules remain immutable evidence and contribute no semantic assertions.",
        },
    ]

    route_locator, route_locator_buckets, route_locator_bounds = emit_route_locator(
        route_incidents,
        active_planes={
            spec["name"]
            for spec in plane_specs
            if spec["lifecycle"] == "active"
        },
        known_planes={spec["name"] for spec in plane_specs},
        known_chunk_paths={
            row["path"]
            for spec in plane_specs
            for row in spec["runtime_shards"]
        },
        check=check,
        expected_paths=expected_paths,
    )
    runtime_manifest_path = OUTPUT / "runtime-manifest.json"
    runtime_manifest = {
        "@id": artifact_iri(runtime_manifest_path),
        "schema": "okf-rich-relationship-runtime-manifest.v1",
        "snapshot": str(core_manifest["snapshot"]),
        "generated_at": GENERATED_AT,
        "semantic_manifest": "data/semantic/manifest.yamlld",
        "assertion_contract": (
            "whole-law/schemas/relationship-assertion-v3.schema.json"
        ),
        "row_contract": (
            "whole-law/schemas/relationship-runtime-row.schema.json"
        ),
        "default_planes": [
            spec["name"]
            for spec in plane_specs
            if spec["lifecycle"] == "active"
        ],
        "route_locator": route_locator,
        "planes": [
            {
                "id": f"{PLANE_BASE}{spec['name']}",
                "name": spec["name"],
                "active": spec["active"],
                "lifecycle": spec["lifecycle"],
                "authority_classes": spec["authority_classes"],
                "assertions": spec["count"],
                "chunks": spec["runtime_shards"],
            }
            for spec in plane_specs
        ],
        "totals": {
            "active_assertions": core_count + effect_count + v3_count,
            "historical_assertions": v2_count,
            "rejected_assertions": 0,
            "all_assertions": core_count + effect_count + v3_count + v2_count,
            "chunks": sum(
                len(spec["runtime_shards"]) for spec in plane_specs
            ),
        },
        "loading_policy": (
            "Load only default_planes unless the reader explicitly requests "
            "a historical plane; rejected planes contain no rows."
        ),
    }
    validate_runtime_manifest(runtime_manifest)
    runtime_manifest_body = render_json(runtime_manifest)
    write_or_check(
        runtime_manifest_path,
        runtime_manifest_body,
        check=check,
    )
    expected_paths.add(runtime_manifest_path)
    bind_root_reader_descriptor(
        runtime_manifest_body,
        check=check,
    )

    manifest_graph: list[dict[str, Any]] = [{
        "@id": "urn:okf:uk-legislation:relationship-dataset:2026-08-09",
        "@type": "okf:RelationshipDataset",
        "title": "UK Legislation rich directed relationship semantic layer",
        "schema": "okf-relationship-semantic-manifest.v1",
        "generated_at": GENERATED_AT,
        "profile": {"@id": f"{PUBLIC}/profile/whole-law/v1/"},
        "assertionSchema": {"@id": f"{PUBLIC}/profile/whole-law/v1/relationship-assertion-v3.schema.json"},
        "routeRegistry": {"@id": artifact_iri(OUTPUT / "iri-route-registry.json")},
        "predicateRegistry": {"@id": artifact_iri(OUTPUT / "predicate-registry.json")},
        "relationshipRuntimeManifest": {
            "@id": artifact_iri(runtime_manifest_path)
        },
        "counts": {
            "active_assertions": core_count + effect_count + v3_count,
            "historical_assertions": v2_count,
            "rejected_assertions": 0,
            "direct_triples": core_count + effect_count + v3_count + v2_count,
            "reified_statements": core_count + effect_count + v3_count + v2_count,
        },
        "notice": "Authority, lifecycle and evidence planes are additive and are never collapsed into semantic identity or legal authority.",
    }]
    for spec in plane_specs:
        source_path = spec["source_manifest"]
        plane_node = {
            "@id": f"{PLANE_BASE}{spec['name']}",
            "@type": "okf:RelationshipPlane",
            "name": spec["name"],
            "active": spec["active"],
            "lifecycle": spec["lifecycle"],
            "authority_classes": spec["authority_classes"],
            "source_schema": spec["source_schema"],
            "source_assertion": source_binding(source_path),
            "sourceMaterial": {"@id": source_material_url(source_path)},
            "assertion_count": spec["count"],
            "shard": [{"@id": row["id"]} for row in spec["shards"]],
            "runtimeShard": [
                {"@id": row["id"]} for row in spec["runtime_shards"]
            ],
            "shards": spec["shards"],
            "runtime_shards": spec["runtime_shards"],
            "notice": spec["notice"],
        }
        if "source_materials" in spec:
            plane_node["source_materials"] = spec["source_materials"]
        manifest_graph.append(plane_node)

    manifest = {
        "@context": CONTEXT,
        "@id": "urn:okf:uk-legislation:relationship-manifest:2026-08-09",
        "@type": "okf:RelationshipSemanticManifest",
        "schema": "okf-relationship-semantic-manifest.v1",
        "generated_at": GENERATED_AT,
        "@graph": manifest_graph,
    }
    manifest_body = render_json(manifest)
    for name in ("manifest.yamlld", "manifest.jsonld"):
        path = OUTPUT / name
        write_or_check(path, manifest_body, check=check)
        expected_paths.add(path)

    registry_rows = sorted(
        (
            {**row, "planes": sorted(row["planes"])}
            for row in route_registry.values()
        ),
        key=lambda row: (row["route"], row["iri"]),
    )
    iri_by_route: dict[str, str] = {}
    for row in registry_rows:
        existing_iri = iri_by_route.setdefault(row["route"], row["iri"])
        if existing_iri != row["iri"]:
            raise SemanticBuildError(
                "semantic route maps to two IRIs: "
                f"{row['route']} -> {existing_iri}, {row['iri']}"
            )
    route_document = {
        "schema": "okf-iri-route-registry.v1",
        "generated_at": GENERATED_AT,
        "identity_policy": "absolute-semantic-iri-plus-validated-local-route",
        "work_routes": work_registry,
        "semantic_and_external_routes": registry_rows,
        "counts": {
            "catalogue_work_routes": len(work_routes),
            "semantic_and_external_routes": len(registry_rows),
        },
    }
    route_path = OUTPUT / "iri-route-registry.json"
    write_or_check(route_path, render_json(route_document), check=check)
    expected_paths.add(route_path)

    registry_by_iri = {entry["iri"] for entry in registry_rows}
    predicate_rows: list[dict[str, Any]] = []
    for (plane, iri), count in sorted(predicate_counts.items()):
        matching = PREDICATES_BY_IRI.get(iri)
        if matching is None:
            raise SemanticBuildError(f"predicate registry cannot describe {iri}")
        predicate_rows.append({
            "iri": iri,
            "label": matching["label"],
            "inverse_label": matching["inverse_label"],
            "plane": plane,
            "assertions": count,
        })
    predicate_document = {
        "schema": "okf-predicate-registry.v1",
        "generated_at": GENERATED_AT,
        "predicates": predicate_rows,
        "counts": {"plane_predicates": len(predicate_rows)},
    }
    predicate_path = OUTPUT / "predicate-registry.json"
    write_or_check(predicate_path, render_json(predicate_document), check=check)
    expected_paths.add(predicate_path)

    # Validate every registered target was observed and every emitted file is
    # owned by this generator.  In build mode stale generated shards are
    # removed one file at a time; source evidence is outside OUTPUT.
    if not registry_by_iri:
        raise SemanticBuildError("semantic route registry is empty")
    if OUTPUT.exists():
        actual_paths = {path for path in OUTPUT.rglob("*") if path.is_file()}
        stale = sorted(actual_paths - expected_paths)
        if check and stale:
            raise SemanticBuildError(
                "stale semantic output(s): "
                + ", ".join(root_relative(path) for path in stale[:10])
            )
        if not check:
            for path in stale:
                path.unlink()

    summary = {
        "active_assertions": core_count + effect_count + v3_count,
        "historical_assertions": v2_count,
        "all_assertions": core_count + effect_count + v3_count + v2_count,
        "shards": len(core_shards) + len(effect_shards) + len(v3_shards) + len(v2_shards),
        "runtime_rows": core_count + effect_count + v3_count + v2_count,
        "runtime_shards": sum(
            len(spec["runtime_shards"]) for spec in plane_specs
        ),
        "route_locator_buckets": route_locator_buckets,
        "route_locator_bounds": route_locator_bounds,
        "semantic_routes": len(registry_rows),
        "plane_counts": actual,
        "shared_assertion_schema": {
            "path": root_relative(SHARED_ASSERTION_SCHEMA),
            "sha256": sha256_file(SHARED_ASSERTION_SCHEMA),
            "assertions_validated": (
                core_count + effect_count + v3_count + v2_count
            ),
        },
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        summary = build(check=args.check)
    except (OSError, KeyError, TypeError, ValueError, SemanticBuildError) as exc:
        print(f"relationship semantic layer {'check' if args.check else 'build'} failed: {exc}")
        return 1
    action = "verified" if args.check else "built"
    print(
        f"relationship semantic layer {action}: "
        f"{summary['active_assertions']:,} active + "
        f"{summary['historical_assertions']:,} historical assertions; "
        f"{summary['shards']:,} bounded shards; "
        f"{summary['semantic_routes']:,} semantic/external routes"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
