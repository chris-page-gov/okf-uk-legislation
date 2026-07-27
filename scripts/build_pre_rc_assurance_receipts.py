#!/usr/bin/env python3
"""Build write-once pre-RC Explorer assurance receipts from external evidence.

The controller performs no network access and does not modify the frozen
checkout or the eligible clean-room reproduction.  It validates the exact
candidate, Explorer release, runtime, archive and observation-controller
bindings before copying the verified external evidence closure into a new
write-once directory and deriving the three receipts consumed by the release
finalizer.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import stat
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

import zstandard

import capture_github_pages_observation as pages_observation
import finalize_release_candidate as finalization


RUNTIME_FILENAME = "explorer-runtime-acceptance.json"
RELEASE_DIRECTORY = "release"
PAGES_DIRECTORY = "pages"
PAGES_SUPPORT_PATHS = (
    pages_observation.RUN_HEADERS_PATH,
    pages_observation.RUN_BODY_PATH,
    pages_observation.ARTIFACT_HEADERS_PATH,
    pages_observation.ARTIFACT_BODY_PATH,
    pages_observation.DOWNLOAD_HEADERS_PATH,
    pages_observation.ZIP_PATH,
    pages_observation.INVENTORY_PATH,
    pages_observation.ATTEMPT_MANIFEST_PATH,
)
PAGES_EVIDENCE_ROLES = {
    pages_observation.RUN_HEADERS_PATH: "run_response_headers",
    pages_observation.RUN_BODY_PATH: "run_response_body",
    pages_observation.ARTIFACT_HEADERS_PATH: "artifact_response_headers",
    pages_observation.ARTIFACT_BODY_PATH: "artifact_response_body",
    pages_observation.DOWNLOAD_HEADERS_PATH: "download_response_headers",
    pages_observation.ZIP_PATH: "pages_zip",
    pages_observation.INVENTORY_PATH: "tar_file_inventory",
}
OUTPUT_FILENAMES = {
    "explorer": finalization.CANONICAL_INPUT_NAMES["explorer"],
    "accessibility": finalization.CANONICAL_INPUT_NAMES["accessibility"],
    "performance": finalization.CANONICAL_INPUT_NAMES["performance"],
}
EXPECTED_BROWSERS = {"chrome", "firefox", "webkit"}
WCAG_STANDARD = "WCAG 2.2 AA"
MAX_RUNTIME_EVIDENCE_BYTES = 64 * 1024 * 1024
MAX_EXPLORER_BUILD_FILES = 4096
MAX_EXPLORER_BUILD_TOTAL_BYTES = 256 * 1024 * 1024
EXPLORER_BUILD_ROOT = "explorer-build"
EXPLORER_BUILD_MANIFEST_NAME = "okf-explorer-build-manifest.json"
EXPLORER_BUILD_MANIFEST_PATH = (
    f"{EXPLORER_BUILD_ROOT}/{EXPLORER_BUILD_MANIFEST_NAME}"
)
EXPLORER_BUILD_INDEX_PATH = f"{EXPLORER_BUILD_ROOT}/index.html"
EXPLORER_BUILD_ALGORITHM = "sha256-canonical-json-materials-v1"
EXPLORER_BUILD_MANIFEST_SCHEMA = "okf-explorer-app-build-manifest.v1"
EXPECTED_SCREENSHOT_PATHS = (
    "output/playwright/legislation-runtime-graph-chrome.png",
    "output/playwright/legislation-runtime-chrome.png",
)


def _safe_relative_path(value: str, label: str) -> str:
    path = PurePosixPath(value)
    try:
        utf16_code_units = len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError as exc:
        raise finalization.FinalizationError(
            f"{label} contains a surrogate code point"
        ) from exc
    if (
        not value
        or utf16_code_units > 4096
        or path.is_absolute()
        or "\\" in value
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in value
        )
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise finalization.FinalizationError(
            f"{label} is not a safe relative path: {value!r}"
        )
    return path.as_posix()


def _require_hex_sha256(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise finalization.FinalizationError(f"{label} is not a SHA-256 digest")
    return value


def _require_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise finalization.FinalizationError(f"{label} must be a non-empty string")
    return value


def _require_exact_keys(
    value: dict[str, Any],
    expected: set[str],
    label: str,
) -> None:
    finalization.require_equal(set(value), expected, f"{label} key set")


def _require_material_shape(value: Any, label: str) -> dict[str, Any]:
    row = finalization.require_object(value, label)
    _require_exact_keys(row, {"path", "bytes", "sha256"}, label)
    relative = _safe_relative_path(
        _require_nonempty_string(row.get("path"), f"{label} path"),
        f"{label} path",
    )
    size = row.get("bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise finalization.FinalizationError(
            f"{label} bytes must be a positive integer"
        )
    return {
        "path": relative,
        "bytes": size,
        "sha256": _require_hex_sha256(row.get("sha256"), f"{label} SHA-256"),
    }


def _require_pages_evidence_material(
    value: Any, label: str
) -> dict[str, Any]:
    row = finalization.require_object(value, label)
    _require_exact_keys(row, {"role", "path", "bytes", "sha256"}, label)
    material = _require_material_shape(
        {key: row[key] for key in ("path", "bytes", "sha256")},
        label,
    )
    finalization.require_equal(
        row.get("role"),
        PAGES_EVIDENCE_ROLES.get(str(material["path"])),
        f"{label} role",
    )
    return material


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
    ) or (isinstance(value, float) and math.isfinite(value))


def _canonical_explorer_build_materials_bytes(
    materials: list[dict[str, Any]],
) -> bytes:
    return (
        json.dumps(
            materials,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _render_explorer_build_manifest(
    *,
    file_count: int,
    tree_sha256: str,
    materials: list[dict[str, Any]],
) -> bytes:
    document = {
        "schema": EXPLORER_BUILD_MANIFEST_SCHEMA,
        "algorithm": EXPLORER_BUILD_ALGORITHM,
        "file_count": file_count,
        "tree_sha256": tree_sha256,
        "materials": materials,
    }
    return (
        json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def _parse_explorer_build_manifest(body: bytes) -> dict[str, Any]:
    label = "Explorer build manifest"
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise finalization.FinalizationError(
            f"{label} is not valid UTF-8 JSON: {exc}"
        ) from exc
    document = finalization.require_object(value, label)
    _require_exact_keys(
        document,
        {
            "schema",
            "algorithm",
            "file_count",
            "tree_sha256",
            "materials",
        },
        label,
    )
    finalization.require_equal(
        document.get("schema"),
        EXPLORER_BUILD_MANIFEST_SCHEMA,
        f"{label} schema",
    )
    finalization.require_equal(
        document.get("algorithm"),
        EXPLORER_BUILD_ALGORITHM,
        f"{label} algorithm",
    )
    file_count = document.get("file_count")
    if (
        not isinstance(file_count, int)
        or isinstance(file_count, bool)
        or file_count <= 0
        or file_count > MAX_EXPLORER_BUILD_FILES
    ):
        raise finalization.FinalizationError(
            f"{label} file_count is outside the permitted range"
        )
    tree_sha256 = _require_hex_sha256(
        document.get("tree_sha256"),
        f"{label} tree SHA-256",
    )
    values = finalization.require_array(
        document.get("materials"),
        f"{label} materials",
    )
    if len(values) != file_count:
        raise finalization.FinalizationError(
            f"{label} material count differs from file_count"
        )
    materials: list[dict[str, Any]] = []
    previous: str | None = None
    for index, value in enumerate(values):
        row = _require_material_shape(value, f"{label} material {index}")
        relative = str(row["path"])
        if relative == EXPLORER_BUILD_MANIFEST_NAME:
            raise finalization.FinalizationError(
                f"{label} must not include itself as a source material"
            )
        if previous is not None and relative <= previous:
            raise finalization.FinalizationError(
                f"{label} material paths are not strictly sorted and unique"
            )
        previous = relative
        materials.append(row)
    calculated_tree = finalization.sha256_bytes(
        _canonical_explorer_build_materials_bytes(materials)
    )
    finalization.require_equal(
        tree_sha256,
        calculated_tree,
        f"{label} canonical tree SHA-256",
    )
    canonical_body = _render_explorer_build_manifest(
        file_count=file_count,
        tree_sha256=tree_sha256,
        materials=materials,
    )
    finalization.require_equal(
        body,
        canonical_body,
        f"{label} canonical bytes",
    )
    return {
        "schema": EXPLORER_BUILD_MANIFEST_SCHEMA,
        "algorithm": EXPLORER_BUILD_ALGORITHM,
        "file_count": file_count,
        "tree_sha256": tree_sha256,
        "materials": materials,
    }


def _expected_explorer_build_directories(
    relative_files: set[str],
) -> set[str]:
    directories: set[str] = set()
    for relative in relative_files:
        parent = PurePosixPath(relative).parent
        while parent != PurePosixPath("."):
            directories.add(parent.as_posix())
            parent = parent.parent
    return directories


def _enumerate_explorer_build_subtree(
    base: Path,
) -> tuple[set[str], set[str]]:
    root = base / EXPLORER_BUILD_ROOT
    try:
        root_mode = root.lstat().st_mode
    except OSError as exc:
        raise finalization.FinalizationError(
            f"cannot inspect Explorer build evidence root {root}: {exc}"
        ) from exc
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        raise finalization.FinalizationError(
            f"Explorer build evidence root must be a real directory: {root}"
        )

    files: set[str] = set()
    directories: set[str] = set()

    def visit(directory: Path, relative_directory: PurePosixPath) -> None:
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda row: row.name)
        except OSError as exc:
            raise finalization.FinalizationError(
                f"cannot enumerate Explorer build evidence {directory}: {exc}"
            ) from exc
        for entry in entries:
            relative = (
                relative_directory / entry.name
                if relative_directory != PurePosixPath(".")
                else PurePosixPath(entry.name)
            )
            safe = _safe_relative_path(
                relative.as_posix(),
                "Explorer build evidence entry",
            )
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                raise finalization.FinalizationError(
                    f"cannot inspect Explorer build evidence entry "
                    f"{entry.path}: {exc}"
                ) from exc
            if stat.S_ISLNK(mode):
                raise finalization.FinalizationError(
                    "Explorer build evidence contains a symbolic link: "
                    f"{entry.path}"
                )
            if stat.S_ISDIR(mode):
                directories.add(safe)
                visit(Path(entry.path), PurePosixPath(safe))
            elif stat.S_ISREG(mode):
                if safe in files:
                    raise finalization.FinalizationError(
                        "Explorer build evidence file path is duplicated: "
                        f"{safe}"
                    )
                files.add(safe)
            else:
                raise finalization.FinalizationError(
                    "Explorer build evidence contains a non-regular entry: "
                    f"{entry.path}"
                )

    visit(root, PurePosixPath("."))
    return files, directories


def _read_runtime_evidence_file(
    *,
    base: Path,
    material: dict[str, Any],
    label: str,
) -> bytes:
    """Read one stable, singly-linked evidence file without following links."""

    relative = _safe_relative_path(str(material["path"]), f"{label} path")
    try:
        base_mode = base.lstat().st_mode
    except OSError as exc:
        raise finalization.FinalizationError(
            f"cannot inspect Explorer runtime evidence directory {base}: {exc}"
        ) from exc
    if stat.S_ISLNK(base_mode) or not stat.S_ISDIR(base_mode):
        raise finalization.FinalizationError(
            "Explorer runtime evidence directory must be a real directory: "
            f"{base}"
        )

    path = base
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        path /= part
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise finalization.FinalizationError(
                f"cannot inspect {label} path component {path}: {exc}"
            ) from exc
        if stat.S_ISLNK(mode):
            raise finalization.FinalizationError(
                f"{label} path contains a symbolic link component: {path}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            raise finalization.FinalizationError(
                f"{label} parent is not a directory: {path}"
            )

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise finalization.FinalizationError(
            f"cannot open {label} {path}: {exc}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise finalization.FinalizationError(
                f"{label} must be a regular file: {path}"
            )
        if before.st_nlink != 1:
            raise finalization.FinalizationError(
                f"{label} must not be hard-linked: {path}"
            )
        finalization.require_equal(
            before.st_size, material["bytes"], f"{label} declared byte count"
        )
        if before.st_size <= 0 or before.st_size > MAX_RUNTIME_EVIDENCE_BYTES:
            raise finalization.FinalizationError(
                f"{label} exceeds the runtime evidence size limit"
            )
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        body = b"".join(chunks)
        after = os.fstat(descriptor)
        identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
            before.st_nlink,
        )
        finalization.require_equal(
            (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
                after.st_nlink,
            ),
            identity,
            f"{label} stable file identity",
        )
        try:
            declared = path.lstat()
        except OSError as exc:
            raise finalization.FinalizationError(
                f"cannot restat {label} {path}: {exc}"
            ) from exc
        finalization.require_equal(
            (declared.st_dev, declared.st_ino, declared.st_nlink),
            (after.st_dev, after.st_ino, 1),
            f"{label} stable path identity",
        )
        finalization.require_equal(
            len(body), material["bytes"], f"{label} actual byte count"
        )
        finalization.require_equal(
            finalization.sha256_bytes(body),
            material["sha256"],
            f"{label} actual SHA-256",
        )
        return body
    finally:
        os.close(descriptor)


def _add_runtime_evidence_file(
    files: dict[str, bytes],
    relative: str,
    body: bytes,
    label: str,
) -> None:
    safe = _safe_relative_path(relative, f"{label} output path")
    if safe in files:
        raise finalization.FinalizationError(
            f"Explorer runtime evidence output path is duplicated: {safe}"
        )
    files[safe] = body


def _validate_explorer_build(
    *,
    explorer_build: dict[str, Any],
    contract_pages: dict[str, Any],
    runtime_path: Path,
    runtime_files: dict[str, bytes],
) -> dict[str, Any]:
    """Reconstruct and retain the complete staged Explorer application build."""

    _require_exact_keys(
        explorer_build,
        {
            "root",
            "manifest",
            "index",
            "files",
            "sha256",
            "algorithm",
            "materials",
        },
        "Explorer runtime Explorer build",
    )
    finalization.require_equal(
        explorer_build.get("root"),
        EXPLORER_BUILD_ROOT,
        "Explorer runtime Explorer build root",
    )
    contract_manifest = _require_material_shape(
        contract_pages.get("build_manifest"),
        "contract Explorer Pages build manifest",
    )
    finalization.require_equal(
        contract_manifest["path"],
        EXPLORER_BUILD_MANIFEST_PATH,
        "contract Explorer Pages build manifest path",
    )
    contract_index = _require_material_shape(
        contract_pages.get("build_index"),
        "contract Explorer Pages build index",
    )
    finalization.require_equal(
        contract_index["path"],
        EXPLORER_BUILD_INDEX_PATH,
        "contract Explorer Pages build index path",
    )
    contract_tree = finalization.require_object(
        contract_pages.get("build_tree"),
        "contract Explorer Pages build tree",
    )
    _require_exact_keys(
        contract_tree,
        {"algorithm", "files", "sha256"},
        "contract Explorer Pages build tree",
    )
    finalization.require_equal(
        contract_tree.get("algorithm"),
        EXPLORER_BUILD_ALGORITHM,
        "contract Explorer Pages build-tree algorithm",
    )
    contract_files = contract_tree.get("files")
    if (
        not isinstance(contract_files, int)
        or isinstance(contract_files, bool)
        or contract_files <= 0
        or contract_files > MAX_EXPLORER_BUILD_FILES
    ):
        raise finalization.FinalizationError(
            "contract Explorer Pages build-tree file count is invalid"
        )
    contract_sha256 = _require_hex_sha256(
        contract_tree.get("sha256"),
        "contract Explorer Pages build-tree SHA-256",
    )

    manifest_material = _require_material_shape(
        explorer_build.get("manifest"),
        "Explorer runtime Explorer build manifest",
    )
    finalization.require_equal(
        manifest_material,
        contract_manifest,
        "contract-bound Explorer Pages build manifest",
    )
    manifest_body = _read_runtime_evidence_file(
        base=runtime_path.parent,
        material=manifest_material,
        label="Explorer runtime Explorer build manifest",
    )
    manifest = _parse_explorer_build_manifest(manifest_body)

    finalization.require_equal(
        explorer_build.get("algorithm"),
        manifest["algorithm"],
        "Explorer runtime Explorer build algorithm",
    )
    finalization.require_equal(
        explorer_build.get("algorithm"),
        EXPLORER_BUILD_ALGORITHM,
        "contract-bound Explorer build algorithm",
    )
    finalization.require_equal(
        explorer_build.get("files"),
        manifest["file_count"],
        "Explorer runtime Explorer build file count",
    )
    finalization.require_equal(
        explorer_build.get("files"),
        contract_files,
        "contract-bound Explorer Pages build file count",
    )
    finalization.require_equal(
        explorer_build.get("sha256"),
        manifest["tree_sha256"],
        "Explorer runtime Explorer build tree SHA-256",
    )
    finalization.require_equal(
        explorer_build.get("sha256"),
        contract_sha256,
        "contract-bound Explorer Pages build-tree SHA-256",
    )

    runtime_material_values = finalization.require_array(
        explorer_build.get("materials"),
        "Explorer runtime Explorer build materials",
    )
    runtime_materials = [
        _require_material_shape(
            value,
            f"Explorer runtime Explorer build material {index}",
        )
        for index, value in enumerate(runtime_material_values)
    ]
    expected_materials = [
        {
            **row,
            "path": f"{EXPLORER_BUILD_ROOT}/{row['path']}",
        }
        for row in manifest["materials"]
    ]
    finalization.require_equal(
        runtime_materials,
        expected_materials,
        "Explorer runtime Explorer build material closure",
    )

    index_rows = [
        row for row in runtime_materials if row["path"] == EXPLORER_BUILD_INDEX_PATH
    ]
    if len(index_rows) != 1:
        raise finalization.FinalizationError(
            "Explorer runtime Explorer build must contain exactly one index.html"
        )
    build_index = _require_material_shape(
        explorer_build.get("index"),
        "Explorer runtime Explorer build index",
    )
    finalization.require_equal(
        build_index,
        index_rows[0],
        "Explorer runtime Explorer build index material",
    )
    finalization.require_equal(
        build_index,
        contract_index,
        "contract-bound Explorer Pages build index",
    )

    expected_relative_files = {
        EXPLORER_BUILD_MANIFEST_NAME,
        *[str(row["path"]) for row in manifest["materials"]],
    }
    actual_files, actual_directories = _enumerate_explorer_build_subtree(
        runtime_path.parent
    )
    finalization.require_equal(
        actual_files,
        expected_relative_files,
        "Explorer build staged file set",
    )
    finalization.require_equal(
        actual_directories,
        _expected_explorer_build_directories(expected_relative_files),
        "Explorer build staged directory set",
    )

    _add_runtime_evidence_file(
        runtime_files,
        str(manifest_material["path"]),
        manifest_body,
        "Explorer runtime Explorer build manifest",
    )
    total_bytes = 0
    actual_source_materials: list[dict[str, Any]] = []
    for index, material in enumerate(runtime_materials):
        body = _read_runtime_evidence_file(
            base=runtime_path.parent,
            material=material,
            label=f"Explorer runtime Explorer build material {index}",
        )
        total_bytes += len(body)
        if total_bytes > MAX_EXPLORER_BUILD_TOTAL_BYTES:
            raise finalization.FinalizationError(
                "Explorer build evidence exceeds the total byte limit"
            )
        actual_source_materials.append(
            {
                "path": PurePosixPath(str(material["path"])).relative_to(
                    EXPLORER_BUILD_ROOT
                ).as_posix(),
                "bytes": len(body),
                "sha256": finalization.sha256_bytes(body),
            }
        )
        _add_runtime_evidence_file(
            runtime_files,
            str(material["path"]),
            body,
            f"Explorer runtime Explorer build material {index}",
        )
    finalization.require_equal(
        actual_source_materials,
        manifest["materials"],
        "rehash-derived Explorer build material closure",
    )
    finalization.require_equal(
        finalization.sha256_bytes(
            _canonical_explorer_build_materials_bytes(
                actual_source_materials
            )
        ),
        contract_sha256,
        "rehash-derived Explorer build tree SHA-256",
    )
    second_files, second_directories = _enumerate_explorer_build_subtree(
        runtime_path.parent
    )
    finalization.require_equal(
        second_files,
        actual_files,
        "stable Explorer build staged file set",
    )
    finalization.require_equal(
        second_directories,
        actual_directories,
        "stable Explorer build staged directory set",
    )
    return {
        "manifest": manifest_material,
        "index": build_index,
        "files": contract_files,
        "sha256": contract_sha256,
        "algorithm": EXPLORER_BUILD_ALGORITHM,
        "materials": runtime_materials,
    }


def _validate_archive_members(archive_path: Path, archive_name: str) -> None:
    """Fail closed on every archive member, including unconsumed members."""

    prefix = archive_name.removesuffix(".tar.zst")
    if not prefix or f"{prefix}.tar.zst" != archive_name:
        raise finalization.FinalizationError(
            "sealed archive filename is not canonical .tar.zst"
        )
    seen: set[str] = set()
    try:
        with archive_path.open("rb") as compressed:
            with zstandard.ZstdDecompressor().stream_reader(compressed) as stream:
                with tarfile.open(fileobj=stream, mode="r|") as archive:
                    for member in archive:
                        relative = _safe_relative_path(
                            member.name, "sealed archive member"
                        )
                        parts = PurePosixPath(relative).parts
                        if not parts or parts[0] != prefix:
                            raise finalization.FinalizationError(
                                "sealed archive member is outside its canonical "
                                f"top-level directory: {member.name}"
                            )
                        if relative in seen:
                            raise finalization.FinalizationError(
                                f"sealed archive duplicates member {member.name}"
                            )
                        seen.add(relative)
                        if not member.isfile():
                            raise finalization.FinalizationError(
                                "sealed archive contains a non-regular member: "
                                f"{member.name}"
                            )
    except finalization.FinalizationError:
        raise
    except (OSError, tarfile.TarError, zstandard.ZstdError) as exc:
        raise finalization.FinalizationError(
            f"cannot inspect sealed release archive {archive_path}: {exc}"
        ) from exc


def _material_from_body(body: bytes, relative: str) -> dict[str, Any]:
    return {
        "path": relative,
        "bytes": len(body),
        "sha256": finalization.sha256_bytes(body),
    }


def _verify_reproduction(reproduction_dir: Path) -> dict[str, Any]:
    """Verify and return the frozen material used by the finalizer."""

    finalization.require_external(reproduction_dir, "reproduction evidence")
    finalization.require_directory(reproduction_dir, "reproduction evidence")
    contract_path = finalization.require_default_contract(
        finalization.DEFAULT_CONTRACT
    )
    contract = finalization.load_json(contract_path)
    finalization.require_equal(
        contract.get("schema"),
        "okf-external-finalization-contract.v3",
        "contract schema",
    )
    schemas = finalization.require_object(
        contract.get("input_schemas"), "contract input schemas"
    )
    candidate_contract = finalization.require_object(
        contract.get("candidate"), "contract candidate"
    )

    package_path = reproduction_dir / "release-package-manifest.json"
    reproduction_path = reproduction_dir / "reproduction-receipt.json"
    provenance_path = reproduction_dir / "provenance-inputs.json"
    package = finalization.load_json(
        finalization.require_regular_file(
            package_path, "release package manifest"
        )
    )
    reproduction = finalization.load_json(
        finalization.require_regular_file(
            reproduction_path, "reproduction receipt"
        )
    )
    provenance = finalization.load_json(
        finalization.require_regular_file(
            provenance_path, "provenance inputs"
        )
    )
    finalization.validate_schema(
        package,
        finalization.schema_path(
            contract_path, str(schemas["release_package_manifest"])
        ),
        "release package manifest",
    )
    finalization.validate_schema(
        reproduction,
        finalization.schema_path(
            contract_path, str(schemas["reproduction_receipt"])
        ),
        "reproduction receipt",
    )
    finalization.validate_schema(
        provenance,
        finalization.ROOT
        / "release-assurance"
        / "schemas"
        / "provenance-inputs.schema.json",
        "provenance inputs",
    )
    bindings = finalization.verify_finalization_bindings(
        provenance, contract_path, contract
    )

    commit = package.get("commit")
    tree = package.get("tree")
    for value, label in ((commit, "commit"), (tree, "tree")):
        if (
            not isinstance(value, str)
            or len(value) != 40
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise finalization.FinalizationError(
                f"release package manifest must bind the 40-hex Git {label}"
            )

    finalization.require_equal(
        reproduction.get("status"), "passed", "reproduction status"
    )
    reproduced_candidate = finalization.require_object(
        reproduction.get("candidate"), "reproduction candidate"
    )
    finalization.require_equal(
        reproduced_candidate.get("commit"), commit, "reproduction commit"
    )
    finalization.require_equal(
        reproduced_candidate.get("tree"), tree, "reproduction tree"
    )
    finalization.require_equal(provenance.get("commit"), commit, "provenance commit")
    finalization.require_equal(provenance.get("tree"), tree, "provenance tree")
    for key, expected in (
        ("exact_ref", True),
        ("declared_frozen", True),
        ("fixture", False),
    ):
        finalization.require_equal(
            reproduced_candidate.get(key),
            expected,
            f"reproduction candidate {key}",
        )

    comparison = finalization.require_object(
        reproduction.get("comparison"), "reproduction comparison"
    )
    finalization.require_equal(
        comparison.get("byte_identical"), True, "byte reproduction"
    )
    finalization.require_equal(
        comparison.get("semantic_identical"), True, "semantic reproduction"
    )
    publication = finalization.require_object(
        package.get("publication"), "package publication"
    )
    inventory = publication.get("inventory_sha256")
    if (
        not isinstance(inventory, str)
        or len(inventory) != 64
        or any(character not in "0123456789abcdef" for character in inventory)
    ):
        raise finalization.FinalizationError(
            "package inventory SHA-256 is invalid"
        )
    finalization.require_equal(
        comparison.get("candidate_inventory_sha256"),
        inventory,
        "candidate inventory",
    )
    finalization.require_equal(
        comparison.get("rebuilt_inventory_sha256"),
        inventory,
        "rebuilt inventory",
    )
    release_gate = finalization.require_object(
        reproduction.get("release_gate"), "reproduction release gate"
    )
    finalization.require_equal(
        release_gate.get("gate"), "GATE-06", "reproduction gate"
    )
    finalization.require_equal(
        release_gate.get("eligible"),
        True,
        "GATE-06 reproduction eligibility",
    )

    archive_name = finalization.require_object(
        contract.get("archive"), "contract archive"
    ).get("filename")
    if not isinstance(archive_name, str):
        raise finalization.FinalizationError(
            "contract archive filename is invalid"
        )
    archive_path = reproduction_dir / archive_name
    archive_material = finalization.material(archive_path, archive_name)
    package_archive = finalization.require_object(
        package.get("archive"), "package archive"
    )
    reproduced_archive = finalization.require_object(
        reproduction.get("archive"), "reproduction archive"
    )
    finalization.require_equal(
        package_archive.get("filename"), archive_name, "archive filename"
    )
    for key in ("bytes", "sha256"):
        finalization.require_equal(
            package_archive.get(key),
            archive_material[key],
            f"sealed archive {key}",
        )
        finalization.require_equal(
            reproduced_archive.get(key),
            archive_material[key],
            f"reproduction archive {key}",
        )

    promotion = finalization.require_object(
        package.get("promotion"), "package promotion"
    )
    for key, expected in (
        ("candidate_tag", candidate_contract["rc_tag"]),
        ("final_tag", candidate_contract["final_tag"]),
        ("asset_filename", archive_name),
        ("asset_name_preserved", True),
        ("archive_bytes_reused", True),
        ("rebuild_prohibited", True),
        ("rename_prohibited", True),
        ("promote_by_sha256", archive_material["sha256"]),
    ):
        finalization.require_equal(
            promotion.get(key), expected, f"promotion {key}"
        )

    outputs = finalization.require_object(
        reproduction.get("outputs"), "reproduction outputs"
    )
    finalization.require_equal(
        outputs.get("archive"), archive_name, "reproduction archive output"
    )
    for key, path in (
        ("release_package_manifest", package_path),
        ("provenance_inputs", provenance_path),
    ):
        declared = finalization.require_object(
            outputs.get(key), f"reproduction output {key}"
        )
        finalization.require_equal(
            declared.get("filename"),
            path.name,
            f"reproduction output {key} filename",
        )
        actual = finalization.material(path, path.name)
        for field in ("bytes", "sha256"):
            finalization.require_equal(
                declared.get(field),
                actual[field],
                f"reproduction output {key} {field}",
            )

    _validate_archive_members(archive_path, archive_name)
    embedded_documents, embedded_materials = (
        finalization.read_embedded_release_files(archive_path, archive_name)
    )
    traceability_contract = finalization.require_object(
        contract.get("traceability"), "contract traceability"
    )
    finalization.require_equal(
        embedded_materials["implementation_traceability"]["sha256"],
        _require_hex_sha256(
            traceability_contract.get("frozen_ledger_sha256"),
            "contract frozen traceability ledger SHA-256",
        ),
        "embedded frozen traceability ledger SHA-256",
    )
    finalization.verify_embedded_release_state(
        embedded_documents,
        embedded_materials,
        contract,
        archive_name,
    )
    finalization.require_equal(
        finalization.material(archive_path, archive_name),
        archive_material,
        "stable sealed archive identity",
    )
    return {
        "contract": contract,
        "contract_path": contract_path,
        "schemas": schemas,
        "commit": commit,
        "tree": tree,
        "inventory": inventory,
        "archive": archive_material,
        "release_observation_controller": bindings[
            "release_observation_controller"
        ],
        "pages_observation_controller": bindings[
            "pages_observation_controller"
        ],
        "pages_observation_schema": bindings[
            "pages_observation_schema"
        ],
    }


def _read_material_body(
    observation_path: Path,
    row: Any,
    label: str,
) -> tuple[str, bytes]:
    verified = finalization.verify_evidence_material(
        observation_path, row, label
    )
    relative = _safe_relative_path(str(verified["path"]), label)
    path = finalization.require_regular_file(
        observation_path.parent / relative, label
    )
    body = path.read_bytes()
    actual = _material_from_body(body, relative)
    for field in ("bytes", "sha256"):
        finalization.require_equal(
            actual[field],
            verified[field],
            f"{label} stable {field}",
        )
    return relative, body


def _observation_evidence_bodies(
    observation_path: Path,
    observation: dict[str, Any],
    observation_body: bytes,
) -> dict[str, bytes]:
    """Return the verified observation closure under its output subdirectory."""

    rows: list[tuple[Any, str]] = []
    release = finalization.require_object(
        observation.get("release"), "observed GitHub release"
    )
    rows.extend(
        [
            (release.get("response_headers"), "release response headers"),
            (release.get("response_body"), "release response body"),
        ]
    )
    tag_resolution = finalization.require_object(
        observation.get("tag_resolution"), "release tag resolution"
    )
    rows.append(
        (tag_resolution.get("response_headers"), "tag response headers")
    )
    rows.extend(
        (value, f"tag response body {index}")
        for index, value in enumerate(
            finalization.require_array(
                tag_resolution.get("response_bodies"), "tag response bodies"
            )
        )
    )
    integrity = finalization.require_object(
        observation.get("integrity"), "release observation integrity"
    )
    rows.append(
        (
            integrity.get("attempt_manifest"),
            "release observation attempt manifest",
        )
    )
    asset = observation.get("asset")
    if asset is not None:
        asset_row = finalization.require_object(
            asset, "observed release asset"
        )
        rows.extend(
            [
                (
                    asset_row.get("response_headers"),
                    "asset response headers",
                ),
                (asset_row.get("response_body"), "asset response body"),
            ]
        )

    result: dict[str, bytes] = {}
    observation_relative = (
        f"{RELEASE_DIRECTORY}/{observation_path.name}"
    )
    result[observation_relative] = observation_body
    for row, label in rows:
        source_relative, body = _read_material_body(
            observation_path, row, label
        )
        output_relative = f"{RELEASE_DIRECTORY}/{source_relative}"
        if output_relative in result:
            raise finalization.FinalizationError(
                "release observation evidence path is duplicated: "
                f"{source_relative}"
            )
        result[output_relative] = body
    return result


def _pages_profile(
    contract: dict[str, Any],
) -> pages_observation.TargetProfile:
    """Construct the controller target solely from the frozen contract."""

    declaration = finalization.require_object(
        contract.get("pages_observation"),
        "contract Pages observation",
    )
    target = finalization.require_object(
        declaration.get("target"), "contract Pages target"
    )
    archive = finalization.require_object(
        declaration.get("archive"), "contract Pages archive"
    )
    zip_row = _require_material_shape(
        archive.get("zip"), "contract Pages ZIP"
    )
    tar = finalization.require_object(
        archive.get("tar"), "contract Pages TAR"
    )
    census = finalization.require_object(
        tar.get("raw_header_census"),
        "contract Pages TAR raw-header census",
    )
    inventory = finalization.require_object(
        archive.get("inventory"), "contract Pages inventory"
    )
    build = finalization.require_object(
        archive.get("build"), "contract Pages build"
    )
    manifest = _require_material_shape(
        build.get("manifest"), "contract Pages build manifest"
    )
    index = _require_material_shape(
        build.get("index"), "contract Pages build index"
    )
    tree = finalization.require_object(
        build.get("tree"), "contract Pages build tree"
    )
    alternate = finalization.require_object(
        declaration.get("durable_alternate"),
        "contract Pages durable alternate",
    )
    repository = _require_nonempty_string(
        target.get("repository"), "contract Pages repository"
    )
    slug = repository.removeprefix("https://github.com/")
    if slug == repository or "/" not in slug:
        raise finalization.FinalizationError(
            "contract Pages repository is not a canonical GitHub URL"
        )
    return pages_observation.TargetProfile(
        repository=repository,
        slug=slug,
        run_id=target["run_id"],
        run_attempt=target["run_attempt"],
        head_sha=target["head_sha"],
        git_tree=target["git_tree"],
        workflow_path=target["workflow_path"],
        artifact_id=target["artifact_id"],
        artifact_name=target["artifact_name"],
        artifact_api_bytes=zip_row["bytes"],
        zip_bytes=zip_row["bytes"],
        zip_sha256=zip_row["sha256"],
        tar_name=tar["name"],
        tar_bytes=tar["bytes"],
        tar_sha256=tar["sha256"],
        tar_member_count=tar["member_count"],
        tar_file_count=tar["file_count"],
        tar_directory_count=tar["directory_count"],
        tar_total_file_bytes=tar["total_file_bytes"],
        tar_inventory_sha256=inventory["materials_sha256"],
        tar_raw_header_count=census["raw_headers"],
        tar_gnu_longname_count=census["gnu_longname_headers"],
        build_manifest_path=manifest["path"],
        build_manifest_bytes=manifest["bytes"],
        build_manifest_sha256=manifest["sha256"],
        build_file_count=tree["files"],
        build_tree_sha256=tree["sha256"],
        build_index_path=index["path"],
        build_index_bytes=index["bytes"],
        build_index_sha256=index["sha256"],
        alternate_asset_id=alternate["asset_id"],
        alternate_asset_name=alternate["name"],
        alternate_asset_url=alternate["url"],
    )


def _pages_evidence_bodies(
    *,
    pages_path: Path,
    context: dict[str, Any],
    runtime: dict[str, Any],
    release_observation: dict[str, Any],
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Reconstruct, cross-bind and retain the complete Pages closure."""

    contract = context["contract"]
    declaration = finalization.require_object(
        contract.get("pages_observation"),
        "contract Pages observation",
    )
    expected_name = _require_nonempty_string(
        declaration.get("output"), "contract Pages output"
    )
    finalization.require_external(pages_path, "Pages observation")
    finalization.require_filename(
        pages_path, expected_name, "Pages observation"
    )
    pages_path = finalization.require_regular_file(
        pages_path, "Pages observation"
    )
    profile = _pages_profile(contract)
    try:
        verified_path = pages_observation._verify_existing(
            pages_path.parent, profile
        )
    except pages_observation.CaptureError as exc:
        raise finalization.FinalizationError(
            f"Pages observation reconstruction failed: {exc}"
        ) from exc
    finalization.require_equal(
        verified_path.resolve(),
        pages_path.resolve(),
        "Pages observation reconstructed path",
    )
    document = finalization.load_json(pages_path)
    finalization.validate_schema(
        document,
        finalization.schema_path(
            context["contract_path"],
            str(context["schemas"]["github_pages_observation"]),
        ),
        "Pages observation",
    )
    finalization.require_equal(
        document.get("target"),
        declaration.get("target"),
        "Pages observation target",
    )
    finalization.require_equal(
        document.get("controller"),
        context["pages_observation_controller"],
        "Pages observation controller",
    )

    document_archive = finalization.require_object(
        document.get("archive"), "Pages observed archive"
    )
    archive_contract = finalization.require_object(
        declaration.get("archive"), "contract Pages archive"
    )
    zip_contract = _require_material_shape(
        archive_contract.get("zip"), "contract Pages ZIP"
    )
    zip_observed = finalization.require_object(
        finalization.require_object(
            document_archive.get("zip"), "Pages observed ZIP"
        ).get("material"),
        "Pages observed ZIP material",
    )
    finalization.require_equal(
        zip_observed, zip_contract, "Pages ZIP material"
    )
    finalization.require_equal(
        document_archive.get("tar"),
        archive_contract.get("tar"),
        "Pages TAR census",
    )
    inventory_observed = finalization.require_object(
        document_archive.get("inventory"),
        "Pages observed inventory",
    )
    inventory_contract = finalization.require_object(
        archive_contract.get("inventory"),
        "contract Pages inventory",
    )
    finalization.require_equal(
        {
            "path": inventory_observed["material"]["path"],
            "bytes": inventory_observed["material"]["bytes"],
            "sha256": inventory_observed["material"]["sha256"],
            "file_count": inventory_observed["file_count"],
            "total_file_bytes": inventory_observed["total_file_bytes"],
            "materials_sha256": inventory_observed["materials_sha256"],
        },
        inventory_contract,
        "Pages inventory",
    )
    build_observed = finalization.require_object(
        document_archive.get("build"), "Pages observed build"
    )
    build_contract = finalization.require_object(
        archive_contract.get("build"), "contract Pages build"
    )
    for key in ("manifest", "index", "tree"):
        finalization.require_equal(
            build_observed.get(key),
            build_contract.get(key),
            f"Pages build {key}",
        )
    not_found = _require_material_shape(
        build_contract.get("not_found"), "contract Pages 404"
    )
    build_materials = finalization.require_array(
        build_observed.get("materials"), "Pages build materials"
    )
    matches = [
        value
        for value in build_materials
        if isinstance(value, dict) and value.get("path") == not_found["path"]
    ]
    finalization.require_equal(
        matches, [not_found], "Pages build 404 material"
    )

    alternate = finalization.require_object(
        declaration.get("durable_alternate"),
        "contract Pages durable alternate",
    )
    finalization.require_equal(
        document.get("durable_alternate"),
        alternate,
        "Pages durable alternate",
    )
    release_asset = finalization.require_object(
        finalization.require_object(
            contract.get("explorer"), "contract Explorer"
        ).get("release_asset"),
        "contract Explorer release asset",
    )
    for key in ("asset_id", "name", "url", "bytes", "sha256"):
        finalization.require_equal(
            alternate.get(key),
            release_asset.get(key),
            f"Pages/release asset {key}",
        )
    observed_release_asset = finalization.require_object(
        release_observation.get("asset"),
        "verified Explorer release asset",
    )
    finalization.require_equal(
        observed_release_asset.get("asset_id"),
        alternate.get("asset_id"),
        "Pages/release observed asset ID",
    )
    for key in ("bytes", "sha256"):
        finalization.require_equal(
            observed_release_asset["material"].get(key),
            alternate.get(key),
            f"Pages/release observed asset {key}",
        )

    runtime_runner = finalization.require_object(
        runtime.get("runner"), "Explorer runtime runner"
    )
    runtime_provenance = finalization.require_object(
        finalization.require_object(
            contract.get("explorer"), "contract Explorer"
        ).get("runtime_provenance"),
        "contract Explorer runtime provenance",
    )
    finalization.require_equal(
        runtime_runner,
        runtime_provenance.get("runner"),
        "Pages-bound runtime runner",
    )
    runtime_inputs = finalization.require_object(
        runtime.get("inputs"), "Explorer runtime inputs"
    )
    runtime_build = finalization.require_object(
        runtime_inputs.get("explorer_build"),
        "Explorer runtime build",
    )
    finalization.require_equal(
        runtime_build.get("sha256"),
        build_observed["tree"]["sha256"],
        "Pages/runtime build tree",
    )
    finalization.require_equal(
        runtime_build.get("files"),
        build_observed["tree"]["files"],
        "Pages/runtime build file count",
    )
    for runtime_key, pages_key in (
        ("manifest", "manifest"),
        ("index", "index"),
    ):
        runtime_material = dict(runtime_build[runtime_key])
        runtime_material["path"] = str(runtime_material["path"]).removeprefix(
            f"{EXPLORER_BUILD_ROOT}/"
        )
        finalization.require_equal(
            runtime_material,
            build_observed[pages_key],
            f"Pages/runtime build {pages_key}",
        )

    files: dict[str, bytes] = {}
    for relative in (*PAGES_SUPPORT_PATHS, expected_name):
        maximum = (
            pages_observation.MAXIMUM_ZIP_BYTES
            if relative == pages_observation.ZIP_PATH
            else pages_observation.MAXIMUM_API_BODY_BYTES * 4
        )
        try:
            body = pages_observation.stable_read(
                pages_path.parent / relative,
                f"Pages evidence {relative}",
                maximum,
            )
        except pages_observation.CaptureError as exc:
            raise finalization.FinalizationError(
                f"cannot retain Pages evidence {relative}: {exc}"
            ) from exc
        files[f"{PAGES_DIRECTORY}/{relative}"] = body
    retained_observation_body = files[
        f"{PAGES_DIRECTORY}/{expected_name}"
    ]
    finalization.require_equal(
        finalization.parse_json_bytes(
            retained_observation_body, "retained Pages observation"
        ),
        document,
        "retained Pages observation document",
    )
    attempt_material = _require_material_shape(
        finalization.require_object(
            document.get("integrity"), "Pages observation integrity"
        ).get("attempt_manifest"),
        "Pages attempt material",
    )
    attempt_relative = str(attempt_material["path"])
    attempt_body = files[f"{PAGES_DIRECTORY}/{attempt_relative}"]
    finalization.require_equal(
        _material_from_body(attempt_body, attempt_relative),
        attempt_material,
        "retained Pages attempt material",
    )
    attempt = finalization.parse_json_bytes(
        attempt_body, "retained Pages attempt"
    )
    declared_support = {
        str(value["path"]): _require_pages_evidence_material(
            value, "Pages attempt evidence material"
        )
        for value in finalization.require_array(
            attempt.get("materials"), "Pages attempt evidence materials"
        )
    }
    finalization.require_equal(
        set(declared_support),
        set(PAGES_SUPPORT_PATHS) - {pages_observation.ATTEMPT_MANIFEST_PATH},
        "Pages attempt evidence path set",
    )
    for relative, declared in declared_support.items():
        finalization.require_equal(
            _material_from_body(
                files[f"{PAGES_DIRECTORY}/{relative}"], relative
            ),
            declared,
            f"retained Pages evidence {relative}",
        )
    try:
        pages_observation._verify_existing(pages_path.parent, profile)
    except pages_observation.CaptureError as exc:
        raise finalization.FinalizationError(
            f"Pages observation changed during retention: {exc}"
        ) from exc
    return files, document


