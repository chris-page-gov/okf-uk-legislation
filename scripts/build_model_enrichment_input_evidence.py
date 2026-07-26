#!/usr/bin/env python3
"""Build credential-free evidence for the future paid enrichment input.

This builder deliberately has no network, credential, model-client or process
surface.  It reads the already published work chunks and the historical
calibration source, then produces:

* a fixed calibration projection with content-derived case identifiers;
* a complete, chunk-reconciling field/eligibility receipt; and
* a human-readable projection of that receipt.

The receipt is preflight evidence only.  It never authorizes a paid model call
and it distinguishes source-advertised CLML manifestations from derived
structure routes.  Neither is treated as a frozen or successfully retrieved
CLML body.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import urlsplit
from typing import Any, Iterable, Iterator
import zlib


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"
DATA_MANIFEST_PATH = BUNDLE / "data" / "manifest.json"
RECORD_MANIFEST_PATH = BUNDLE / "data" / "records" / "manifest.json"
DESCRIPTOR_PATH = BUNDLE / "okf-explorer.json"
HISTORICAL_CALIBRATION_PATH = (
    ROOT / "enrichment" / "codex-assisted-v2-calibration.json"
)
CALIBRATION_MANIFEST_PATH = (
    ROOT / "enrichment" / "model-assisted-calibration-manifest-v1.json"
)
RECEIPT_PATH = (
    ROOT
    / "whole-law"
    / "assurance"
    / "model-assisted-input-eligibility-20260726.json"
)
REPORT_PATH = RECEIPT_PATH.with_suffix(".md")
BUILDER_PATH = Path(__file__).resolve()

EXPECTED_SNAPSHOT = "legislation-work-index-2026-07-11T18:00:00Z"
EXPECTED_WORKS = 365_786
EXPECTED_CHUNKS = 366
EXPECTED_SOURCE_ADVERTISED_CLML_ROUTES = 137_119
EXPECTED_DERIVED_STRUCTURE_ROUTES = 228_667
EXPECTED_GENERATED_NOTES_BOILERPLATE = 35_156
EXPECTED_NON_BOILERPLATE_NONEMPTY_NOTES = 85_640
EXPECTED_SUBSTANTIVE_SOURCE_NOTES = 85_638
EXPECTED_HISTORICAL_CALIBRATION_SHA256 = (
    "f31f3204926927ea49eb839e629987b4a3f5e98e72f85e9a7f0981d794028fb3"
)
OBSERVED_DATE = "2026-07-26"
IO_BLOCK_BYTES = 64 * 1024
MAX_JSON_FILE_BYTES = 8 * 1024 * 1024
MAX_AUXILIARY_FILE_BYTES = 64 * 1024 * 1024
MAX_WORK_CHUNK_COMPRESSED_BYTES = 4 * 1024 * 1024
MAX_WORK_CHUNK_DECOMPRESSED_BYTES = 16 * 1024 * 1024
MAX_WORK_CHUNK_RECORDS = 1_000

SOURCE_METADATA_FIELDS = (
    "area_served",
    "category",
    "creation_date",
    "document_type",
    "jurisdiction",
    "legal_status",
    "lifecycle_status",
    "metadata_modified",
    "number",
    "publisher",
    "publisher_title",
    "source_adapter",
    "source_tier",
    "tags",
    "type_code",
    "year",
)
REQUIRED_CORE_SOURCE_METADATA_FIELDS = (
    "category",
    "document_type",
    "jurisdiction",
    "metadata_modified",
    "publisher",
    "source_adapter",
    "source_tier",
    "tags",
    "type_code",
    "year",
)

TITLE_KINDS = (
    "substantive",
    "uri-fallback",
    "missing-or-non-substantive",
)
CLML_ROUTE_STATES = (
    "source-advertised-official-https-route-unfrozen",
    "derived-structure-route-unverified-unfrozen",
    "other-recorded-route-unverified-unfrozen",
    "not-recorded",
)
NOTES_EVIDENCE_STATES = (
    "substantive-source-note",
    "generated-boilerplate",
    "non-prose-source-value",
    "empty",
)
INPUT_OUTCOMES = (
    "candidate-local-semantic-evidence",
    "deferred-frozen-clml-required",
    "terminal-insufficient-input-evidence",
    "terminal-invalid-input-record",
)
PRIORITY_STRATA = (
    "P1-fallback-resolve-derived-structure-route",
    "P2-fallback-resolve-advertised-clml-route",
    "P3-fallback-with-substantive-notes",
    "P4-substantive-title-and-notes",
    "P5-substantive-title-without-notes",
    "P6-no-semantic-text-and-no-recorded-route",
    "P7-invalid-input-record",
)

GENERATED_NOTES_RE = re.compile(
    r"^Official .+ record for .+ number .+\.$"
)


class EvidenceError(ValueError):
    """Raised when an input cannot support deterministic evidence."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_bounded_bytes(path: Path, max_bytes: int, label: str) -> bytes:
    """Read one regular file without allowing size races or excess bytes."""

    if (
        isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or max_bytes < 0
    ):
        raise EvidenceError(f"{label} byte bound is invalid")
    if not path.is_file() or path.is_symlink():
        raise EvidenceError(f"{label} is not a regular file: {path}")
    declared_size = path.stat().st_size
    if declared_size > max_bytes:
        raise EvidenceError(
            f"{label} exceeds the {max_bytes}-byte bound: {declared_size}"
        )
    with path.open("rb") as stream:
        body = stream.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise EvidenceError(f"{label} grew beyond its byte bound")
        if stream.read(1):
            raise EvidenceError(f"{label} has trailing bytes beyond its bound")
    if len(body) != declared_size:
        raise EvidenceError(
            f"{label} size changed while being read: "
            f"{declared_size} != {len(body)}"
        )
    return body


def file_binding(path: Path) -> dict[str, Any]:
    body = read_bounded_bytes(
        path,
        MAX_AUXILIARY_FILE_BYTES,
        "bound source material",
    )
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256_bytes(body),
        "bytes": len(body),
    }


def render_json(value: Any) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Return the repository's explicitly scoped compact canonical form."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_text(value: Any) -> str:
    """Normalize model-visible text without changing letter case."""

    text = unicodedata.normalize("NFC", str(value or ""))
    return " ".join(text.split())


def canonical_value(value: Any) -> Any:
    if isinstance(value, str):
        return canonical_text(value)
    if isinstance(value, list):
        normalized = [canonical_value(item) for item in value]
        if all(isinstance(item, str) for item in normalized):
            return sorted(set(normalized))
        return normalized
    if isinstance(value, dict):
        return {
            str(key): canonical_value(item)
            for key, item in sorted(value.items())
        }
    return value


