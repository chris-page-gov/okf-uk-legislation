#!/usr/bin/env python3
"""Seal and verify immutable legislation-effects acquisition evidence.

Official Atom responses are downloaded content.  The exact source bytes are
kept in a deterministic, bounded tar.xz archive, while the Git-visible
publication projection contains only request metadata, byte counts and
digests.  Verification reads archive members in memory and never extracts them
to the working tree.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import lzma
import os
import re
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = (
    ROOT / "evidence" / "source-acquisitions" / "legislation-effects"
)
ARCHIVE_ROOT = EVIDENCE_ROOT / "archives"
RECEIPT_ROOT = EVIDENCE_ROOT / "archive-receipts"
PROJECTION_ROOT = EVIDENCE_ROOT / "publication-projections"

SNAPSHOT_RE = re.compile(r"^legislation-effects-\d{4}-\d{2}-\d{2}$")
CAPTURE_RE = re.compile(
    r"^[a-z0-9]+-\d{4}-\d+/(?:affected|affecting)/"
    r"page-\d{3}\.(?:xml|envelope\.json)$"
)
PUSH_PROTECTION_SHAPE = re.compile(rb"key-[A-Za-z0-9_-]{20,64}")
UNSAFE_XML_DECLARATION = re.compile(
    rb"<!\s*(?:DOCTYPE|ENTITY)\b",
    re.IGNORECASE,
)

ARCHIVE_SCHEMA = "okf-legislation-effects-evidence-archive-receipt.v1"
INTEGRITY_SCHEMA = "okf-legislation-effects-original-integrity.v1"
PROJECTION_SCHEMA = "okf-legislation-effects-evidence-projection.v1"
ARCHIVE_FORMAT = "application/x-xz; profile=application/x-tar"

MAX_ARCHIVE_FILES = 1_000
MAX_ARCHIVE_FILE_BYTES = 1 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 64 * 1024 * 1024


def render_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"Unsafe archive member path: {value!r}")
    return path


def load_json_bytes(value: bytes, label: str) -> dict[str, Any]:
    try:
        result = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid JSON in {label}: {error}") from error
    if not isinstance(result, dict):
        raise ValueError(f"{label} is not a JSON object")
    return result


def tree_receipts(files: dict[str, bytes]) -> list[dict[str, Any]]:
    return [
        {
            "path": relative,
            "bytes": len(body),
            "sha256": sha256_bytes(body),
        }
        for relative, body in sorted(files.items())
    ]


def tree_digest(receipts: list[dict[str, Any]]) -> str:
    return sha256_bytes(canonical_json_bytes(receipts))


def directory_snapshot(snapshot_dir: Path) -> dict[str, bytes]:
    if not SNAPSHOT_RE.fullmatch(snapshot_dir.name):
        raise ValueError("Snapshot directory name is invalid")
    files: dict[str, bytes] = {}
    for path in sorted(snapshot_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlink is not allowed in evidence: {path}")
        if not path.is_file():
            continue
        relative = safe_relative_path(
            path.relative_to(snapshot_dir).as_posix()
        ).as_posix()
        if not CAPTURE_RE.fullmatch(relative):
            raise ValueError(f"Unexpected effects evidence path: {relative}")
        body = path.read_bytes()
        if len(body) > MAX_ARCHIVE_FILE_BYTES:
            raise ValueError(f"Evidence member exceeds size bound: {relative}")
        files[relative] = body
    if not files:
        raise ValueError("Effects evidence directory is empty")
    return files


def original_integrity(
    snapshot_id: str,
    source_files: dict[str, bytes],
) -> dict[str, Any]:
    receipts = tree_receipts(source_files)
    return {
        "schema": INTEGRITY_SCHEMA,
        "snapshot_id": snapshot_id,
        "file_count": len(receipts),
        "total_bytes": sum(row["bytes"] for row in receipts),
        "tree_sha256": tree_digest(receipts),
        "files": receipts,
    }


def validate_capture_tree(
    snapshot_id: str,
    source_files: dict[str, bytes],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not SNAPSHOT_RE.fullmatch(snapshot_id):
        raise ValueError("Invalid effects snapshot ID")
    if not source_files:
        raise ValueError("Effects evidence contains no source files")
    if len(source_files) > MAX_ARCHIVE_FILES - 1:
        raise ValueError("Effects evidence exceeds file-count bound")
    if sum(len(body) for body in source_files.values()) > MAX_ARCHIVE_TOTAL_BYTES:
        raise ValueError("Effects evidence exceeds total-byte bound")

    paths = set(source_files)
    xml_paths = sorted(path for path in paths if path.endswith(".xml"))
    envelope_paths = sorted(
        path for path in paths if path.endswith(".envelope.json")
    )
    if not xml_paths or len(xml_paths) != len(envelope_paths):
        raise ValueError("Effects evidence body/envelope counts do not reconcile")

    captures: list[dict[str, Any]] = []
    matched_files: list[str] = []
    match_occurrences = 0
    unique_matches: set[bytes] = set()
    for body_path in xml_paths:
        if not CAPTURE_RE.fullmatch(body_path):
            raise ValueError(f"Unexpected effects evidence path: {body_path}")
        envelope_path = body_path.removesuffix(".xml") + ".envelope.json"
        if envelope_path not in source_files:
            raise ValueError(f"Missing capture envelope: {body_path}")
        body = source_files[body_path]
        if len(body) > MAX_ARCHIVE_FILE_BYTES:
            raise ValueError(f"Evidence member exceeds size bound: {body_path}")
        envelope = load_json_bytes(
            source_files[envelope_path],
            envelope_path,
        )
        if envelope.get("schema") != "okf-source-response-envelope.v1":
            raise ValueError(f"Unexpected envelope schema: {envelope_path}")
        if envelope.get("body_bytes") != len(body):
            raise ValueError(f"Envelope body byte count differs: {body_path}")
        if envelope.get("body_sha256") != sha256_bytes(body):
            raise ValueError(f"Envelope body digest differs: {body_path}")
        request = envelope.get("request", {})
        request_url = request.get("url")
        final_url = envelope.get("final_url")
        if request.get("method") != "GET":
            raise ValueError(f"Envelope request method is not GET: {envelope_path}")
        request_headers = request.get("headers", {})
        if not isinstance(request_headers, dict) or not set(
            key.lower() for key in request_headers
        ).issubset({"accept", "user-agent"}):
            raise ValueError(
                f"Envelope contains a non-public request header: {envelope_path}"
            )
        for label, url in (("request", request_url), ("final", final_url)):
            parsed = urlsplit(url) if isinstance(url, str) else None
            if (
                parsed is None
                or parsed.scheme != "https"
                or parsed.hostname != "www.legislation.gov.uk"
            ):
                raise ValueError(
                    f"Envelope {label} URL is outside the official host: "
                    f"{envelope_path}"
                )
        if envelope.get("success") and UNSAFE_XML_DECLARATION.search(body):
            raise ValueError(
                f"Successful response contains a prohibited XML declaration: "
                f"{body_path}"
            )

        matches = PUSH_PROTECTION_SHAPE.findall(body)
        if matches:
            matched_files.append(body_path)
            match_occurrences += len(matches)
            unique_matches.update(matches)
        captures.append({
            "body": {
                "archive_member": f"{snapshot_id}/{body_path}",
                "bytes": len(body),
                "sha256": sha256_bytes(body),
            },
            "envelope": {
                "archive_member": f"{snapshot_id}/{envelope_path}",
                "bytes": len(source_files[envelope_path]),
                "sha256": sha256_bytes(source_files[envelope_path]),
            },
            "request": {
                "method": request.get("method"),
                "url": request_url,
            },
            "response": {
                "final_url": final_url,
                "media_type": envelope.get("media_type"),
                "retrieved_at": envelope.get("retrieved_at"),
                "schema_fingerprint": envelope.get("schema_fingerprint"),
                "status": envelope.get("status"),
                "success": envelope.get("success"),
            },
            "rights": envelope.get("rights"),
            "tool": {
                "name": envelope.get("tool"),
                "version": envelope.get("tool_version"),
            },
        })

    unexpected = paths - set(xml_paths) - set(envelope_paths)
    if unexpected:
        raise ValueError("Effects evidence contains unexpected source files")
    match_summary = {
        "classification": (
            "public-legislation-identifiers-misclassified-as-credentials"
        ),
        "detector": "GitHub push protection",
        "matched_file_count": len(matched_files),
        "match_occurrence_count": match_occurrences,
        "unique_match_count": len(unique_matches),
        "matched_paths_sha256": sha256_bytes(
            ("\n".join(matched_files) + "\n").encode("utf-8")
        ),
        "values_recorded_in_receipt_or_projection": False,
        "values_are_credentials": False,
    }
    return captures, {
        "summary": match_summary,
        "values": unique_matches,
    }


def write_deterministic_archive(
    archive_path: Path,
    snapshot_id: str,
    files: dict[str, bytes],
) -> None:
    if not SNAPSHOT_RE.fullmatch(snapshot_id):
        raise ValueError("Invalid effects snapshot ID")
    if len(files) > MAX_ARCHIVE_FILES:
        raise ValueError("Archive exceeds file-count bound")
    if any(len(body) > MAX_ARCHIVE_FILE_BYTES for body in files.values()):
        raise ValueError("Archive member exceeds per-file size bound")
    if sum(len(body) for body in files.values()) > MAX_ARCHIVE_TOTAL_BYTES:
        raise ValueError("Archive exceeds total-byte bound")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive_path.with_name(f".{archive_path.name}.tmp")
    try:
        with lzma.open(
            temporary,
            mode="wb",
            format=lzma.FORMAT_XZ,
            check=lzma.CHECK_SHA256,
            preset=9 | lzma.PRESET_EXTREME,
        ) as compressed:
            with tarfile.open(
                fileobj=compressed,
                mode="w|",
                format=tarfile.USTAR_FORMAT,
            ) as archive:
                for relative, body in sorted(files.items()):
                    safe_relative_path(relative)
                    info = tarfile.TarInfo(f"{snapshot_id}/{relative}")
                    info.size = len(body)
                    info.mode = 0o644
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    info.mtime = 0
                    archive.addfile(info, io.BytesIO(body))
        if archive_path.exists():
            if archive_path.read_bytes() != temporary.read_bytes():
                raise FileExistsError(
                    "Immutable effects archive already exists with different bytes"
                )
            temporary.unlink()
        else:
            os.replace(temporary, archive_path)
    finally:
        temporary.unlink(missing_ok=True)


def read_archive_files(
    archive_path: Path,
    *,
    expected_snapshot_id: str,
) -> dict[str, bytes]:
    prefix = f"{expected_snapshot_id}/"
    files: dict[str, bytes] = {}
    total = 0
    try:
        archive = tarfile.open(archive_path, mode="r:xz")
    except (lzma.LZMAError, tarfile.TarError) as error:
        raise ValueError(f"Invalid effects evidence archive: {error}") from error
    with archive:
        for member in archive:
            if not member.isfile():
                raise ValueError(
                    f"Archive contains a non-regular member: {member.name}"
                )
            if not member.name.startswith(prefix):
                raise ValueError("Archive member is outside the snapshot directory")
            relative = safe_relative_path(
                member.name[len(prefix) :]
            ).as_posix()
            if relative in files:
                raise ValueError(f"Duplicate archive member: {relative}")
            if member.size > MAX_ARCHIVE_FILE_BYTES:
                raise ValueError(f"Archive member exceeds size bound: {relative}")
            if len(files) >= MAX_ARCHIVE_FILES:
                raise ValueError("Archive exceeds file-count bound")
            total += member.size
            if total > MAX_ARCHIVE_TOTAL_BYTES:
                raise ValueError("Archive exceeds total-byte bound")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"Cannot read archive member: {relative}")
            body = extracted.read(MAX_ARCHIVE_FILE_BYTES + 1)
            if len(body) != member.size:
                raise ValueError(f"Archive member size differs: {relative}")
            files[relative] = body
    if not files:
        raise ValueError("Effects evidence archive is empty")
    return files


def validate_original_integrity(
    snapshot_id: str,
    files: dict[str, bytes],
) -> tuple[dict[str, Any], dict[str, bytes]]:
    integrity_body = files.get("integrity.json")
    if integrity_body is None:
        raise ValueError("Effects evidence archive has no integrity.json")
    integrity = load_json_bytes(integrity_body, "integrity.json")
    if integrity.get("schema") != INTEGRITY_SCHEMA:
        raise ValueError("Unexpected effects original integrity schema")
    if integrity.get("snapshot_id") != snapshot_id:
        raise ValueError("Effects original integrity snapshot differs")
    source_files = {
        path: body
        for path, body in files.items()
        if path != "integrity.json"
    }
    expected = original_integrity(snapshot_id, source_files)
    if integrity != expected:
        raise ValueError("Effects original integrity manifest does not reconcile")
    return integrity, source_files


def archive_paths(snapshot_id: str) -> tuple[Path, Path, Path]:
    if not SNAPSHOT_RE.fullmatch(snapshot_id):
        raise ValueError("Invalid effects snapshot ID")
    return (
        ARCHIVE_ROOT / f"{snapshot_id}.tar.xz",
        RECEIPT_ROOT / f"{snapshot_id}.json",
        PROJECTION_ROOT / f"{snapshot_id}.json",
    )


def write_immutable(path: Path, body: bytes, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(body)
        if path.exists():
            if path.read_bytes() != body:
                raise FileExistsError(
                    f"Immutable {label} already exists with different bytes"
                )
            temporary.unlink()
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_receipt(
    *,
    snapshot_id: str,
    archived_at: str,
    archive_path: Path,
    files: dict[str, bytes],
    match_summary: dict[str, Any],
    match_values: set[bytes],
) -> dict[str, Any]:
    archive_bytes = archive_path.read_bytes()
    exposed_values = set(PUSH_PROTECTION_SHAPE.findall(archive_bytes))
    if exposed_values.intersection(match_values):
        raise ValueError(
            "Compressed archive exposes a detector-shaped source identifier"
        )
    integrity, source_files = validate_original_integrity(snapshot_id, files)
    receipts = tree_receipts(files)
    return {
        "schema": ARCHIVE_SCHEMA,
        "snapshot_id": snapshot_id,
        "archived_at": archived_at,
        "archive": {
            "path": archive_path.relative_to(ROOT).as_posix(),
            "media_type": ARCHIVE_FORMAT,
            "bytes": len(archive_bytes),
            "sha256": sha256_bytes(archive_bytes),
            "file_count": len(files),
            "uncompressed_file_bytes": sum(len(body) for body in files.values()),
            "tree_sha256": tree_digest(receipts),
            "normalized_tar_metadata": {
                "format": "ustar",
                "gid": 0,
                "mode": "0644",
                "mtime": 0,
                "uid": 0,
            },
            "safe_read_limits": {
                "max_files": MAX_ARCHIVE_FILES,
                "max_file_bytes": MAX_ARCHIVE_FILE_BYTES,
                "max_total_bytes": MAX_ARCHIVE_TOTAL_BYTES,
                "path_traversal_rejected": True,
                "regular_files_only": True,
            },
        },
        "original_integrity": {
            "path": "integrity.json",
            "bytes": len(files["integrity.json"]),
            "sha256": sha256_bytes(files["integrity.json"]),
            "file_count": integrity["file_count"],
            "total_bytes": integrity["total_bytes"],
            "tree_sha256": integrity["tree_sha256"],
            "all_source_files_verified": True,
        },
        "publication_trigger": match_summary,
        "publication_projection": {
            "path": (
                PROJECTION_ROOT / f"{snapshot_id}.json"
            ).relative_to(ROOT).as_posix(),
            "contains_response_bodies": False,
            "contains_detector_matched_values": False,
            "replaceable": True,
        },
        "assurance": {
            "byte_recovery_verified": (
                len(source_files) == integrity["file_count"]
            ),
            "compressed_blob_exposes_detected_plaintext": False,
            "immutable_original": True,
            "publication_projection_is_original": False,
        },
    }


def build_projection(
    *,
    snapshot_id: str,
    receipt_path: Path,
    receipt: dict[str, Any],
    captures: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": PROJECTION_SCHEMA,
        "snapshot_id": snapshot_id,
        "generated_from": {
            "archive_path": receipt["archive"]["path"],
            "archive_sha256": receipt["archive"]["sha256"],
            "archive_tree_sha256": receipt["archive"]["tree_sha256"],
            "original_tree_sha256": receipt["original_integrity"]["tree_sha256"],
            "receipt_path": receipt_path.relative_to(ROOT).as_posix(),
            "receipt_sha256": sha256_file(receipt_path),
        },
        "capture_count": len(captures),
        "captures": captures,
        "publication_policy": {
            "contains_response_bodies": False,
            "contains_response_headers": False,
            "contains_detector_matched_values": False,
            "detector_match_occurrence_count_in_original": (
                receipt["publication_trigger"]["match_occurrence_count"]
            ),
            "immutable_original": False,
            "replaceable": True,
        },
    }


def create_archive(
    snapshot_dir: Path,
    *,
    archived_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot_dir = snapshot_dir.resolve()
    snapshot_id = snapshot_dir.name
    source_files = directory_snapshot(snapshot_dir)
    captures, detector = validate_capture_tree(snapshot_id, source_files)
    integrity = original_integrity(snapshot_id, source_files)
    files = dict(source_files)
    files["integrity.json"] = render_json(integrity).encode("utf-8")
    archive_path, receipt_path, projection_path = archive_paths(snapshot_id)
    write_deterministic_archive(archive_path, snapshot_id, files)
    receipt = build_receipt(
        snapshot_id=snapshot_id,
        archived_at=archived_at,
        archive_path=archive_path,
        files=files,
        match_summary=detector["summary"],
        match_values=detector["values"],
    )
    receipt_body = render_json(receipt).encode("utf-8")
    if PUSH_PROTECTION_SHAPE.search(receipt_body):
        raise ValueError("Archive receipt contains a detector-shaped value")
    write_immutable(receipt_path, receipt_body, "archive receipt")
    projection = build_projection(
        snapshot_id=snapshot_id,
        receipt_path=receipt_path,
        receipt=receipt,
        captures=captures,
    )
    projection_body = render_json(projection).encode("utf-8")
    if PUSH_PROTECTION_SHAPE.search(projection_body):
        raise ValueError("Publication projection contains a detector-shaped value")
    projection_path.parent.mkdir(parents=True, exist_ok=True)
    projection_path.write_bytes(projection_body)
    validate_archive(snapshot_id)
    return receipt, projection


def validate_archive(
    snapshot_id: str,
) -> tuple[dict[str, Any], dict[str, bytes], dict[str, Any]]:
    archive_path, receipt_path, projection_path = archive_paths(snapshot_id)
    receipt = load_json_bytes(receipt_path.read_bytes(), str(receipt_path))
    if receipt.get("schema") != ARCHIVE_SCHEMA:
        raise ValueError("Unexpected effects archive receipt schema")
    if receipt.get("snapshot_id") != snapshot_id:
        raise ValueError("Effects archive receipt snapshot differs")
    archive_bytes = archive_path.read_bytes()
    archive_record = receipt.get("archive", {})
    if archive_record.get("bytes") != len(archive_bytes):
        raise ValueError("Effects archive byte count differs from receipt")
    if archive_record.get("sha256") != sha256_bytes(archive_bytes):
        raise ValueError("Effects archive digest differs from receipt")
    files = read_archive_files(
        archive_path,
        expected_snapshot_id=snapshot_id,
    )
    receipts = tree_receipts(files)
    if archive_record.get("file_count") != len(files):
        raise ValueError("Effects archive file count differs from receipt")
    if archive_record.get("uncompressed_file_bytes") != sum(
        len(body) for body in files.values()
    ):
        raise ValueError("Effects archive uncompressed bytes differ from receipt")
    if archive_record.get("tree_sha256") != tree_digest(receipts):
        raise ValueError("Effects archive tree digest differs from receipt")
    integrity, source_files = validate_original_integrity(snapshot_id, files)
    integrity_record = receipt.get("original_integrity", {})
    if integrity_record.get("sha256") != sha256_bytes(files["integrity.json"]):
        raise ValueError("Effects original integrity digest differs")
    if integrity_record.get("file_count") != integrity["file_count"]:
        raise ValueError("Effects original file count differs")
    if integrity_record.get("total_bytes") != integrity["total_bytes"]:
        raise ValueError("Effects original byte count differs")
    if integrity_record.get("tree_sha256") != integrity["tree_sha256"]:
        raise ValueError("Effects original tree digest differs")

    captures, detector = validate_capture_tree(snapshot_id, source_files)
    if receipt.get("publication_trigger") != detector["summary"]:
        raise ValueError("Effects publication trigger receipt differs")
    exposed_values = set(PUSH_PROTECTION_SHAPE.findall(archive_bytes))
    if exposed_values.intersection(detector["values"]):
        raise ValueError(
            "Compressed archive exposes a detector-shaped source identifier"
        )
    projection = load_json_bytes(
        projection_path.read_bytes(),
        str(projection_path),
    )
    if projection != build_projection(
        snapshot_id=snapshot_id,
        receipt_path=receipt_path,
        receipt=receipt,
        captures=captures,
    ):
        raise ValueError("Effects publication projection is out of date")
    if PUSH_PROTECTION_SHAPE.search(receipt_path.read_bytes()):
        raise ValueError("Effects archive receipt contains a detector-shaped value")
    if PUSH_PROTECTION_SHAPE.search(projection_path.read_bytes()):
        raise ValueError(
            "Effects publication projection contains a detector-shaped value"
        )
    validation = {
        "schema": "okf-legislation-effects-evidence-archive-validation.v1",
        "snapshot_id": snapshot_id,
        "archive_sha256": archive_record["sha256"],
        "archive_bytes": archive_record["bytes"],
        "source_file_count": integrity["file_count"],
        "source_total_bytes": integrity["total_bytes"],
        "source_tree_sha256": integrity["tree_sha256"],
        "capture_count": len(captures),
        "detector_matched_file_count": (
            detector["summary"]["matched_file_count"]
        ),
        "detector_match_occurrence_count": (
            detector["summary"]["match_occurrence_count"]
        ),
        "byte_recovery_verified": True,
        "projection_value_safe": True,
        "compressed_blob_plaintext_check_passed": True,
    }
    return validation, source_files, projection


def extract_archive(
    snapshot_id: str,
    destination: Path,
) -> None:
    _, source_files, _ = validate_archive(snapshot_id)
    snapshot_dir = destination / snapshot_id
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    for relative, body in sorted(source_files.items()):
        target = snapshot_dir.joinpath(*safe_relative_path(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(body)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seal and verify legislation-effects acquisition evidence"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser(
        "create",
        help="seal a completed loose capture directory",
    )
    create.add_argument("--snapshot-dir", type=Path, required=True)
    create.add_argument("--archived-at", required=True)
    check = subparsers.add_parser(
        "check",
        help="verify archive, original bytes, receipt and projection",
    )
    check.add_argument("--snapshot-id", required=True)
    extract = subparsers.add_parser(
        "extract",
        help="explicitly recover exact source bytes",
    )
    extract.add_argument("--snapshot-id", required=True)
    extract.add_argument("--destination", type=Path, required=True)
    extract.add_argument(
        "--acknowledge-untrusted-content",
        action="store_true",
        help="required because extraction materializes downloaded content",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "create":
            receipt, projection = create_archive(
                args.snapshot_dir,
                archived_at=args.archived_at,
            )
            result = {
                "archive": receipt["archive"],
                "capture_count": projection["capture_count"],
                "publication_trigger": receipt["publication_trigger"],
            }
        elif args.command == "check":
            result, _, _ = validate_archive(args.snapshot_id)
        elif args.command == "extract":
            if not args.acknowledge_untrusted_content:
                raise ValueError(
                    "Extraction requires --acknowledge-untrusted-content"
                )
            extract_archive(
                args.snapshot_id,
                args.destination.resolve(),
            )
            result = {
                "snapshot_id": args.snapshot_id,
                "destination": str(args.destination.resolve()),
                "byte_recovery_verified": True,
            }
        else:  # pragma: no cover
            raise ValueError(f"Unsupported command: {args.command}")
        print(render_json(result), end="")
        return 0
    except (FileNotFoundError, KeyError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
