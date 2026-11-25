#!/usr/bin/env python3
"""Assemble the typed Reader transport separately from the audited source pack."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from build_legislation_okf import BASE, gzip_json, https_url, inflate_single_gzip, large_corpus
from build_checksums import build as build_checksums
from reader_payload_encoding import (
    COMPRESSED_PATH,
    ORIGINAL_PATH,
    POLICY_PATH,
    REPORT_PATH,
    project as project_payload_encoding,
)


PROFILE = f"{BASE}/schema/legislation"
REVISION = re.compile(r"/([0-9]{4}-[0-9]{2}-[0-9]{2}|enacted|made|created|adopted|prospective)$")
LANGUAGE = re.compile(r"/(english|welsh)$")
WORK_SHARD = re.compile(r"data/works-(0|[1-9][0-9]*)\.json\.gz")
RECEIPT = "data/reader-transport/v2/receipt.json"
PAGES_LIMIT = 1_000_000_000


def typed_work(record: dict) -> dict:
    source = https_url(record.get("structure_url") or "")
    work = https_url(record.get("document_uri") or "")
    parsed = urlparse(source)
    if not parsed.path.endswith("/data.xml") or parsed.query or not work or urlparse(work).query:
        raise ValueError(f"Missing an official CLML representation for {record['name']}")
    expression_path = parsed.path.removesuffix("/data.xml")
    work_path = urlparse(work).path.rstrip("/")
    language = LANGUAGE.search(expression_path)
    requested_language = LANGUAGE.search(work_path)
    if requested_language and (not language or language.group(1) != requested_language.group(1)):
        raise ValueError(f"CLML language does not match {record['name']}")
    expression_path = LANGUAGE.sub("", expression_path)
    work_path = LANGUAGE.sub("", work_path)
    revision = REVISION.search(expression_path)
    requested_revision = REVISION.search(work_path)
    if REVISION.sub("", expression_path) != REVISION.sub("", work_path):
        raise ValueError(f"CLML work does not match {record['name']}")
    version = revision.group(1) if revision else "latest"
    if requested_revision and requested_revision.group(1) != version:
        raise ValueError(f"CLML version does not match {record['name']}")
    suffix = f"-{language.group(1)}" if language else ""
    representation = {
        "id": f"{record['name']}-clml-{version}{suffix}",
        "dataset": record["name"],
        "name": "Official structured legislation (CLML)",
        "resource_type": "authoritative-structure",
        "source_access": {
            "url": source, "label": "Official structured legislation (CLML)",
            "media_type": "application/xml", "display_mode": "xml",
            "content_profile": PROFILE, "representation_version": version,
            "retrieval_mode": "live",
        },
        "provenance": {
            "source_url": record["legislation_id_uri"],
            "representation_basis": "official-feed-link"
            if record.get("manifestations", {}).get("clml") == source else "official-format-route",
        },
    }
    other_representations = [row for row in record.get("source_representations", [])
                             if row["id"] != representation["id"]]
    result = {**record, "core_role": "extension", "source_representations": [*other_representations, representation]}
    if https_url(result.get("source_api_url") or "") == source:
        del result["source_api_url"]
    return result


def render_at(path: Path, value: dict) -> bytes:
    body = large_corpus.render_json(value).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return body


def project(root: Path, source_commit: str) -> dict:
    original_checksums = (root / "checksums.json").read_bytes()
    manifest = json.loads((root / "data/manifest.json").read_bytes())
    locator_file = root / "data/records/manifest.json"
    locator_before = locator_file.read_bytes()
    locator = json.loads(locator_before)
    chunk_paths = manifest["chunks"]["datasets"]
    chunks = locator["record_chunks"]
    if (
        not chunk_paths or len(chunk_paths) > 2_048
        or len(set(chunk_paths)) != len(chunk_paths)
        or set(chunk_paths) != {row["path"] for row in chunks}
        or len(chunk_paths) != len(chunks)
        or not all(WORK_SHARD.fullmatch(path) for path in chunk_paths)
    ):
        raise ValueError("The source manifest and locator must declare the same bounded work shards")
    default_bytes = decoded_bytes = work_count = compressed_bytes = 0
    rewritten = []
    for entry in chunks:
        path = root / entry["path"]
        before = inflate_single_gzip(path)
        source_digest = sha256(path.read_bytes()).hexdigest()
        if source_digest != entry["sha256"] or path.stat().st_size != entry["compressed_bytes"]:
            raise ValueError(f"Source shard does not match the frozen locator: {entry['path']}")
        records = json.loads(before)
        if len(records) != entry["records"]:
            raise ValueError(f"Work count differs from the frozen locator: {entry['path']}")
        typed = [typed_work(record) for record in records]
        body = gzip_json(typed)
        path.write_bytes(body)
        entry.update(sha256=sha256(body).hexdigest(), compressed_bytes=len(body))
        default_bytes += len(before)
        decoded_bytes += len(large_corpus.render_json(typed).encode("utf-8"))
        work_count += len(typed)
        compressed_bytes += len(body)
        rewritten.append({**entry, "source_sha256": source_digest})
    if work_count != manifest["counts"]["works"]:
        raise ValueError("Typed transport does not cover the declared work set")

    # Preserve the canonical answer bytes in Source, while encoding this one
    # newly introduced large payload in the disposable Pages transport.
    project_payload_encoding(root, source_commit)

    locator_bytes = render_at(locator_file, locator)
    performance_file = root / "data/performance.json"
    performance = json.loads(performance_file.read_bytes())
    performance["planes"]["work_records"].update(compressed_bytes=compressed_bytes, decoded_json_bytes=decoded_bytes)
    performance["targeted_record_hydration"]["maximum_record_chunk_bytes"] = max(row["compressed_bytes"] for row in chunks)
    performance["full_hydration"]["decoded_json_bytes_before_object_overhead"] += decoded_bytes - default_bytes
    descriptor_file = root / "okf-explorer.json"
    descriptor_before = descriptor_file.read_bytes()
    receipt = {
        "canonical_descriptor_sha256": sha256(descriptor_before).hexdigest(),
        "canonical_descriptor_bytes": len(descriptor_before),
        "descriptor_policy": "preserve-exact-source-bytes",
        "schema": "okf-legislation-reader-transport.v2",
        "source_commit": source_commit,
        "source_manifest": f"https://raw.githubusercontent.com/chris-page-gov/okf-uk-legislation/{source_commit}/bundle/data/manifest.json",
        "source_checksums_sha256": sha256(original_checksums).hexdigest(),
        "work_count": work_count, "work_shards": rewritten,
    }
    receipt_bytes = render_at(root / RECEIPT, receipt)
    # The source and Pages descriptors have the same exact bytes. The typed
    # work shards are a separate transport, discovered through interfaces.json.
    # Their complete locator and source/transport digests are bound above.
    performance["startup"]["control_plane_bytes"] += len(locator_bytes) - len(locator_before)
    render_at(performance_file, performance)
    checksums = build_checksums(root)
    original_files = json.loads(original_checksums)["files"]
    published_files = json.loads(checksums)["files"]
    changed = {name for name in original_files.keys() | published_files.keys()
               if original_files.get(name) != published_files.get(name)}
    allowed = {
        *chunk_paths, "data/records/manifest.json", "data/performance.json", RECEIPT,
        POLICY_PATH, ORIGINAL_PATH, COMPRESSED_PATH, REPORT_PATH,
    }
    if unexpected := changed - allowed:
        raise ValueError(f"Unexpected changes outside the typed Reader transport: {sorted(unexpected)[:10]}")
    if descriptor_file.read_bytes() != descriptor_before:
        raise ValueError("Typed transport changed the canonical source descriptor")
    (root / "checksums.json").write_text(checksums, encoding="utf-8")
    # The canonical Whole-Law validator still requires its original payloads.
    # This explicit typed-site integrity pass verifies and decodes the one
    # declared gzip representation before accepting the projection.
    from check_whole_law_okf import check_integrity

    errors: list[str] = []
    check_integrity(errors, pack=root / "whole-law", typed_site_root=root)
    if errors:
        raise ValueError("Typed Whole-Law payload integrity failed: " + "; ".join(errors[:5]))
    size = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    if size > PAGES_LIMIT:
        raise ValueError(f"Typed Reader Site would exceed the Pages limit: {size} bytes")
    return {"work_count": work_count, "work_shards": len(chunks), "site_bytes": size,
            "receipt_sha256": sha256(receipt_bytes).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        parser.error("Use the exact frozen-source commit.")
    if source in (output, *output.parents) or args.output.exists():
        parser.error("Choose an unused output directory outside the frozen source.")
    try:
        with TemporaryDirectory(prefix="legislation-reader-", dir=output.parent) as temporary:
            staged = Path(temporary) / "bundle"
            shutil.copytree(source, staged)
            summary = project(staged, args.source_commit)
            subprocess.run(
                [sys.executable, str(Path(__file__).with_name("check_legislation_okf.py")), "--bundle", str(staged)],
                check=True,
            )
            staged.rename(output)
    except (KeyError, OSError, subprocess.CalledProcessError, TypeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
