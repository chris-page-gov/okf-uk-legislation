#!/usr/bin/env python3
"""Rebuild the browser-safe legislation discovery plane from published shards.

This deliberately leaves work, relationship, official-effects and enrichment
datapacks untouched.  It replaces only generated search/facet/locator files
and synchronizes their descriptor, overview, analysis and performance
contracts.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

import build_legislation_okf as builder

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "bundle"
DATA = PACK / "data"
IMMUTABLE_INPUTS = (
    ROOT / "research",
    ROOT / "evidence",
    DATA / "effects",
    DATA / "enrichment",
)
DISCOVERY_RECORD_FIELDS = {
    "access_model",
    "category",
    "confidence",
    "contract_status",
    "creation_date",
    "documentation",
    "document_type",
    "document_uri",
    "effects_made_url",
    "effects_received_url",
    "eli_class",
    "formats",
    "host",
    "id",
    "jurisdiction",
    "legal_status",
    "legislation_id_uri",
    "license_basis",
    "license_confidence",
    "license_id",
    "license_source_id",
    "license_source_title",
    "license_title",
    "metadata_modified",
    "name",
    "notes",
    "number",
    "protocol",
    "published_at",
    "publisher",
    "publisher_title",
    "quality",
    "quality_score",
    "record_type",
    "resource_count",
    "route",
    "schema_org_type",
    "source_adapter",
    "source_tier",
    "structure_url",
    "table_of_contents_url",
    "tags",
    "timestamp",
    "title",
    "topics",
    "type_code",
    "updated_at",
    "url",
    "year",
}


def load_json(path: Path) -> Any:
    if path.suffix == ".gz":
        return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = builder.large_corpus.render_json(value)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(body, encoding="utf-8")
    temporary.replace(path)


def write_files(root: Path, files: dict[Path, str | bytes]) -> None:
    for relative, body in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            path.write_bytes(body)
        else:
            path.write_text(body, encoding="utf-8")


def body_bytes(body: str | bytes) -> bytes:
    return body if isinstance(body, bytes) else body.encode("utf-8")


def check_generated_files(files: dict[Path, str | bytes]) -> list[str]:
    """Compare every discovery output without writing into the publication."""

    expected = set(files)
    actual = {
        path.relative_to(PACK)
        for root in (DATA / "search", DATA / "records")
        if root.is_dir()
        for path in root.rglob("*")
        if path.is_file()
    }
    errors: list[str] = []
    for relative in sorted(expected | actual):
        path = PACK / relative
        if relative not in expected:
            errors.append(f"unexpected: {relative}")
        elif not path.is_file():
            errors.append(f"missing: {relative}")
        elif path.read_bytes() != body_bytes(files[relative]):
            errors.append(f"out of date: {relative}")
    return errors


def replace_generated_tree(staged: Path, target: Path) -> None:
    """Replace one allowlisted generated tree without touching source datapacks."""

    if target not in {DATA / "search", DATA / "records"}:
        raise ValueError(f"refusing to replace non-discovery path: {target}")
    backup = DATA / f".{target.name}.previous-{os.getpid()}"
    if backup.exists():
        shutil.rmtree(backup)
    if target.exists():
        target.replace(backup)
    try:
        staged.replace(target)
    except Exception:
        if backup.exists() and not target.exists():
            backup.replace(target)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def tree_digest(paths: tuple[Path, ...]) -> str:
    """Digest immutable inputs by path and bytes, independent of mtimes."""

    digest = hashlib.sha256()
    for root in paths:
        if not root.exists():
            digest.update(f"missing:{root.relative_to(ROOT)}\n".encode("utf-8"))
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(ROOT).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            digest.update(b"\0")
    return digest.hexdigest()


def load_records(
    manifest: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[tuple[Path, int]],
    list[dict[str, Any]],
]:
    records: list[dict[str, Any]] = []
    chunks: list[tuple[Path, int]] = []
    chunk_metadata: list[dict[str, Any]] = []
    for relative in manifest["chunks"]["datasets"]:
        path = PACK / relative
        body = path.read_bytes()
        rows = json.loads(gzip.decompress(body).decode("utf-8"))
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"work chunk must be a non-empty list: {relative}")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"work chunk contains a non-object: {relative}")
            records.append(
                {
                    key: value
                    for key, value in row.items()
                    if key in DISCOVERY_RECORD_FIELDS
                }
            )
        chunks.append((Path(relative), len(rows)))
        chunk_metadata.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(body).hexdigest(),
                "compressed_bytes": len(body),
                "records": len(rows),
                "compression": "gzip",
            }
        )
    return records, chunks, chunk_metadata


def resolved_bundle_path(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"unsafe bundle-relative path: {relative}")
    resolved = (PACK / candidate).resolve()
    if not resolved.is_relative_to(PACK.resolve()):
        raise ValueError(f"path escapes the bundle: {relative}")
    return resolved


def relationship_dimensions(
    manifest: dict[str, Any],
) -> tuple[int, int, list[dict[str, Any]], str]:
    """Stream every materialized relationship and produce exact dimensions."""

    counts: Counter[tuple[str, str, str, str, str]] = Counter()

    def consume(rows: Any, datapack: str) -> int:
        if not isinstance(rows, list):
            raise ValueError(f"{datapack} relationship chunk is not a list")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"{datapack} relationship row is not an object")
            predicate = str(
                row.get("predicate") or row.get("kind") or "relationship"
            )
            counts[
                (
                    datapack,
                    predicate,
                    builder.normalized_relationship_authority(row),
                    builder.normalized_relationship_confidence(row),
                    builder.normalized_relationship_freshness(row),
                )
            ] += 1
        return len(rows)

    core_total = 0
    for relative in manifest["chunks"]["relationships"]:
        core_total += consume(load_json(resolved_bundle_path(relative)), "core")
    expected_core = int(manifest["counts"]["relationships"])
    if core_total != expected_core:
        raise ValueError(
            f"core relationship count mismatch: {core_total} != {expected_core}"
        )

    generated_at = str(manifest["generated_at"])
    provider_total = 0
    for directory, datapack, count_key in (
        ("effects", "legislation-effects", "assertions"),
        ("enrichment", "codex-assisted-v2", "assertions"),
    ):
        provider_manifest_path = DATA / directory / "manifest.json"
        if not provider_manifest_path.is_file():
            continue
        provider = load_json(provider_manifest_path)
        generated_at = max(generated_at, str(provider.get("generated_at", "")))
        observed = 0
        for chunk in provider.get("chunks", []):
            relative = str(chunk["path"])
            path = resolved_bundle_path(relative)
            body = path.read_bytes()
            expected_hash = str(chunk.get("sha256", ""))
            if hashlib.sha256(body).hexdigest() != expected_hash:
                raise ValueError(f"provider chunk hash mismatch: {relative}")
            expected_bytes = chunk.get(
                "compressed_bytes",
                chunk.get("bytes"),
            )
            if expected_bytes is not None and len(body) != int(expected_bytes):
                raise ValueError(f"provider chunk byte count mismatch: {relative}")
            rows = json.loads(gzip.decompress(body).decode("utf-8"))
            chunk_count = consume(rows, datapack)
            if chunk_count != int(chunk["records"]):
                raise ValueError(f"provider chunk record mismatch: {relative}")
            observed += chunk_count
        expected = int(provider.get("counts", {}).get(count_key, 0))
        if observed != expected:
            raise ValueError(
                f"{datapack} relationship count mismatch: {observed} != {expected}"
            )
        provider_total += observed

    rows = [
        {
            "datapack": datapack,
            "predicate": predicate,
            "authority": authority,
            "confidence": confidence,
            "freshness": freshness,
            "count": count,
        }
        for (
            datapack,
            predicate,
            authority,
            confidence,
            freshness,
        ), count in sorted(counts.items())
    ]
    return core_total, core_total + provider_total, rows, generated_at


def gzip_measure(paths: list[Path]) -> dict[str, int]:
    compressed = 0
    decoded = 0
    for path in paths:
        body = path.read_bytes()
        compressed += len(body)
        decoded += len(gzip.decompress(body)) if path.suffix == ".gz" else len(body)
    return {
        "files": len(paths),
        "compressed_bytes": compressed,
        "decoded_json_bytes": decoded,
    }


def performance_report(
    descriptor: dict[str, Any],
    locator: dict[str, Any],
) -> dict[str, Any]:
    work_paths = sorted(DATA.glob("works-*.json.gz"))
    relationship_paths = sorted(DATA.glob("relationships-*.json.gz"))
    result_paths = sorted((DATA / "search").glob("results-*.json.gz"))
    search_paths = sorted(
        path
        for path in (DATA / "search").rglob("*")
        if path.is_file()
    )
    postings_paths = sorted((DATA / "search" / "postings").glob("*.json.gz"))
    filter_paths = sorted((DATA / "search" / "filters").glob("*.json.gz"))
    lexicon_paths = sorted((DATA / "search" / "lexicon").glob("*.json.gz"))
    control_paths = [
        PACK / "okf-explorer.json",
        DATA / "manifest.json",
        DATA / "overview.json",
        DATA / "analysis" / "overview.json",
        DATA / "facets.json",
        DATA / "presentation.json",
        DATA / "search" / "manifest.json",
        DATA / "records" / "manifest.json",
    ]
    bucket_sizes = [
        int(row["compressed_bytes"])
        for row in locator["manifest"]["buckets"].values()
    ]
    planes = {
        "work_records": gzip_measure(work_paths),
        "core_relationships": gzip_measure(relationship_paths),
        "search_result_projection": gzip_measure(result_paths),
    }
    return {
        "schema": "okf-large-corpus-performance.v1",
        "snapshot": descriptor["snapshot"],
        "generated_at": descriptor["generated_at"],
        "records": descriptor["counts"]["records"],
        "startup": {
            "mode": "overview-first",
            "control_plane_bytes": sum(
                path.stat().st_size for path in control_paths if path.is_file()
            ),
            "target_bytes": 1_048_576,
        },
        "planes": planes,
        "search_plane": {
            "files": len(search_paths),
            "published_bytes": sum(path.stat().st_size for path in search_paths),
            "schema": "okf-static-search.v2",
            "exact_filter_postings": len(builder.SEARCH_FILTER_FIELDS),
            "maximum_postings_shard_bytes": max(
                (path.stat().st_size for path in postings_paths),
                default=0,
            ),
            "maximum_filter_shard_bytes": max(
                (path.stat().st_size for path in filter_paths),
                default=0,
            ),
            "maximum_lexicon_shard_bytes": max(
                (path.stat().st_size for path in lexicon_paths),
                default=0,
            ),
            "maximum_result_projection_shard_bytes": max(
                (path.stat().st_size for path in result_paths),
                default=0,
            ),
            "maximum_result_shards_per_query": 16,
        },
        "targeted_record_hydration": {
            "schema": "okf-record-locator-sharded.v1",
            "buckets": len(bucket_sizes),
            "median_locator_bucket_bytes": int(median(bucket_sizes)),
            "maximum_locator_bucket_bytes": max(bucket_sizes),
            "record_chunk_count": len(work_paths),
            "maximum_record_chunk_bytes": max(
                path.stat().st_size for path in work_paths
            ),
        },
        "full_hydration": {
            "browser_supported": False,
            "decoded_json_bytes_before_object_overhead": sum(
                row["decoded_json_bytes"] for row in planes.values()
            ),
            "reason": (
                "Decoding every work, relationship and search projection at once "
                "exceeds the 256 MiB browser-memory acceptance target before "
                "JavaScript object overhead."
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify every generated discovery byte without modifying bundle/.",
    )
    args = parser.parse_args(argv)
    immutable_before = tree_digest(IMMUTABLE_INPUTS)
    descriptor = load_json(PACK / "okf-explorer.json")
    manifest = load_json(DATA / "manifest.json")
    records, record_chunks, record_chunk_metadata = load_records(manifest)
    if len(records) != int(manifest["counts"]["works"]):
        raise SystemExit("Published work shards do not match the manifest count")

    generated_at = str(descriptor["generated_at"])
    snapshot = str(
        descriptor.get("snapshot")
        or f"legislation-work-index-{generated_at}"
    )
    facets = builder.build_facets(records)
    discovery_records, route_aliases, route_collisions = (
        builder.disambiguate_discovery_routes(records)
    )
    search = builder.build_legislation_search(discovery_records, snapshot)
    locator = builder.build_record_locator(
        discovery_records,
        record_chunks,
        snapshot,
    )
    locator["manifest"].update(
        {
            "route_aliases": route_aliases,
            "route_collisions": route_collisions,
            "collision_routes": len(route_collisions),
        }
    )
    locator["manifest"]["record_chunks"] = record_chunk_metadata
    presentation = builder.explorer_presentation(snapshot)
    (
        core_relationships,
        combined_relationships,
        relationship_rows,
        composition_generated_at,
    ) = relationship_dimensions(manifest)
    relationship_composition = builder.relationship_composition_document(
        relationship_rows,
        snapshot,
        composition_generated_at,
    )
    analysis = builder.analysis_for(
        records,
        facets,
        generated_at,
        core_relationship_count=core_relationships,
        combined_relationship_count=combined_relationships,
        relationship_rows=relationship_rows,
        snapshot=snapshot,
    )

    search_files = builder.search_publication_files(search, snapshot)
    locator_files = builder.record_locator_publication_files(locator)
    generated_files: dict[Path, str | bytes] = {
        **search_files,
        **locator_files,
    }

    def publish_json(relative: str | Path, value: Any) -> None:
        relative_path = Path(relative)
        generated_files[relative_path] = builder.large_corpus.render_json(value)
        if not args.check:
            write_json(PACK / relative_path, value)

    if not args.check:
        with tempfile.TemporaryDirectory(
            prefix=".discovery-staging-",
            dir=DATA,
        ) as temporary:
            staging = Path(temporary)
            write_files(staging, search_files)
            write_files(staging, locator_files)
            replace_generated_tree(staging / "data" / "search", DATA / "search")
            replace_generated_tree(staging / "data" / "records", DATA / "records")
    publish_json("data/facets.json", facets)
    publish_json("data/presentation.json", presentation)
    publish_json("data/analysis/overview.json", analysis)
    publish_json("data/relationship-composition.json", relationship_composition)

    manifest["snapshot"] = snapshot
    manifest["indexes"].update(
        {
            "facets": "data/facets.json",
            "presentation": "data/presentation.json",
            "record_locator": "data/records/manifest.json",
            "search": "data/search/manifest.json",
            "performance": "data/performance.json",
            "relationship_composition": "data/relationship-composition.json",
        }
    )
    manifest["performance"].update(
        {
            "startup_mode": "overview-first",
            "full_record_hydration": "single-shard-by-route-or-search-ordinal",
            "full_corpus_hydration": "disabled-in-browser",
            "facet_hydration": "exact-v2-filter-postings",
            "search": (
                "bounded gzip static worker shards plus official remote "
                "full-text Atom search"
            ),
        }
    )
    manifest["search"] = {
        "schema": search["manifest"]["schema"],
        "documents": len(records),
        "tokens": search["manifest"]["counts"]["tokens"],
        "result_limit": search["manifest"]["result_limit"],
        "filter_postings": len(search["manifest"]["entrypoints"]["filter_postings"]),
    }
    manifest["counts"].update(
        {
            "core_relationships": core_relationships,
            "relationships_with_external_datapacks": combined_relationships,
            "external_datapack_relationships": (
                combined_relationships - core_relationships
            ),
        }
    )
    publish_json("data/manifest.json", manifest)

    overview = load_json(DATA / "overview.json")
    recent_ordinals = sorted(
        range(len(records)),
        key=lambda ordinal: str(records[ordinal].get("creation_date", "")),
        reverse=True,
    )[:12]
    overview.update(
        {
            "snapshot": snapshot,
            "counts": {
                **overview.get("counts", {}),
                **descriptor["counts"],
                "core_relationships": core_relationships,
                "relationships": combined_relationships,
                "external_datapack_relationships": (
                    combined_relationships - core_relationships
                ),
            },
            "recent_datasets": [
                builder.search_result_document(
                    discovery_records[ordinal],
                    ordinal,
                )
                for ordinal in recent_ordinals
            ],
            "facet_previews": {
                key: rows[:18] for key, rows in facets.items()
            },
        }
    )
    publish_json("data/overview.json", overview)

    descriptor["snapshot"] = snapshot
    descriptor["entrypoints"].update(
        {
            "presentation": "data/presentation.json",
            "record_locator": "data/records/manifest.json",
            "performance": "data/performance.json",
            "publication_contract": "docs/uk-legislation-okf.md",
            "relationship_composition": "data/relationship-composition.json",
            "search_manifest": "data/search/manifest.json",
        }
    )
    descriptor["performance"] = manifest["performance"]
    descriptor["counts"].update(
        {
            "core_relationships": core_relationships,
            "relationships": combined_relationships,
            "relationships_with_external_datapacks": combined_relationships,
            "external_datapack_relationships": (
                combined_relationships - core_relationships
            ),
        }
    )
    descriptor.setdefault("extensions", {})[
        "okf-large-corpus-publication.v2"
    ] = {
        "search": "okf-static-search.v2",
        "facets": "exact-filter-postings",
        "records": "fnv1a32-route-locator",
        "route_aliases": "declared-only-for-colliding-legacy-routes",
        "compression": "pre-compressed-gzip",
        "full_corpus_browser_hydration": False,
    }
    descriptor["discovery"] = {
        "repository": "https://github.com/chris-page-gov/okf-uk-legislation",
        "documentation": (
            "https://chris-page-gov.github.io/okf-uk-legislation/docs/"
        ),
        "raw_subpath": "bundle",
        "release_archive": (
            "https://github.com/chris-page-gov/okf-uk-legislation/releases"
        ),
        "semantic_descriptor": (
            "https://chris-page-gov.github.io/okf-uk-legislation/"
            "okf-bundle.yamlld"
        ),
        "routes": [
            {
                "kind": "published",
                "purpose": "descriptor",
                "priority": 10,
                "url": (
                    "https://chris-page-gov.github.io/okf-uk-legislation/"
                    "okf-explorer.json"
                ),
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
    }
    publish_json("okf-explorer.json", descriptor)

    performance = performance_report(descriptor, locator)
    publish_json("data/performance.json", performance)
    immutable_after = tree_digest(IMMUTABLE_INPUTS)
    if immutable_after != immutable_before:
        raise SystemExit(
            "Immutable research, evidence, effects or enrichment input changed "
            "during the discovery rebuild"
        )
    if args.check:
        errors = check_generated_files(generated_files)
        if errors:
            print("Legislation discovery publication is not synchronized:")
            for error in errors[:100]:
                print(f"- {error}")
            return 1
        action = "Verified"
    else:
        action = "Rebuilt"
    print(
        f"{action} browser-safe discovery for "
        f"{len(records):,} works: "
        f"{search['manifest']['counts']['tokens']:,} search tokens, "
        f"{len(builder.SEARCH_FILTER_FIELDS)} exact facets, "
        f"{len(locator['manifest']['buckets'])} locator buckets, "
        f"{combined_relationships:,} exact relationship rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
