#!/usr/bin/env python3
"""Execute and receipt the Whole-Law semantic and row-contract gates.

The RDF scope is deliberately bounded to the authored/generated Whole-Law
semantic descriptor.  The legislation corpus is a chunked JSON data plane:
every core and provider relationship row is validated exhaustively against its
declared JSON Schema, but those rows are not misrepresented as RDF triples.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.metadata
import json
import sys
import warnings
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import jsonschema
    import rdflib
    import yaml_ld
    from pyld import jsonld
    from pyshacl import validate as shacl_validate
    from rdflib.compare import isomorphic
    from yaml_ld.to_rdf import ToRDFOptions
except ImportError as exc:  # pragma: no cover - CI reports dependency setup
    raise SystemExit(
        "Semantic validation dependencies are missing; install "
        "requirements-validation.txt"
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"
SOURCE = ROOT / "whole-law"
PACK = BUNDLE / "whole-law"
RECEIPT = SOURCE / "assurance" / "semantic-conformance.json"
PUBLISHED_RECEIPT = PACK / "assurance" / "semantic-conformance.json"

AUTHORED_YAML = SOURCE / "okf-bundle.yamlld"
PUBLISHED_YAML = PACK / "okf-bundle.yamlld"
GENERATED_JSONLD = PACK / "okf-bundle.jsonld"
CONTEXT = SOURCE / "ontology" / "context.jsonld"
SHAPES = SOURCE / "ontology" / "shapes.ttl"
VOCABULARY = SOURCE / "ontology" / "vocabulary.ttl"
EXAMPLES = SOURCE / "ontology" / "examples.jsonld"
SOURCE_REGISTER = PACK / "data" / "source-register.json"
FEDERATION_DESCRIPTOR = PACK / "okf-explorer.json"

SCHEMAS = {
    "federation": SOURCE / "schemas" / "federation.schema.json",
    "provider_datapack": SOURCE / "schemas" / "provider-datapack.schema.json",
    "core_relationship_row": (
        SOURCE / "schemas" / "core-relationship-row.schema.json"
    ),
    "provider_relationship_assertion": (
        SOURCE / "schemas" / "relationship-assertion.schema.json"
    ),
}
PROVIDER_MANIFESTS = {
    "legislation-effects": BUNDLE / "data" / "effects" / "manifest.json",
    "codex-assisted-v3": BUNDLE / "data" / "enrichment-v3" / "manifest.json",
}

OKFLAW = rdflib.Namespace(
    "https://chris-page-gov.github.io/okf-uk-legislation/"
    "profile/whole-law/v1#"
)
SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
ENTITY_CONTRACT_CLASSES = {
    "legal_manifestation": OKFLAW.LegalManifestation,
    "provision": OKFLAW.Provision,
    "case": OKFLAW.Case,
    "court": OKFLAW.Court,
    "organisation": OKFLAW.Organisation,
    "publication": OKFLAW.Publication,
    "source_record": OKFLAW.SourceRecord,
    "jurisdiction": OKFLAW.Jurisdiction,
    "temporal_state": OKFLAW.TemporalState,
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def render(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def material(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def graph_from_document(path: Path) -> rdflib.ConjunctiveGraph:
    nquads = yaml_ld.to_rdf(
        path,
        options=ToRDFOptions(format="application/n-quads"),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        graph = rdflib.ConjunctiveGraph()
        graph.parse(data=nquads, format="nquads")
    return graph


def _node_label(graph: rdflib.Graph, node: rdflib.term.Node) -> str:
    try:
        return graph.namespace_manager.normalizeUri(node)
    except Exception:
        return str(node)


def validate_shacl_graph(
    data_graph: rdflib.Graph,
    *,
    graph_name: str,
    shapes_graph: rdflib.Graph,
    vocabulary_graph: rdflib.Graph,
) -> tuple[dict[str, Any], list[str]]:
    """Validate one complete descriptor graph and summarize its SHACL report."""

    errors: list[str] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        conforms, report_graph, _ = shacl_validate(
            data_graph,
            shacl_graph=shapes_graph,
            ont_graph=vocabulary_graph,
            inference="rdfs",
            advanced=True,
        )
    result_nodes = set(
        report_graph.subjects(rdflib.RDF.type, SH.ValidationResult)
    )
    severity_counts = Counter(
        _node_label(report_graph, severity)
        for result in result_nodes
        for severity in report_graph.objects(result, SH.resultSeverity)
    )
    target_classes = set(shapes_graph.objects(None, SH.targetClass))
    explicit_typed_nodes = set(data_graph.subjects(rdflib.RDF.type, None))
    explicit_types = {
        rdf_type
        for node in explicit_typed_nodes
        for rdf_type in data_graph.objects(node, rdflib.RDF.type)
    }
    uncovered_types = sorted(
        str(rdf_type) for rdf_type in explicit_types - target_classes
    )
    target_counts = {
        _node_label(shapes_graph, rdf_type): len(
            set(data_graph.subjects(rdflib.RDF.type, rdf_type))
        )
        for rdf_type in sorted(target_classes, key=str)
        if any(data_graph.subjects(rdflib.RDF.type, rdf_type))
    }

    federation_count = len(
        set(data_graph.subjects(rdflib.RDF.type, OKFLAW.Federation))
    )
    source_register_count = len(
        set(data_graph.subjects(rdflib.RDF.type, OKFLAW.SourceRegister))
    )
    if federation_count != 1:
        errors.append(
            f"{graph_name} must contain one typed Federation, found "
            f"{federation_count}"
        )
    if source_register_count != 1:
        errors.append(
            f"{graph_name} must contain one typed SourceRegister, found "
            f"{source_register_count}"
        )
    if uncovered_types:
        errors.append(
            f"{graph_name} has typed descriptor nodes without a SHACL target: "
            + ", ".join(uncovered_types)
        )
    if not conforms:
        errors.append(
            f"{graph_name} failed SHACL with {len(result_nodes)} validation "
            "result(s)"
        )

    return (
        {
            "conforms": bool(conforms),
            "explicit_typed_nodes": len(explicit_typed_nodes),
            "federation_focus_nodes": federation_count,
            "source_register_focus_nodes": source_register_count,
            "target_counts": dict(sorted(target_counts.items())),
            "uncovered_explicit_types": uncovered_types,
            "validation_results": len(result_nodes),
            "severity_counts": dict(sorted(severity_counts.items())),
        },
        errors,
    )


def schema_validator(path: Path) -> jsonschema.Draft202012Validator:
    schema = load(path)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )


def validate_one_instance(
    instance: Any,
    validator: jsonschema.Draft202012Validator,
    *,
    label: str,
    errors: list[str],
) -> int:
    violations = list(validator.iter_errors(instance))
    if violations:
        errors.append(f"{label}: {violations[0].message}")
    return len(violations)


def safe_bundle_path(relative: str, errors: list[str]) -> Path | None:
    pure = PurePosixPath(relative)
    if (
        not relative
        or pure.is_absolute()
        or "\\" in relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        errors.append(f"unsafe provider chunk path: {relative!r}")
        return None
    candidate = BUNDLE.joinpath(*pure.parts)
    try:
        candidate.resolve().relative_to(BUNDLE.resolve())
    except ValueError:
        errors.append(f"provider chunk escapes bundle: {relative!r}")
        return None
    return candidate


def decode_chunk(
    body: bytes,
    compression: str,
    *,
    label: str,
    errors: list[str],
) -> Any:
    try:
        if compression == "gzip":
            payload = gzip.decompress(body)
        elif compression == "none":
            payload = body
        else:
            errors.append(
                f"{label}: unsupported compression {compression!r} for "
                "exhaustive validation"
            )
            return None
        return json.loads(payload)
    except Exception as exc:
        errors.append(f"{label}: cannot decode JSON payload: {exc}")
        return None


def validate_core_rows(
    validator: jsonschema.Draft202012Validator,
    errors: list[str],
) -> dict[str, Any]:
    inventory: list[dict[str, Any]] = []
    rows_validated = 0
    rows_invalid = 0
    violations = 0
    chunks = sorted((BUNDLE / "data").glob("relationships-*.json.gz"))
    for chunk in chunks:
        body = chunk.read_bytes()
        rows = decode_chunk(
            body,
            "gzip",
            label=chunk.relative_to(ROOT).as_posix(),
            errors=errors,
        )
        if not isinstance(rows, list):
            if rows is not None:
                errors.append(
                    f"{chunk.relative_to(ROOT)}: relationship chunk is not an array"
                )
            continue
        inventory.append(
            {
                "path": chunk.relative_to(BUNDLE).as_posix(),
                "bytes": len(body),
                "records": len(rows),
                "sha256": sha256_bytes(body),
            }
        )
        rows_validated += len(rows)
        for index, row in enumerate(rows):
            row_violations = list(validator.iter_errors(row))
            if row_violations:
                rows_invalid += 1
                violations += len(row_violations)
                if rows_invalid <= 20:
                    errors.append(
                        "core relationship contract failure "
                        f"{chunk.relative_to(ROOT)}[{index}]: "
                        f"{row_violations[0].message}"
                    )

    summary = load(BUNDLE / "data" / "relationship-summary.json")
    expected_rows = int(summary["core_total"])
    if rows_validated != expected_rows:
        errors.append(
            "core relationship row count differs from summary: "
            f"{rows_validated} != {expected_rows}"
        )
    return {
        "schema": "okf-core-relationship-row.v1",
        "chunks_validated": len(chunks),
        "rows_expected": expected_rows,
        "rows_validated": rows_validated,
        "rows_invalid": rows_invalid,
        "schema_violations": violations,
        "chunk_inventory_sha256": sha256_bytes(canonical_bytes(inventory)),
    }


def validate_provider_rows(
    manifest_validator: jsonschema.Draft202012Validator,
    row_validator: jsonschema.Draft202012Validator,
    errors: list[str],
) -> tuple[list[dict[str, Any]], int]:
    results: list[dict[str, Any]] = []
    all_rows = 0
    for datapack_id, manifest_path in PROVIDER_MANIFESTS.items():
        manifest = load(manifest_path)
        manifest_violations = validate_one_instance(
            manifest,
            manifest_validator,
            label=f"{manifest_path.relative_to(ROOT)}",
            errors=errors,
        )
        inventory: list[dict[str, Any]] = []
        declared_paths: set[str] = set()
        rows_validated = 0
        rows_invalid = 0
        row_violations = 0
        for chunk_index, declaration in enumerate(manifest.get("chunks", [])):
            relative = declaration.get("path", "")
            declared_paths.add(relative)
            path = safe_bundle_path(relative, errors)
            if path is None:
                continue
            if not path.is_file():
                errors.append(f"provider chunk is missing: {relative}")
                continue
            body = path.read_bytes()
            actual_sha256 = sha256_bytes(body)
            if len(body) != declaration.get("bytes"):
                errors.append(
                    f"{relative}: byte count differs from provider manifest"
                )
            if actual_sha256 != declaration.get("sha256"):
                errors.append(f"{relative}: SHA-256 differs from provider manifest")
            rows = decode_chunk(
                body,
                declaration.get("compression", ""),
                label=relative,
                errors=errors,
            )
            if not isinstance(rows, list):
                if rows is not None:
                    errors.append(f"{relative}: provider chunk is not an array")
                continue
            if len(rows) != declaration.get("records"):
                errors.append(
                    f"{relative}: record count differs from provider manifest"
                )
            inventory.append(
                {
                    "path": relative,
                    "bytes": len(body),
                    "records": len(rows),
                    "sha256": actual_sha256,
                }
            )
            rows_validated += len(rows)
            for row_index, row in enumerate(rows):
                violations_for_row = list(row_validator.iter_errors(row))
                if violations_for_row:
                    rows_invalid += 1
                    row_violations += len(violations_for_row)
                    if rows_invalid <= 20:
                        errors.append(
                            "provider relationship contract failure "
                            f"{relative}[{row_index}]: "
                            f"{violations_for_row[0].message}"
                        )

        expected_rows = int(manifest.get("counts", {}).get("assertions", -1))
        if rows_validated != expected_rows:
            errors.append(
                f"{datapack_id}: declared {expected_rows} assertions but "
                f"validated {rows_validated}"
            )
        actual_chunk_paths: set[str] = set()
        chunk_directories = {
            PurePosixPath(relative).parent
            for relative in declared_paths
            if relative
        }
        for chunk_directory in sorted(chunk_directories, key=str):
            directory = safe_bundle_path(
                chunk_directory.as_posix(),
                errors,
            )
            if directory is None or not directory.is_dir():
                errors.append(
                    f"{datapack_id}: declared chunk directory is missing: "
                    f"{chunk_directory}"
                )
                continue
            actual_chunk_paths.update(
                path.relative_to(BUNDLE).as_posix()
                for path in directory.glob("*.json.gz")
                if path.is_file()
            )
        if declared_paths != actual_chunk_paths:
            errors.append(
                f"{datapack_id}: declared and present provider chunk sets differ"
            )
        results.append(
            {
                "datapack_id": datapack_id,
                "manifest": material(manifest_path),
                "manifest_schema_violations": manifest_violations,
                "chunks_declared": len(manifest.get("chunks", [])),
                "chunks_validated": len(inventory),
                "rows_expected": expected_rows,
                "rows_validated": rows_validated,
                "rows_invalid": rows_invalid,
                "schema_violations": row_violations,
                "chunk_inventory_sha256": sha256_bytes(
                    canonical_bytes(inventory)
                ),
            }
        )
        all_rows += rows_validated
    return results, all_rows


def semantic_materials() -> dict[str, Any]:
    return {
        "validator": material(Path(__file__).resolve()),
        "authored_yaml_ld": material(AUTHORED_YAML),
        "published_yaml_ld": material(PUBLISHED_YAML),
        "generated_json_ld": material(GENERATED_JSONLD),
        "context": material(CONTEXT),
        "shapes": material(SHAPES),
        "vocabulary": material(VOCABULARY),
        "contract_examples": material(EXAMPLES),
        "source_register": material(SOURCE_REGISTER),
        "federation_descriptor": material(FEDERATION_DESCRIPTOR),
        "schemas": {
            name: material(path) for name, path in sorted(SCHEMAS.items())
        },
    }


def build_receipt() -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    materials = semantic_materials()

    if sha256(AUTHORED_YAML) != sha256(PUBLISHED_YAML):
        errors.append("published YAML-LD is not byte-identical to its authored source")
    for relative in (
        Path("ontology/context.jsonld"),
        Path("ontology/shapes.ttl"),
        Path("ontology/vocabulary.ttl"),
        *(
            Path("schemas") / path.name
            for path in SCHEMAS.values()
        ),
    ):
        authored = SOURCE / relative
        published = PACK / relative
        if not published.is_file() or sha256(authored) != sha256(published):
            errors.append(f"published semantic contract differs: {relative}")

    yaml_expanded: Any = None
    json_expanded: Any = None
    yaml_graph: rdflib.ConjunctiveGraph | None = None
    json_graph: rdflib.ConjunctiveGraph | None = None
    yaml_canonical = ""
    json_canonical = ""
    yaml_round_trip = False
    json_round_trip = False
    api_operations: dict[str, Any] = {}
    try:
        yaml_expanded = yaml_ld.expand(AUTHORED_YAML)
        json_expanded = yaml_ld.expand(GENERATED_JSONLD)
        if not yaml_expanded or not json_expanded:
            errors.append("YAML-LD or JSON-LD expands to an empty graph")
        yaml_graph = graph_from_document(AUTHORED_YAML)
        json_graph = graph_from_document(GENERATED_JSONLD)
        if not isomorphic(yaml_graph, json_graph):
            errors.append("authored YAML-LD and generated JSON-LD graphs differ")
        canonical_options = {
            "algorithm": "URDNA2015",
            "format": "application/n-quads",
        }
        yaml_canonical = jsonld.normalize(yaml_expanded, canonical_options)
        json_canonical = jsonld.normalize(json_expanded, canonical_options)
        if yaml_canonical != json_canonical:
            errors.append(
                "YAML-LD and JSON-LD canonical N-Quads serializations differ"
            )
        for name, path, graph in (
            ("YAML-LD", AUTHORED_YAML, yaml_graph),
            ("JSON-LD", GENERATED_JSONLD, json_graph),
        ):
            nquads = yaml_ld.to_rdf(
                path,
                options=ToRDFOptions(format="application/n-quads"),
            )
            round_trip_document = yaml_ld.from_rdf(nquads)
            round_trip_nquads = yaml_ld.to_rdf(
                round_trip_document,
                options=ToRDFOptions(format="application/n-quads"),
            )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                round_trip_graph = rdflib.ConjunctiveGraph()
                round_trip_graph.parse(data=round_trip_nquads, format="nquads")
            passed = isomorphic(graph, round_trip_graph)
            if name == "YAML-LD":
                yaml_round_trip = passed
            else:
                json_round_trip = passed
            if not passed:
                errors.append(f"{name} RDF round-trip changed the semantic graph")

        context = load(CONTEXT)["@context"]
        expected_id = (
            "https://chris-page-gov.github.io/okf-uk-legislation/whole-law/"
        )
        for representation, path in (
            ("authored_yaml_ld", AUTHORED_YAML),
            ("generated_json_ld", GENERATED_JSONLD),
        ):
            compacted = yaml_ld.compact(path, context)
            flattened = yaml_ld.flatten(path, context)
            framed = yaml_ld.frame(
                path,
                {"@context": context, "@type": "okflaw:Federation"},
            )
            framed_id = framed.get("id") or framed.get("@id")
            api_operations[representation] = {
                "compaction_non_empty": bool(compacted),
                "flattening_non_empty": bool(flattened),
                "framing_non_empty": bool(framed),
                "framed_federation_id": framed_id,
                "framed_identity_retained": framed_id == expected_id,
            }
            if not all((compacted, flattened, framed)):
                errors.append(
                    f"{representation} JSON-LD API operation produced an empty "
                    "document"
                )
            if framed_id != expected_id:
                errors.append(
                    f"{representation} framing did not retain Federation identity"
                )
    except Exception as exc:
        errors.append(f"semantic expansion/equivalence failed: {exc}")

    shapes_graph = rdflib.Graph()
    vocabulary_graph = rdflib.Graph()
    shapes_graph.parse(SHAPES, format="turtle")
    vocabulary_graph.parse(VOCABULARY, format="turtle")
    shape_count = len(
        set(shapes_graph.subjects(rdflib.RDF.type, SH.NodeShape))
    )
    shacl_results: dict[str, Any] = {}
    if yaml_graph is not None and json_graph is not None:
        for name, graph in (
            ("authored_yaml_ld", yaml_graph),
            ("generated_json_ld", json_graph),
        ):
            result, shacl_errors = validate_shacl_graph(
                graph,
                graph_name=name,
                shapes_graph=shapes_graph,
                vocabulary_graph=vocabulary_graph,
            )
            shacl_results[name] = result
            errors.extend(shacl_errors)
    examples_graph = rdflib.Graph()
    examples_graph.parse(EXAMPLES, format="json-ld")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        examples_conforms, examples_report, _ = shacl_validate(
            examples_graph,
            shacl_graph=shapes_graph,
            ont_graph=vocabulary_graph,
            inference="rdfs",
            advanced=True,
        )
    example_results = set(
        examples_report.subjects(rdflib.RDF.type, SH.ValidationResult)
    )
    if not examples_conforms:
        errors.append(
            "semantic contract examples failed SHACL with "
            f"{len(example_results)} validation result(s)"
        )
    entity_contract_targets: dict[str, Any] = {}
    for label, rdf_type in ENTITY_CONTRACT_CLASSES.items():
        focus_nodes = set(examples_graph.subjects(rdflib.RDF.type, rdf_type))
        shape_nodes = set(shapes_graph.subjects(SH.targetClass, rdf_type))
        required_property_shapes = {
            property_shape
            for shape in shape_nodes
            for property_shape in shapes_graph.objects(shape, SH.property)
            if any(
                int(value) >= 1
                for value in shapes_graph.objects(property_shape, SH.minCount)
            )
        }
        entity_contract_targets[label] = {
            "class": str(rdf_type),
            "example_focus_nodes": len(focus_nodes),
            "node_shapes": len(shape_nodes),
            "required_property_constraints": len(required_property_shapes),
        }
        if not focus_nodes:
            errors.append(
                f"entity contract {label} has no explicit example focus node"
            )
        if not shape_nodes:
            errors.append(f"entity contract {label} has no SHACL node shape")
        if not required_property_shapes:
            errors.append(
                f"entity contract {label} has no required SHACL property constraint"
            )

    source_register = load(SOURCE_REGISTER)
    expected_source_hash = f"sha256:{sha256(SOURCE_REGISTER)}"
    source_classes = len(
        {
            source_class
            for row in source_register["records"]
            for source_class in row.get("source_classes", [])
        }
    )
    access_methods = sum(
        len(row.get("access_methods", []))
        for row in source_register["records"]
    )
    source_contract_matches = False
    if yaml_graph is not None:
        source_nodes = set(
            yaml_graph.subjects(rdflib.RDF.type, OKFLAW.SourceRegister)
        )
        source_hashes = {
            str(value)
            for node in source_nodes
            for value in yaml_graph.objects(node, OKFLAW.sourceHash)
        }
        if source_hashes != {expected_source_hash}:
            errors.append(
                "semantic SourceRegister hash does not bind the published register"
            )
        expected_source_node = rdflib.URIRef(
            "https://chris-page-gov.github.io/okf-uk-legislation/"
            "whole-law/data/source-register.json"
        )
        expected_facts = {
            OKFLAW.registerSchema: source_register["schema"],
            OKFLAW.recordCount: str(len(source_register["records"])),
            OKFLAW.sourceClassCount: str(source_classes),
            OKFLAW.accessMethodCount: str(access_methods),
            OKFLAW.accessTestDate: source_register["access_test_date"],
            OKFLAW.sourceHash: expected_source_hash,
        }
        actual_facts = {
            predicate: {
                str(value)
                for value in yaml_graph.objects(expected_source_node, predicate)
            }
            for predicate in expected_facts
        }
        mismatched_facts = [
            _node_label(yaml_graph, predicate)
            for predicate, expected in expected_facts.items()
            if actual_facts[predicate] != {expected}
        ]
        if source_nodes != {expected_source_node}:
            mismatched_facts.append("rdf:type okflaw:SourceRegister")
        if mismatched_facts:
            errors.append(
                "semantic SourceRegister facts differ from the published "
                "register: "
                + ", ".join(sorted(mismatched_facts))
            )
        else:
            source_contract_matches = True

        expected_federation = rdflib.URIRef(
            "https://chris-page-gov.github.io/okf-uk-legislation/whole-law/"
        )
        expected_federation_links = {
            OKFLAW.descriptor: rdflib.URIRef(
                "https://chris-page-gov.github.io/okf-uk-legislation/"
                "whole-law/okf-explorer.json"
            ),
            OKFLAW.childBundle: rdflib.URIRef(
                "https://chris-page-gov.github.io/okf-uk-legislation/"
                "okf-explorer.json"
            ),
            OKFLAW.sourceRegister: expected_source_node,
        }
        for predicate, expected in expected_federation_links.items():
            actual = set(yaml_graph.objects(expected_federation, predicate))
            if actual != {expected}:
                errors.append(
                    "semantic Federation link differs for "
                    f"{_node_label(yaml_graph, predicate)}"
                )

    federation_validator = schema_validator(SCHEMAS["federation"])
    provider_manifest_validator = schema_validator(
        SCHEMAS["provider_datapack"]
    )
    core_validator = schema_validator(SCHEMAS["core_relationship_row"])
    provider_row_validator = schema_validator(
        SCHEMAS["provider_relationship_assertion"]
    )
    federation_violations = validate_one_instance(
        load(FEDERATION_DESCRIPTOR),
        federation_validator,
        label=FEDERATION_DESCRIPTOR.relative_to(ROOT).as_posix(),
        errors=errors,
    )
    core_result = validate_core_rows(core_validator, errors)
    provider_results, provider_rows = validate_provider_rows(
        provider_manifest_validator,
        provider_row_validator,
        errors,
    )
    root_relationship_summary = load(
        BUNDLE / "data" / "relationship-summary.json"
    )
    federation_relationship_summary = load(
        PACK / "data" / "relationship-summary.json"
    )
    expected_provider_rows = int(
        root_relationship_summary["external_datapack_total"]
    )
    if provider_rows != expected_provider_rows:
        errors.append(
            "provider relationship total differs from Whole-Law summary: "
            f"{provider_rows} != {expected_provider_rows}"
        )
    all_relationship_rows = core_result["rows_validated"] + provider_rows
    expected_all_rows = int(root_relationship_summary["combined_total"])
    if all_relationship_rows != expected_all_rows:
        errors.append(
            "total relationship rows differ from Whole-Law summary: "
            f"{all_relationship_rows} != {expected_all_rows}"
        )
    if int(federation_relationship_summary["total"]) != expected_all_rows:
        errors.append(
            "Whole-Law federation and legislation relationship summaries differ"
        )

    root_descriptor = load(BUNDLE / "okf-explorer.json")
    catalogued_works = int(root_descriptor["counts"]["works"])
    explicit_legal_work_types = {OKFLAW.LegalWork, OKFLAW.LegislationWork}
    rdf_legal_works = (
        len(
            {
                subject
                for subject, rdf_type in yaml_graph.subject_objects(
                    rdflib.RDF.type
                )
                if rdf_type in explicit_legal_work_types
            }
        )
        if yaml_graph is not None
        else 0
    )
    if rdf_legal_works != 0:
        errors.append(
            "semantic descriptor unexpectedly materialises legal-work nodes; "
            "update the scope contract before claiming them"
        )

    generated_document = load(GENERATED_JSONLD)
    processors = {
        distribution: importlib.metadata.version(distribution)
        for distribution in (
            "jsonschema",
            "PyLD",
            "pyshacl",
            "rdflib",
            "yaml-ld",
        )
    }
    input_fingerprint = sha256_bytes(canonical_bytes(materials))
    receipt = {
        "schema": "okf-semantic-conformance.v1",
        "generated_at": generated_document["generatedAt"],
        "status": "passed" if not errors else "failed",
        "scope": {
            "semantic_graph": (
                "The complete authored/generated Whole-Law federation "
                "descriptor graph: one Federation and its governed "
                "SourceRegister contract node."
            ),
            "catalogued_legal_works": catalogued_works,
            "rdf_materialized_legal_works": rdf_legal_works,
            "relationship_rows_materialized_as_rdf": 0,
            "relationship_rows_exhaustively_validated_as_json": (
                all_relationship_rows
            ),
            "claim_boundary": (
                "The 365,786 catalogued legal works and relationship data plane "
                "are not materialised as RDF in this publication. SHACL covers "
                "the complete two-node semantic descriptor graph; JSON Schema "
                "covers every compact core and provider relationship row."
            ),
        },
        "materials": materials,
        "input_fingerprint_sha256": input_fingerprint,
        "processors": processors,
        "semantic_equivalence": {
            "yaml_ld_expanded_non_empty": bool(yaml_expanded),
            "json_ld_expanded_non_empty": bool(json_expanded),
            "graphs_isomorphic": bool(
                yaml_graph is not None
                and json_graph is not None
                and isomorphic(yaml_graph, json_graph)
            ),
            "yaml_graph_triples": len(yaml_graph) if yaml_graph is not None else 0,
            "json_graph_triples": len(json_graph) if json_graph is not None else 0,
            "canonical_nquads_sha256": (
                sha256_bytes(yaml_canonical.encode("utf-8"))
                if yaml_canonical
                else None
            ),
            "canonical_serializations_equal": (
                bool(yaml_canonical)
                and yaml_canonical == json_canonical
            ),
            "yaml_ld_rdf_round_trip": yaml_round_trip,
            "json_ld_rdf_round_trip": json_round_trip,
            "json_ld_api_operations": api_operations,
        },
        "shacl": {
            "node_shapes_declared": shape_count,
            "descriptor_graphs_validated": 2,
            "results": shacl_results,
            "contract_examples": {
                "conforms": bool(examples_conforms),
                "triples": len(examples_graph),
                "validation_results": len(example_results),
                "entity_contract_targets": entity_contract_targets,
                "all_named_entity_contracts_non_vacuous": all(
                    row["example_focus_nodes"] >= 1
                    and row["node_shapes"] >= 1
                    and row["required_property_constraints"] >= 1
                    for row in entity_contract_targets.values()
                ),
            },
        },
        "json_schema": {
            "federation_descriptor": {
                "instances_validated": 1,
                "schema_violations": federation_violations,
            },
            "core_relationships": core_result,
            "provider_relationships": provider_results,
            "totals": {
                "core_rows": core_result["rows_validated"],
                "provider_rows": provider_rows,
                "relationship_rows": all_relationship_rows,
                "invalid_rows": core_result["rows_invalid"]
                + sum(row["rows_invalid"] for row in provider_results),
                "schema_violations": core_result["schema_violations"]
                + sum(row["schema_violations"] for row in provider_results),
            },
        },
        "source_contract": {
            "schema": source_register["schema"],
            "records": len(source_register["records"]),
            "source_classes": source_classes,
            "access_methods": access_methods,
            "access_test_date": source_register["access_test_date"],
            "published_sha256": sha256(SOURCE_REGISTER),
            "semantic_hash_binding": expected_source_hash,
            "semantic_values_match_published_register": source_contract_matches,
        },
        "errors": errors,
    }
    return receipt, errors


def compare_receipt(receipt: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = render(receipt)
    for path, label in (
        (RECEIPT, "authored assurance receipt"),
        (PUBLISHED_RECEIPT, "published assurance receipt"),
    ):
        if not path.is_file():
            errors.append(f"{label} is missing: {path.relative_to(ROOT)}")
        elif path.read_bytes() != expected:
            errors.append(f"{label} is stale: {path.relative_to(ROOT)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Recompute and compare both authored and published receipts.",
    )
    args = parser.parse_args()

    receipt, errors = build_receipt()
    if args.check:
        errors.extend(compare_receipt(receipt))
    else:
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        RECEIPT.write_bytes(render(receipt))

    if errors:
        print("Whole-Law semantic conformance failed:")
        for error in errors[:100]:
            print(f"- {error}")
        return 1
    totals = receipt["json_schema"]["totals"]
    print(
        "Whole-Law semantic conformance passed: "
        f"{receipt['semantic_equivalence']['yaml_graph_triples']} descriptor "
        f"triples, {totals['core_rows']} core rows, "
        f"{totals['provider_rows']} provider rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
