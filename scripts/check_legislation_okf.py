#!/usr/bin/env python3
"""Validate the checked-in complete legislation OKF publication pack."""

from __future__ import annotations

import json
import gzip
import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import legislation_effects_evidence_archive as effects_evidence

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "bundle"
ACTIVE_RELATIONSHIP_PROVIDER_MANIFESTS = (
    ("effects", "legislation-effects"),
    ("enrichment-v3", "codex-assisted-v3"),
)
MINIMUM_COMPLETE_WORKS = 300_000
REQUIRED_TYPE_CODES = {"ukpga", "uksi", "asp", "ssi", "anaw", "asc", "wsi", "nia", "nisr", "eur"}
VALID_STATUS = {"draft", "stable", "deprecated"}
SEARCH_FILTER_FIELDS = {
    "category",
    "type_code",
    "document_type",
    "creation_year",
    "jurisdiction",
    "legal_status",
    "publisher",
    "topic",
    "format",
    "tag",
    "license",
    "host",
    "resource_type",
    "update_year",
}


def load(path: Path):
    if path.suffix == ".gz":
        return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def route_bucket(route: str) -> str:
    value = 0x811C9DC5
    for byte in route.encode("utf-8"):
        value ^= byte
        value = (value * 0x01000193) & 0xFFFFFFFF
    return f"{(value >> 24) & 0xFF:02x}"


def parse_frontmatter(raw: str) -> dict[str, Any]:
    """Parse the JSON-compatible YAML emitted by the deterministic builder."""
    values: dict[str, Any] = {}
    for line in raw.splitlines():
        key, separator, value = line.partition(":")
        if not separator or not key.strip():
            raise ValueError(f"unsupported frontmatter line: {line}")
        key = key.strip()
        if key in values:
            raise ValueError(f"duplicate frontmatter key: {key}")
        value = value.strip()
        try:
            values[key] = json.loads(value)
        except json.JSONDecodeError:
            values[key] = value
    return values


def valid_actor(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or any(character.isspace() for character in value)
    ):
        return False
    if value.startswith(("human:", "process:")):
        return bool(value.split(":", 1)[1])
    producer, separator, version = value.partition("/")
    return bool(separator and producer and version)


def valid_datetime(value: Any) -> bool:
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def valid_date(value: Any) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def check_usage_window(errors: list[str], value: Any, context: str) -> None:
    if not isinstance(value, dict):
        errors.append(f"usage_window is not a mapping: {context}")
        return
    start = value.get("from")
    end = value.get("to")
    if not valid_date(start) or not valid_date(end):
        errors.append(f"usage_window dates are invalid: {context}")
    elif start > end:
        errors.append(f"usage_window is reversed: {context}")


def check_sources(
    errors: list[str],
    sources: Any,
    shared_usage_window: Any,
    context: str,
) -> None:
    if not isinstance(sources, list) or not sources:
        errors.append(f"standard source provenance is missing: {context}")
        return
    if shared_usage_window is not None:
        check_usage_window(errors, shared_usage_window, context)
    for index, source in enumerate(sources):
        source_context = f"{context} sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"source is not a mapping: {source_context}")
            continue
        if not isinstance(source.get("resource"), str) or not source["resource"].strip():
            errors.append(f"source resource is missing: {source_context}")
        if "author" in source and not valid_actor(source["author"]):
            errors.append(f"source author is not an OKF actor: {source_context}")
        if "last_modified" in source and not valid_date(source["last_modified"]):
            errors.append(f"source last_modified is invalid: {source_context}")
        if "usage_window" in source:
            check_usage_window(errors, source["usage_window"], source_context)
        if "usage_count" in source:
            usage_count = source["usage_count"]
            if (
                isinstance(usage_count, bool)
                or not isinstance(usage_count, (int, float))
                or usage_count < 0
            ):
                errors.append(f"source usage_count is invalid: {source_context}")
            if shared_usage_window is None and "usage_window" not in source:
                errors.append(f"source usage_count has no usage_window: {source_context}")


