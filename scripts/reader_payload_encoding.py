"""Project and validate the single approved large evaluation payload encoding."""

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
ORIGINAL_PATH = (
    "whole-law/evaluation/executions/"
    "eval-76d593e3295063f2cbe5/answers.json"
)
COMPRESSED_PATH = ORIGINAL_PATH + ".gz"
REPORT_PATH = (
    "whole-law/evaluation/executions/"
    "eval-76d593e3295063f2cbe5/report.html"
)
EXECUTION_INDEX_PATH = "whole-law/evaluation/executions/index.json"
APPROVED_RUN_ID = ORIGINAL_PATH.split("/")[-2]
ARCHIVE_FALLBACK = (
    "https://github.com/chris-page-gov/okf-uk-legislation/releases/tag/v0.5.0"
)
MAX_ORIGINAL_BYTES = 32_000_000
MAX_COMPRESSED_BYTES = 32_000_000
SOURCE_COMMIT_RE = re.compile(r"[0-9a-f]{40}")


def _json(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _safe_file(root: Path, relative: str) -> Path:
    path_value = PurePosixPath(relative)
    if path_value.is_absolute() or ".." in path_value.parts:
        raise ValueError("Payload path is not a contained relative path")
    path = root.joinpath(*path_value.parts)
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Payload path is not a regular contained file: {relative}")
    return path


def deterministic_gzip(body: bytes) -> bytes:
    """Compress exact bytes with a stable header and no embedded filename."""

    output = BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0, compresslevel=9) as stream:
        stream.write(body)
    return output.getvalue()


def inflate_single_gzip(body: bytes, *, expected_bytes: int, max_bytes: int = MAX_ORIGINAL_BYTES) -> bytes:
    """Inflate one bounded gzip member and reject suffixes or concatenated members."""

    if not isinstance(expected_bytes, int) or expected_bytes < 0 or expected_bytes > max_bytes:
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


def _source_url(source_commit: str) -> str:
    if not SOURCE_COMMIT_RE.fullmatch(source_commit):
        raise ValueError("Payload source commit must be a full lowercase Git SHA")
    return (
        "https://raw.githubusercontent.com/chris-page-gov/okf-uk-legislation/"
        f"{source_commit}/bundle/{ORIGINAL_PATH}"
    )


def _report_insert(raw_url: str) -> bytes:
    return (
        " <span class=\"encoded-answer-access\">"
        "<a href=\"answers.json.gz\">Download the exact answers as gzip-compressed JSON</a>; "
        f"<a href=\"{raw_url}\">fetch the original JSON bytes from the pinned source commit</a>; "
        f"<a href=\"{ARCHIVE_FALLBACK}\">open the full release archive fallback</a>."
        "</span>"
    ).encode("utf-8")


def _require_current_execution(bundle: Path) -> None:
    index = _json(_safe_file(bundle, EXECUTION_INDEX_PATH))
    if index.get("latest_run_id") != APPROVED_RUN_ID:
        raise ValueError("Payload encoding policy does not name the current evaluation execution")


