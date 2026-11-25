"""Encode two fixed migration answer objects without changing canonical evidence."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import gzip
import json
from pathlib import Path, PurePosixPath
import re
import zlib

SCHEMA = "okf-reader-payload-encoding.v1"
POLICY_PATH = "data/reader-transport/v1/payload-encoding.json"
CURRENT_RUN_ID = "eval-76d593e3295063f2cbe5"
EARLIER_MIGRATION_RUN_ID = "eval-1edbcf9ff765b952ee03"
APPROVED_RUN_IDS = (CURRENT_RUN_ID, EARLIER_MIGRATION_RUN_ID)
ORIGINAL_PATHS = tuple(f"whole-law/evaluation/executions/{run}/answers.json" for run in APPROVED_RUN_IDS)
COMPRESSED_PATHS = tuple(path + ".gz" for path in ORIGINAL_PATHS)
REPORT_PATHS = tuple(str(PurePosixPath(path).with_name("report.html")) for path in ORIGINAL_PATHS)
ORIGINAL_PATH, COMPRESSED_PATH, REPORT_PATH = ORIGINAL_PATHS[0], COMPRESSED_PATHS[0], REPORT_PATHS[0]
APPROVED_RUN_ID = CURRENT_RUN_ID
EXECUTION_INDEX_PATH = "whole-law/evaluation/executions/index.json"
ARCHIVE_FALLBACK = "https://github.com/chris-page-gov/okf-uk-legislation/releases/tag/v0.5.0"
POLICY = "two-fixed-unpublished-migration-answer-objects-only"
MAX_ORIGINAL_BYTES = MAX_COMPRESSED_BYTES = 32_000_000
SOURCE_COMMIT_RE = re.compile(r"[0-9a-f]{40}")


def _json(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _safe_file(root: Path, relative: str) -> Path:
    value = PurePosixPath(relative)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError("Payload path is not a contained relative path")
    path = root.joinpath(*value.parts)
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Payload path is not a regular contained file: {relative}")
    return path


def _index(bundle: Path) -> None:
    index = _json(_safe_file(bundle, EXECUTION_INDEX_PATH))
    if index.get("latest_run_id") != CURRENT_RUN_ID:
        raise ValueError("Payload encoding policy does not name the current evaluation execution")
    executions = index.get("executions")
    if not isinstance(executions, list):
        raise ValueError("Evaluation execution index is invalid")
    runs = {row.get("run_id") for row in executions if isinstance(row, dict)}
    if not set(APPROVED_RUN_IDS) <= runs:
        raise ValueError("Approved migration executions are absent from the execution index")


def _inner(bundle: Path) -> dict:
    rows = _json(bundle / "whole-law/integrity.json").get("files")
    if not isinstance(rows, list):
        raise ValueError("Canonical Whole-Law integrity list is missing")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str) or row["path"] in result:
            raise ValueError("Canonical Whole-Law integrity contains an invalid or duplicate path")
        result["whole-law/" + row["path"]] = row
    return result


def _matches(body: bytes, row: dict) -> bool:
    return isinstance(row, dict) and type(row.get("bytes")) is int and len(body) == row["bytes"] and sha256(body).hexdigest() == row.get("sha256")


def deterministic_gzip(body: bytes) -> bytes:
    output = BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0, compresslevel=9) as stream:
        stream.write(body)
    return output.getvalue()


def inflate_single_gzip(body: bytes, *, expected_bytes: int, max_bytes: int = MAX_ORIGINAL_BYTES) -> bytes:
    if type(expected_bytes) is not int or expected_bytes < 0 or expected_bytes > max_bytes:
        raise ValueError("Declared payload size is outside the decompression bound")
    if len(body) > MAX_COMPRESSED_BYTES:
        raise ValueError("Compressed payload exceeds its bound")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        decoded = decoder.decompress(body, expected_bytes + 1)
        if len(decoded) > expected_bytes or decoder.unconsumed_tail:
            raise ValueError("Decoded payload exceeds its declared size")
        decoded += decoder.flush(expected_bytes + 1 - len(decoded))
    except zlib.error as error:
        raise ValueError("Invalid gzip payload") from error
    if len(decoded) != expected_bytes or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("Payload is not exactly one gzip member of the declared size")
    return decoded


def _source_url(source_commit: str, path: str) -> str:
    if not isinstance(source_commit, str) or not SOURCE_COMMIT_RE.fullmatch(source_commit):
        raise ValueError("Payload source commit must be a full lowercase Git SHA")
    if path not in ORIGINAL_PATHS:
        raise ValueError("Payload mapping is not an approved answers object")
    return f"https://raw.githubusercontent.com/chris-page-gov/okf-uk-legislation/{source_commit}/bundle/{path}"


def _report_insert(raw_url: str) -> bytes:
    return (
        ' <span class="encoded-answer-access">'
        '<a href="answers.json.gz">Download the exact answers as gzip-compressed JSON</a>; '
        f'<a href="{raw_url}">fetch the original JSON bytes from the pinned source commit</a>; '
        f'<a href="{ARCHIVE_FALLBACK}">open the full release archive fallback</a>.'
        '</span>'
    ).encode("utf-8")


def _ai(source_commit: str) -> dict:
    return {"purpose": "Retrieve exact answers for the two named migration evaluation runs",
            "manifest_path": POLICY_PATH, "payload_paths": list(ORIGINAL_PATHS),
            "transport_paths": list(COMPRESSED_PATHS),
            "plain_source_urls": [_source_url(source_commit, path) for path in ORIGINAL_PATHS],
            "archive_fallback": ARCHIVE_FALLBACK}


def project(bundle: Path, source_commit: str) -> dict:
    _source_url(source_commit, ORIGINAL_PATH)
    _index(bundle)
    if (bundle / POLICY_PATH).exists() or (bundle / POLICY_PATH).is_symlink():
        raise ValueError("Payload projection requires a fresh typed bundle")
    checksums = _json(bundle / "checksums.json").get("files")
    inner = _inner(bundle)
    if not isinstance(checksums, dict):
        raise ValueError("Canonical checksum map is missing")
    prepared = []
    # Validate both objects and reports before replacing either one.
    for original, compressed_path, report_path in zip(ORIGINAL_PATHS, COMPRESSED_PATHS, REPORT_PATHS):
        row, canonical_row = checksums.get(original), inner.get(original)
        if not isinstance(row, dict) or not isinstance(canonical_row, dict):
            raise ValueError("Selected answers file is not bound by both canonical integrity maps")
        if (row.get("bytes"), row.get("sha256")) != (canonical_row.get("bytes"), canonical_row.get("sha256")):
            raise ValueError("Canonical checksum and Whole-Law integrity identities differ")
        if (bundle / compressed_path).exists() or (bundle / compressed_path).is_symlink():
            raise ValueError("Encoded output requires an unused regular-file destination")
        source = _safe_file(bundle, original)
        if source.stat().st_size > MAX_ORIGINAL_BYTES:
            raise ValueError("Original payload exceeds the decode bound")
        body = source.read_bytes()
        if not _matches(body, row):
            raise ValueError("Selected answers bytes differ from the canonical source identity")
        report_file = _safe_file(bundle, report_path)
        if report_file.stat().st_size > MAX_ORIGINAL_BYTES:
            raise ValueError("Report exceeds the projection bound")
        report = report_file.read_bytes()
        if report_path not in inner or not _matches(report, inner[report_path]) or not _matches(report, checksums.get(report_path, {})):
            raise ValueError("Selected report is not bound by both canonical integrity maps")
        marker = b"<code>answers.json</code>"
        if report.count(marker) != 1:
            raise ValueError("Selected report does not contain exactly one answers reference")
        compressed = deterministic_gzip(body)
        if len(compressed) > MAX_COMPRESSED_BYTES:
            raise ValueError("Compressed answers exceed the encoded payload bound")
        raw_url = _source_url(source_commit, original)
        projected_report = report.replace(marker, marker + _report_insert(raw_url), 1)
        prepared.append((original, compressed_path, report_path, body, compressed, report, projected_report, raw_url))
    manifest = {"schema": SCHEMA, "policy": POLICY, "source_commit": source_commit,
                "archive_fallback": ARCHIVE_FALLBACK, "payloads": [], "report_projections": [],
                "ai_access": _ai(source_commit)}
    for original, compressed_path, report_path, body, compressed, report, projected, raw_url in prepared:
        (bundle / compressed_path).write_bytes(compressed)
        (bundle / original).unlink()
        (bundle / report_path).write_bytes(projected)
        manifest["payloads"].append({"path": original, "bytes": len(body), "sha256": sha256(body).hexdigest(),
            "decoded_media_type": "application/json", "source_url": raw_url, "transport_path": compressed_path,
            "transport_bytes": len(compressed), "transport_sha256": sha256(compressed).hexdigest(),
            "transport_media_type": "application/gzip", "content_encoding": "gzip"})
        manifest["report_projections"].append({"path": report_path, "source_bytes": len(report),
            "source_sha256": sha256(report).hexdigest(), "transport_bytes": len(projected),
            "transport_sha256": sha256(projected).hexdigest(), "added_fragment_sha256": sha256(_report_insert(raw_url)).hexdigest()})
    target = bundle / POLICY_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def validate(bundle: Path, *, checksums: dict | None = None) -> set[str]:
    _index(bundle)
    manifest = _json(_safe_file(bundle, POLICY_PATH))
    payloads, reports = manifest.get("payloads"), manifest.get("report_projections")
    if manifest.get("schema") != SCHEMA or manifest.get("policy") != POLICY or not isinstance(payloads, list) or not isinstance(reports, list) or len(payloads) != 2 or len(reports) != 2:
        raise ValueError("Unknown or over-broad typed payload encoding policy")
    if [item.get("path") for item in payloads if isinstance(item, dict)] != list(ORIGINAL_PATHS) or [item.get("path") for item in reports if isinstance(item, dict)] != list(REPORT_PATHS):
        raise ValueError("Payload mapping is not the two approved answers objects")
    commit = manifest.get("source_commit", "")
    if manifest.get("archive_fallback") != ARCHIVE_FALLBACK or manifest.get("ai_access") != _ai(commit):
        raise ValueError("Payload source or AI access routes differ from the pinned declared policy")
    inner = _inner(bundle)
    if checksums is None:
        checksums = _json(bundle / "checksums.json").get("files")
    if not isinstance(checksums, dict):
        raise ValueError("Typed-site checksum map is invalid")
    for item, report_spec, original, transport, report_path in zip(payloads, reports, ORIGINAL_PATHS, COMPRESSED_PATHS, REPORT_PATHS):
        raw_url = _source_url(commit, original)
        if item.get("transport_path") != transport or item.get("source_url") != raw_url:
            raise ValueError("Payload mapping is not an approved answers object")
        if (item.get("decoded_media_type"), item.get("transport_media_type"), item.get("content_encoding")) != ("application/json", "application/gzip", "gzip"):
            raise ValueError("Payload media encoding metadata is invalid")
        canonical = inner.get(original, {})
        if (item.get("bytes"), item.get("sha256")) != (canonical.get("bytes"), canonical.get("sha256")):
            raise ValueError("Encoded payload does not match the canonical Whole-Law integrity identity")
        compressed_file = _safe_file(bundle, transport)
        if compressed_file.stat().st_size > MAX_COMPRESSED_BYTES:
            raise ValueError("Compressed payload exceeds its bound")
        compressed = compressed_file.read_bytes()
        if len(compressed) != item.get("transport_bytes") or sha256(compressed).hexdigest() != item.get("transport_sha256"):
            raise ValueError("Encoded payload differs from its manifest")
        decoded = inflate_single_gzip(compressed, expected_bytes=item["bytes"])
        if sha256(decoded).hexdigest() != item["sha256"]:
            raise ValueError("Decoded payload differs from its canonical identity")
        if (bundle / original).exists() or (bundle / original).is_symlink():
            raise ValueError("Typed site must contain only the encoded selected payloads")
        report = _safe_file(bundle, report_path).read_bytes()
        marker, fragment = b"<code>answers.json</code>", _report_insert(raw_url)
        if report.count(marker + fragment) != 1:
            raise ValueError("Report does not expose the exact encoded and source access links")
        restored = report.replace(marker + fragment, marker, 1)
        report_canonical = inner.get(report_path, {})
        if not _matches(restored, report_canonical) or len(restored) != report_spec.get("source_bytes") or sha256(restored).hexdigest() != report_spec.get("source_sha256") or len(report) != report_spec.get("transport_bytes") or sha256(report).hexdigest() != report_spec.get("transport_sha256") or report_spec.get("added_fragment_sha256") != sha256(fragment).hexdigest():
            raise ValueError("Report projection is not a reversible source-linked edit")
        for path, body in ((transport, compressed), (report_path, report)):
            if not _matches(body, checksums.get(path, {})):
                raise ValueError(f"Typed payload projection is not bound by checksums: {path}")
    if not _matches((bundle / POLICY_PATH).read_bytes(), checksums.get(POLICY_PATH, {})):
        raise ValueError("Typed payload policy is not bound by checksums")
    return set(ORIGINAL_PATHS) | set(REPORT_PATHS)