def check_attested_computation(
    errors: list[str],
    values: dict[str, Any],
    body: str,
    context: str,
) -> None:
    runtime = values.get("runtime")
    if not isinstance(runtime, str) or not runtime.strip():
        errors.append(f"Attested Computation runtime is missing: {context}")
    parameters = values.get("parameters", [])
    if not isinstance(parameters, list):
        errors.append(f"Attested Computation parameters are not a list: {context}")
    else:
        for index, parameter in enumerate(parameters):
            parameter_context = f"{context} parameters[{index}]"
            if not isinstance(parameter, dict):
                errors.append(f"Attested Computation parameter is not a mapping: {parameter_context}")
                continue
            if not isinstance(parameter.get("name"), str) or not parameter["name"].strip():
                errors.append(f"Attested Computation parameter name is missing: {parameter_context}")
            if not isinstance(parameter.get("type"), str) or not parameter["type"].strip():
                errors.append(f"Attested Computation parameter type is missing: {parameter_context}")
            if not isinstance(parameter.get("required"), bool):
                errors.append(f"Attested Computation parameter required is not boolean: {parameter_context}")
    for field in ("executor", "attester"):
        contract = values.get(field)
        if (
            not isinstance(contract, dict)
            or not isinstance(contract.get("resource"), str)
            or not contract["resource"].strip()
        ):
            errors.append(f"Attested Computation {field}.resource is missing: {context}")
    executor = values.get("executor")
    if isinstance(executor, dict):
        receipt = executor.get("receipt")
        if (
            not isinstance(receipt, list)
            or not receipt
            or any(not isinstance(field, str) or not field.strip() for field in receipt)
        ):
            errors.append(f"Attested Computation executor.receipt is invalid: {context}")
    computation = values.get("computation")
    inline = bool(
        re.search(
            r"(?ms)^# Computation\s*$.*?^```[^\n]*\n.+?^```\s*$",
            body,
        )
    )
    if computation is not None and (not isinstance(computation, str) or not computation.strip()):
        errors.append(f"Attested Computation computation path is invalid: {context}")
    if computation is None and not inline:
        errors.append(f"Attested Computation has no inline or file computation: {context}")
    if computation is not None and inline:
        errors.append(f"Attested Computation has both inline and file computation: {context}")


def check_markdown(errors: list[str], generated_at: str) -> int:
    concepts = 0
    legislation_markdown = [
        PACK / "index.md",
        PACK / "log.md",
        *[
            path
            for directory in (
                "access",
                "methodology",
                "ontology",
                "topics",
                "types",
            )
            for path in (PACK / directory).rglob("*.md")
        ],
    ]
    for path in sorted(legislation_markdown):
        if not path.is_file():
            errors.append(
                f"required legislation Markdown is missing: {path.relative_to(PACK)}"
            )
            continue
        relative = path.relative_to(PACK)
        text = path.read_text(encoding="utf-8")
        if relative == Path("index.md"):
            if not text.startswith("---\n"):
                errors.append("root index.md does not declare OKF v0.2")
                continue
            try:
                raw, body = text[4:].split("\n---\n", 1)
                values = parse_frontmatter(raw)
            except ValueError as error:
                errors.append(f"root index.md frontmatter is invalid: {error}")
                continue
            if values != {"okf_version": "0.2"}:
                errors.append("root index.md frontmatter must contain only okf_version 0.2")
            if not re.search(r"(?m)^# .+", body):
                errors.append("root index.md has no section heading")
            continue
        if path.name in {"index.md", "log.md"}:
            if text.startswith("---\n"):
                errors.append(f"reserved Markdown has frontmatter: {relative}")
            if not re.search(r"(?m)^# .+", text):
                errors.append(f"reserved Markdown has no section heading: {relative}")
            if path.name == "log.md":
                headings = re.findall(r"(?m)^## (.+)$", text)
                if not headings:
                    errors.append(f"log has no dated entries: {relative}")
                for heading in headings:
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", heading):
                        errors.append(f"log date is not ISO 8601: {heading}")
            continue
        concepts += 1
        if not text.startswith("---\n"):
            errors.append(f"concept has no frontmatter: {relative}")
            continue
        try:
            raw, body = text[4:].split("\n---\n", 1)
            values = parse_frontmatter(raw)
        except ValueError as error:
            errors.append(f"concept frontmatter is invalid: {relative}: {error}")
            continue
        if not isinstance(values.get("type"), str) or not values["type"].strip():
            errors.append(f"concept type is missing: {relative}")
        if "timestamp" in values:
            errors.append(f"legacy timestamp remains in concept: {relative}")
        generated = values.get("generated")
        if not isinstance(generated, dict):
            errors.append(f"generated.by/at is missing: {relative}")
        else:
            if not valid_actor(generated.get("by")):
                errors.append(f"generated.by is not an OKF actor: {relative}")
            if not valid_datetime(generated.get("at")):
                errors.append(f"generated.at is not an ISO 8601 datetime: {relative}")
            elif generated["at"] != generated_at:
                errors.append(f"generated.at is not the publication time: {relative}")
        status = values.get("status")
        if status not in VALID_STATUS:
            errors.append(f"lifecycle status is missing or invalid: {relative}")
        if "stale_after" in values and not valid_date(values["stale_after"]):
            errors.append(f"stale_after is not an ISO 8601 date: {relative}")
        check_sources(errors, values.get("sources"), values.get("usage_window"), str(relative))
        if "verified" in values:
            events = values["verified"] if isinstance(values["verified"], list) else [values["verified"]]
            if not events:
                errors.append(f"verified is empty: {relative}")
            for event in events:
                if (
                    not isinstance(event, dict)
                    or not valid_actor(event.get("by"))
                    or not valid_datetime(event.get("at"))
                ):
                    errors.append(f"verified event is invalid: {relative}")
            errors.append(f"unsupported verification claim present: {relative}")
        if values.get("type") == "Attested Computation":
            check_attested_computation(errors, values, body, str(relative))
    return concepts


