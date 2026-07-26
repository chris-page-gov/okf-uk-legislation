#!/usr/bin/env python3
"""Create and verify sealed source-access evidence archives.

Completed acquisition attempts are immutable evidence.  This module packages an
attempt as a deterministic XZ-compressed tar archive, verifies every extracted
file against the attempt's original integrity manifest, and creates a receipt
that binds the archive, original tree and any publication redaction.

The archive is intentionally distinct from the replaceable, metadata-only
publication projection.  Verification never extracts untrusted response bodies
to the working tree.  Explicit extraction requires a separate acknowledgement.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import lzma
import os
import re
import subprocess
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = (
    ROOT / "evidence" / "source-acquisitions" / "whole-law-access"
)
ARCHIVE_ROOT = EVIDENCE_ROOT / "archives"
RECEIPT_ROOT = EVIDENCE_ROOT / "archive-receipts"

ARCHIVE_SCHEMA = "okf-source-access-archive-receipt.v1"
INTEGRITY_SCHEMA = "okf-source-access-integrity.v1"
ARCHIVE_FORMAT = "application/x-xz; profile=application/x-tar"
RUN_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$")

# This recognises the credential-shaped lexical form reported by push
# protection.  Matched values are used transiently for validation only and are
# never printed or written to a receipt.
PUSH_PROTECTION_SHAPE = re.compile(rb"key-[A-Za-z0-9_-]{20,64}")

MAX_ARCHIVE_FILES = 1_000
MAX_ARCHIVE_FILE_BYTES = 8 * 1024 * 1024
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


def load_json_bytes(value: bytes, label: str) -> dict[str, Any]:
    try:
        result = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid JSON in archived {label}: {error}") from error
    if not isinstance(result, dict):
        raise ValueError(f"Archived {label} is not a JSON object")
    return result


def safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"Unsafe archive member path: {value!r}")
    return path


def tree_receipts(files: dict[str, bytes]) -> list[dict[str, Any]]:
    return [
        {
            "path": path,
            "bytes": len(body),
            "sha256": sha256_bytes(body),
        }
        for path, body in sorted(files.items())
    ]


def tree_digest(receipts: list[dict[str, Any]]) -> str:
    return sha256_bytes(canonical_json_bytes(receipts))


def git_snapshot(
    revision: str,
    run_tree_path: str,
) -> tuple[str, dict[str, bytes]]:
    """Read a run exactly from a Git object without checking it out."""

    full_revision = subprocess.check_output(
        ["git", "rev-parse", f"{revision}^{{commit}}"],
        cwd=ROOT,
        text=True,
    ).strip()
    listing = subprocess.check_output(
        [
            "git",
            "ls-tree",
            "-r",
            "-z",
            "--long",
            full_revision,
            run_tree_path,
        ],
        cwd=ROOT,
    )
    prefix = f"{run_tree_path.rstrip('/')}/"
    files: dict[str, bytes] = {}
    for raw_row in listing.split(b"\0"):
        if not raw_row:
            continue
        metadata, raw_path = raw_row.split(b"\t", 1)
        fields = metadata.decode("ascii").split()
        if len(fields) != 4 or fields[1] != "blob":
            raise ValueError("Git run tree contains a non-blob entry")
        path = raw_path.decode("utf-8")
        if not path.startswith(prefix):
            raise ValueError("Git returned a path outside the requested run")
        relative = safe_relative_path(path[len(prefix) :]).as_posix()
        body = subprocess.check_output(
            ["git", "cat-file", "blob", fields[2]],
            cwd=ROOT,
        )
        if len(body) != int(fields[3]):
            raise ValueError(f"Git blob size mismatch: {relative}")
        files[relative] = body
    if not files:
        raise ValueError("Git snapshot contains no run files")
    return full_revision, files


def directory_snapshot(run_dir: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(run_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlink is not allowed in evidence: {path}")
        if not path.is_file():
            continue
        relative = safe_relative_path(
            path.relative_to(run_dir).as_posix()
        ).as_posix()
        files[relative] = path.read_bytes()
    if not files:
        raise ValueError("Evidence directory contains no files")
    return files


def write_deterministic_archive(
    archive_path: Path,
    run_id: str,
    files: dict[str, bytes],
) -> None:
    """Write a byte-reproducible tar.xz with normalized metadata."""

    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError(f"Invalid evidence run ID: {run_id}")
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
                    info = tarfile.TarInfo(f"{run_id}/{relative}")
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
                    f"Immutable archive already exists with different bytes: "
                    f"{archive_path}"
                )
            temporary.unlink()
        else:
            os.replace(temporary, archive_path)
    finally:
        temporary.unlink(missing_ok=True)


def read_archive_files(
    archive_path: Path,
    *,
    expected_run_id: str,
) -> dict[str, bytes]:
    """Read a bounded archive without extracting it to disk."""

    prefix = f"{expected_run_id}/"
    files: dict[str, bytes] = {}
    total = 0
    try:
        archive = tarfile.open(archive_path, mode="r:xz")
    except (lzma.LZMAError, tarfile.TarError) as error:
        raise ValueError(f"Invalid source-access archive: {error}") from error
    with archive:
        for member in archive:
            if not member.isfile():
                raise ValueError(
                    f"Archive contains a non-regular member: {member.name}"
                )
            if not member.name.startswith(prefix):
                raise ValueError("Archive member is outside its run directory")
            relative = safe_relative_path(
                member.name[len(prefix) :]
            ).as_posix()
            if relative in files:
                raise ValueError(f"Duplicate archive member: {relative}")
            if member.size > MAX_ARCHIVE_FILE_BYTES:
                raise ValueError(f"Archive member exceeds size limit: {relative}")
            total += member.size
            if total > MAX_ARCHIVE_TOTAL_BYTES:
                raise ValueError("Archive exceeds uncompressed size limit")
            if len(files) >= MAX_ARCHIVE_FILES:
                raise ValueError("Archive exceeds file-count limit")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"Cannot read archive member: {relative}")
            body = extracted.read(MAX_ARCHIVE_FILE_BYTES + 1)
            if len(body) != member.size:
                raise ValueError(f"Archive member size mismatch: {relative}")
            files[relative] = body
    if not files:
        raise ValueError("Source-access archive is empty")
    return files


def validate_original_integrity(
    files: dict[str, bytes],
) -> dict[str, Any]:
    integrity_body = files.get("integrity.json")
    if integrity_body is None:
        raise ValueError("Archive has no original integrity.json")
    integrity = load_json_bytes(integrity_body, "integrity.json")
    if integrity.get("schema") != INTEGRITY_SCHEMA:
        raise ValueError("Unexpected original evidence integrity schema")
    declared = {
        row["path"]: row
        for row in integrity.get("files", [])
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    }
    actual = set(files) - {"integrity.json"}
    if set(declared) != actual:
        raise ValueError("Original integrity manifest file list is incomplete")
    for relative, row in declared.items():
        body = files[relative]
        if row.get("bytes") != len(body):
            raise ValueError(
                f"Original integrity byte count mismatch: {relative}"
            )
        if row.get("sha256") != sha256_bytes(body):
            raise ValueError(f"Original integrity hash mismatch: {relative}")
    if integrity.get("file_count") != len(actual):
        raise ValueError("Original integrity file count is inconsistent")
    if integrity.get("total_bytes") != sum(len(files[path]) for path in actual):
        raise ValueError("Original integrity total bytes are inconsistent")
    return integrity


def flagged_payload_validation(
    files: dict[str, bytes],
    archive_bytes: bytes,
    *,
    body_path: str,
    envelope_path: str,
) -> dict[str, Any]:
    body = files.get(body_path)
    envelope_body = files.get(envelope_path)
    if body is None or envelope_body is None:
        raise ValueError("Flagged public payload or envelope is absent")
    envelope = load_json_bytes(envelope_body, envelope_path)
    body_record = envelope["response"]["body"]
    if body_record.get("stored_path") != Path(body_path).name:
        raise ValueError("Original envelope no longer references its body")
    if body_record.get("captured_bytes") != len(body):
        raise ValueError("Original envelope body byte count is inconsistent")
    body_sha256 = sha256_bytes(body)
    if body_record.get("sha256") != body_sha256:
        raise ValueError("Original envelope body hash is inconsistent")
    matches = set(PUSH_PROTECTION_SHAPE.findall(body))
    if not matches:
        raise ValueError("Expected credential-shaped public identifiers absent")
    if any(value in archive_bytes for value in matches):
        raise ValueError(
            "Compressed archive blob exposes a detected plaintext sequence"
        )
    return {
        "bytes": len(body),
        "credential_shaped_public_identifier_count": len(matches),
        "path": body_path,
        "sha256": body_sha256,
        "compressed_blob_exposes_detected_plaintext": False,
    }


def build_archive_receipt(
    *,
    archive_path: Path,
    run_id: str,
    files: dict[str, bytes],
    archived_at: str,
    source_snapshot: dict[str, Any],
    flagged_body_path: str | None,
    flagged_envelope_path: str | None,
) -> dict[str, Any]:
    archive_bytes = archive_path.read_bytes()
    integrity = validate_original_integrity(files)
    receipts = tree_receipts(files)
    publication_trigger = None
    if flagged_body_path is not None or flagged_envelope_path is not None:
        if flagged_body_path is None or flagged_envelope_path is None:
            raise ValueError("Both flagged payload paths must be supplied")
        flagged = flagged_payload_validation(
            files,
            archive_bytes,
            body_path=flagged_body_path,
            envelope_path=flagged_envelope_path,
        )
        publication_trigger = {
            "classification": (
                "public-clml-identifiers-misclassified-as-credentials"
            ),
            "detector": "GitHub push protection",
            "payload": flagged,
            "values_recorded_in_receipt": False,
            "values_are_credentials": False,
        }
    integrity_body = files["integrity.json"]
    return {
        "schema": ARCHIVE_SCHEMA,
        "archived_at": archived_at,
        "run_id": run_id,
        "archive": {
            "path": archive_path.relative_to(ROOT).as_posix(),
            "media_type": ARCHIVE_FORMAT,
            "bytes": len(archive_bytes),
            "sha256": sha256_bytes(archive_bytes),
            "file_count": len(files),
            "uncompressed_file_bytes": sum(len(value) for value in files.values()),
            "tree_sha256": tree_digest(receipts),
            "normalized_tar_metadata": {
                "format": "ustar",
                "uid": 0,
                "gid": 0,
                "mode": "0644",
                "mtime": 0,
            },
            "safe_extraction_limits": {
                "max_files": MAX_ARCHIVE_FILES,
                "max_file_bytes": MAX_ARCHIVE_FILE_BYTES,
                "max_total_bytes": MAX_ARCHIVE_TOTAL_BYTES,
                "regular_files_only": True,
                "path_traversal_rejected": True,
            },
        },
        "source_snapshot": source_snapshot,
        "original_integrity": {
            "path": "integrity.json",
            "bytes": len(integrity_body),
            "sha256": sha256_bytes(integrity_body),
            "declared_file_count": integrity["file_count"],
            "declared_total_bytes": integrity["total_bytes"],
            "all_declared_files_verified": True,
        },
        "publication_trigger": publication_trigger,
        "assurance": {
            "byte_recovery": (
                "Every original run file is recoverable byte-for-byte after "
                "bounded safe extraction and is verified by SHA-256."
            ),
            "immutable_original": True,
            "publication_projection_is_original": False,
        },
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(render_json(receipt), encoding="utf-8")
        if path.exists():
            if path.read_bytes() != temporary.read_bytes():
                raise FileExistsError(
                    f"Immutable archive receipt already exists with different "
                    f"bytes: {path}"
                )
            temporary.unlink()
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def create_archive(
    *,
    run_id: str,
    files: dict[str, bytes],
    archive_path: Path,
    receipt_path: Path,
    archived_at: str,
    source_snapshot: dict[str, Any],
    flagged_body_path: str | None = None,
    flagged_envelope_path: str | None = None,
) -> dict[str, Any]:
    write_deterministic_archive(archive_path, run_id, files)
    receipt = build_archive_receipt(
        archive_path=archive_path,
        run_id=run_id,
        files=files,
        archived_at=archived_at,
        source_snapshot=source_snapshot,
        flagged_body_path=flagged_body_path,
        flagged_envelope_path=flagged_envelope_path,
    )
    write_receipt(receipt_path, receipt)
    validate_archive(archive_path, receipt_path)
    return receipt


def validate_archive(
    archive_path: Path,
    receipt_path: Path,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema") != ARCHIVE_SCHEMA:
        raise ValueError("Unexpected source-access archive receipt schema")
    run_id = receipt.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("Archive receipt has an invalid run ID")
    archive_record = receipt.get("archive", {})
    archive_bytes = archive_path.read_bytes()
    if archive_record.get("bytes") != len(archive_bytes):
        raise ValueError("Archive byte count does not match receipt")
    if archive_record.get("sha256") != sha256_bytes(archive_bytes):
        raise ValueError("Archive SHA-256 does not match receipt")
    files = read_archive_files(archive_path, expected_run_id=run_id)
    receipts = tree_receipts(files)
    if archive_record.get("file_count") != len(files):
        raise ValueError("Archive file count does not match receipt")
    if archive_record.get("uncompressed_file_bytes") != sum(
        len(value) for value in files.values()
    ):
        raise ValueError("Archive uncompressed byte count does not match receipt")
    if archive_record.get("tree_sha256") != tree_digest(receipts):
        raise ValueError("Archive extracted tree digest does not match receipt")
    integrity = validate_original_integrity(files)
    integrity_record = receipt.get("original_integrity", {})
    integrity_body = files["integrity.json"]
    if integrity_record.get("sha256") != sha256_bytes(integrity_body):
        raise ValueError("Original integrity manifest digest does not match")
    if integrity_record.get("declared_file_count") != integrity["file_count"]:
        raise ValueError("Original declared file count does not match receipt")
    if integrity_record.get("declared_total_bytes") != integrity["total_bytes"]:
        raise ValueError("Original declared byte count does not match receipt")
    trigger = receipt.get("publication_trigger")
    flagged = None
    if trigger is not None:
        payload_record = trigger.get("payload", {})
        flagged = flagged_payload_validation(
            files,
            archive_bytes,
            body_path=payload_record.get("path", ""),
            envelope_path=(
                f"methods/{Path(payload_record.get('path', '')).parent.name}/"
                "envelope.json"
            ),
        )
        if payload_record != flagged:
            raise ValueError(
                "Flagged public payload receipt does not match archive"
            )
    result = {
        "schema": "okf-source-access-archive-validation.v1",
        "run_id": run_id,
        "archive_sha256": archive_record["sha256"],
        "archive_bytes": archive_record["bytes"],
        "file_count": len(files),
        "uncompressed_file_bytes": archive_record["uncompressed_file_bytes"],
        "tree_sha256": archive_record["tree_sha256"],
        "original_integrity_sha256": integrity_record["sha256"],
        "original_integrity_file_count": integrity["file_count"],
        "original_integrity_total_bytes": integrity["total_bytes"],
        "flagged_public_payload_sha256": (
            flagged["sha256"] if flagged is not None else None
        ),
        "flagged_public_payload_bytes": (
            flagged["bytes"] if flagged is not None else None
        ),
        "byte_recovery_verified": True,
        "compressed_blob_plaintext_check_passed": True,
    }
    return result, files


def extract_archive(
    archive_path: Path,
    receipt_path: Path,
    destination: Path,
) -> None:
    validation, files = validate_archive(archive_path, receipt_path)
    run_dir = destination / validation["run_id"]
    run_dir.mkdir(parents=True, exist_ok=False)
    for relative, body in sorted(files.items()):
        target = run_dir.joinpath(*safe_relative_path(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(body)


def default_paths(run_id: str) -> tuple[Path, Path]:
    return (
        ARCHIVE_ROOT / f"{run_id}.tar.xz",
        RECEIPT_ROOT / f"{run_id}.json",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or verify sealed Whole-Law access evidence"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    from_git = subparsers.add_parser(
        "from-git",
        help="seal an exact run tree from a local Git object",
    )
    from_git.add_argument("--revision", required=True)
    from_git.add_argument("--run-id", required=True)
    from_git.add_argument("--archived-at", required=True)

    from_directory = subparsers.add_parser(
        "from-directory",
        help="seal a completed run directory",
    )
    from_directory.add_argument("--run-dir", type=Path, required=True)
    from_directory.add_argument("--archived-at", required=True)

    check = subparsers.add_parser("check", help="verify a sealed archive")
    check.add_argument("--run-id", required=True)

    extract = subparsers.add_parser(
        "extract",
        help="explicitly recover the verified original run",
    )
    extract.add_argument("--run-id", required=True)
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
        if args.command == "from-git":
            if not RUN_ID_RE.fullmatch(args.run_id):
                raise ValueError("Invalid --run-id")
            run_tree_path = (
                "evidence/source-acquisitions/whole-law-access/"
                f"{args.run_id}"
            )
            revision, files = git_snapshot(args.revision, run_tree_path)
            archive_path, receipt_path = default_paths(args.run_id)
            receipt = create_archive(
                run_id=args.run_id,
                files=files,
                archive_path=archive_path,
                receipt_path=receipt_path,
                archived_at=args.archived_at,
                source_snapshot={
                    "kind": "pre-publication-local-git-object",
                    "revision": revision,
                    "tree_path": run_tree_path,
                    "dependency_after_history_rewrite": False,
                },
                flagged_body_path="methods/SRC002-A01/body.bin",
                flagged_envelope_path="methods/SRC002-A01/envelope.json",
            )
            print(
                render_json(
                    {
                        "archive": receipt["archive"],
                        "receipt": receipt_path.relative_to(ROOT).as_posix(),
                    }
                ),
                end="",
            )
        elif args.command == "from-directory":
            run_dir = args.run_dir.resolve()
            run_id = run_dir.name
            if not RUN_ID_RE.fullmatch(run_id):
                raise ValueError("Run directory name is not a valid run ID")
            files = directory_snapshot(run_dir)
            archive_path, receipt_path = default_paths(run_id)
            receipt = create_archive(
                run_id=run_id,
                files=files,
                archive_path=archive_path,
                receipt_path=receipt_path,
                archived_at=args.archived_at,
                source_snapshot={
                    "kind": "completed-run-directory",
                    "tree_path": run_dir.relative_to(ROOT).as_posix(),
                    "dependency_after_archiving": False,
                },
                flagged_body_path="methods/SRC002-A01/body.bin",
                flagged_envelope_path="methods/SRC002-A01/envelope.json",
            )
            print(
                render_json(
                    {
                        "archive": receipt["archive"],
                        "receipt": receipt_path.relative_to(ROOT).as_posix(),
                    }
                ),
                end="",
            )
        elif args.command == "check":
            archive_path, receipt_path = default_paths(args.run_id)
            validation, _ = validate_archive(archive_path, receipt_path)
            print(render_json(validation), end="")
        elif args.command == "extract":
            if not args.acknowledge_untrusted_content:
                raise ValueError(
                    "Extraction requires --acknowledge-untrusted-content"
                )
            archive_path, receipt_path = default_paths(args.run_id)
            extract_archive(
                archive_path,
                receipt_path,
                args.destination.resolve(),
            )
            print(
                f"Verified original recovered beneath {args.destination}\n",
                end="",
            )
        else:  # pragma: no cover
            raise ValueError(f"Unsupported command: {args.command}")
    except (
        FileNotFoundError,
        KeyError,
        OSError,
        subprocess.CalledProcessError,
        ValueError,
    ) as error:
        print(f"ERROR: {error}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