def project(bundle: Path, source_commit: str) -> dict:
    """Replace only the selected answers file in a disposable typed bundle."""

    raw_url = _source_url(source_commit)
    _require_current_execution(bundle)
    checksums = _json(bundle / "checksums.json").get("files")
    if not isinstance(checksums, dict):
        raise ValueError("Canonical checksum map is missing")
    inner = _json(bundle / "whole-law/integrity.json").get("files")
    if not isinstance(inner, list):
        raise ValueError("Canonical Whole-Law integrity list is missing")
    checksum_row = checksums.get(ORIGINAL_PATH)
    inner_row = next((row for row in inner if row.get("path") == ORIGINAL_PATH.removeprefix("whole-law/")), None)
    if not isinstance(checksum_row, dict) or not isinstance(inner_row, dict):
        raise ValueError("Selected answers file is not bound by both canonical integrity maps")
    if checksum_row.get("bytes") != inner_row.get("bytes") or checksum_row.get("sha256") != inner_row.get("sha256"):
        raise ValueError("Canonical checksum and Whole-Law integrity identities differ")
    original = _safe_file(bundle, ORIGINAL_PATH)
    body = original.read_bytes()
    if len(body) != checksum_row["bytes"] or sha256(body).hexdigest() != checksum_row["sha256"]:
        raise ValueError("Selected answers bytes differ from the canonical source identity")
    compressed = deterministic_gzip(body)
    if len(compressed) > MAX_COMPRESSED_BYTES:
        raise ValueError("Compressed answers exceed the encoded payload bound")
    compressed_path = bundle / COMPRESSED_PATH
    compressed_path.parent.mkdir(parents=True, exist_ok=True)
    compressed_path.write_bytes(compressed)
    original.unlink()

    report_path = _safe_file(bundle, REPORT_PATH)
    report_body = report_path.read_bytes()
    marker = b"<code>answers.json</code>"
    if report_body.count(marker) != 1:
        raise ValueError("Selected report does not contain exactly one answers reference")
    projected_report = report_body.replace(marker, marker + _report_insert(raw_url), 1)
    report_path.write_bytes(projected_report)

    manifest = {
        "schema": SCHEMA,
        "policy": "one-fixed-current-evaluation-answers-object-only",
        "source_commit": source_commit,
        "archive_fallback": ARCHIVE_FALLBACK,
        "payloads": [{
            "path": ORIGINAL_PATH,
            "bytes": len(body),
            "sha256": sha256(body).hexdigest(),
            "decoded_media_type": "application/json",
            "source_url": raw_url,
            "transport_path": COMPRESSED_PATH,
            "transport_bytes": len(compressed),
            "transport_sha256": sha256(compressed).hexdigest(),
            "transport_media_type": "application/gzip",
            "content_encoding": "gzip",
        }],
        "report_projection": {
            "path": REPORT_PATH,
            "source_bytes": len(report_body),
            "source_sha256": sha256(report_body).hexdigest(),
            "transport_bytes": len(projected_report),
            "transport_sha256": sha256(projected_report).hexdigest(),
            "added_fragment_sha256": sha256(_report_insert(raw_url)).hexdigest(),
        },
        "ai_access": {
            "purpose": "Retrieve the exact answer payload for the named evaluation run",
            "manifest_path": POLICY_PATH,
            "payload_path": ORIGINAL_PATH,
            "transport_path": COMPRESSED_PATH,
            "plain_source_url": raw_url,
            "archive_fallback": ARCHIVE_FALLBACK,
        },
    }
    manifest_path = bundle / POLICY_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def validate(bundle: Path, *, checksums: dict | None = None) -> set[str]:
    """Validate the typed payload replacement; return canonical paths it satisfies."""

    manifest = _json(_safe_file(bundle, POLICY_PATH))
    _require_current_execution(bundle)
    payloads = manifest.get("payloads")
    if manifest.get("schema") != SCHEMA or manifest.get("policy") != "one-fixed-current-evaluation-answers-object-only" or not isinstance(payloads, list) or len(payloads) != 1:
        raise ValueError("Unknown or over-broad typed payload encoding policy")
    item = payloads[0]
    if not isinstance(item, dict) or item.get("path") != ORIGINAL_PATH or item.get("transport_path") != COMPRESSED_PATH:
        raise ValueError("Payload mapping is not the single approved answers object")
    raw_url = _source_url(manifest.get("source_commit", ""))
    if item.get("source_url") != raw_url or manifest.get("archive_fallback") != ARCHIVE_FALLBACK:
        raise ValueError("Payload source or archive fallback is not the pinned declared route")
    if item.get("decoded_media_type") != "application/json" or item.get("transport_media_type") != "application/gzip" or item.get("content_encoding") != "gzip":
        raise ValueError("Payload media encoding metadata is invalid")
    inner_rows = _json(bundle / "whole-law/integrity.json").get("files", [])
    if not isinstance(inner_rows, list):
        raise ValueError("Canonical Whole-Law integrity list is invalid")
    inner_row = next((row for row in inner_rows if row.get("path") == ORIGINAL_PATH.removeprefix("whole-law/")), None)
    report_inner_row = next((row for row in inner_rows if row.get("path") == REPORT_PATH.removeprefix("whole-law/")), None)
    if not isinstance(inner_row, dict) or item.get("bytes") != inner_row.get("bytes") or item.get("sha256") != inner_row.get("sha256"):
        raise ValueError("Encoded payload does not match the canonical Whole-Law integrity identity")
    if not isinstance(report_inner_row, dict):
        raise ValueError("Projected report is not bound by canonical Whole-Law integrity")
    if item["bytes"] > MAX_ORIGINAL_BYTES:
        raise ValueError("Original payload exceeds the decode bound")
    compressed_path = _safe_file(bundle, COMPRESSED_PATH)
    compressed = compressed_path.read_bytes()
    if len(compressed) != item.get("transport_bytes") or sha256(compressed).hexdigest() != item.get("transport_sha256"):
        raise ValueError("Encoded payload differs from its manifest")
    decoded = inflate_single_gzip(compressed, expected_bytes=item["bytes"])
    if sha256(decoded).hexdigest() != item["sha256"]:
        raise ValueError("Decoded payload differs from its canonical identity")
    original_path = bundle / ORIGINAL_PATH
    if original_path.exists() or original_path.is_symlink():
        raise ValueError("Typed site must contain only the encoded selected payload")

    report = _safe_file(bundle, REPORT_PATH).read_bytes()
    report_spec = manifest.get("report_projection")
    fragment = _report_insert(raw_url)
    marker = b"<code>answers.json</code>"
    if not isinstance(report_spec, dict) or report.count(marker + fragment) != 1:
        raise ValueError("Report does not expose the exact encoded and source access links")
    restored_report = report.replace(marker + fragment, marker, 1)
    if (
        sha256(restored_report).hexdigest() != report_spec.get("source_sha256")
        or len(restored_report) != report_spec.get("source_bytes")
        or report_spec.get("source_sha256") != report_inner_row.get("sha256")
        or report_spec.get("source_bytes") != report_inner_row.get("bytes")
        or sha256(report).hexdigest() != report_spec.get("transport_sha256")
        or len(report) != report_spec.get("transport_bytes")
        or report_spec.get("path") != REPORT_PATH
        or report_spec.get("added_fragment_sha256") != sha256(fragment).hexdigest()
    ):
        raise ValueError("Report projection is not a reversible source-linked edit")
    ai = manifest.get("ai_access")
    expected_ai = {
        "purpose": "Retrieve the exact answer payload for the named evaluation run",
        "manifest_path": POLICY_PATH,
        "payload_path": ORIGINAL_PATH,
        "transport_path": COMPRESSED_PATH,
        "plain_source_url": raw_url,
        "archive_fallback": ARCHIVE_FALLBACK,
    }
    if ai != expected_ai:
        raise ValueError("AI access mapping differs from the payload policy")
    if checksums is None:
        checksums = _json(bundle / "checksums.json").get("files", {})
    if not isinstance(checksums, dict):
        raise ValueError("Typed-site checksum map is invalid")
    for path, data in ((COMPRESSED_PATH, compressed), (REPORT_PATH, report), (POLICY_PATH, (bundle / POLICY_PATH).read_bytes())):
        row = checksums.get(path)
        if not isinstance(row, dict) or row.get("bytes") != len(data) or row.get("sha256") != sha256(data).hexdigest():
            raise ValueError(f"Typed payload projection is not bound by checksums: {path}")
    return {ORIGINAL_PATH, REPORT_PATH}