def is_absolute_http_uri(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def is_substantive_text(value: Any, identifiers: Iterable[str] = ()) -> bool:
    text = canonical_text(value)
    if not text or is_absolute_http_uri(text):
        return False
    identifier_set = {
        canonical_text(identifier)
        for identifier in identifiers
        if canonical_text(identifier)
    }
    if text in identifier_set:
        return False
    return any(character.isalpha() for character in text)


def title_kind(record: dict[str, Any]) -> str:
    title = canonical_text(record.get("title"))
    if not title or not any(character.isalpha() for character in title):
        return "missing-or-non-substantive"
    if is_absolute_http_uri(title):
        return "uri-fallback"
    return "substantive"


def notes_evidence(
    record: dict[str, Any],
) -> tuple[str | None, str]:
    identifiers = (
        canonical_text(record.get("id")),
        canonical_text(record.get("title")),
        canonical_text(record.get("document_uri")),
        canonical_text(record.get("legislation_id_uri")),
    )
    value = canonical_text(record.get("notes"))
    if not value:
        return None, "empty"
    if GENERATED_NOTES_RE.fullmatch(value):
        return None, "generated-boilerplate"
    if not is_substantive_text(value, identifiers):
        return None, "non-prose-source-value"
    return value, "substantive-source-note"


def substantive_notes(record: dict[str, Any]) -> str | None:
    return notes_evidence(record)[0]


def clml_route(record: dict[str, Any]) -> dict[str, Any]:
    manifestations = record.get("manifestations")
    advertised = canonical_text(
        manifestations.get("clml")
        if isinstance(manifestations, dict)
        else None
    )
    structure = canonical_text(record.get("structure_url"))
    route = advertised or structure
    if not route:
        return {
            "advertised_route": None,
            "route": None,
            "route_origin": "none",
            "state": "not-recorded",
            "structure_route": None,
        }
    parsed = urlsplit(route)
    official_https = (
        parsed.scheme.lower() == "https"
        and parsed.hostname in {"www.legislation.gov.uk", "legislation.gov.uk"}
    )
    if advertised and official_https:
        state = "source-advertised-official-https-route-unfrozen"
        origin = "source-advertised-manifestation"
    elif not advertised and structure and official_https:
        state = "derived-structure-route-unverified-unfrozen"
        origin = "deterministically-derived-structure-route"
    else:
        state = "other-recorded-route-unverified-unfrozen"
        origin = (
            "source-advertised-manifestation"
            if advertised
            else "recorded-structure-route"
        )
    return {
        "advertised_route": advertised or None,
        "route": route,
        "route_origin": origin,
        "state": state,
        "structure_route": structure or None,
    }


def source_metadata(record: dict[str, Any]) -> dict[str, Any]:
    return {
        field: canonical_value(record.get(field))
        for field in SOURCE_METADATA_FIELDS
    }


def field_present(value: Any) -> bool:
    return value not in (None, "", [])


def classify_input(
    record: dict[str, Any],
    *,
    identity_valid: bool,
) -> tuple[str, str]:
    if not identity_valid:
        return "terminal-invalid-input-record", "P7-invalid-input-record"
    kind = title_kind(record)
    notes = substantive_notes(record)
    route = clml_route(record)
    local_text = kind == "substantive" or notes is not None

    if kind != "substantive" and notes is None:
        if route["route"] is not None:
            stratum = (
                "P2-fallback-resolve-advertised-clml-route"
                if route["route_origin"] == "source-advertised-manifestation"
                else "P1-fallback-resolve-derived-structure-route"
            )
            return (
                "deferred-frozen-clml-required",
                stratum,
            )
        return (
            "terminal-insufficient-input-evidence",
            "P6-no-semantic-text-and-no-recorded-route",
        )
    if kind != "substantive":
        return (
            "candidate-local-semantic-evidence",
            "P3-fallback-with-substantive-notes",
        )
    if notes is not None:
        return (
            "candidate-local-semantic-evidence",
            "P4-substantive-title-and-notes",
        )
    if not local_text:
        raise AssertionError("unreachable local evidence classification")
    return (
        "candidate-local-semantic-evidence",
        "P5-substantive-title-without-notes",
    )


def model_input_projection(
    record: dict[str, Any],
    *,
    outcome: str,
    priority_stratum: str,
) -> dict[str, Any]:
    route = clml_route(record)
    kind = title_kind(record)
    notes, notes_state = notes_evidence(record)
    return {
        "clml": {
            "advertised_route": route["advertised_route"],
            "frozen_body_sha256": None,
            "route": route["route"],
            "route_origin": route["route_origin"],
            "state": route["state"],
            "structure_route": route["structure_route"],
        },
        "id": canonical_text(record.get("id")),
        "input_eligibility_outcome": outcome,
        "long_title_equivalent": {
            "interpretation": (
                "official-source notes/synopsis; not asserted to be an exact "
                "statutory long title"
            ),
            "source_field": "notes",
            "state": notes_state,
            "value": notes,
        },
        "priority_stratum": priority_stratum,
        "source_metadata": source_metadata(record),
        "title": {
            "kind": kind,
            "value": canonical_text(record.get("title")) or None,
        },
    }


def counter_template(values: Iterable[str]) -> Counter[str]:
    return Counter({value: 0 for value in values})


def add_counter(target: Counter[str], source: Counter[str]) -> None:
    for key, value in source.items():
        target[key] += value


def canonical_chunk_root(rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(str(row["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["sha256"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(row["compressed_bytes"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(row["records"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def derived_chunk_root(
    rows: list[dict[str, Any]],
    digest_field: str,
) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(str(row["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row[digest_field]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(row["records"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def safe_bundle_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise EvidenceError(f"unsafe bundle path: {relative}")
    bundle = (root / "bundle").resolve()
    path = (bundle / candidate).resolve()
    if not path.is_relative_to(bundle):
        raise EvidenceError(f"bundle path escapes publication: {relative}")
    if not path.is_file() or path.is_symlink():
        raise EvidenceError(f"work chunk is not a regular file: {relative}")
    return path


def load_json(path: Path) -> Any:
    body = read_bounded_bytes(path, MAX_JSON_FILE_BYTES, "JSON material")
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"invalid bounded JSON material: {path}") from error


def _sha256_regular_file(path: Path, expected_bytes: int, label: str) -> str:
    """Hash exactly ``expected_bytes`` without buffering the whole file."""

    digest = hashlib.sha256()
    observed = 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(IO_BLOCK_BYTES)
            if not block:
                break
            observed += len(block)
            if observed > expected_bytes:
                raise EvidenceError(
                    f"{label} contains trailing bytes beyond its locator size"
                )
            digest.update(block)
    if observed != expected_bytes:
        raise EvidenceError(
            f"{label} size changed while hashing: "
            f"{expected_bytes} != {observed}"
        )
    return digest.hexdigest()


def _bounded_single_member_gzip(
    path: Path,
    *,
    max_decompressed_bytes: int,
    label: str,
) -> bytes:
    """Stream one gzip member and reject bombs, truncation and trailing data."""

    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    output = bytearray()
    reached_eof = False
    try:
        with path.open("rb") as stream:
            while not reached_eof:
                block = stream.read(IO_BLOCK_BYTES)
                if not block:
                    break
                pending = block
                while pending:
                    remaining = max_decompressed_bytes - len(output)
                    piece = decompressor.decompress(pending, remaining + 1)
                    output.extend(piece)
                    if len(output) > max_decompressed_bytes:
                        raise EvidenceError(
                            f"{label} exceeds the "
                            f"{max_decompressed_bytes}-byte decompressed bound"
                        )
                    if decompressor.unused_data:
                        raise EvidenceError(
                            f"{label} has a trailing gzip member or bytes"
                        )
                    next_pending = decompressor.unconsumed_tail
                    if decompressor.eof:
                        if next_pending or stream.read(1):
                            raise EvidenceError(
                                f"{label} has trailing compressed bytes"
                            )
                        reached_eof = True
                        break
                    if (
                        next_pending
                        and next_pending == pending
                        and not piece
                    ):
                        raise EvidenceError(
                            f"{label} gzip decoder made no progress"
                        )
                    pending = next_pending
    except zlib.error as error:
        raise EvidenceError(f"invalid gzip work chunk: {label}") from error
    if not decompressor.eof:
        raise EvidenceError(f"truncated gzip work chunk: {label}")
    tail = decompressor.flush(max_decompressed_bytes - len(output) + 1)
    output.extend(tail)
    if len(output) > max_decompressed_bytes:
        raise EvidenceError(
            f"{label} exceeds the "
            f"{max_decompressed_bytes}-byte decompressed bound"
        )
    return bytes(output)


def load_verified_work_chunk(
    path: Path,
    relative: str,
    locator: Any,
    *,
    max_compressed_bytes: int = MAX_WORK_CHUNK_COMPRESSED_BYTES,
    max_decompressed_bytes: int = MAX_WORK_CHUNK_DECOMPRESSED_BYTES,
    max_records: int = MAX_WORK_CHUNK_RECORDS,
) -> tuple[list[dict[str, Any]], str, int]:
    """Verify a work locator completely before bounded gzip decompression."""

    if not isinstance(locator, dict):
        raise EvidenceError(f"record locator is not an object: {relative}")
    if str(locator.get("path")) != relative:
        raise EvidenceError(f"record locator path/order mismatch: {relative}")
    if locator.get("compression") != "gzip":
        raise EvidenceError(f"record locator compression is not gzip: {relative}")
    compressed_bytes = locator.get("compressed_bytes")
    if (
        isinstance(compressed_bytes, bool)
        or not isinstance(compressed_bytes, int)
        or compressed_bytes <= 0
        or compressed_bytes > max_compressed_bytes
    ):
        raise EvidenceError(
            f"record locator compressed size is outside the governed bound: "
            f"{relative}"
        )
    records = locator.get("records")
    if (
        isinstance(records, bool)
        or not isinstance(records, int)
        or records <= 0
        or records > max_records
    ):
        raise EvidenceError(
            f"record locator record count is outside the governed bound: "
            f"{relative}"
        )
    locator_sha = locator.get("sha256")
    if (
        not isinstance(locator_sha, str)
        or re.fullmatch(r"[0-9a-f]{64}", locator_sha) is None
    ):
        raise EvidenceError(f"record locator digest is invalid: {relative}")
    observed_size = path.stat().st_size
    if observed_size != compressed_bytes:
        raise EvidenceError(
            f"record locator compressed_bytes mismatch for {relative}: "
            f"{compressed_bytes!r} != {observed_size!r}"
        )
    observed_sha = _sha256_regular_file(
        path,
        compressed_bytes,
        f"work chunk {relative}",
    )
    if observed_sha != locator_sha:
        raise EvidenceError(
            f"record locator sha256 mismatch for {relative}: "
            f"{locator_sha!r} != {observed_sha!r}"
        )

    body = _bounded_single_member_gzip(
        path,
        max_decompressed_bytes=max_decompressed_bytes,
        label=f"work chunk {relative}",
    )
    try:
        text = body.decode("utf-8")
        rows, end = json.JSONDecoder().raw_decode(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"invalid gzip JSON work chunk: {relative}") from error
    if text[end:] not in {"", "\n"}:
        raise EvidenceError(
            f"work chunk has unexpected trailing JSON bytes: {relative}"
        )
    if not isinstance(rows, list) or not rows:
        raise EvidenceError(f"work chunk is not a non-empty list: {relative}")
    if len(rows) > max_records:
        raise EvidenceError(
            f"work chunk exceeds the {max_records}-record bound: {relative}"
        )
    if len(rows) != records:
        raise EvidenceError(
            f"record locator records mismatch for {relative}: "
            f"{records!r} != {len(rows)!r}"
        )
    return rows, observed_sha, observed_size


def iter_model_input_bindings(
    root: Path = ROOT,
) -> Iterator[dict[str, Any]]:
    """Yield source-order record IDs and hashes of exact model projections.

    The per-record ``input_sha256`` is SHA-256 over
    :func:`canonical_json_bytes` for the same projection whose LF-terminated
    bytes form the published ordered input-projection root.  This iterator
    rechecks every frozen work chunk against the record manifest while
    yielding, so a terminal paid-run ledger can be joined to the actual corpus
    rather than merely to copied aggregate roots.
    """

    manifest = load_json(root / "bundle" / "data" / "manifest.json")
    record_manifest = load_json(
        root / "bundle" / "data" / "records" / "manifest.json"
    )
    source_paths = manifest.get("chunks", {}).get("datasets")
    locator_chunks = record_manifest.get("record_chunks")
    if (
        not isinstance(source_paths, list)
        or not source_paths
        or not isinstance(locator_chunks, list)
        or len(locator_chunks) != len(source_paths)
    ):
        raise EvidenceError(
            "model-input binding source and record manifests do not reconcile"
        )
    seen_ids: set[str] = set()
    ordinal = 0
    candidate_ordinal = 0
    for chunk_index, relative_value in enumerate(source_paths):
        relative = str(relative_value)
        path = safe_bundle_path(root, relative)
        locator = locator_chunks[chunk_index]
        records, _, _ = load_verified_work_chunk(
            path,
            relative,
            locator,
        )
        for row_index, record in enumerate(records):
            if not isinstance(record, dict):
                raise EvidenceError(
                    f"work row {row_index} is not an object: {relative}"
                )
            identifier = canonical_text(record.get("id"))
            identity_valid = bool(identifier) and identifier not in seen_ids
            if identifier:
                if identifier in seen_ids:
                    raise EvidenceError(
                        f"duplicate work ID in paid input projection: "
                        f"{identifier}"
                    )
                seen_ids.add(identifier)
            outcome, stratum = classify_input(
                record,
                identity_valid=identity_valid,
            )
            projection = model_input_projection(
                record,
                outcome=outcome,
                priority_stratum=stratum,
            )
            projection_bytes = canonical_json_bytes(projection)
            current_candidate_ordinal = (
                candidate_ordinal
                if outcome == "candidate-local-semantic-evidence"
                else None
            )
            yield {
                "candidate_ordinal": current_candidate_ordinal,
                "input_bytes": len(projection_bytes),
                "input_eligibility_outcome": outcome,
                "input_sha256": sha256_bytes(projection_bytes),
                "ordinal": ordinal,
                "priority_stratum": stratum,
                "projection": projection,
                "record_id": identifier,
            }
            if current_candidate_ordinal is not None:
                candidate_ordinal += 1
            ordinal += 1


def scan_corpus(root: Path = ROOT) -> dict[str, Any]:
    data_manifest_path = root / "bundle" / "data" / "manifest.json"
    record_manifest_path = (
        root / "bundle" / "data" / "records" / "manifest.json"
    )
    descriptor_path = root / "bundle" / "okf-explorer.json"
    manifest = load_json(data_manifest_path)
    record_manifest = load_json(record_manifest_path)
    descriptor = load_json(descriptor_path)

    source_paths = manifest.get("chunks", {}).get("datasets")
    if not isinstance(source_paths, list) or not source_paths:
        raise EvidenceError("data manifest has no dataset chunks")
    if len(source_paths) != len(set(source_paths)):
        raise EvidenceError("data manifest contains duplicate work chunk paths")
    locator_chunks = record_manifest.get("record_chunks")
    if not isinstance(locator_chunks, list):
        raise EvidenceError("record locator manifest lacks record_chunks")
    if len(locator_chunks) != len(source_paths):
        raise EvidenceError("record locator and data manifest chunk counts differ")

    global_title = counter_template(TITLE_KINDS)
    global_notes = counter_template(NOTES_EVIDENCE_STATES)
    global_clml = counter_template(CLML_ROUTE_STATES)
    global_outcomes = counter_template(INPUT_OUTCOMES)
    global_strata = counter_template(PRIORITY_STRATA)
    global_source_fields = Counter(
        {field: 0 for field in SOURCE_METADATA_FIELDS}
    )
    chunks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    duplicate_ids = 0
    missing_ids = 0
    records = 0
    source_semantic_digest = hashlib.sha256()
    ordered_identity_digest = hashlib.sha256()
    ordered_projection_digest = hashlib.sha256()

    for index, relative_value in enumerate(source_paths):
        relative = str(relative_value)
        path = safe_bundle_path(root, relative)
        locator = locator_chunks[index]
        rows, body_sha, compressed_bytes = load_verified_work_chunk(
            path,
            relative,
            locator,
        )

        source_semantic_digest.update(relative.encode("utf-8"))
        source_semantic_digest.update(body_sha.encode("ascii"))
        chunk_identity_digest = hashlib.sha256()
        chunk_projection_digest = hashlib.sha256()
        chunk_title = counter_template(TITLE_KINDS)
        chunk_notes = counter_template(NOTES_EVIDENCE_STATES)
        chunk_clml = counter_template(CLML_ROUTE_STATES)
        chunk_outcomes = counter_template(INPUT_OUTCOMES)
        chunk_strata = counter_template(PRIORITY_STRATA)

        for row_index, record in enumerate(rows):
            if not isinstance(record, dict):
                raise EvidenceError(
                    f"work row {row_index} is not an object: {relative}"
                )
            records += 1
            identifier = canonical_text(record.get("id"))
            identity_valid = bool(identifier)
            if not identifier:
                missing_ids += 1
            elif identifier in seen_ids:
                duplicate_ids += 1
                identity_valid = False
            else:
                seen_ids.add(identifier)

            kind = title_kind(record)
            notes, notes_state = notes_evidence(record)
            route = clml_route(record)
            outcome, stratum = classify_input(
                record,
                identity_valid=identity_valid,
            )
            chunk_title[kind] += 1
            chunk_notes[notes_state] += 1
            chunk_clml[route["state"]] += 1
            chunk_outcomes[outcome] += 1
            chunk_strata[stratum] += 1
            metadata = source_metadata(record)
            for field, value in metadata.items():
                if field_present(value):
                    global_source_fields[field] += 1

            identity_line = identifier.encode("utf-8") + b"\n"
            projection_line = (
                canonical_json_bytes(
                    model_input_projection(
                        record,
                        outcome=outcome,
                        priority_stratum=stratum,
                    )
                )
                + b"\n"
            )
            chunk_identity_digest.update(identity_line)
            ordered_identity_digest.update(identity_line)
            chunk_projection_digest.update(projection_line)
            ordered_projection_digest.update(projection_line)

        add_counter(global_title, chunk_title)
        add_counter(global_notes, chunk_notes)
        add_counter(global_clml, chunk_clml)
        add_counter(global_outcomes, chunk_outcomes)
        add_counter(global_strata, chunk_strata)
        chunks.append(
            {
                "compressed_bytes": compressed_bytes,
                "coverage": {
                    "clml_route_state": dict(chunk_clml),
                    "input_eligibility_outcome": dict(chunk_outcomes),
                    "notes": dict(chunk_notes),
                    "priority_stratum": dict(chunk_strata),
                    "title": dict(chunk_title),
                },
                "ordered_identity_sha256": chunk_identity_digest.hexdigest(),
                "ordered_input_projection_sha256": (
                    chunk_projection_digest.hexdigest()
                ),
                "path": relative,
                "records": len(rows),
                "sha256": body_sha,
            }
        )

    raw_chunk_root = canonical_chunk_root(chunks)
    semantic_chunk_root = derived_chunk_root(
        chunks,
        "ordered_input_projection_sha256",
    )
    identity_chunk_root = derived_chunk_root(
        chunks,
        "ordered_identity_sha256",
    )
    descriptor_counts = descriptor.get("counts", {})
    manifest_counts = manifest.get("counts", {})

    checks = [
        {
            "id": "MEI-001",
            "dimension": "snapshot-binding",
            "status": (
                "passed"
                if manifest.get("snapshot") == EXPECTED_SNAPSHOT
                and record_manifest.get("snapshot") == EXPECTED_SNAPSHOT
                and descriptor.get("snapshot") == EXPECTED_SNAPSHOT
                else "failed"
            ),
            "evidence": {
                "expected": EXPECTED_SNAPSHOT,
                "data_manifest": manifest.get("snapshot"),
                "record_manifest": record_manifest.get("snapshot"),
                "descriptor": descriptor.get("snapshot"),
            },
        },
        {
            "id": "MEI-002",
            "dimension": "complete-denominator",
            "status": (
                "passed"
                if records == EXPECTED_WORKS
                and len(seen_ids) == EXPECTED_WORKS
                and missing_ids == 0
                and duplicate_ids == 0
                and manifest_counts.get("works") == EXPECTED_WORKS
                and descriptor_counts.get("works") == EXPECTED_WORKS
                else "failed"
            ),
            "evidence": {
                "records": records,
                "unique_ids": len(seen_ids),
                "missing_ids": missing_ids,
                "duplicate_ids": duplicate_ids,
                "manifest_works": manifest_counts.get("works"),
                "descriptor_works": descriptor_counts.get("works"),
            },
        },
        {
            "id": "MEI-003",
            "dimension": "chunk-reconciliation",
            "status": (
                "passed"
                if len(chunks) == EXPECTED_CHUNKS
                and sum(item["records"] for item in chunks) == EXPECTED_WORKS
                else "failed"
            ),
            "evidence": {
                "chunks": len(chunks),
                "records": sum(item["records"] for item in chunks),
                "record_locator_chunks": len(locator_chunks),
            },
        },
        {
            "id": "MEI-004",
            "dimension": "field-partitions",
            "status": (
                "passed"
                if sum(global_title.values()) == EXPECTED_WORKS
                and sum(global_notes.values()) == EXPECTED_WORKS
                and sum(global_clml.values()) == EXPECTED_WORKS
                else "failed"
            ),
            "evidence": {
                "title": dict(global_title),
                "notes": dict(global_notes),
                "clml_route_state": dict(global_clml),
            },
        },
        {
            "id": "MEI-005",
            "dimension": "outcome-and-priority-partitions",
            "status": (
                "passed"
                if sum(global_outcomes.values()) == EXPECTED_WORKS
                and sum(global_strata.values()) == EXPECTED_WORKS
            else "failed"
            ),
            "evidence": {
                "input_eligibility_outcomes": dict(global_outcomes),
                "priority_strata": dict(global_strata),
            },
        },
        {
            "id": "MEI-006",
            "dimension": "core-source-metadata",
            "status": (
                "passed"
                if all(
                    global_source_fields[field] == EXPECTED_WORKS
                    for field in REQUIRED_CORE_SOURCE_METADATA_FIELDS
                )
                else "failed"
            ),
            "evidence": {
                field: global_source_fields[field]
                for field in REQUIRED_CORE_SOURCE_METADATA_FIELDS
            },
        },
        {
            "id": "MEI-007",
            "dimension": "clml-claim-boundary",
            "status": (
                "passed"
                if (
                    global_clml[
                        "source-advertised-official-https-route-unfrozen"
                    ]
                    == EXPECTED_SOURCE_ADVERTISED_CLML_ROUTES
                    and global_clml[
                        "derived-structure-route-unverified-unfrozen"
                    ]
                    == EXPECTED_DERIVED_STRUCTURE_ROUTES
                    and sum(global_clml.values()) == EXPECTED_WORKS
                )
                else "failed"
            ),
            "evidence": {
                "recorded_or_derived_routes": sum(
                    count
                    for state, count in global_clml.items()
                    if state != "not-recorded"
                ),
                "source_advertised_manifestation_routes": global_clml[
                    "source-advertised-official-https-route-unfrozen"
                ],
                "derived_structure_routes": global_clml[
                    "derived-structure-route-unverified-unfrozen"
                ],
                "frozen_bodies": 0,
                "claim": (
                    "A source-advertised manifestation or deterministically "
                    "derived structure route is not treated as a retrieved, "
                    "available, parsed or frozen CLML body."
                ),
            },
        },
        {
            "id": "MEI-008",
            "dimension": "notes-boilerplate-boundary",
            "status": (
                "passed"
                if (
                    global_notes["generated-boilerplate"]
                    == EXPECTED_GENERATED_NOTES_BOILERPLATE
                    and (
                        global_notes["substantive-source-note"]
                        + global_notes["non-prose-source-value"]
                    )
                    == EXPECTED_NON_BOILERPLATE_NONEMPTY_NOTES
                    and global_notes["substantive-source-note"]
                    == EXPECTED_SUBSTANTIVE_SOURCE_NOTES
                )
                else "failed"
            ),
            "evidence": {
                "generated_boilerplate": global_notes[
                    "generated-boilerplate"
                ],
                "non_boilerplate_nonempty": (
                    global_notes["substantive-source-note"]
                    + global_notes["non-prose-source-value"]
                ),
                "non_prose_source_values": global_notes[
                    "non-prose-source-value"
                ],
                "substantive_source_notes": global_notes[
                    "substantive-source-note"
                ],
                "pattern": GENERATED_NOTES_RE.pattern,
            },
        },
    ]

    return {
        "checks": checks,
        "chunks": chunks,
        "counts": {
            "chunks": len(chunks),
            "duplicate_ids": duplicate_ids,
            "missing_ids": missing_ids,
            "records": records,
            "unique_ids": len(seen_ids),
        },
        "coverage": {
            "clml_route_state": dict(global_clml),
            "input_eligibility_outcome": dict(global_outcomes),
            "notes": dict(global_notes),
            "priority_stratum": dict(global_strata),
            "source_metadata_fields": dict(global_source_fields),
            "title": dict(global_title),
        },
        "roots": {
            "ordered_identity_sha256": ordered_identity_digest.hexdigest(),
            "ordered_identity_chunk_root_sha256": identity_chunk_root,
            "ordered_input_projection_sha256": (
                ordered_projection_digest.hexdigest()
            ),
            "ordered_input_projection_chunk_root_sha256": (
                semantic_chunk_root
            ),
            "source_chunk_root_sha256": raw_chunk_root,
            "source_input_semantic_sha256": (
                source_semantic_digest.hexdigest()
            ),
        },
        "snapshot": str(manifest.get("snapshot")),
    }


def case_payload(row: dict[str, Any]) -> dict[str, Any]:
    title = canonical_text(row.get("title"))
    topics_value = row.get("expected_topics")
    if not isinstance(topics_value, list):
        raise EvidenceError("calibration expected_topics must be an array")
    topics = sorted(
        {
            canonical_text(topic)
            for topic in topics_value
            if canonical_text(topic)
        }
    )
    case_kind = canonical_text(
        row.get(
            "case_kind",
            "positive" if topics else "negative-no-supported-assertion",
        )
    )
    audit_family = canonical_text(row.get("audit_family")) or None
    if not title:
        raise EvidenceError("calibration case has an empty title")
    return {
        "audit_family": audit_family,
        "case_kind": case_kind,
        "expected_topics": topics,
        "title": title,
    }


def rule_test_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "near_miss_negative": canonical_text(row.get("near_miss_negative")),
        "positive": canonical_text(row.get("positive")),
        "rule_id": canonical_text(row.get("rule_id")),
    }
    if not all(payload.values()):
        raise EvidenceError("calibration rule test is incomplete")
    return payload


def ordered_binding_root(
    rows: Iterable[tuple[str, str]],
) -> str:
    digest = hashlib.sha256()
    for identifier, semantic_hash in rows:
        digest.update(identifier.encode("utf-8"))
        digest.update(b"\0")
        digest.update(semantic_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def build_calibration_manifest(root: Path = ROOT) -> dict[str, Any]:
    historical_path = (
        root / "enrichment" / "codex-assisted-v2-calibration.json"
    )
    body = read_bounded_bytes(
        historical_path,
        MAX_JSON_FILE_BYTES,
        "historical calibration JSON",
    )
    historical_sha = sha256_bytes(body)
    if historical_sha != EXPECTED_HISTORICAL_CALIBRATION_SHA256:
        raise EvidenceError(
            "historical calibration bytes changed: "
            f"{historical_sha} != "
            f"{EXPECTED_HISTORICAL_CALIBRATION_SHA256}"
        )
    historical = json.loads(body)
    cases_value = historical.get("cases")
    rule_tests_value = historical.get("rule_tests")
    if not isinstance(cases_value, list) or not isinstance(
        rule_tests_value,
        list,
    ):
        raise EvidenceError("historical calibration arrays are missing")

    cases: list[dict[str, Any]] = []
    case_ids: set[str] = set()
    case_root_rows: list[tuple[str, str]] = []
    for index, row in enumerate(cases_value):
        if not isinstance(row, dict):
            raise EvidenceError(f"calibration case {index} is not an object")
        payload = case_payload(row)
        semantic_hash = sha256_bytes(canonical_json_bytes(payload))
        case_id = f"urn:okf:calibration:sha256:{semantic_hash}"
        if case_id in case_ids:
            raise EvidenceError(f"duplicate stable calibration case: {case_id}")
        case_ids.add(case_id)
        case_root_rows.append((case_id, semantic_hash))
        cases.append(
            {
                "canonical_sha256": semantic_hash,
                "case_id": case_id,
                "source_index": index,
                **payload,
            }
        )

    rule_tests: list[dict[str, Any]] = []
    rule_ids: set[str] = set()
    rule_root_rows: list[tuple[str, str]] = []
    for index, row in enumerate(rule_tests_value):
        if not isinstance(row, dict):
            raise EvidenceError(f"rule test {index} is not an object")
        payload = rule_test_payload(row)
        rule_id = payload["rule_id"]
        if rule_id in rule_ids:
            raise EvidenceError(f"duplicate calibration rule test: {rule_id}")
        rule_ids.add(rule_id)
        semantic_hash = sha256_bytes(canonical_json_bytes(payload))
        rule_root_rows.append((rule_id, semantic_hash))
        rule_tests.append(
            {
                "canonical_sha256": semantic_hash,
                "source_index": index,
                **payload,
            }
        )

    content = {
        "artifact_state": "fixed-pre-model-selection",
        "canonicalization": {
            "case_id": (
                "urn:okf:calibration:sha256:<SHA-256 of the canonical case "
                "payload>"
            ),
            "json": (
                "UTF-8 JSON, lexicographically sorted object keys, compact "
                "comma/colon separators, ensure_ascii=false, allow_nan=false"
            ),
            "text": (
                "Unicode NFC; leading/trailing and repeated Unicode "
                "whitespace collapsed to one ASCII space; case preserved"
            ),
            "topic_arrays": "canonicalized, deduplicated and sorted",
        },
        "cases": cases,
        "counts": {
            "cases": len(cases),
            "negative_cases": sum(
                not case["expected_topics"] for case in cases
            ),
            "positive_cases": sum(
                bool(case["expected_topics"]) for case in cases
            ),
            "rule_tests": len(rule_tests),
        },
        "fixed_on": OBSERVED_DATE,
        "id": "uk-legislation-model-enrichment-calibration-v1",
        "rule_tests": rule_tests,
        "schema": "okf-model-calibration-manifest.v1",
        "source": {
            "mutation_policy": (
                "immutable historical input; corrections require a separately "
                "identified successor"
            ),
            "path": historical_path.relative_to(root).as_posix(),
            "sha256": historical_sha,
        },
        "suite_roots": {
            "case_set_sha256": ordered_binding_root(
                sorted(case_root_rows)
            ),
            "case_source_order_sha256": ordered_binding_root(case_root_rows),
            "rule_test_source_order_sha256": ordered_binding_root(
                rule_root_rows
            ),
        },
    }
    content_semantic_sha = sha256_bytes(canonical_json_bytes(content))
    return {
        **content,
        "integrity": {
            "content_semantic_sha256": content_semantic_sha,
            "historical_source_bytes_sha256": historical_sha,
        },
    }


def percentage(count: int, denominator: int) -> float:
    return round(count / denominator, 9) if denominator else 0.0


def build_receipt(
    scan: dict[str, Any],
    calibration_manifest: dict[str, Any],
    calibration_bytes: bytes,
    root: Path = ROOT,
) -> dict[str, Any]:
    coverage = scan["coverage"]
    records = scan["counts"]["records"]
    outcomes = coverage["input_eligibility_outcome"]
    strata = coverage["priority_stratum"]
    source_fields = coverage["source_metadata_fields"]
    title = coverage["title"]
    notes = coverage["notes"]
    clml = coverage["clml_route_state"]
    checks = list(scan["checks"])
    checks.append(
        {
            "id": "MEI-009",
            "dimension": "fixed-calibration",
            "status": (
                "passed"
                if calibration_manifest["counts"]["cases"] == 58
                and calibration_manifest["counts"]["rule_tests"] == 55
                and calibration_manifest["source"]["sha256"]
                == EXPECTED_HISTORICAL_CALIBRATION_SHA256
                else "failed"
            ),
            "evidence": {
                "cases": calibration_manifest["counts"]["cases"],
                "rule_tests": calibration_manifest["counts"]["rule_tests"],
                "source_sha256": calibration_manifest["source"]["sha256"],
                "case_set_sha256": calibration_manifest["suite_roots"][
                    "case_set_sha256"
                ],
            },
        }
    )
    passed = all(check["status"] == "passed" for check in checks)

    return {
        "artifact_state": "credential-free-preflight-evidence",
        "bindings": {
            "builder": file_binding(root / "scripts" / BUILDER_PATH.name),
            "calibration_manifest": {
                "bytes": len(calibration_bytes),
                "path": CALIBRATION_MANIFEST_PATH.relative_to(ROOT).as_posix(),
                "sha256": sha256_bytes(calibration_bytes),
            },
            "historical_calibration": file_binding(
                root
                / "enrichment"
                / "codex-assisted-v2-calibration.json"
            ),
            "record_locator_manifest": file_binding(
                root
                / "bundle"
                / "data"
                / "records"
                / "manifest.json"
            ),
        },
        "checks": checks,
        "chunks": scan["chunks"],
        "decision": {
            "api_calls_authorized": False,
            "evidence_status": "passed" if passed else "failed",
            "paid_run_authorized": False,
            "reason": (
                "This receipt establishes the frozen local work-chunk "
                "denominator and evidence availability only. Every "
                "source-advertised or derived CLML route still lacks a frozen "
                "body binding, and the "
                "separate governed model, review, cost and credential gates "
                "must pass before any paid call."
            ),
            "secret_access_authorized": False,
        },
        "eligibility": {
            "complete_denominator": records,
            "input_eligibility_outcome_vocabulary": [
                {
                    "assertions_permitted_by_this_receipt": False,
                    "count": outcomes[
                        "candidate-local-semantic-evidence"
                    ],
                    "meaning": (
                        "A substantive official title or notes/synopsis is "
                        "present in the frozen work chunk. CLML resolution and "
                        "separate run authorization remain outstanding."
                    ),
                    "model_call_permitted_by_this_receipt": False,
                    "terminal": False,
                    "value": "candidate-local-semantic-evidence",
                },
                {
                    "assertions_permitted_by_this_receipt": False,
                    "count": outcomes["deferred-frozen-clml-required"],
                    "meaning": (
                        "No local substantive title or notes is present; an "
                        "advertised CLML manifestation or derived structure "
                        "route is recorded but its body is not frozen. Resolve "
                        "and bind it, or record an immutable unavailable "
                        "result."
                    ),
                    "model_call_permitted_by_this_receipt": False,
                    "terminal": False,
                    "value": "deferred-frozen-clml-required",
                },
                {
                    "assertions_permitted_by_this_receipt": False,
                    "count": outcomes[
                        "terminal-insufficient-input-evidence"
                    ],
                    "meaning": (
                        "After the declared official evidence routes are "
                        "resolved, no substantive frozen evidence exists. "
                        "Record abstention and emit no semantic assertion."
                    ),
                    "model_call_permitted_by_this_receipt": False,
                    "terminal": True,
                    "value": "terminal-insufficient-input-evidence",
                },
                {
                    "assertions_permitted_by_this_receipt": False,
                    "count": outcomes["terminal-invalid-input-record"],
                    "meaning": (
                        "The source row lacks a unique usable work identity. "
                        "No model call or assertion is permitted."
                    ),
                    "model_call_permitted_by_this_receipt": False,
                    "terminal": True,
                    "value": "terminal-invalid-input-record",
                },
            ],
            "insufficiency_policy": {
                "assertions_permitted": False,
                "default_classification_permitted": False,
                "model_call_permitted": False,
                "required_terminal_outcome": (
                    "terminal-insufficient-input-evidence"
                ),
                "reentry_condition": (
                    "A new separately frozen official evidence input changes "
                    "the canonical model-input projection hash."
                ),
            },
            "local_semantic_evidence_candidates": outcomes[
                "candidate-local-semantic-evidence"
            ],
            "outcome_counts": outcomes,
            "paid_run_eligible_now": 0,
            "paid_run_eligibility_note": (
                "The optional direct API profile is outside the current "
                "release and this receipt intentionally cannot authorize it. "
                "The governed Codex workflow consumes this frozen input "
                "evidence without an API key or direct API call."
            ),
        },
        "field_coverage": {
            "clml_manifestation": {
                "claim_boundary": (
                    "A source-advertised manifestation is kept separate from "
                    "a deterministically derived structure route. Neither is "
                    "evidence of current HTTP availability, successful "
                    "parsing, annotations or frozen content."
                ),
                "counts": clml,
                "derived_structure_route_total": clml[
                    "derived-structure-route-unverified-unfrozen"
                ],
                "recorded_or_derived_route_total": sum(
                    count
                    for state, count in clml.items()
                    if state != "not-recorded"
                ),
                "frozen_body_bound": 0,
                "source_advertised_manifestation_total": clml[
                    "source-advertised-official-https-route-unfrozen"
                ],
            },
            "long_title_equivalent": {
                "counts": notes,
                "generated_boilerplate_definition": (
                    "Full-form regex `^Official .+ record for .+ number "
                    ".+\\.$`, matching the deterministic corpus-builder "
                    "fallback template."
                ),
                "interpretation": (
                    "Only a nonempty, non-boilerplate `notes` value containing "
                    "alphabetic prose is treated as substantive official "
                    "source synopsis/long-title-equivalent evidence. It is not "
                    "asserted to be an exact statutory long title."
                ),
                "non_boilerplate_nonempty": (
                    notes["substantive-source-note"]
                    + notes["non-prose-source-value"]
                ),
                "source_field": "notes",
                "substantive_rate": percentage(
                    notes["substantive-source-note"],
                    records,
                ),
            },
            "source_metadata": {
                "core_complete_count": min(
                    source_fields[field]
                    for field in REQUIRED_CORE_SOURCE_METADATA_FIELDS
                ),
                "core_fields": list(
                    REQUIRED_CORE_SOURCE_METADATA_FIELDS
                ),
                "field_counts": source_fields,
            },
            "title": {
                "counts": title,
                "substantive_rate": percentage(
                    title["substantive"],
                    records,
                ),
                "uri_fallback_rate": percentage(
                    title["uri-fallback"],
                    records,
                ),
            },
        },
        "limitations": [
            (
                "No OpenAI API request, model selection, secret read or "
                "billing action is performed or authorized by this evidence."
            ),
            (
                "137,119 works source-advertise a CLML manifestation and "
                "228,667 have only a deterministically derived structure "
                "route. This snapshot binds zero retrieved CLML bodies; "
                "neither route class proves live availability or annotation "
                "coverage."
            ),
            (
                "The notes field contains 35,156 deterministic `Official … "
                "record for …` fallback strings, which are excluded from "
                "semantic evidence. Remaining prose can be explanatory or "
                "synopsis text; it is not represented as an exact statutory "
                "long title."
            ),
            (
                "This is deterministic input and eligibility evidence, not "
                "legal-semantic classification, legal advice or independent "
                "validation of future model outputs."
            ),
            (
                "The current governed Codex workflow must record its own "
                "terminal outcome for every work; these preflight outcomes "
                "must not be substituted for that terminal ledger. Any "
                "separately authorised future direct API profile would also "
                "need its own independent outcome ledger."
            ),
        ],
        "observed_date": OBSERVED_DATE,
        "priority_strata": [
            {
                "count": strata[
                    "P1-fallback-resolve-derived-structure-route"
                ],
                "id": "P1-fallback-resolve-derived-structure-route",
                "model_call_permitted_by_this_receipt": False,
                "purpose": (
                    "Highest evidence-resolution priority: verify the "
                    "deterministically derived structure route, then freeze "
                    "the CLML body or record immutable unavailability."
                ),
            },
            {
                "count": strata[
                    "P2-fallback-resolve-advertised-clml-route"
                ],
                "id": "P2-fallback-resolve-advertised-clml-route",
                "model_call_permitted_by_this_receipt": False,
                "purpose": (
                    "Resolve a source-advertised CLML manifestation for a "
                    "URI-title record with no substantive local notes."
                ),
            },
            {
                "count": strata[
                    "P3-fallback-with-substantive-notes"
                ],
                "id": "P3-fallback-with-substantive-notes",
                "model_call_permitted_by_this_receipt": False,
                "purpose": (
                    "High-review-risk candidates whose title is a URI but "
                    "whose notes contain substantive local evidence."
                ),
            },
            {
                "count": strata["P4-substantive-title-and-notes"],
                "id": "P4-substantive-title-and-notes",
                "model_call_permitted_by_this_receipt": False,
                "purpose": (
                    "Richest local frozen text candidates for governed "
                    "calibration and evidence-support checks."
                ),
            },
            {
                "count": strata[
                    "P5-substantive-title-without-notes"
                ],
                "id": "P5-substantive-title-without-notes",
                "model_call_permitted_by_this_receipt": False,
                "purpose": (
                    "Substantive-title candidates with thinner local prose "
                    "evidence and recorded but unfrozen CLML routes."
                ),
            },
            {
                "count": strata[
                    "P6-no-semantic-text-and-no-recorded-route"
                ],
                "id": "P6-no-semantic-text-and-no-recorded-route",
                "model_call_permitted_by_this_receipt": False,
                "purpose": (
                    "Terminal insufficiency unless new frozen official "
                    "evidence is added."
                ),
            },
            {
                "count": strata["P7-invalid-input-record"],
                "id": "P7-invalid-input-record",
                "model_call_permitted_by_this_receipt": False,
                "purpose": "Terminal invalid-source outcome.",
            },
        ],
        "roots": {
            **scan["roots"],
            "algorithms": {
                "ordered_identity": (
                    "SHA-256 over canonical work ID plus LF in source chunk "
                    "and row order"
                ),
                "ordered_input_projection": (
                    "SHA-256 over one compact canonical model-input projection "
                    "plus LF per work, in source chunk and row order"
                ),
                "raw_chunk_root": (
                    "SHA-256 over manifest-order path NUL compressed SHA-256 "
                    "NUL compressed bytes NUL records LF"
                ),
                "source_input_semantic": (
                    "SHA-256 over manifest-order UTF-8 source path followed by "
                    "ASCII compressed-byte SHA-256, without separators; "
                    "compatible with the v2 independent audit"
                ),
            },
        },
        "schema": "okf-model-enrichment-input-eligibility.v1",
        "scope": {
            "calibration_cases": calibration_manifest["counts"]["cases"],
            "calibration_rule_tests": calibration_manifest["counts"][
                "rule_tests"
            ],
            "source_chunks": scan["counts"]["chunks"],
            "source_snapshot": scan["snapshot"],
            "works": records,
        },
    }


def markdown_report(receipt: dict[str, Any]) -> str:
    scope = receipt["scope"]
    coverage = receipt["field_coverage"]
    title = coverage["title"]["counts"]
    notes = coverage["long_title_equivalent"]["counts"]
    clml = coverage["clml_manifestation"]
    outcomes = receipt["eligibility"]["outcome_counts"]
    checks = receipt["checks"]

    lines = [
        "# Model-assisted enrichment input and eligibility evidence",
        "",
        f"Observed date: **{receipt['observed_date']}**",
        "",
        (
            "This credential-free preflight reconciles all "
            f"**{scope['works']:,} works** in "
            f"**{scope['source_chunks']:,} source chunks**. It performs and "
            "authorizes no model call, credential read or billing action."
        ),
        "",
        "## Decision",
        "",
        (
            f"Evidence status: **{receipt['decision']['evidence_status']}**. "
            "Current workflow: **Codex, no direct API calls**. Optional "
            "direct API profile authorized: **no**."
        ),
        "",
        receipt["decision"]["reason"],
        "",
        "## Frozen input coverage",
        "",
        "| Dimension | State | Works | Share |",
        "| --- | --- | ---: | ---: |",
        (
            f"| Title | Substantive | {title['substantive']:,} | "
            f"{percentage(title['substantive'], scope['works']):.3%} |"
        ),
        (
            f"| Title | URI fallback | {title['uri-fallback']:,} | "
            f"{percentage(title['uri-fallback'], scope['works']):.3%} |"
        ),
        (
            "| Title | Missing/non-substantive | "
            f"{title['missing-or-non-substantive']:,} | "
            f"{percentage(title['missing-or-non-substantive'], scope['works']):.3%} |"
        ),
        (
            "| Notes/synopsis | Substantive source prose | "
            f"{notes['substantive-source-note']:,} | "
            f"{percentage(notes['substantive-source-note'], scope['works']):.3%} |"
        ),
        (
            "| Notes/synopsis | Generated boilerplate excluded | "
            f"{notes['generated-boilerplate']:,} | "
            f"{percentage(notes['generated-boilerplate'], scope['works']):.3%} |"
        ),
        (
            "| Notes/synopsis | Non-prose source value excluded | "
            f"{notes['non-prose-source-value']:,} | "
            f"{percentage(notes['non-prose-source-value'], scope['works']):.3%} |"
        ),
        (
            f"| Notes/synopsis | Empty | {notes['empty']:,} | "
            f"{percentage(notes['empty'], scope['works']):.3%} |"
        ),
        (
            "| CLML | Source-advertised manifestation, body unfrozen | "
            f"{clml['source_advertised_manifestation_total']:,} | "
            f"{percentage(clml['source_advertised_manifestation_total'], scope['works']):.3%} |"
        ),
        (
            "| CLML | Derived structure route, unverified/body unfrozen | "
            f"{clml['derived_structure_route_total']:,} | "
            f"{percentage(clml['derived_structure_route_total'], scope['works']):.3%} |"
        ),
        (
            f"| CLML | Frozen body bound | {clml['frozen_body_bound']:,} | "
            f"{percentage(clml['frozen_body_bound'], scope['works']):.3%} |"
        ),
        "",
        (
            "The 35,156 full-form `Official … record for … number ….` "
            "builder fallbacks are excluded. The remaining 85,640 nonempty "
            "source values contain 85,638 substantive prose values and two "
            "non-prose remnants. Notes are not asserted to be exact statutory "
            "long titles. Neither CLML route class is a successful access or "
            "content receipt."
        ),
        "",
        "## Preflight outcomes",
        "",
        "| Outcome | Works | Terminal |",
        "| --- | ---: | :---: |",
    ]
    vocabulary = {
        item["value"]: item
        for item in receipt["eligibility"][
            "input_eligibility_outcome_vocabulary"
        ]
    }
    for value in INPUT_OUTCOMES:
        lines.append(
            f"| `{value}` | {outcomes[value]:,} | "
            f"{'yes' if vocabulary[value]['terminal'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            (
                "Insufficient frozen evidence always means abstention: no "
                "model call, default classification or semantic assertion. "
                "Re-entry requires newly frozen official evidence and a "
                "changed canonical input-projection hash."
            ),
            "",
            "## Evidence-resolution priority strata",
            "",
            "| Priority | Works | Purpose |",
            "| --- | ---: | --- |",
        ]
    )
    for row in receipt["priority_strata"]:
        lines.append(f"| `{row['id']}` | {row['count']:,} | {row['purpose']} |")
    lines.extend(
        [
            "",
            "Priority is for evidence resolution and review planning, not "
            "automatic paid-call order.",
            "",
            "## Stable roots",
            "",
            (
                "- Source snapshot: "
                f"`{scope['source_snapshot']}`"
            ),
            (
                "- Raw source chunk root: "
                f"`{receipt['roots']['source_chunk_root_sha256']}`"
            ),
            (
                "- Source-input compatibility root: "
                f"`{receipt['roots']['source_input_semantic_sha256']}`"
            ),
            (
                "- Ordered work identity root: "
                f"`{receipt['roots']['ordered_identity_sha256']}`"
            ),
            (
                "- Ordered canonical input-projection root: "
                f"`{receipt['roots']['ordered_input_projection_sha256']}`"
            ),
            (
                "- Fixed calibration case-set root: "
                f"`{receipt['bindings']['calibration_manifest']['sha256']}`"
            ),
            "",
            "## Checks",
            "",
            "| Check | Dimension | Status |",
            "| --- | --- | --- |",
        ]
    )
    for check in checks:
        lines.append(
            f"| `{check['id']}` | {check['dimension']} | "
            f"{check['status']} |"
        )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in receipt["limitations"]],
            "",
        ]
    )
    return "\n".join(lines)


def build_artifacts(root: Path = ROOT) -> dict[Path, bytes]:
    calibration_manifest = build_calibration_manifest(root)
    calibration_bytes = render_json(calibration_manifest).encode("utf-8")
    scan = scan_corpus(root)
    receipt = build_receipt(
        scan,
        calibration_manifest,
        calibration_bytes,
        root,
    )
    report = markdown_report(receipt)
    return {
        Path("enrichment/model-assisted-calibration-manifest-v1.json"): (
            calibration_bytes
        ),
        Path(
            "whole-law/assurance/"
            "model-assisted-input-eligibility-20260726.json"
        ): render_json(receipt).encode("utf-8"),
        Path(
            "whole-law/assurance/"
            "model-assisted-input-eligibility-20260726.md"
        ): report.encode("utf-8"),
    }


def artifact_mismatches(
    artifacts: dict[Path, bytes],
    root: Path = ROOT,
) -> list[str]:
    errors: list[str] = []
    for relative, expected in artifacts.items():
        path = root / relative
        if not path.is_file() or path.is_symlink():
            errors.append(f"missing or non-regular: {relative}")
        elif path.stat().st_size != len(expected):
            errors.append(f"out of date: {relative}")
        elif read_bounded_bytes(
            path,
            len(expected),
            f"generated artifact {relative}",
        ) != expected:
            errors.append(f"out of date: {relative}")
    return errors


def write_artifacts(
    artifacts: dict[Path, bytes],
    root: Path = ROOT,
) -> None:
    for relative, body in artifacts.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(body)
        temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the tracked generated evidence is missing or stale",
    )
    args = parser.parse_args(argv)
    try:
        artifacts = build_artifacts()
    except (EvidenceError, OSError, json.JSONDecodeError) as error:
        print(f"model enrichment input evidence failed: {error}", file=sys.stderr)
        return 1
    if args.check:
        mismatches = artifact_mismatches(artifacts)
        if mismatches:
            for mismatch in mismatches:
                print(mismatch, file=sys.stderr)
            return 1
        print(
            "model enrichment input evidence current: "
            f"{EXPECTED_WORKS:,} works; {EXPECTED_CHUNKS} chunks; "
            "58 fixed calibration cases; paid calls authorized=false"
        )
        return 0
    write_artifacts(artifacts)
    print(
        "wrote model enrichment input evidence: "
        f"{EXPECTED_WORKS:,} works; {EXPECTED_CHUNKS} chunks; "
        "58 fixed calibration cases; paid calls authorized=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