def _validate_receipts(
    receipts: dict[str, dict[str, Any]],
    context: dict[str, Any],
) -> None:
    schemas = context["schemas"]
    contract_path = context["contract_path"]
    for key, schema_key, label in (
        (
            "explorer",
            "explorer_release_receipt",
            "Explorer release receipt",
        ),
        (
            "accessibility",
            "accessibility_assurance_receipt",
            "accessibility assurance receipt",
        ),
        (
            "performance",
            "performance_assurance_receipt",
            "performance assurance receipt",
        ),
    ):
        finalization.validate_schema(
            receipts[key],
            finalization.schema_path(contract_path, str(schemas[schema_key])),
            label,
        )


def _reject_nonfinite_numbers(value: Any, label: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise finalization.FinalizationError(
            f"{label} contains a non-finite numeric value"
        )
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_nonfinite_numbers(child, f"{label} {key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_nonfinite_numbers(child, f"{label} item {index}")


def _validate_runtime_evidence(
    runtime: dict[str, Any],
    *,
    runtime_path: Path,
    explorer_contract: dict[str, Any],
) -> dict[str, Any]:
    """Reconstruct the exact nested material closure omitted by the schema."""

    _reject_nonfinite_numbers(runtime, "Explorer runtime receipt")
    runtime_files: dict[str, bytes] = {}

    contract_provenance = finalization.require_object(
        explorer_contract.get("runtime_provenance"),
        "contract Explorer runtime provenance",
    )
    _require_exact_keys(
        contract_provenance,
        {"runner", "site_assembly", "pages"},
        "contract Explorer runtime provenance",
    )
    contract_runner = _require_material_shape(
        contract_provenance.get("runner"),
        "contract Explorer runtime runner",
    )
    site_assembly = finalization.require_object(
        contract_provenance.get("site_assembly"),
        "contract Explorer site assembly provenance",
    )
    _require_exact_keys(
        site_assembly,
        {"app_manifest_module", "assembler", "verifier"},
        "contract Explorer site assembly provenance",
    )
    for role in ("app_manifest_module", "assembler", "verifier"):
        _require_material_shape(
            site_assembly.get(role),
            f"contract Explorer site assembly {role}",
        )
    contract_pages = finalization.require_object(
        contract_provenance.get("pages"),
        "contract Explorer Pages provenance",
    )
    _require_exact_keys(
        contract_pages,
        {
            "workflow_path",
            "workflow_bytes",
            "workflow_sha256",
            "run_id",
            "run_attempt",
            "commit",
            "artifact_id",
            "artifact_name",
            "artifact_zip",
            "artifact_tar",
            "build_manifest",
            "build_index",
            "build_tree",
        },
        "contract Explorer Pages provenance",
    )
    workflow_path = _safe_relative_path(
        _require_nonempty_string(
            contract_pages.get("workflow_path"),
            "contract Explorer Pages workflow path",
        ),
        "contract Explorer Pages workflow path",
    )
    workflow_bytes = contract_pages.get("workflow_bytes")
    if (
        not isinstance(workflow_bytes, int)
        or isinstance(workflow_bytes, bool)
        or workflow_bytes <= 0
    ):
        raise finalization.FinalizationError(
            "contract Explorer Pages workflow byte count is invalid"
        )
    _require_hex_sha256(
        contract_pages.get("workflow_sha256"),
        "contract Explorer Pages workflow SHA-256",
    )
    for key, label in (
        ("run_id", "run ID"),
        ("run_attempt", "run attempt"),
        ("artifact_id", "artifact ID"),
    ):
        value = contract_pages.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise finalization.FinalizationError(
                f"contract Explorer Pages {label} is invalid"
            )
    _require_nonempty_string(
        contract_pages.get("artifact_name"),
        "contract Explorer Pages artifact name",
    )
    for key, label in (
        ("artifact_zip", "artifact ZIP"),
        ("artifact_tar", "artifact TAR"),
    ):
        artifact = finalization.require_object(
            contract_pages.get(key),
            f"contract Explorer Pages {label}",
        )
        _require_exact_keys(
            artifact,
            {"bytes", "sha256"},
            f"contract Explorer Pages {label}",
        )
        size = artifact.get("bytes")
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
        ):
            raise finalization.FinalizationError(
                f"contract Explorer Pages {label} byte count is invalid"
            )
        _require_hex_sha256(
            artifact.get("sha256"),
            f"contract Explorer Pages {label} SHA-256",
        )
    pages_commit = contract_pages.get("commit")
    finalization.require_equal(
        pages_commit,
        explorer_contract.get("required_commit"),
        "contract Explorer Pages commit",
    )
    finalization.require_equal(
        contract_pages.get("run_id"),
        explorer_contract.get("pages_workflow_run_id"),
        "contract Explorer Pages workflow run ID",
    )
    finalization.require_equal(
        PurePosixPath(workflow_path).name,
        explorer_contract.get("pages_workflow"),
        "contract Explorer Pages workflow filename",
    )
    runner = finalization.require_object(
        runtime.get("runner"), "Explorer runtime runner"
    )
    runner_material = _require_material_shape(
        {
            key: runner.get(key)
            for key in ("path", "bytes", "sha256")
        },
        "Explorer runtime runner",
    )
    if not str(runner_material["path"]).endswith(".mjs"):
        raise finalization.FinalizationError(
            "Explorer runtime runner path must identify an .mjs controller"
        )
    finalization.require_equal(
        runner_material,
        contract_runner,
        "contract-bound Explorer runtime runner",
    )
    _add_runtime_evidence_file(
        runtime_files,
        str(runner_material["path"]),
        _read_runtime_evidence_file(
            base=runtime_path.parent,
            material=runner_material,
            label="Explorer runtime runner",
        ),
        "Explorer runtime runner",
    )

    inputs = finalization.require_object(
        runtime.get("inputs"), "Explorer runtime inputs"
    )
    _require_exact_keys(
        inputs,
        {
            "bundle_root",
            "federation_descriptor",
            "legislation_descriptor",
            "explorer_build",
        },
        "Explorer runtime inputs",
    )
    bundle_root = _require_nonempty_string(
        inputs.get("bundle_root"), "Explorer runtime bundle root"
    )
    bundle_root = _safe_relative_path(
        bundle_root, "Explorer runtime bundle root"
    )
    if PurePosixPath(bundle_root).name != "bundle":
        raise finalization.FinalizationError(
            "Explorer runtime bundle root must identify the frozen bundle"
        )
    federation = _require_material_shape(
        inputs.get("federation_descriptor"),
        "Explorer runtime federation descriptor",
    )
    legislation = _require_material_shape(
        inputs.get("legislation_descriptor"),
        "Explorer runtime legislation descriptor",
    )
    for material, label in (
        (federation, "Explorer runtime federation descriptor"),
        (legislation, "Explorer runtime legislation descriptor"),
    ):
        relative = _safe_relative_path(
            f"{bundle_root}/{material['path']}", f"{label} resolved path"
        )
        resolved_material = {**material, "path": relative}
        _add_runtime_evidence_file(
            runtime_files,
            relative,
            _read_runtime_evidence_file(
                base=runtime_path.parent,
                material=resolved_material,
                label=label,
            ),
            label,
        )
    explorer_build = finalization.require_object(
        inputs.get("explorer_build"), "Explorer runtime Explorer build"
    )
    verified_build = _validate_explorer_build(
        explorer_build=explorer_build,
        contract_pages=contract_pages,
        runtime_path=runtime_path,
        runtime_files=runtime_files,
    )
    build_index = verified_build["index"]
    build_files = verified_build["files"]
    build_sha256 = verified_build["sha256"]

    outputs = finalization.require_object(
        runtime.get("outputs"), "Explorer runtime outputs"
    )
    _require_exact_keys(
        outputs, {"receipt", "screenshots"}, "Explorer runtime outputs"
    )
    receipt_path = _require_nonempty_string(
        outputs.get("receipt"), "Explorer runtime output receipt"
    )
    if receipt_path != RUNTIME_FILENAME:
        raise finalization.FinalizationError(
            f"Explorer runtime output receipt must be {RUNTIME_FILENAME}"
        )
    screenshot_values = finalization.require_array(
        outputs.get("screenshots"), "Explorer runtime screenshots"
    )
    if len(screenshot_values) != len(EXPECTED_SCREENSHOT_PATHS):
        raise finalization.FinalizationError(
            "Explorer runtime screenshots must contain exactly the two "
            "canonical captures"
        )
    screenshots: list[dict[str, Any]] = []
    screenshot_paths: set[str] = set()
    for index, (value, expected_path) in enumerate(
        zip(
            screenshot_values,
            EXPECTED_SCREENSHOT_PATHS,
            strict=True,
        )
    ):
        screenshot = _require_material_shape(
            value, f"Explorer runtime screenshot {index}"
        )
        finalization.require_equal(
            screenshot["path"],
            expected_path,
            f"Explorer runtime screenshot {index} canonical path",
        )
        if screenshot["path"] in screenshot_paths:
            raise finalization.FinalizationError(
                "Explorer runtime screenshot path is duplicated: "
                f"{screenshot['path']}"
            )
        screenshot_paths.add(str(screenshot["path"]))
        screenshots.append(screenshot)
        _add_runtime_evidence_file(
            runtime_files,
            str(screenshot["path"]),
            _read_runtime_evidence_file(
                base=runtime_path.parent,
                material=screenshot,
                label=f"Explorer runtime screenshot {index}",
            ),
            f"Explorer runtime screenshot {index}",
        )

    expected_checks: dict[str, dict[str, Any]] = {
        "federation_descriptor": {
            "id": "federation_descriptor",
            "status": "passed",
            **federation,
        },
        "legislation_descriptor": {
            "id": "legislation_descriptor",
            "status": "passed",
            **legislation,
        },
        "explorer_build_manifest": {
            "id": "explorer_build_manifest",
            "status": "passed",
            **verified_build["manifest"],
        },
        "explorer_build_materials": {
            "id": "explorer_build_materials",
            "status": "passed",
            "files": len(verified_build["materials"]),
        },
        "explorer_build_index": {
            "id": "explorer_build_index",
            "status": "passed",
            "sha256": build_index["sha256"],
        },
        "explorer_build_tree": {
            "id": "explorer_build_tree",
            "status": "passed",
            "algorithm": verified_build["algorithm"],
            "files": build_files,
            "sha256": build_sha256,
            "computed_sha256": build_sha256,
        },
    }
    for screenshot in screenshots:
        check_id = f"screenshot:{screenshot['path']}"
        expected_checks[check_id] = {
            "id": check_id,
            "status": "passed",
            **screenshot,
        }

    integrity = finalization.require_object(
        runtime.get("integrity"), "Explorer runtime integrity"
    )
    _require_exact_keys(
        integrity, {"status", "summary", "checks"}, "Explorer runtime integrity"
    )
    checks = finalization.require_array(
        integrity.get("checks"), "Explorer runtime integrity checks"
    )
    actual_checks: dict[str, dict[str, Any]] = {}
    for value in checks:
        row = finalization.require_object(
            value, "Explorer runtime integrity check"
        )
        check_id = row.get("id")
        if (
            not isinstance(check_id, str)
            or not check_id
            or check_id in actual_checks
        ):
            raise finalization.FinalizationError(
                "Explorer runtime integrity check id is invalid or duplicated"
            )
        actual_checks[check_id] = row
    finalization.require_equal(
        set(actual_checks),
        set(expected_checks),
        "Explorer runtime integrity check ID set",
    )
    finalization.require_equal(
        [str(value.get("id")) for value in checks],
        list(expected_checks),
        "Explorer runtime integrity check order",
    )
    for check_id, expected in expected_checks.items():
        finalization.require_equal(
            actual_checks[check_id],
            expected,
            f"Explorer runtime integrity check {check_id}",
        )
    summary = finalization.require_object(
        integrity.get("summary"), "Explorer runtime integrity summary"
    )
    for key in ("checks_total", "checks_passed"):
        finalization.require_equal(
            summary.get(key),
            len(expected_checks),
            f"Explorer runtime integrity summary {key}",
        )

    browser_values = finalization.require_array(
        runtime.get("browsers"), "Explorer runtime browser evidence"
    )
    browser_ids: set[str] = set()
    for value in browser_values:
        row = finalization.require_object(
            value, "Explorer runtime browser evidence row"
        )
        browser = row.get("browser")
        if not isinstance(browser, str) or browser in browser_ids:
            raise finalization.FinalizationError(
                "Explorer runtime browser evidence is invalid or duplicated"
            )
        browser_ids.add(browser)
    finalization.require_equal(
        browser_ids,
        EXPECTED_BROWSERS,
        "Explorer runtime browser evidence set",
    )

    gates = finalization.require_object(
        runtime.get("gates"), "Explorer runtime gates"
    )
    for gate_id in ("startup_transfer", "cold_search", "warm_search"):
        gate = finalization.require_object(
            gates.get(gate_id), f"Explorer runtime gate {gate_id}"
        )
        values = finalization.require_object(
            gate.get("browser_values"),
            f"Explorer runtime gate {gate_id} browser values",
        )
        for browser, value in values.items():
            if not _is_finite_number(value):
                raise finalization.FinalizationError(
                    f"Explorer {gate_id} {browser} browser metric is not finite"
                )
    accessibility_gate = finalization.require_object(
        gates.get("accessibility"), "Explorer accessibility gate"
    )
    wcag_standard = accessibility_gate.get("standard")
    finalization.require_equal(
        wcag_standard,
        WCAG_STANDARD,
        "Explorer accessibility evidenced WCAG standard",
    )
    return {
        "wcag_standard": str(wcag_standard),
        "files": runtime_files,
    }


def _build_expected_files(
    *,
    context: dict[str, Any],
    runtime_path: Path,
    observation_path: Path,
    pages_observation_path: Path,
) -> tuple[dict[str, bytes], dict[str, dict[str, Any]]]:
    contract = context["contract"]
    schemas = context["schemas"]
    explorer_contract = finalization.require_object(
        contract.get("explorer"), "contract Explorer"
    )
    observation_names = finalization.require_object(
        contract.get("release_observations"), "contract release observations"
    )

    finalization.require_external(runtime_path, "Explorer runtime receipt")
    finalization.require_filename(
        runtime_path, RUNTIME_FILENAME, "Explorer runtime receipt"
    )
    runtime_path = finalization.require_regular_file(
        runtime_path, "Explorer runtime receipt"
    )
    try:
        runtime_body = runtime_path.read_bytes()
    except OSError as exc:
        raise finalization.FinalizationError(
            f"cannot read Explorer runtime receipt {runtime_path}: {exc}"
        ) from exc
    runtime = finalization.parse_json_bytes(
        runtime_body, "Explorer runtime receipt"
    )
    finalization.validate_schema(
        runtime,
        finalization.schema_path(
            context["contract_path"],
            str(schemas["explorer_runtime_receipt"]),
        ),
        "Explorer runtime receipt",
    )
    runtime_evidence = _validate_runtime_evidence(
        runtime,
        runtime_path=runtime_path,
        explorer_contract=explorer_contract,
    )
    wcag_standard = runtime_evidence["wcag_standard"]
    runtime_explorer = finalization.require_object(
        runtime.get("explorer"), "Explorer runtime release"
    )
    explorer_commit = runtime_explorer.get("commit")
    if not isinstance(explorer_commit, str):
        raise finalization.FinalizationError("Explorer commit is invalid")
    required_explorer_commit = explorer_contract.get("required_commit")
    if (
        not isinstance(required_explorer_commit, str)
        or len(required_explorer_commit) != 40
        or any(
            character not in "0123456789abcdef"
            for character in required_explorer_commit
        )
    ):
        raise finalization.FinalizationError(
            "contract required Explorer commit is invalid"
        )
    finalization.require_equal(
        explorer_commit,
        required_explorer_commit,
        "Explorer runtime required commit",
    )
    runtime_outcome = finalization.reconstruct_explorer_runtime(
        runtime,
        contract=contract,
        commit=context["commit"],
        tree=context["tree"],
        inventory=context["inventory"],
        explorer_commit=explorer_commit,
    )

    expected_observation_name = str(observation_names["explorer"])
    finalization.require_external(
        observation_path, "Explorer release observation"
    )
    finalization.require_filename(
        observation_path,
        expected_observation_name,
        "Explorer release observation",
    )
    observation_path = finalization.require_regular_file(
        observation_path, "Explorer release observation"
    )
    verified_observation = finalization.verify_github_release_observation(
        observation_path=observation_path,
        contract=contract,
        release_observation_controller=context[
            "release_observation_controller"
        ],
        expected_repository=str(explorer_contract["repository"]),
        expected_tag=str(explorer_contract["required_tag"]),
        expected_commit=explorer_commit,
        expected_filename=expected_observation_name,
        expected_tag_object=str(explorer_contract["required_tag_object"]),
        expected_asset=finalization.require_object(
            explorer_contract.get("release_asset"),
            "contract Explorer release asset",
        ),
    )

    try:
        observation_body = observation_path.read_bytes()
    except OSError as exc:
        raise finalization.FinalizationError(
            f"cannot read Explorer release observation {observation_path}: {exc}"
        ) from exc
    finalization.require_equal(
        finalization.parse_json_bytes(
            observation_body, "Explorer release observation"
        ),
        verified_observation["document"],
        "stable Explorer release observation",
    )
    files = _observation_evidence_bodies(
        observation_path,
        verified_observation["document"],
        observation_body,
    )
    pages_files, _pages_document = _pages_evidence_bodies(
        pages_path=pages_observation_path,
        context=context,
        runtime=runtime,
        release_observation=verified_observation,
    )
    for relative, body in pages_files.items():
        _add_runtime_evidence_file(
            files,
            relative,
            body,
            "Pages observation evidence",
        )
    for relative, body in runtime_evidence["files"].items():
        _add_runtime_evidence_file(
            files,
            relative,
            body,
            "Explorer runtime evidence",
        )
    _add_runtime_evidence_file(
        files,
        RUNTIME_FILENAME,
        runtime_body,
        "Explorer runtime receipt",
    )
    runtime_material = _material_from_body(runtime_body, RUNTIME_FILENAME)
    observation_relative = (
        f"{RELEASE_DIRECTORY}/{expected_observation_name}"
    )
    observation_material = _material_from_body(
        files[observation_relative], observation_relative
    )
    pages_observation_relative = (
        f"{PAGES_DIRECTORY}/"
        f"{context['contract']['pages_observation']['output']}"
    )
    pages_observation_material = _material_from_body(
        files[pages_observation_relative],
        pages_observation_relative,
    )
    candidate = {
        "repository": contract["candidate"]["repository"],
        "commit": context["commit"],
        "tree": context["tree"],
        "bundle_tree_sha256": context["inventory"],
    }
    explorer = {
        "repository": explorer_contract["repository"],
        "tag": explorer_contract["required_tag"],
        "commit": explorer_commit,
    }
    runtime_evidence_materials = [
        _material_from_body(body, relative)
        for relative, body in sorted(runtime_evidence["files"].items())
    ]
    release_evidence_materials = [
        _material_from_body(body, relative)
        for relative, body in sorted(files.items())
        if relative.startswith(f"{RELEASE_DIRECTORY}/")
        and relative != observation_relative
    ]
    pages_evidence_materials = [
        _material_from_body(body, relative)
        for relative, body in sorted(files.items())
        if relative.startswith(f"{PAGES_DIRECTORY}/")
        and relative != pages_observation_relative
    ]
    explorer_receipt = {
        "schema": "okf-explorer-release-receipt.v3",
        "status": "published",
        "repository": explorer["repository"],
        "tag": explorer["tag"],
        "commit": explorer_commit,
        "release_url": (
            f"{explorer['repository']}/releases/tag/{explorer['tag']}"
        ),
        "materials": [
            {"role": "release_observation", **observation_material},
            {"role": "pages_observation", **pages_observation_material},
            {"role": "runtime", **runtime_material},
        ],
        "release_evidence": release_evidence_materials,
        "pages_evidence": pages_evidence_materials,
        "runtime_evidence": runtime_evidence_materials,
    }
    accessibility_receipt = {
        "schema": "okf-accessibility-assurance-receipt.v2",
        "status": "passed",
        "gate": "GATE-07",
        "candidate": candidate,
        "archive": context["archive"],
        "explorer": explorer,
        "browsers": runtime_outcome["browsers"],
        "keyboard_operable": runtime_outcome["keyboard_operable"],
        "wcag": {
            "standard": wcag_standard,
            "serious_violations": 0,
            "critical_violations": 0,
        },
        "materials": [{"role": "runtime", **runtime_material}],
        "assurance_boundary": (
            "Derived from the verified external Explorer runtime acceptance "
            "v2 receipt for the exact frozen candidate."
        ),
    }
    performance_receipt = {
        "schema": "okf-performance-assurance-receipt.v2",
        "status": "passed",
        "gate": "GATE-08",
        "candidate": candidate,
        "archive": context["archive"],
        "explorer": explorer,
        "measurements": runtime_outcome["measurements"],
        "materials": [{"role": "runtime", **runtime_material}],
        "assurance_boundary": (
            "Derived from the verified external Explorer runtime acceptance "
            "v2 receipt for the exact frozen candidate."
        ),
    }
    receipts = {
        "explorer": explorer_receipt,
        "accessibility": accessibility_receipt,
        "performance": performance_receipt,
    }
    _validate_receipts(receipts, context)
    for key, receipt in receipts.items():
        _add_runtime_evidence_file(
            files,
            OUTPUT_FILENAMES[key],
            finalization.render(receipt),
            f"{key} assurance receipt",
        )
    return files, receipts


def _expected_directories(files: dict[str, bytes]) -> set[str]:
    result: set[str] = set()
    for relative in files:
        parent = PurePosixPath(relative).parent
        while parent != PurePosixPath("."):
            result.add(parent.as_posix())
            parent = parent.parent
    return result


def _normalized_lexical_path(path: Path, label: str) -> Path:
    if ".." in path.parts:
        raise finalization.FinalizationError(
            f"{label} must not contain a parent-directory component: {path}"
        )
    return Path(os.path.abspath(finalization.lexical_absolute(path)))


def _output_safe_root(
    *,
    output_dir: Path,
    reproduction_dir: Path,
    runtime_path: Path,
    observation_path: Path,
    pages_observation_path: Path,
    declared_root: Path | None,
) -> tuple[Path, Path]:
    output = _normalized_lexical_path(
        output_dir, "pre-RC assurance output directory"
    )
    if declared_root is not None:
        root = _normalized_lexical_path(
            declared_root, "pre-RC assurance safe external root"
        )
    else:
        locations = [
            output,
            _normalized_lexical_path(
                reproduction_dir, "reproduction evidence"
            ),
            _normalized_lexical_path(
                runtime_path.parent, "runtime evidence directory"
            ),
            _normalized_lexical_path(
                observation_path.parent,
                "release-observation evidence directory",
            ),
            _normalized_lexical_path(
                pages_observation_path.parent,
                "Pages-observation evidence directory",
            ),
        ]
        try:
            root = Path(
                os.path.commonpath([os.fspath(path) for path in locations])
            )
        except ValueError as exc:
            raise finalization.FinalizationError(
                "cannot infer a common safe external root for pre-RC output"
            ) from exc
    try:
        output.relative_to(root)
    except ValueError as exc:
        raise finalization.FinalizationError(
            "pre-RC assurance output must be beneath its safe external root"
        ) from exc
    return root, output


def _reject_output_symlink_components(root: Path, output: Path) -> None:
    """Inspect each lexical component at and below the trusted root."""

    try:
        root_stat = root.lstat()
    except OSError as exc:
        raise finalization.FinalizationError(
            f"cannot inspect pre-RC assurance safe external root {root}: {exc}"
        ) from exc
    if stat.S_ISLNK(root_stat.st_mode):
        raise finalization.FinalizationError(
            "pre-RC assurance safe external root must not be a symbolic link: "
            f"{root}"
        )
    if not stat.S_ISDIR(root_stat.st_mode):
        raise finalization.FinalizationError(
            f"pre-RC assurance safe external root is not a directory: {root}"
        )
    current = root
    for part in output.relative_to(root).parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            break
        except OSError as exc:
            raise finalization.FinalizationError(
                "cannot inspect pre-RC assurance output path component "
                f"{current}: {exc}"
            ) from exc
        if stat.S_ISLNK(mode):
            raise finalization.FinalizationError(
                "pre-RC assurance output path contains a symbolic link "
                f"component: {current}"
            )


def _verify_existing_output(
    output_dir: Path, expected: dict[str, bytes]
) -> None:
    finalization.require_directory(
        output_dir, "pre-RC assurance output directory"
    )
    actual_files: dict[str, Path] = {}
    actual_directories: set[str] = set()
    try:
        for root, directories, filenames in os.walk(
            output_dir, topdown=True, followlinks=False
        ):
            root_path = Path(root)
            for name in directories:
                path = root_path / name
                if path.is_symlink():
                    raise finalization.FinalizationError(
                        "pre-RC assurance output contains a symbolic link: "
                        f"{path}"
                    )
                relative = path.relative_to(output_dir).as_posix()
                actual_directories.add(relative)
            for name in filenames:
                path = root_path / name
                file_stat = path.lstat()
                if not stat.S_ISREG(file_stat.st_mode):
                    raise finalization.FinalizationError(
                        "pre-RC assurance output contains a non-regular file: "
                        f"{path}"
                    )
                if file_stat.st_nlink != 1:
                    raise finalization.FinalizationError(
                        "pre-RC assurance output contains a hard-linked file: "
                        f"{path}"
                    )
                relative = path.relative_to(output_dir).as_posix()
                actual_files[relative] = path
    except OSError as exc:
        raise finalization.FinalizationError(
            f"cannot inspect pre-RC assurance output {output_dir}: {exc}"
        ) from exc

    if set(actual_files) != set(expected):
        raise finalization.FinalizationError(
            "refusing divergent pre-existing pre-RC assurance output file set"
        )
    if actual_directories != _expected_directories(expected):
        raise finalization.FinalizationError(
            "refusing divergent pre-existing pre-RC assurance output "
            "directory set"
        )
    for relative, body in expected.items():
        if actual_files[relative].read_bytes() != body:
            raise finalization.FinalizationError(
                "refusing to replace different immutable pre-RC assurance "
                f"output: {actual_files[relative]}"
            )


def _publish_new_directory(
    output_dir: Path,
    expected: dict[str, bytes],
    *,
    safe_root: Path,
) -> None:
    parent = output_dir.parent
    _reject_output_symlink_components(
        safe_root,
        _normalized_lexical_path(
            output_dir, "pre-RC assurance output directory"
        ),
    )
    finalization.reject_symlink_chain(
        parent, "pre-RC assurance output parent"
    )
    finalization.require_directory(
        parent, "pre-RC assurance output parent"
    )
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=parent)
    )
    try:
        for relative, body in sorted(expected.items()):
            safe_relative = _safe_relative_path(
                relative, "pre-RC assurance output path"
            )
            path = temporary / safe_relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
        try:
            os.rename(temporary, output_dir)
        except OSError:
            if output_dir.exists():
                _verify_existing_output(output_dir, expected)
                return
            raise
        temporary = Path()
    except finalization.FinalizationError:
        raise
    except OSError as exc:
        raise finalization.FinalizationError(
            f"cannot publish pre-RC assurance output {output_dir}: {exc}"
        ) from exc
    finally:
        if temporary != Path():
            shutil.rmtree(temporary, ignore_errors=True)