def check_discovery_publication(
    errors: list[str],
    descriptor: dict[str, Any],
    manifest: dict[str, Any],
    routes: list[str],
) -> None:
    initial_error_count = len(errors)
    snapshot = descriptor.get("snapshot")
    if not isinstance(snapshot, str) or not snapshot:
        errors.append("descriptor snapshot is missing")
    elif manifest.get("snapshot") != snapshot:
        errors.append("descriptor and data manifest snapshots differ")

    entrypoints = descriptor.get("entrypoints", {})
    for name in (
        "presentation",
        "record_locator",
        "performance",
        "relationship_composition",
        "search_manifest",
    ):
        relative = entrypoints.get(name)
        if not relative or not (PACK / relative).is_file():
            errors.append(f"browser-safe discovery entrypoint is missing: {name}")
    if len(errors) != initial_error_count:
        return

    search = load(PACK / entrypoints["search_manifest"])
    if search.get("schema") != "okf-static-search.v2":
        errors.append("static search does not use the bounded v2 contract")
    if search.get("snapshot") != snapshot:
        errors.append("static search snapshot differs from the descriptor")
    search_entries = search.get("entrypoints", {})
    filters = search_entries.get("filter_postings", {})
    if set(filters) != SEARCH_FILTER_FIELDS:
        errors.append("static search does not publish postings for every facet")
    if search_entries.get("sort_values") != "data/search/sort-values.json.gz":
        errors.append("static search deterministic sort values are missing")

    shard_path = PACK / str(search.get("shard_metadata", ""))
    if not shard_path.is_file():
        errors.append("static search shard-integrity document is missing")
    else:
        shard_document = load(shard_path)
        shards = shard_document.get("shards", {})
        canonical = json.dumps(
            shards,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != search.get(
            "shard_manifest_sha256"
        ):
            errors.append("static search shard manifest digest is invalid")
        declared_paths: set[str] = set()
        for group, rows in shards.items():
            for row in rows:
                relative = str(row.get("path", ""))
                declared_paths.add(relative)
                path = PACK / relative
                if not path.is_file():
                    errors.append(f"missing static search shard: {relative}")
                    continue
                if path.stat().st_size != int(row.get("compressed_bytes", -1)):
                    errors.append(f"static search shard byte mismatch: {relative}")
                elif file_sha256(path) != row.get("sha256"):
                    errors.append(f"static search shard hash mismatch: {relative}")
                try:
                    load(path)
                except Exception as exc:
                    errors.append(
                        f"static search shard is not decodable ({group}): "
                        f"{relative}: {exc}"
                    )
        actual_paths = {
            path.relative_to(PACK).as_posix()
            for path in (PACK / "data" / "search").rglob("*")
            if path.is_file()
            and path.name not in {"manifest.json", "shards.json"}
        }
        if declared_paths != actual_paths:
            errors.append("static search shard path set is not exact")

    locator = load(PACK / entrypoints["record_locator"])
    if locator.get("schema") != "okf-record-locator-sharded.v1":
        errors.append("record locator schema is invalid")
    if locator.get("algorithm") != "fnv1a32-prefix-2":
        errors.append("record locator hash algorithm is invalid")
    if locator.get("snapshot") != snapshot:
        errors.append("record locator snapshot differs from the descriptor")
    if locator.get("records") != len(routes):
        errors.append("record locator count differs from work count")
    chunk_size = int(locator.get("chunk_size", 0))
    record_chunks = locator.get("record_chunks", [])
    if not chunk_size or not isinstance(record_chunks, list):
        errors.append("record locator work-shard contract is incomplete")
    else:
        for row in record_chunks:
            if not isinstance(row, dict):
                errors.append("record locator work shards are not integrity-bound")
                break
            path = PACK / str(row.get("path", ""))
            if not path.is_file():
                errors.append(f"record locator work shard is missing: {row.get('path')}")
            elif path.stat().st_size != int(row.get("compressed_bytes", -1)):
                errors.append(f"record locator work shard byte mismatch: {row.get('path')}")
            elif file_sha256(path) != row.get("sha256"):
                errors.append(f"record locator work shard hash mismatch: {row.get('path')}")

    route_aliases = locator.get("route_aliases", {})
    if not isinstance(route_aliases, dict):
        errors.append("record locator route aliases are not a mapping")
        route_aliases = {}
    collision_rows = locator.get("route_collisions", [])
    declared_aliases = {
        alias
        for collision in collision_rows
        if isinstance(collision, dict)
        for alias in collision.get("aliases", [])
    }
    if declared_aliases != set(route_aliases):
        errors.append("record locator collision ledger and route aliases differ")
    if int(locator.get("collision_routes", -1)) != len(collision_rows):
        errors.append("record locator collision-route count is inconsistent")
    located = 0
    for bucket, row in locator.get("buckets", {}).items():
        path = PACK / str(row.get("path", ""))
        if not path.is_file():
            errors.append(f"record locator bucket is missing: {row.get('path')}")
            continue
        if path.stat().st_size != int(row.get("compressed_bytes", -1)):
            errors.append(f"record locator bucket byte mismatch: {row.get('path')}")
            continue
        if file_sha256(path) != row.get("sha256"):
            errors.append(f"record locator bucket hash mismatch: {row.get('path')}")
            continue
        payload = load(path)
        if len(payload) != int(row.get("records", -1)):
            errors.append(f"record locator bucket count mismatch: {bucket}")
        for route, location in payload.items():
            located += 1
            if route_bucket(route) != bucket:
                errors.append(f"record locator route is in the wrong bucket: {route}")
                continue
            if (
                not isinstance(location, list)
                or len(location) != 2
                or any(not isinstance(value, int) for value in location)
            ):
                errors.append(f"record locator location is invalid: {route}")
                continue
            ordinal = location[0] * chunk_size + location[1]
            expected_record_route = str(route_aliases.get(route, route))
            if (
                ordinal >= len(routes)
                or routes[ordinal] != expected_record_route
            ):
                errors.append(f"record locator points to the wrong work: {route}")
    if located != len(routes):
        errors.append(f"record locator contains {located} routes, expected {len(routes)}")

    composition = load(PACK / entrypoints["relationship_composition"])
    total = int(composition.get("total", -1))
    if composition.get("schema") != "okf-relationship-composition.v1":
        errors.append("relationship composition schema is invalid")
    if composition.get("snapshot") != snapshot:
        errors.append("relationship composition snapshot differs from the descriptor")
    for dimension in (
        "by_datapack",
        "by_predicate",
        "by_authority",
        "by_confidence",
        "by_freshness",
    ):
        if sum(int(value) for value in composition.get(dimension, {}).values()) != total:
            errors.append(f"relationship composition does not reconcile {dimension}")
    if sum(
        int(row.get("count", 0))
        for row in composition.get("breakdown", [])
    ) != total:
        errors.append("relationship composition breakdown does not reconcile")
    expected_total = int(
        descriptor.get("counts", {}).get(
            "relationships_with_external_datapacks",
            -1,
        )
    )
    if total != expected_total:
        errors.append(
            f"relationship composition total {total} differs from {expected_total}"
        )
    if int(composition.get("by_datapack", {}).get("core", -1)) != int(
        manifest.get("counts", {}).get("relationships", -1)
    ):
        errors.append("relationship composition core total differs from core chunks")
    by_datapack = composition.get("by_datapack", {})
    if "codex-assisted-v2" in by_datapack:
        errors.append(
            "relationship composition must exclude historical "
            "codex-assisted-v2 assertions"
        )
    for directory, datapack in ACTIVE_RELATIONSHIP_PROVIDER_MANIFESTS:
        provider_path = PACK / "data" / directory / "manifest.json"
        if not provider_path.is_file():
            continue
        provider_count = int(
            load(provider_path).get("counts", {}).get("assertions", -1)
        )
        if int(
            by_datapack.get(datapack, -1)
        ) != provider_count:
            errors.append(
                f"relationship composition {datapack} total differs from provider"
            )

    presentation = load(PACK / entrypoints["presentation"])
    if presentation.get("schema") != "okf-explorer-presentation.v1":
        errors.append("Explorer presentation contract is invalid")
    presented_facets = {
        str(row.get("key"))
        for row in presentation.get("facets", [])
    }
    if not {"category", "jurisdiction", "creation_year", "document_type"}.issubset(
        presented_facets
    ):
        errors.append("Explorer presentation omits essential legislation facets")

    performance = load(PACK / entrypoints["performance"])
    startup = performance.get("startup", {})
    if int(startup.get("control_plane_bytes", 2**63)) > int(
        startup.get("target_bytes", 0)
    ):
        errors.append("Explorer startup control plane exceeds its declared target")
    if performance.get("full_hydration", {}).get("browser_supported") is not False:
        errors.append("performance contract permits unsafe full-corpus hydration")
    for key, value in performance.get("search_plane", {}).items():
        if key.startswith("maximum_") and key.endswith("_bytes") and int(value) >= 64_000_000:
            errors.append(f"browser search shard exceeds 64 MB: {key}={value}")


def check_effects_evidence(errors: list[str]) -> None:
    provider_path = PACK / "data" / "effects" / "manifest.json"
    if not provider_path.is_file():
        errors.append("official effects provider manifest is missing")
        return
    provider = load(provider_path)
    snapshot_id = provider.get("snapshot_id")
    if not isinstance(snapshot_id, str):
        errors.append("official effects snapshot ID is missing")
        return
    try:
        validation, _, projection = effects_evidence.validate_archive(
            snapshot_id
        )
    except (FileNotFoundError, KeyError, OSError, ValueError) as error:
        errors.append(f"official effects evidence is invalid: {error}")
        return
    acquisition = provider.get("acquisition", {})
    archive_path, receipt_path, projection_path = (
        effects_evidence.archive_paths(snapshot_id)
    )
    expected_routes = {
        "evidence_archive": archive_path.relative_to(ROOT).as_posix(),
        "evidence_archive_receipt": receipt_path.relative_to(ROOT).as_posix(),
        "evidence_publication_projection": (
            projection_path.relative_to(ROOT).as_posix()
        ),
    }
    for key, expected in expected_routes.items():
        if acquisition.get(key) != expected:
            errors.append(
                f"official effects acquisition {key} does not bind sealed evidence"
            )
    if "evidence_root" in acquisition:
        errors.append(
            "official effects acquisition still publishes a loose evidence root"
        )
    if validation["capture_count"] != projection.get("capture_count"):
        errors.append("official effects evidence capture counts do not reconcile")

    archive_members = {
        row.get("body", {}).get("archive_member")
        for row in projection.get("captures", [])
    }
    archive_route = expected_routes["evidence_archive"]
    assertions_path = PACK / "data" / "effects" / "assertions.json.gz"
    if not assertions_path.is_file():
        errors.append("official effects assertions chunk is missing")
        return
    assertions = load(assertions_path)
    expected_assertions = provider.get("counts", {}).get("assertions")
    if len(assertions) != expected_assertions:
        errors.append("official effects assertion count differs from manifest")
    for row in assertions:
        evidence_rows = row.get("evidence", [])
        if not evidence_rows:
            errors.append("official effects assertion has no evidence")
            break
        for evidence in evidence_rows:
            if evidence.get("capture") != archive_route:
                errors.append(
                    "official effects assertion references loose capture evidence"
                )
                return
            if evidence.get("capture_member") not in archive_members:
                errors.append(
                    "official effects assertion references an unknown archive member"
                )
                return


def main() -> int:
    errors: list[str] = []
    descriptor_path = PACK / "okf-explorer.json"
    manifest_path = PACK / "data" / "manifest.json"
    if not descriptor_path.is_file() or not manifest_path.is_file():
        print("Legislation OKF check failed: generated pack is missing")
        return 1
    descriptor = load(descriptor_path)
    manifest = load(manifest_path)
    counts = manifest.get("counts", {})
    if descriptor.get("okf_version") != "0.2":
        errors.append("Explorer descriptor does not declare okf_version 0.2")
    if manifest.get("okf_version") != "0.2":
        errors.append("data manifest does not declare okf_version 0.2")
    for semantic_name in ("okf-bundle.yamlld", "okf-bundle.jsonld"):
        semantic_path = PACK / semantic_name
        if semantic_path.is_file() and load(semantic_path).get("okf_version") != "0.2":
            errors.append(f"{semantic_name} does not declare okf_version 0.2")
    if descriptor.get("kind") != "okf-large-corpus":
        errors.append("descriptor kind is not okf-large-corpus")
    if counts.get("works", 0) < MINIMUM_COMPLETE_WORKS:
        errors.append(f"work count {counts.get('works', 0):,} is below completeness floor {MINIMUM_COMPLETE_WORKS:,}")
    extension = descriptor.get("extensions", {}).get("okf-legislation-corpus.v1", {})
    if extension.get("mode") != "complete-work-index-live-subdivision-resolver":
        errors.append("legislation progressive-discovery extension is absent")
    for required in (
        "okf-bundle.yamlld",
        "okf-bundle.jsonld",
        "enrichment/model-assisted-v1.json",
        "enrichment/model-assisted-v1-independent-audit.json",
        "enrichment/model-assisted-v1-independent-audit.md",
    ):
        if not (PACK / required).is_file():
            errors.append(f"semantic publication artifact missing: {required}")
    v1_rule_path = PACK / "enrichment" / "model-assisted-v1.json"
    v1_audit_path = (
        PACK / "enrichment" / "model-assisted-v1-independent-audit.json"
    )
    v1_rejected = False
    if v1_rule_path.is_file() and v1_audit_path.is_file():
        v1_audit = load(v1_audit_path)
        v1_rule_sha256 = hashlib.sha256(v1_rule_path.read_bytes()).hexdigest()
        if v1_audit.get("subject", {}).get("sha256") != v1_rule_sha256:
            errors.append("legacy v1 independent audit is not bound to the rule artifact")
        v1_rejected = (
            v1_audit.get("decision", {}).get("verdict")
            == "rejected-fail-closed"
        )
        if not v1_rejected:
            errors.append("legacy v1 independent audit is not fail-closed")
        if (
            v1_audit.get("affected_outputs", {}).get(
                "governed_v1_assertions_permitted"
            )
            != 0
        ):
            errors.append("legacy v1 audit permits governed assertions")
    for name in ("data_manifest", "overview_index", "analysis_overview", "search_manifest", "markdown_index", "ontology", "evaluation"):
        target = descriptor.get("entrypoints", {}).get(name)
        if not target:
            errors.append(f"descriptor entrypoint {name} is missing")
            continue
        resolved = (PACK / target).resolve()
        if not resolved.is_file():
            errors.append(f"descriptor entrypoint {name} does not resolve: {target}")

    work_files = manifest.get("chunks", {}).get("datasets", [])
    works = 0
    type_codes: set[str] = set()
    ids: set[str] = set()
    routes: list[str] = []
    for relative in work_files:
        path = PACK / relative
        if not path.is_file():
            errors.append(f"missing work chunk: {relative}")
            continue
        for record in load(path):
            works += 1
            record_id = record.get("id")
            if record_id in ids:
                errors.append(f"duplicate work ID: {record_id}")
            ids.add(record_id)
            routes.append(str(record.get("route", "")))
            type_codes.add(record.get("type_code", ""))
            if not str(record_id).startswith("https://www.legislation.gov.uk/id/"):
                errors.append(f"non-official work ID: {record_id}")
            if not str(record.get("structure_url", "")).startswith("https://www.legislation.gov.uk/"):
                errors.append(f"missing official CLML structure URL: {record_id}")
            if record.get("record_type") != "Legislation Work":
                errors.append(f"wrong normalized record type: {record_id}")
            if v1_rejected:
                enrichment = record.get("semantic_enrichment", {})
                if enrichment.get("model_rules_applied") is not False:
                    errors.append(
                        f"rejected v1 rules are not fail-closed on work: {record_id}"
                    )
                if enrichment.get("model_assisted_topics"):
                    errors.append(
                        f"rejected v1 topic remains on work: {record_id}"
                    )
                if record.get("semantic_entities"):
                    errors.append(
                        f"rejected v1 entity remains on work: {record_id}"
                    )
            if len(errors) > 100:
                break
        if len(errors) > 100:
            break
    if works != counts.get("works"):
        errors.append(f"manifest says {counts.get('works')} works but chunks contain {works}")
    missing_types = sorted(REQUIRED_TYPE_CODES - type_codes)
    if missing_types:
        errors.append(f"required primary/secondary/devolved/EU type codes absent: {', '.join(missing_types)}")

    relationship_rows = 0
    relationship_kinds: set[str] = set()
    for relative in manifest.get("chunks", {}).get("relationships", []):
        path = PACK / relative
        if not path.is_file():
            errors.append(f"missing relationship chunk: {relative}")
            continue
        for row in load(path):
            relationship_rows += 1
            relationship_kinds.add(str(row.get("kind", "")))
            if not row.get("source") or not row.get("target") or not row.get("evidence_type") or not row.get("confidence"):
                errors.append(f"relationship lacks route/provenance fields: {row}")
                break
    if relationship_rows != counts.get("relationships"):
        errors.append(f"manifest says {counts.get('relationships')} relationships but chunks contain {relationship_rows}")
    for required_kind in ("classified as", "has document type"):
        if required_kind not in relationship_kinds:
            errors.append(f"required semantic relationship kind absent: {required_kind}")
    if v1_rejected and "mentions entity" in relationship_kinds:
        errors.append("core graph contains rejected legacy v1 entity assertions")
    if v1_rejected:
        historical_extension = descriptor.get("extensions", {}).get(
            "okf-model-enrichment.v1-historical",
            {},
        )
        if historical_extension.get("applied") is not False:
            errors.append("legacy v1 descriptor extension does not declare applied=false")
        if historical_extension.get("governed_assertions") != 0:
            errors.append("legacy v1 descriptor extension has governed assertions")
    adjacency_path = manifest.get("indexes", {}).get("relationship_adjacency", "")
    if not adjacency_path or not (PACK / adjacency_path).is_file():
        errors.append("route-scoped relationship adjacency manifest is missing")
    else:
        adjacency = load(PACK / adjacency_path)
        if adjacency.get("algorithm") != "fnv1a32-prefix-2" or adjacency.get("relationships") != relationship_rows:
            errors.append("relationship adjacency contract/count does not match relationship chunks")
        for relative in adjacency.get("buckets", {}).values():
            if not (PACK / relative).is_file():
                errors.append(f"missing adjacency bucket: {relative}")

    search_manifest = load(PACK / manifest["indexes"]["search"])
    if search_manifest.get("counts", {}).get("documents") != counts.get("works"):
        errors.append("static search document count does not equal work count")
    facets = load(PACK / manifest["indexes"]["facets"])
    for key in ("category", "type_code", "document_type", "creation_year", "jurisdiction", "topic", "format"):
        if not facets.get(key):
            errors.append(f"required progressive-discovery facet is empty: {key}")
    check_discovery_publication(errors, descriptor, manifest, routes)
    check_effects_evidence(errors)
    for required in ("ontology/index.md", "access/index.md", "methodology/index.md", "topics/index.md", "types/index.md"):
        if not (PACK / required).is_file():
            errors.append(f"required Markdown concept index missing: {required}")
    oversized = [path.relative_to(ROOT).as_posix() for path in PACK.rglob("*") if path.is_file() and path.stat().st_size >= 100_000_000]
    if oversized:
        errors.append(f"GitHub-incompatible files >=100MB: {', '.join(oversized)}")
    concept_count = check_markdown(errors, descriptor.get("generated_at", ""))

    if errors:
        print("Legislation OKF check failed:")
        for error in errors[:100]:
            print(f"- {error}")
        return 1
    print(f"Legislation OKF check passed: {works:,} unique works, {relationship_rows:,} relationships, {len(type_codes)} type codes, {len(work_files)} work chunks, {concept_count} OKF v0.2 concepts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
