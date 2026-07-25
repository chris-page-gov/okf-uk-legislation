#!/usr/bin/env python3
"""Validate the checked-in complete legislation OKF publication pack."""

from __future__ import annotations

import json
import gzip
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "bundle"
MINIMUM_COMPLETE_WORKS = 300_000
REQUIRED_TYPE_CODES = {"ukpga", "uksi", "asp", "ssi", "anaw", "asc", "wsi", "nia", "nisr", "eur"}
VALID_STATUS = {"draft", "stable", "deprecated"}


def load(path: Path):
    if path.suffix == ".gz":
        return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


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
    for path in sorted(PACK.rglob("*.md")):
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
    for required in ("okf-bundle.yamlld", "okf-bundle.jsonld", "enrichment/model-assisted-v1.json"):
        if not (PACK / required).is_file():
            errors.append(f"semantic publication artifact missing: {required}")
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
            type_codes.add(record.get("type_code", ""))
            if not str(record_id).startswith("https://www.legislation.gov.uk/id/"):
                errors.append(f"non-official work ID: {record_id}")
            if not str(record.get("structure_url", "")).startswith("https://www.legislation.gov.uk/"):
                errors.append(f"missing official CLML structure URL: {record_id}")
            if record.get("record_type") != "Legislation Work":
                errors.append(f"wrong normalized record type: {record_id}")
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
    for required_kind in ("classified as", "has document type", "mentions entity"):
        if required_kind not in relationship_kinds:
            errors.append(f"required semantic relationship kind absent: {required_kind}")
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