def build_pre_rc_assurance_receipts(
    *,
    reproduction_dir: Path,
    runtime_path: Path,
    explorer_observation_path: Path,
    pages_observation_path: Path,
    output_dir: Path,
    safe_external_root: Path | None = None,
) -> dict[str, Path]:
    """Validate evidence and create or idempotently verify the output."""

    output_root, lexical_output = _output_safe_root(
        output_dir=output_dir,
        reproduction_dir=reproduction_dir,
        runtime_path=runtime_path,
        observation_path=explorer_observation_path,
        pages_observation_path=pages_observation_path,
        declared_root=safe_external_root,
    )
    _reject_output_symlink_components(output_root, lexical_output)
    finalization.require_external(
        lexical_output, "pre-RC assurance output directory"
    )
    resolved_output = output_dir.resolve(strict=False)
    resolved_reproduction = reproduction_dir.resolve(strict=False)
    resolved_runtime_parent = runtime_path.parent.resolve(strict=False)
    resolved_observation_parent = explorer_observation_path.parent.resolve(
        strict=False
    )
    resolved_pages_observation_parent = (
        pages_observation_path.parent.resolve(strict=False)
    )
    for source, label in (
        (resolved_reproduction, "reproduction evidence"),
        (resolved_runtime_parent, "runtime evidence"),
        (resolved_observation_parent, "release-observation evidence"),
        (
            resolved_pages_observation_parent,
            "Pages-observation evidence",
        ),
    ):
        if resolved_output == source or resolved_output.is_relative_to(source):
            raise finalization.FinalizationError(
                "pre-RC assurance output must be a separate external "
                f"directory from {label}"
            )

    context = _verify_reproduction(reproduction_dir)
    expected, _ = _build_expected_files(
        context=context,
        runtime_path=runtime_path,
        observation_path=explorer_observation_path,
        pages_observation_path=pages_observation_path,
    )
    _reject_output_symlink_components(output_root, lexical_output)
    if output_dir.exists():
        _verify_existing_output(output_dir, expected)
    else:
        _publish_new_directory(
            output_dir,
            expected,
            safe_root=output_root,
        )
    return {
        key: output_dir / filename
        for key, filename in OUTPUT_FILENAMES.items()
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--reproduction-dir", type=Path, required=True)
    result.add_argument("--runtime", type=Path, required=True)
    result.add_argument("--explorer-observation", type=Path, required=True)
    result.add_argument("--pages-observation", type=Path, required=True)
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument("--safe-external-root", type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        receipts = build_pre_rc_assurance_receipts(
            reproduction_dir=args.reproduction_dir,
            runtime_path=args.runtime,
            explorer_observation_path=args.explorer_observation,
            pages_observation_path=args.pages_observation,
            output_dir=args.output_dir,
            safe_external_root=args.safe_external_root,
        )
        print(
            json.dumps(
                {
                    "output_dir": str(args.output_dir),
                    "receipts": {
                        key: str(path) for key, path in receipts.items()
                    },
                    "status": "passed",
                },
                sort_keys=True,
            )
        )
        return 0
    except (
        finalization.FinalizationError,
        KeyError,
        TypeError,
        ValueError,
        OSError,
    ) as exc:
        print(f"pre-RC assurance receipt build failed: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
