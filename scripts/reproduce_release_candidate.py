#!/usr/bin/env python3
"""Rebuild, compare and package an exact OKF release candidate.

The production path checks out a requested Git commit into a temporary detached
worktree, verifies the already-installed pinned dependencies, executes only the
profile's offline build/validation commands, compares every publication byte
and canonical semantic digest, and creates one deterministic ``tar.zst``.

Nothing is installed and no repository or release is mutated.  The receipt,
package manifest and provenance inputs are written outside the checkout so a
later promotion can attach the exact archive bytes without rebuilding.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from math import ceil
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

try:
    import jsonschema
    import rdflib
    import yaml_ld
    import zstandard
    from pyld import jsonld
    from yaml_ld.document_parsers.json_parser import JSONDocumentParser
    from yaml_ld.document_parsers.yaml_parser import YAMLDocumentParser
    from yaml_ld.expand import ExpandOptions
except ImportError as exc:  # pragma: no cover - dependency setup failure
    raise SystemExit(
        "Reproduction dependencies are unavailable. Install the exact versions "
        "in requirements-validation.txt before running; the reproduction tool "
        "never installs dependencies itself."
    ) from exc

import validation_dependency_lock as validation_lock


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "release-assurance" / "reproduction-profile.json"
CONTROLLER = Path(__file__).resolve()
VALIDATION_LOCK_PARSER_CONTROLLER = Path(
    validation_lock.__file__
).resolve()
CANONICAL_DIRECT_REQUIREMENTS = "requirements-validation.in"
CANONICAL_DEPENDENCY_LOCK = "requirements-validation.txt"
CANONICAL_DEPENDENCY_LOCK_PARSER = "scripts/validation_dependency_lock.py"
CANONICAL_BOOTSTRAP_DISTRIBUTION_ALLOWLIST = ("pip",)
CANONICAL_FINALIZATION_CONTROLLER = (
    "scripts/finalize_release_candidate.py"
)
CANONICAL_FINALIZATION_CONTRACT = (
    "release-assurance/external-finalization-contract.json"
)
CANONICAL_RELEASE_OBSERVATION_CONTROLLER = (
    "scripts/capture_github_release_observation.py"
)
CANONICAL_PAGES_OBSERVATION_CONTROLLER = (
    "scripts/capture_github_pages_observation.py"
)
CANONICAL_PAGES_OBSERVATION_SCHEMA = (
    "release-assurance/schemas/github-pages-observation.schema.json"
)
CANONICAL_ASSURANCE_RECEIPT_CONTROLLERS = (
    "scripts/build_pre_rc_assurance_receipts.py",
    "scripts/build_post_rc_assurance_receipts.py",
)
CANONICAL_DEPLOYED_MANIFEST_TEMPLATE = (
    "release-assurance/deployed-entrypoints-manifest.json"
)
CANONICAL_DEPLOYED_PROBE_CONTROLLER = (
    "scripts/probe_deployed_entrypoints.py"
)
CANONICAL_DEPLOYED_PROBE_CONTROLLER_VERSION = "1.0.0"
CANONICAL_OUTPUT_SCHEMAS = {
    "reproduction_receipt": (
        "release-assurance/schemas/reproduction-receipt.schema.json"
    ),
    "release_package_manifest": (
        "release-assurance/schemas/release-package-manifest.schema.json"
    ),
    "provenance_inputs": (
        "release-assurance/schemas/provenance-inputs.schema.json"
    ),
}
EXACT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
SAFE_REF = re.compile(r"^[A-Za-z0-9._/@+~-]{1,256}$")
DENIED_OFFLINE_SCRIPT_TOKENS = {
    "capture",
    "download",
    "fetch",
    "live",
    "probe",
    "refresh",
}
NETWORK_GUARD_BODY = """\
\"\"\"Process-local network guard for an OKF offline reproduction command.\"\"\"
import os as _os
import socket as _socket
import subprocess as _subprocess

_MESSAGE = "OKF reproduction network access is disabled"
_INET_FAMILIES = {_socket.AF_INET, _socket.AF_INET6}
_ORIGINAL_SOCKET = _socket.socket
_ORIGINAL_POPEN = _subprocess.Popen
_BLOCKED_PROGRAMS = {
    "curl", "ftp", "nc", "ncat", "netcat", "scp", "sftp", "ssh", "telnet", "wget"
}
_BLOCKED_GIT_SUBCOMMANDS = {
    "clone", "fetch", "ls-remote", "pull", "push", "remote", "submodule"
}


def _blocked(*_args, **_kwargs):
    raise RuntimeError(_MESSAGE)


class _OfflineSocket(_ORIGINAL_SOCKET):
    def _internet(self):
        return self.family in _INET_FAMILIES

    def connect(self, address):
        if self._internet():
            raise RuntimeError(_MESSAGE)
        return super().connect(address)

    def connect_ex(self, address):
        if self._internet():
            raise RuntimeError(_MESSAGE)
        return super().connect_ex(address)

    def bind(self, address):
        if self._internet():
            raise RuntimeError(_MESSAGE)
        return super().bind(address)

    def listen(self, backlog=0):
        if self._internet():
            raise RuntimeError(_MESSAGE)
        return super().listen(backlog)

    def sendto(self, *args):
        if self._internet():
            raise RuntimeError(_MESSAGE)
        return super().sendto(*args)


def _offline_popen(args, *pargs, **kwargs):
    if isinstance(args, (str, bytes)) or kwargs.get("shell"):
        raise RuntimeError(_MESSAGE)
    command = args if isinstance(args, (list, tuple)) else [args]
    executable = _os.path.basename(str(command[0])).lower() if command else ""
    if executable in _BLOCKED_PROGRAMS:
        raise RuntimeError(_MESSAGE)
    if executable == "git" and any(
        str(value) in _BLOCKED_GIT_SUBCOMMANDS for value in command[1:]
    ):
        raise RuntimeError(_MESSAGE)
    return _ORIGINAL_POPEN(args, *pargs, **kwargs)


_socket.socket = _OfflineSocket
_socket.create_connection = _blocked
_socket.getaddrinfo = _blocked
_socket.gethostbyaddr = _blocked
_socket.gethostbyname = _blocked
_socket.gethostbyname_ex = _blocked
_socket.getnameinfo = _blocked
_subprocess.Popen = _offline_popen
"""


class ReproductionError(RuntimeError):
    """A fail-closed reproduction or packaging error."""


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def render(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def material(path: Path, *, relative_to: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(relative_to).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def run(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    stdout: Any = subprocess.PIPE,
    stderr: Any = subprocess.PIPE,
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        check=False,
        stdout=stdout,
        stderr=stderr,
        text=stdout == subprocess.PIPE,
    )


def git(repo: Path, *args: str) -> str:
    result = run(["git", *args], cwd=repo)
    if result.returncode:
        raise ReproductionError(
            f"git {' '.join(args)} failed: "
            f"{str(result.stderr).strip()[:2000]}"
        )
    return str(result.stdout).strip()


def validate_ref(value: str) -> None:
    if (
        not SAFE_REF.fullmatch(value)
        or value.startswith("-")
        or ".." in value
        or "@{" in value
        or value.endswith(".lock")
    ):
        raise ReproductionError(f"unsafe or unsupported Git ref: {value!r}")


def safe_relative(value: str, *, label: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or path.as_posix() != value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ReproductionError(f"unsafe {label} path: {value!r}")
    return path


def json_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ReproductionError(f"invalid JSON Pointer: {pointer!r}")
    current = document
    for encoded in pointer[1:].split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif (
            isinstance(current, list)
            and token.isdigit()
            and int(token) < len(current)
        ):
            current = current[int(token)]
        else:
            raise ReproductionError(
                f"required receipt JSON Pointer does not resolve: {pointer}"
            )
    return current


def checkout_path(root: Path, relative: str, *, label: str) -> Path:
    pure = safe_relative(relative, label=label)
    path = root.joinpath(*pure.parts)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ReproductionError(f"{label} path escapes checkout: {relative}") from exc
    return path


def finalization_schema_declarations(
    contract: dict[str, Any],
) -> list[str]:
    """Return the exact, de-duplicated schema set declared by the finalizer."""

    if contract.get("schema") != "okf-external-finalization-contract.v3":
        raise ReproductionError(
            "finalization contract schema is not "
            "okf-external-finalization-contract.v3"
        )
    input_schemas = contract.get("input_schemas")
    if not isinstance(input_schemas, dict) or not input_schemas:
        raise ReproductionError(
            "finalization contract input_schemas must be a non-empty object"
        )

    declarations: list[str] = []
    for name, relative in input_schemas.items():
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(relative, str)
        ):
            raise ReproductionError(
                "finalization contract contains an invalid input schema"
            )
        declarations.append(
            safe_relative(
                relative,
                label=f"finalization input schema {name}",
            ).as_posix()
        )

    output_declarations: list[str] = []

    def collect_output_schemas(value: Any, location: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                child = f"{location}/{key}"
                if key == "output_schema":
                    if not isinstance(nested, str):
                        raise ReproductionError(
                            f"finalization contract {child} must be a path"
                        )
                    output_declarations.append(
                        safe_relative(
                            nested,
                            label=f"finalization output schema {child}",
                        ).as_posix()
                    )
                else:
                    collect_output_schemas(nested, child)
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                collect_output_schemas(nested, f"{location}/{index}")

    collect_output_schemas(contract, "")
    if not output_declarations:
        raise ReproductionError(
            "finalization contract declares no output schemas"
        )
    declarations.extend(output_declarations)
    return sorted(set(declarations))


def finalization_materials(
    checkout: Path,
    profile: dict[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
]:
    """Hash-bind every controller, the finalization contract and its schemas."""

    controller_path = checkout_path(
        checkout,
        profile["finalization_controller"],
        label="finalization controller",
    )
    observation_controller_path = checkout_path(
        checkout,
        profile["release_observation_controller"],
        label="release observation controller",
    )
    pages_observation_controller_path = checkout_path(
        checkout,
        profile["pages_observation_controller"],
        label="Pages observation controller",
    )
    pages_observation_schema_path = checkout_path(
        checkout,
        profile["pages_observation_schema"],
        label="Pages observation schema",
    )
    assurance_controller_paths = [
        checkout_path(
            checkout,
            relative,
            label="assurance receipt controller",
        )
        for relative in profile["assurance_receipt_controllers"]
    ]
    deployed_manifest_template_path = checkout_path(
        checkout,
        profile["deployed_manifest_template"],
        label="deployed manifest template",
    )
    deployed_probe_controller_path = checkout_path(
        checkout,
        profile["deployed_probe_controller"],
        label="deployed probe controller",
    )
    contract_path = checkout_path(
        checkout,
        profile["finalization_contract"],
        label="finalization contract",
    )
    for path, label in (
        (controller_path, "finalization controller"),
        (observation_controller_path, "release observation controller"),
        (pages_observation_controller_path, "Pages observation controller"),
        (pages_observation_schema_path, "Pages observation schema"),
        (contract_path, "finalization contract"),
        *(
            (path, "assurance receipt controller")
            for path in assurance_controller_paths
        ),
        (deployed_manifest_template_path, "deployed manifest template"),
        (deployed_probe_controller_path, "deployed probe controller"),
    ):
        if not path.is_file() or path.is_symlink():
            raise ReproductionError(
                f"{label} is missing or is not a regular file: "
                f"{path.relative_to(checkout)}"
            )
    try:
        contract = load(contract_path)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ReproductionError(
            "finalization contract is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(contract, dict):
        raise ReproductionError("finalization contract must be an object")
    release_observations = contract.get("release_observations")
    if not isinstance(release_observations, dict):
        raise ReproductionError(
            "finalization contract release_observations must be an object"
        )
    if (
        release_observations.get("controller")
        != profile["release_observation_controller"]
    ):
        raise ReproductionError(
            "finalization contract and reproduction profile disagree on the "
            "release observation controller"
        )
    pages_observation = contract.get("pages_observation")
    if not isinstance(pages_observation, dict):
        raise ReproductionError(
            "finalization contract pages_observation must be an object"
        )
    if (
        pages_observation.get("controller")
        != profile["pages_observation_controller"]
        or pages_observation.get("schema")
        != profile["pages_observation_schema"]
    ):
        raise ReproductionError(
            "finalization contract and reproduction profile disagree on the "
            "Pages observation controller or schema"
        )
    if (
        contract.get("assurance_receipt_controllers")
        != profile["assurance_receipt_controllers"]
    ):
        raise ReproductionError(
            "finalization contract and reproduction profile disagree on the "
            "assurance receipt controllers"
        )
    if (
        contract.get("deployed_manifest_template")
        != profile["deployed_manifest_template"]
    ):
        raise ReproductionError(
            "finalization contract and reproduction profile disagree on the "
            "deployed manifest template"
        )
    deployed_probe_contract = contract.get("deployed_probe_controller")
    if deployed_probe_contract != {
        "path": profile["deployed_probe_controller"],
        "version": CANONICAL_DEPLOYED_PROBE_CONTROLLER_VERSION,
    }:
        raise ReproductionError(
            "finalization contract and reproduction profile disagree on the "
            "deployed probe controller"
        )
    explorer = contract.get("explorer")
    if not isinstance(explorer, dict):
        raise ReproductionError(
            "finalization contract Explorer declaration must be an object"
        )
    explorer_runtime_provenance = explorer.get("runtime_provenance")
    if not isinstance(explorer_runtime_provenance, dict):
        raise ReproductionError(
            "finalization contract Explorer runtime provenance must be an object"
        )

    schemas: list[dict[str, Any]] = []
    for relative in finalization_schema_declarations(contract):
        path = checkout_path(
            checkout,
            relative,
            label="finalization schema",
        )
        if not path.is_file() or path.is_symlink():
            raise ReproductionError(
                f"finalization schema is missing or is not a regular file: "
                f"{relative}"
            )
        try:
            schema = load(path)
            jsonschema.Draft202012Validator.check_schema(schema)
        except (
            json.JSONDecodeError,
            UnicodeDecodeError,
            jsonschema.SchemaError,
        ) as exc:
            raise ReproductionError(
                f"invalid finalization schema: {relative}"
            ) from exc
        schemas.append(material(path, relative_to=checkout))
    if not schemas:
        raise ReproductionError(
            "finalization contract produced no schema materials"
        )
    return (
        material(controller_path, relative_to=checkout),
        material(observation_controller_path, relative_to=checkout),
        material(pages_observation_controller_path, relative_to=checkout),
        material(pages_observation_schema_path, relative_to=checkout),
        [
            material(path, relative_to=checkout)
            for path in assurance_controller_paths
        ],
        material(deployed_manifest_template_path, relative_to=checkout),
        material(deployed_probe_controller_path, relative_to=checkout),
        material(contract_path, relative_to=checkout),
        schemas,
        explorer_runtime_provenance,
    )


def parse_dependency_lock(
    lock_path: Path,
    direct_path: Path,
) -> validation_lock.ValidationDependencyLock:
    """Parse the complete hash lock with the repository's strict controller."""

    try:
        return validation_lock.load_validation_dependency_lock(
            lock_path,
            direct_path,
        )
    except validation_lock.DependencyLockError as exc:
        raise ReproductionError(
            f"validation dependency lock is invalid: {exc}"
        ) from exc


def dependency_lock_identity(
    dependency_lock: validation_lock.ValidationDependencyLock,
) -> dict[str, Any]:
    return {
        "package_count": len(dependency_lock.requirements),
        "direct_count": len(dependency_lock.direct_requirements),
        "transitive_count": len(dependency_lock.transitive_names),
        "artifact_hash_count": len(dependency_lock.artifact_hashes),
        "identity_sha256": dependency_lock.identity_digest,
        "artifact_hash_sha256": dependency_lock.artifact_hash_digest,
    }


def verify_environment(
    checkout: Path,
    profile: dict[str, Any],
) -> dict[str, Any]:
    python_pin = profile["python"]
    actual_python = {
        "major": sys.version_info.major,
        "minor": sys.version_info.minor,
        "micro": sys.version_info.micro,
    }
    if any(
        actual_python[component] != python_pin[component]
        for component in ("major", "minor", "micro")
    ):
        raise ReproductionError(
            "Python version differs from reproduction profile: "
            f"{actual_python['major']}.{actual_python['minor']}."
            f"{actual_python['micro']} != "
            f"{python_pin['major']}.{python_pin['minor']}."
            f"{python_pin['micro']}"
        )

    direct_path = checkout_path(
        checkout,
        profile["direct_requirements"],
        label="direct validation requirements",
    )
    lock_path = checkout_path(
        checkout,
        profile["dependency_lock"],
        label="dependency lock",
    )
    parser_path = checkout_path(
        checkout,
        profile["dependency_lock_parser"],
        label="dependency lock parser",
    )
    for path, label in (
        (direct_path, "direct validation requirements"),
        (lock_path, "dependency lock"),
        (parser_path, "dependency lock parser"),
    ):
        if not path.is_file() or path.is_symlink():
            raise ReproductionError(
                f"{label} is missing, not regular, or a symlink"
            )
    if parser_path.read_bytes() != VALIDATION_LOCK_PARSER_CONTROLLER.read_bytes():
        raise ReproductionError(
            "target dependency lock parser differs from the executing parser"
        )

    dependency_lock = parse_dependency_lock(lock_path, direct_path)
    identity = dependency_lock_identity(dependency_lock)
    if identity != profile["dependency_lock_identity"]:
        raise ReproductionError(
            "validation dependency lock identity differs from reproduction "
            "profile"
        )

    installed_versions = dict(
        validation_lock.installed_distribution_versions()
    )
    bootstrap_allowlist = profile["bootstrap_distribution_allowlist"]
    try:
        comparison = validation_lock.compare_installed_versions(
            dependency_lock,
            installed_versions,
            allow_extra=bootstrap_allowlist,
        )
    except validation_lock.DependencyLockError as exc:
        raise ReproductionError(
            f"installed distribution inventory is invalid: {exc}"
        ) from exc
    if comparison.missing:
        raise ReproductionError(
            "pinned dependencies are unavailable: "
            + ", ".join(comparison.missing)
        )
    if comparison.mismatched:
        raise ReproductionError(
            "pinned dependencies differ: "
            + ", ".join(
                f"{row.name} {row.actual} != {row.expected}"
                for row in comparison.mismatched
            )
        )
    if comparison.unexpected:
        raise ReproductionError(
            "undeclared installed distributions are forbidden: "
            + ", ".join(comparison.unexpected)
        )

    installed: list[dict[str, Any]] = []
    for requirement in dependency_lock.requirements:
        actual = installed_versions[requirement.name]
        installed.append(
            {
                "name": requirement.name,
                "required": requirement.version,
                "installed": actual,
                "matches": True,
            }
        )

    zstd_profile = profile["zstandard"]
    zstd_distribution = zstd_profile["distribution"]
    zstd_required = zstd_profile["version"]
    try:
        zstd_installed = importlib.metadata.version(zstd_distribution)
    except importlib.metadata.PackageNotFoundError as exc:
        raise ReproductionError(
            f"pinned Zstandard implementation is unavailable: "
            f"{zstd_distribution}=={zstd_required}"
        ) from exc
    if zstd_installed != zstd_required:
        raise ReproductionError(
            f"pinned Zstandard implementation differs: "
            f"{zstd_installed} != {zstd_required}"
        )
    if zstandard.__version__ != zstd_required:
        raise ReproductionError(
            "Zstandard module and distribution versions do not agree: "
            f"{zstandard.__version__} != {zstd_required}"
        )
    return {
        "python": actual_python,
        "python_executable": str(Path(sys.executable).resolve()),
        "dependencies": installed,
        "dependencies_exact": comparison.matches,
        "dependency_direct_requirements": material(
            direct_path,
            relative_to=checkout,
        ),
        "dependency_lock": material(lock_path, relative_to=checkout),
        "dependency_lock_identity": identity,
        "dependency_lock_parser": material(
            parser_path,
            relative_to=checkout,
        ),
        "bootstrap_distribution_allowlist": bootstrap_allowlist,
        "bootstrap_distributions_present": sorted(
            set(installed_versions) - set(dependency_lock.by_name)
        ),
        "zstandard": {
            "distribution": zstd_distribution,
            "version": zstd_installed,
            "module_version": zstandard.__version__,
            "level": zstd_profile["level"],
            "threads": zstd_profile["threads"],
        },
    }


def validate_profile(profile: dict[str, Any]) -> None:
    if profile.get("schema") != "okf-reproduction-profile.v2":
        raise ReproductionError("reproduction profile schema is not v2")
    for key, expected in (
        (
            "finalization_controller",
            CANONICAL_FINALIZATION_CONTROLLER,
        ),
        (
            "finalization_contract",
            CANONICAL_FINALIZATION_CONTRACT,
        ),
        (
            "release_observation_controller",
            CANONICAL_RELEASE_OBSERVATION_CONTROLLER,
        ),
        (
            "pages_observation_controller",
            CANONICAL_PAGES_OBSERVATION_CONTROLLER,
        ),
        (
            "pages_observation_schema",
            CANONICAL_PAGES_OBSERVATION_SCHEMA,
        ),
    ):
        declared = profile.get(key)
        if declared != expected:
            raise ReproductionError(
                f"{key} must use canonical path {expected!r}"
            )
        safe_relative(declared, label=key.replace("_", " "))
    assurance_controllers = profile.get("assurance_receipt_controllers")
    if assurance_controllers != list(CANONICAL_ASSURANCE_RECEIPT_CONTROLLERS):
        raise ReproductionError(
            "assurance_receipt_controllers must use the canonical ordered paths"
        )
    for declared in assurance_controllers:
        safe_relative(declared, label="assurance receipt controller")
    if (
        profile.get("deployed_manifest_template")
        != CANONICAL_DEPLOYED_MANIFEST_TEMPLATE
    ):
        raise ReproductionError(
            "deployed_manifest_template must use the canonical path"
        )
    safe_relative(
        profile["deployed_manifest_template"],
        label="deployed manifest template",
    )
    if (
        profile.get("deployed_probe_controller")
        != CANONICAL_DEPLOYED_PROBE_CONTROLLER
    ):
        raise ReproductionError(
            "deployed_probe_controller must use the canonical path"
        )
    safe_relative(
        profile["deployed_probe_controller"],
        label="deployed probe controller",
    )
    safe_relative(profile["publication_root"], label="publication root")
    for key, expected in (
        ("direct_requirements", CANONICAL_DIRECT_REQUIREMENTS),
        ("dependency_lock", CANONICAL_DEPENDENCY_LOCK),
        ("dependency_lock_parser", CANONICAL_DEPENDENCY_LOCK_PARSER),
    ):
        if profile.get(key) != expected:
            raise ReproductionError(
                f"{key} must use canonical path {expected!r}"
            )
        safe_relative(profile[key], label=key.replace("_", " "))
    if profile.get("bootstrap_distribution_allowlist") != list(
        CANONICAL_BOOTSTRAP_DISTRIBUTION_ALLOWLIST
    ):
        raise ReproductionError(
            "bootstrap_distribution_allowlist must equal the minimal "
            "canonical allowlist"
        )
    lock_identity = profile.get("dependency_lock_identity")
    expected_identity_keys = {
        "package_count",
        "direct_count",
        "transitive_count",
        "artifact_hash_count",
        "identity_sha256",
        "artifact_hash_sha256",
    }
    if (
        not isinstance(lock_identity, dict)
        or set(lock_identity) != expected_identity_keys
        or any(
            not isinstance(lock_identity[key], int)
            or lock_identity[key] <= 0
            for key in (
                "package_count",
                "direct_count",
                "transitive_count",
                "artifact_hash_count",
            )
        )
        or lock_identity["package_count"]
        != lock_identity["direct_count"] + lock_identity["transitive_count"]
        or lock_identity["artifact_hash_count"] < lock_identity["package_count"]
        or any(
            not isinstance(lock_identity[key], str)
            or re.fullmatch(r"[0-9a-f]{64}", lock_identity[key]) is None
            for key in ("identity_sha256", "artifact_hash_sha256")
        )
    ):
        raise ReproductionError(
            "dependency_lock_identity must be a complete canonical lock receipt"
        )
    if set(profile.get("python", {})) != {"major", "minor", "micro"}:
        raise ReproductionError(
            "Python profile must pin major, minor and micro exactly"
        )
    if any(
        not isinstance(profile["python"][component], int)
        or profile["python"][component] < 0
        for component in ("major", "minor", "micro")
    ):
        raise ReproductionError("Python version pins must be non-negative integers")
    if profile["zstandard"].get("threads") != 0:
        raise ReproductionError(
            "Zstandard must be pinned to single-threaded mode (threads=0)"
        )
    archive = profile["archive"]
    for key in (
        "max_files",
        "max_file_bytes",
        "max_total_file_bytes",
        "max_tar_bytes",
        "max_compression_ratio",
    ):
        if not isinstance(archive.get(key), int) or archive[key] <= 0:
            raise ReproductionError(f"archive limit {key} must be positive")
    safe_relative(archive["prefix"], label="archive prefix")
    if not archive["filename"].endswith(".tar.zst"):
        raise ReproductionError("release archive filename must end in .tar.zst")
    safe_relative(archive["filename"], label="archive filename")
    if archive["filename"] != f"{archive['prefix']}.tar.zst":
        raise ReproductionError(
            "release archive filename must equal archive prefix plus .tar.zst"
        )
    promotion = profile.get("promotion")
    if not isinstance(promotion, dict):
        raise ReproductionError("promotion contract is required")
    for key in ("candidate_tag", "final_tag"):
        value = promotion.get(key)
        if not isinstance(value, str):
            raise ReproductionError(f"promotion {key} must be a string")
        validate_ref(value)
    if promotion["candidate_tag"] == promotion["final_tag"]:
        raise ReproductionError("candidate and final release tags must differ")
    if promotion.get("asset_filename") != archive["filename"]:
        raise ReproductionError(
            "promotion asset filename must equal the deterministic archive filename"
        )
    for key in (
        "asset_name_preserved",
        "archive_bytes_reused",
        "rebuild_prohibited",
        "rename_prohibited",
    ):
        if promotion.get(key) is not True:
            raise ReproductionError(f"promotion {key} must be true")
    semantic_pairs = profile.get("semantic_pairs")
    if not isinstance(semantic_pairs, list) or not semantic_pairs:
        raise ReproductionError("semantic_pairs must be a non-empty array")
    semantic_ids: set[str] = set()
    for pair in semantic_pairs:
        if (
            not isinstance(pair, dict)
            or set(pair) - {"id", "yaml_ld", "json_ld", "turtle"}
            or not isinstance(pair.get("id"), str)
            or not pair["id"]
            or pair["id"] in semantic_ids
            or not isinstance(pair.get("yaml_ld"), str)
            or not pair["yaml_ld"]
            or not isinstance(pair.get("json_ld"), str)
            or not pair["json_ld"]
            or (
                "turtle" in pair
                and (
                    not isinstance(pair["turtle"], str)
                    or not pair["turtle"]
                )
            )
        ):
            raise ReproductionError("semantic pair declaration is invalid")
        semantic_ids.add(pair["id"])
        safe_relative(pair["yaml_ld"], label="semantic YAML-LD")
        safe_relative(pair["json_ld"], label="semantic JSON-LD")
        if "turtle" in pair:
            safe_relative(pair["turtle"], label="semantic Turtle")
        if pair["id"] == "whole-law" and pair.get("turtle") != (
            "bundle/whole-law/okf-bundle.ttl"
        ):
            raise ReproductionError(
                "Whole-Law semantic pair must bind canonical Turtle"
            )
        if pair["id"] == "uk-legislation" and "turtle" in pair:
            raise ReproductionError(
                "root UK Legislation semantic pair remains YAML-LD/JSON-LD"
            )
    context_urls: set[str] = set()
    for context in profile.get("offline_contexts", []):
        if (
            not isinstance(context, dict)
            or not isinstance(context.get("url"), str)
            or not context["url"].startswith("https://")
            or context["url"] in context_urls
            or not isinstance(context.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", context["sha256"])
        ):
            raise ReproductionError("invalid offline JSON-LD context declaration")
        context_urls.add(context["url"])
        safe_relative(context["path"], label="offline JSON-LD context")
    receipt_ids: set[str] = set()
    for receipt in profile.get("required_receipts", []):
        if (
            not isinstance(receipt, dict)
            or not isinstance(receipt.get("id"), str)
            or not receipt["id"]
            or receipt["id"] in receipt_ids
            or not isinstance(receipt.get("schema"), str)
            or not receipt["schema"]
            or not isinstance(receipt.get("assertions"), list)
            or not receipt["assertions"]
        ):
            raise ReproductionError("invalid required receipt declaration")
        receipt_ids.add(receipt["id"])
        safe_relative(receipt["path"], label="required receipt")
        for assertion in receipt["assertions"]:
            if (
                not isinstance(assertion, dict)
                or not isinstance(assertion.get("pointer"), str)
                or (("equals" in assertion) == ("equals_pointer" in assertion))
                or (
                    "equals_pointer" in assertion
                    and not isinstance(assertion["equals_pointer"], str)
                )
            ):
                raise ReproductionError(
                    f"invalid required receipt assertion: {assertion!r}"
                )
    offline_rows = profile.get("explicit_offline_invocations", [])
    if not isinstance(offline_rows, list):
        raise ReproductionError(
            "explicit_offline_invocations must be an array"
        )
    explicit_offline_invocations: set[tuple[str, tuple[str, ...]]] = set()
    for row in offline_rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("script"), str)
            or not isinstance(row.get("arguments"), list)
            or any(
                not isinstance(value, str) or not value
                for value in row.get("arguments", [])
            )
            or not isinstance(row.get("reason"), str)
            or not row["reason"].strip()
        ):
            raise ReproductionError(
                "invalid explicit offline invocation declaration"
            )
        script = safe_relative(
            row["script"],
            label="explicit offline script",
        )
        invocation = (script.as_posix(), tuple(row["arguments"]))
        if invocation in explicit_offline_invocations:
            raise ReproductionError(
                f"duplicate explicit offline invocation: {row!r}"
            )
        explicit_offline_invocations.add(invocation)
    used_offline_invocations: set[tuple[str, tuple[str, ...]]] = set()
    for category in ("build_commands", "validation_commands"):
        commands = profile.get(category)
        if not isinstance(commands, list) or not commands:
            raise ReproductionError(f"{category} must be a non-empty array")
        for command in commands:
            if (
                not isinstance(command, list)
                or len(command) < 2
                or command[0] != "{python}"
                or any(not isinstance(token, str) or not token for token in command)
            ):
                raise ReproductionError(
                    f"invalid non-shell command in {category}: {command!r}"
                )
            if command[1] == "-m":
                if len(command) < 3 or command[2] != "unittest":
                    raise ReproductionError(
                        f"only Python unittest is allowed via -m: {command!r}"
                    )
                continue
            script = safe_relative(command[1], label="build script")
            if script.parts[0] != "scripts" or script.suffix != ".py":
                raise ReproductionError(
                    f"command must execute a repository Python script: {command!r}"
                )
            lowered = script.name.lower()
            if any(token in lowered for token in DENIED_OFFLINE_SCRIPT_TOKENS):
                invocation = (script.as_posix(), tuple(command[2:]))
                if invocation not in explicit_offline_invocations:
                    raise ReproductionError(
                        "network-sensitive script invocation is not explicitly "
                        f"allowlisted as offline: {command!r}"
                    )
                used_offline_invocations.add(invocation)
            if (
                script.name == "build_legislation_effects.py"
                and category == "build_commands"
                and "--offline" not in command
            ):
                raise ReproductionError(
                    "effects rebuild must include the --offline guard"
                )
    if explicit_offline_invocations != used_offline_invocations:
        unused = sorted(explicit_offline_invocations - used_offline_invocations)
        raise ReproductionError(
            f"unused explicit offline invocation declarations: {unused}"
        )
    if profile.get("output_schemas") != CANONICAL_OUTPUT_SCHEMAS:
        raise ReproductionError(
            "output_schemas must equal the canonical reproduction schema set"
        )
    for path in profile["output_schemas"].values():
        safe_relative(path, label="output schema")
    network = profile["network_policy"]
    if (
        network.get("dependency_installation_during_run") is not False
        or network.get("build_commands_are_offline") is not True
        or network.get("credentials_inherited") is not False
        or network.get("python_socket_guard") is not True
        or network.get("network_cli_guard") is not True
    ):
        raise ReproductionError("reproduction network policy is not fail-closed")


def inventory_publication(
    publication_root: Path,
    limits: dict[str, int],
) -> dict[str, Any]:
    if not publication_root.is_dir() or publication_root.is_symlink():
        raise ReproductionError("publication root is missing or is a symlink")
    rows: list[dict[str, Any]] = []
    total_bytes = 0
    for path in sorted(publication_root.rglob("*")):
        if path.is_symlink():
            raise ReproductionError(
                f"publication contains a symlink: {path.relative_to(publication_root)}"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise ReproductionError(
                f"publication contains a non-regular file: "
                f"{path.relative_to(publication_root)}"
            )
        relative = path.relative_to(publication_root).as_posix()
        safe_relative(relative, label="publication member")
        size = path.stat().st_size
        if size > limits["max_file_bytes"]:
            raise ReproductionError(
                f"publication member exceeds byte limit: {relative} ({size})"
            )
        total_bytes += size
        if total_bytes > limits["max_total_file_bytes"]:
            raise ReproductionError("publication exceeds total uncompressed limit")
        rows.append(
            {
                "path": relative,
                "bytes": size,
                "sha256": sha256(path),
            }
        )
        if len(rows) > limits["max_files"]:
            raise ReproductionError("publication exceeds file-count limit")
    if not rows:
        raise ReproductionError("publication contains no files")
    return {
        "files": len(rows),
        "bytes": total_bytes,
        "inventory_sha256": sha256_bytes(canonical_bytes(rows)),
        "rows": rows,
    }


def semantic_digests(
    checkout: Path,
    pairs: Iterable[dict[str, str]],
    contexts: Iterable[dict[str, str]],
) -> list[dict[str, Any]]:
    context_documents: dict[str, dict[str, Any]] = {}
    context_materials: list[dict[str, Any]] = []
    for context in contexts:
        path = checkout_path(
            checkout,
            context["path"],
            label="offline JSON-LD context",
        )
        if sha256(path) != context["sha256"]:
            raise ReproductionError(
                f"offline JSON-LD context digest differs: {context['url']}"
            )
        document = load(path)
        if not isinstance(document, dict) or "@context" not in document:
            raise ReproductionError(
                f"offline JSON-LD context is invalid: {context['url']}"
            )
        context_documents[context["url"]] = document
        context_materials.append(
            {
                "url": context["url"],
                **material(path, relative_to=checkout),
            }
        )

    def offline_document_loader(
        url: str,
        _options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if url not in context_documents:
            raise ReproductionError(
                f"undeclared remote JSON-LD context requested offline: {url}"
            )
        return {
            "contentType": "application/ld+json",
            "contextUrl": None,
            "document": context_documents[url],
            "documentUrl": url,
        }

    expand_options = ExpandOptions(documentLoader=offline_document_loader)
    results: list[dict[str, Any]] = []
    for pair in pairs:
        yaml_path = checkout_path(
            checkout,
            pair["yaml_ld"],
            label=f"{pair['id']} YAML-LD",
        )
        json_path = checkout_path(
            checkout,
            pair["json_ld"],
            label=f"{pair['id']} JSON-LD",
        )
        yaml_document = YAMLDocumentParser()(
            io.BytesIO(yaml_path.read_bytes()),
            yaml_path.as_posix(),
            {},
        )
        json_document = JSONDocumentParser()(
            io.BytesIO(json_path.read_bytes()),
            json_path.as_posix(),
            {},
        )
        yaml_expanded = yaml_ld.expand(yaml_document, expand_options)
        json_expanded = yaml_ld.expand(json_document, expand_options)
        options = {
            "algorithm": "URDNA2015",
            "format": "application/n-quads",
        }
        yaml_canonical = jsonld.normalize(yaml_expanded, options)
        json_canonical = jsonld.normalize(json_expanded, options)
        if not yaml_canonical or yaml_canonical != json_canonical:
            raise ReproductionError(
                f"{pair['id']} YAML-LD and JSON-LD canonical graphs differ"
            )
        result = {
            "id": pair["id"],
            "yaml_ld": material(yaml_path, relative_to=checkout),
            "json_ld": material(json_path, relative_to=checkout),
            "canonical_nquads_sha256": sha256_bytes(
                yaml_canonical.encode("utf-8")
            ),
            "canonical_nquads_bytes": len(
                yaml_canonical.encode("utf-8")
            ),
            "canonical_nquads_statements": len(
                [
                    line
                    for line in yaml_canonical.splitlines()
                    if line.strip()
                ]
            ),
            "representations_equivalent": True,
        }
        turtle_relative = pair.get("turtle")
        if turtle_relative is not None:
            turtle_path = checkout_path(
                checkout,
                turtle_relative,
                label=f"{pair['id']} Turtle",
            )
            if not turtle_path.is_file() or turtle_path.is_symlink():
                raise ReproductionError(
                    f"{pair['id']} Turtle is missing, not regular, or a symlink"
                )
            turtle_body = turtle_path.read_bytes()
            try:
                turtle_graph = rdflib.Graph()
                turtle_graph.parse(
                    data=turtle_body.decode("utf-8"),
                    format="turtle",
                )
                # The publication contract requires the Turtle representation
                # to be the canonical default-graph N-Quads byte stream.  Do
                # not round-trip it through RDFLib before comparing semantics:
                # RDFLib is permitted to canonicalize literal lexical forms
                # while serializing (for example, xsd:dateTime ``Z`` becomes
                # ``+00:00``), which changes the RDF term even though the
                # original canonical stream is valid Turtle.  The parse above
                # still provides the independent Turtle syntax check; PyLD
                # consumes the original bytes for the graph comparison.
                turtle_document = jsonld.from_rdf(
                    turtle_body.decode("utf-8"),
                    {"format": "application/n-quads"},
                )
                turtle_canonical = jsonld.normalize(
                    turtle_document,
                    options,
                )
            except Exception as exc:
                raise ReproductionError(
                    f"{pair['id']} Turtle cannot be parsed as an RDF dataset"
                ) from exc
            if (
                not turtle_canonical
                or turtle_canonical != yaml_canonical
            ):
                raise ReproductionError(
                    f"{pair['id']} Turtle canonical graph differs from "
                    "YAML-LD and JSON-LD"
                )
            if turtle_body != turtle_canonical.encode("utf-8"):
                raise ReproductionError(
                    f"{pair['id']} Turtle is not the canonical dataset "
                    "serialization"
                )
            result["turtle"] = material(
                turtle_path,
                relative_to=checkout,
            )
        if context_materials:
            result["offline_contexts"] = context_materials
        results.append(result)
    return results


def verify_required_receipts(
    checkout: Path,
    declarations: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for declaration in declarations:
        path = checkout_path(
            checkout,
            declaration["path"],
            label=f"{declaration['id']} receipt",
        )
        try:
            document = load(path)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise ReproductionError(
                f"required receipt is missing or invalid: {declaration['id']}"
            ) from exc
        if (
            not isinstance(document, dict)
            or document.get("schema") != declaration["schema"]
        ):
            raise ReproductionError(
                f"required receipt schema differs: {declaration['id']}"
            )
        checks: list[dict[str, Any]] = []
        for assertion in declaration["assertions"]:
            actual = json_pointer(document, assertion["pointer"])
            if "equals_pointer" in assertion:
                expected = json_pointer(document, assertion["equals_pointer"])
                expectation: Any = {
                    "equals_pointer": assertion["equals_pointer"]
                }
            else:
                expected = assertion["equals"]
                expectation = {"equals": expected}
            if type(actual) is not type(expected) or actual != expected:
                raise ReproductionError(
                    f"required receipt assertion failed: "
                    f"{declaration['id']} {assertion['pointer']}"
                )
            checks.append(
                {
                    "pointer": assertion["pointer"],
                    **expectation,
                    "passed": True,
                }
            )
        receipts.append(
            {
                "id": declaration["id"],
                "schema": declaration["schema"],
                "material": material(path, relative_to=checkout),
                "assertions": checks,
                "status": "passed",
            }
        )
    return receipts


def normalized_environment(home: Path) -> dict[str, str]:
    home.mkdir(parents=True, exist_ok=True)
    temp = home / "tmp"
    cache = home / "cache"
    temp.mkdir()
    cache.mkdir()
    guard = home / "python-guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(
        NETWORK_GUARD_BODY,
        encoding="utf-8",
    )
    return {
        "ALL_PROXY": "http://127.0.0.1:9",
        "GIT_ASKPASS": "/usr/bin/false",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": str(home),
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "LANG": "C",
        "LC_ALL": "C",
        "NO_COLOR": "1",
        "NO_PROXY": "",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INDEX": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(guard),
        "PYTHONUTF8": "1",
        "SOURCE_DATE_EPOCH": "0",
        "SSH_ASKPASS": "/usr/bin/false",
        "TMPDIR": str(temp),
        "TZ": "UTC",
        "UV_CACHE_DIR": str(cache),
    }


def command_materials(
    checkout: Path,
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    paths: set[Path] = {
        checkout_path(
            checkout,
            profile["direct_requirements"],
            label="direct validation requirements",
        ),
        checkout_path(
            checkout,
            profile["dependency_lock_parser"],
            label="dependency lock parser",
        ),
    }
    for category in ("build_commands", "validation_commands"):
        for command in profile[category]:
            if command[1] == "-m":
                continue
            paths.add(
                checkout_path(
                    checkout,
                    command[1],
                    label="command script",
                )
            )
    return [
        material(path, relative_to=checkout)
        for path in sorted(paths)
    ]


def execute_commands(
    checkout: Path,
    output_dir: Path,
    profile: dict[str, Any],
    env: dict[str, str],
) -> list[dict[str, Any]]:
    logs = output_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    receipts: list[dict[str, Any]] = []
    command_number = 0
    for category in ("build_commands", "validation_commands"):
        for configured in profile[category]:
            command_number += 1
            argv = [
                str(Path(sys.executable).resolve())
                if token == "{python}"
                else token
                for token in configured
            ]
            log_path = logs / f"{command_number:02d}-{category[:-9]}.log"
            with log_path.open("wb") as log:
                result = run(
                    argv,
                    cwd=checkout,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            if log_path.stat().st_size > 16 * 1024 * 1024:
                raise ReproductionError(
                    f"command log exceeds 16 MiB: {' '.join(configured)}"
                )
            receipts.append(
                {
                    "index": command_number,
                    "category": category,
                    "argv": configured,
                    "exit_code": result.returncode,
                    "log": f"logs/{log_path.name}",
                    "log_identity_note": (
                        "Diagnostic output is retained but excluded from the "
                        "deterministic receipt identity because test runners "
                        "report wall-clock durations."
                    ),
                }
            )
            if result.returncode:
                tail = log_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )[-4000:]
                tail = tail.replace(str(checkout), "<CLEAN_CHECKOUT>")
                raise ReproductionError(
                    f"offline {category} command failed "
                    f"({result.returncode}): {' '.join(configured)}\n{tail}"
                )
    return receipts


def deterministic_tar(
    publication_root: Path,
    inventory: dict[str, Any],
    tar_path: Path,
    *,
    prefix: str,
    limits: dict[str, int],
) -> dict[str, Any]:
    with tarfile.open(tar_path, "w", format=tarfile.GNU_FORMAT) as archive:
        for row in inventory["rows"]:
            source = publication_root / row["path"]
            info = tarfile.TarInfo(
                name=f"{prefix}/bundle/{row['path']}"
            )
            info.size = row["bytes"]
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = "root"
            info.gname = "root"
            info.mtime = 0
            with source.open("rb") as handle:
                archive.addfile(info, handle)
    if tar_path.stat().st_size > limits["max_tar_bytes"]:
        raise ReproductionError("normalized tar exceeds configured byte limit")
    return {
        "bytes": tar_path.stat().st_size,
        "sha256": sha256(tar_path),
    }


def validate_tar(
    tar_path: Path,
    inventory: dict[str, Any],
    *,
    prefix: str,
    limits: dict[str, int],
) -> None:
    expected = {row["path"]: row for row in inventory["rows"]}
    seen: set[str] = set()
    total = 0
    with tarfile.open(tar_path, "r:") as archive:
        members = archive.getmembers()
        if len(members) > limits["max_files"]:
            raise ReproductionError("release tar exceeds member-count limit")
        for member in members:
            name = PurePosixPath(member.name)
            if (
                name.is_absolute()
                or any(part in {"", ".", ".."} for part in name.parts)
                or not member.isfile()
                or member.issym()
                or member.islnk()
                or member.isdev()
            ):
                raise ReproductionError(
                    f"unsafe release tar member: {member.name!r}"
                )
            required_prefix = PurePosixPath(prefix) / "bundle"
            try:
                relative = name.relative_to(required_prefix).as_posix()
            except ValueError as exc:
                raise ReproductionError(
                    f"release tar member is outside publication prefix: "
                    f"{member.name!r}"
                ) from exc
            if relative in seen or relative not in expected:
                raise ReproductionError(
                    f"unexpected or duplicate release tar member: {relative}"
                )
            if member.size > limits["max_file_bytes"]:
                raise ReproductionError(
                    f"release tar member exceeds byte limit: {relative}"
                )
            total += member.size
            if total > limits["max_total_file_bytes"]:
                raise ReproductionError(
                    "release tar exceeds total uncompressed limit"
                )
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ReproductionError(
                    f"release tar member cannot be read: {relative}"
                )
            digest = hashlib.sha256()
            read = 0
            for chunk in iter(lambda: extracted.read(1024 * 1024), b""):
                read += len(chunk)
                if read > member.size:
                    raise ReproductionError(
                        f"release tar member exceeds declared size: {relative}"
                    )
                digest.update(chunk)
            if (
                read != expected[relative]["bytes"]
                or digest.hexdigest() != expected[relative]["sha256"]
            ):
                raise ReproductionError(
                    f"release tar member differs from publication: {relative}"
                )
            seen.add(relative)
    if seen != set(expected):
        raise ReproductionError("release tar omits publication members")


def build_tar_zst(
    publication_root: Path,
    inventory: dict[str, Any],
    output_path: Path,
    profile: dict[str, Any],
    scratch: Path,
) -> dict[str, Any]:
    archive_profile = profile["archive"]
    zstd_profile = profile["zstandard"]
    tar_path = scratch / "release.tar"
    tar_material = deterministic_tar(
        publication_root,
        inventory,
        tar_path,
        prefix=archive_profile["prefix"],
        limits=archive_profile,
    )
    temporary_archive = scratch / "release.tar.zst"
    compressor = zstandard.ZstdCompressor(
        level=zstd_profile["level"],
        threads=zstd_profile["threads"],
        write_checksum=zstd_profile["write_checksum"],
        write_content_size=zstd_profile["write_content_size"],
        write_dict_id=zstd_profile["write_dict_id"],
    )
    with tar_path.open("rb") as source, temporary_archive.open("wb") as target:
        compressor.copy_stream(
            source,
            target,
            size=tar_path.stat().st_size,
        )
    compressed_size = temporary_archive.stat().st_size
    if compressed_size <= 0:
        raise ReproductionError("Zstandard archive is empty")
    if compressed_size > archive_profile["max_tar_bytes"]:
        raise ReproductionError(
            "Zstandard archive exceeds the configured compressed-byte bound"
        )
    ratio = tar_path.stat().st_size / compressed_size
    if ratio > archive_profile["max_compression_ratio"]:
        raise ReproductionError(
            f"release archive compression ratio exceeds limit: {ratio:.2f}"
        )

    decompressed = scratch / "verified-release.tar"
    # python-zstandard specifies max_window_size in KiB, while the profile
    # records byte limits.  Keep the decoder allocation bound aligned with the
    # configured maximum tar size rather than accidentally multiplying it.
    decompressor = zstandard.ZstdDecompressor(
        max_window_size=ceil(archive_profile["max_tar_bytes"] / 1024)
    )
    total = 0
    with (
        temporary_archive.open("rb") as source,
        decompressor.stream_reader(source) as reader,
        decompressed.open("wb") as target,
    ):
        while True:
            chunk = reader.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > archive_profile["max_tar_bytes"]:
                raise ReproductionError(
                    "decompressed release archive exceeds byte limit"
                )
            target.write(chunk)
    if (
        total != tar_material["bytes"]
        or sha256(decompressed) != tar_material["sha256"]
    ):
        raise ReproductionError(
            "Zstandard decompression differs from normalized tar"
        )
    validate_tar(
        decompressed,
        inventory,
        prefix=archive_profile["prefix"],
        limits=archive_profile,
    )

    copy_once(temporary_archive, output_path)
    return {
        "filename": output_path.name,
        "format": "application/zstd",
        "content_profile": "application/x-tar",
        "bytes": output_path.stat().st_size,
        "sha256": sha256(output_path),
        "normalized_tar_bytes": tar_material["bytes"],
        "normalized_tar_sha256": tar_material["sha256"],
        "compression_ratio": round(ratio, 6),
        "zstandard": {
            "distribution": zstd_profile["distribution"],
            "version": zstd_profile["version"],
            "level": zstd_profile["level"],
            "threads": zstd_profile["threads"],
            "checksum": zstd_profile["write_checksum"],
            "content_size": zstd_profile["write_content_size"],
            "dictionary_id": zstd_profile["write_dict_id"],
        },
        "validation": {
            "safe_paths": True,
            "regular_files_only": True,
            "bounded_members": True,
            "bounded_uncompressed_bytes": True,
            "all_member_hashes_match": True,
        },
    }


def validate_output(
    document: dict[str, Any],
    schema_path: Path,
) -> None:
    schema = load(schema_path)
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )
    violations = list(validator.iter_errors(document))
    if violations:
        raise ReproductionError(
            f"{schema_path.name} rejects generated output: "
            f"{violations[0].message}"
        )


def write_once(path: Path, body: bytes) -> None:
    if path.exists():
        if path.read_bytes() != body:
            raise ReproductionError(
                f"refusing to replace different immutable output: {path}"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if not path.is_file() or path.read_bytes() != body:
                raise ReproductionError(
                    f"refusing to replace different immutable output: {path}"
                )
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def copy_once(source: Path, path: Path) -> None:
    if path.exists():
        if (
            not path.is_file()
            or path.stat().st_size != source.stat().st_size
            or sha256(path) != sha256(source)
        ):
            raise ReproductionError(
                f"refusing to replace different immutable output: {path}"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as target, source.open("rb") as source_handle:
            temporary = Path(target.name)
            shutil.copyfileobj(source_handle, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if (
                not path.is_file()
                or path.stat().st_size != source.stat().st_size
                or sha256(path) != sha256(source)
            ):
                raise ReproductionError(
                    f"refusing to replace different immutable output: {path}"
                )
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run_reproduction(
    repository: Path,
    requested_ref: str,
    output_dir: Path,
    *,
    controller_profile: Path = DEFAULT_PROFILE,
    candidate_frozen: bool = False,
    fixture: bool = False,
    require_controller_binding: bool = True,
    keep_worktree: bool = False,
) -> dict[str, Any]:
    repository = repository.resolve()
    output_dir = output_dir.resolve()
    validate_ref(requested_ref)
    if not (repository / ".git").exists():
        raise ReproductionError(f"repository is not a Git checkout: {repository}")
    try:
        output_dir.relative_to(repository)
    except ValueError:
        pass
    else:
        raise ReproductionError(
            "reproduction outputs must be outside the source repository"
        )
    controller_profile_body = controller_profile.read_bytes()
    controller_profile_document = json.loads(controller_profile_body)
    validate_profile(controller_profile_document)

    commit = git(repository, "rev-parse", "--verify", f"{requested_ref}^{{commit}}")
    if not EXACT_COMMIT.fullmatch(commit):
        raise ReproductionError("Git did not resolve an exact 40-character commit")
    tree = git(repository, "show", "-s", "--format=%T", commit)
    commit_time = git(repository, "show", "-s", "--format=%cI", commit)
    exact_ref = bool(
        EXACT_COMMIT.fullmatch(requested_ref) and requested_ref == commit
    )
    if candidate_frozen and not exact_ref:
        raise ReproductionError(
            "--candidate-frozen requires the exact 40-character commit as --ref"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    worktree_parent = Path(
        tempfile.mkdtemp(prefix="okf-reproduction-worktree-")
    )
    checkout = worktree_parent / "checkout"
    added = False
    try:
        result = run(
            ["git", "worktree", "add", "--detach", str(checkout), commit],
            cwd=repository,
        )
        if result.returncode:
            raise ReproductionError(
                "cannot create clean detached worktree: "
                f"{str(result.stderr).strip()[:2000]}"
            )
        added = True
        if git(checkout, "status", "--porcelain=v1", "--untracked-files=all"):
            raise ReproductionError("new detached worktree is not clean")

        try:
            profile_relative = controller_profile.resolve().relative_to(
                repository
            ).as_posix()
        except ValueError as exc:
            raise ReproductionError(
                "controller reproduction profile must be inside the repository"
            ) from exc
        target_profile = checkout_path(
            checkout,
            profile_relative,
            label="target reproduction profile",
        )
        if target_profile.read_bytes() != controller_profile_body:
            raise ReproductionError(
                "target commit reproduction profile differs from controller"
            )
        profile = load(target_profile)
        validate_profile(profile)

        target_controller = checkout / "scripts" / CONTROLLER.name
        if not target_controller.is_file() or target_controller.is_symlink():
            raise ReproductionError(
                "target commit omits the canonical reproduction controller"
            )
        if require_controller_binding:
            if target_controller.read_bytes() != CONTROLLER.read_bytes():
                raise ReproductionError(
                    "target commit reproduction controller differs from the "
                    "executing controller"
                )
        (
            finalization_controller_material,
            release_observation_controller_material,
            pages_observation_controller_material,
            pages_observation_schema_material,
            assurance_receipt_controller_materials,
            deployed_manifest_template_material,
            deployed_probe_controller_material,
            finalization_contract_material,
            finalization_schema_materials,
            explorer_runtime_provenance,
        ) = finalization_materials(checkout, profile)

        environment = verify_environment(checkout, profile)
        required_receipts = verify_required_receipts(
            checkout,
            profile.get("required_receipts", []),
        )
        archive_limits = profile["archive"]
        publication_root = checkout_path(
            checkout,
            profile["publication_root"],
            label="publication root",
        )
        candidate_inventory = inventory_publication(
            publication_root,
            archive_limits,
        )
        candidate_semantics = semantic_digests(
            checkout,
            profile["semantic_pairs"],
            profile.get("offline_contexts", []),
        )

        execution_home = worktree_parent / "isolated-home"
        command_env = normalized_environment(execution_home)
        command_receipts = execute_commands(
            checkout,
            output_dir,
            profile,
            command_env,
        )

        rebuilt_inventory = inventory_publication(
            publication_root,
            archive_limits,
        )
        rebuilt_semantics = semantic_digests(
            checkout,
            profile["semantic_pairs"],
            profile.get("offline_contexts", []),
        )
        byte_identical = (
            candidate_inventory["rows"] == rebuilt_inventory["rows"]
        )
        semantic_identical = candidate_semantics == rebuilt_semantics
        if not byte_identical:
            candidate_rows = {
                row["path"]: row for row in candidate_inventory["rows"]
            }
            rebuilt_rows = {
                row["path"]: row for row in rebuilt_inventory["rows"]
            }
            differing = sorted(
                path
                for path in set(candidate_rows) | set(rebuilt_rows)
                if candidate_rows.get(path) != rebuilt_rows.get(path)
            )
            raise ReproductionError(
                "clean checkout did not reproduce publication bytes; first "
                f"differing paths: {differing[:20]}"
            )
        if not semantic_identical:
            raise ReproductionError(
                "clean checkout did not reproduce canonical semantic digests"
            )
        dirty_after = git(
            checkout,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        )
        if dirty_after:
            raise ReproductionError(
                "rebuild left tracked or untracked differences despite matching "
                "publication inventory"
            )

        scratch = Path(tempfile.mkdtemp(prefix="okf-release-archive-"))
        try:
            archive_path = output_dir / profile["archive"]["filename"]
            archive = build_tar_zst(
                publication_root,
                rebuilt_inventory,
                archive_path,
                profile,
                scratch,
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

        profile_material = material(target_profile, relative_to=checkout)
        controller_material = material(
            target_controller,
            relative_to=checkout,
        )
        provenance = {
            "schema": "okf-reproduction-provenance-inputs.v2",
            "commit": commit,
            "tree": tree,
            "commit_time": commit_time,
            "controller": controller_material,
            "finalization_controller": finalization_controller_material,
            "release_observation_controller": (
                release_observation_controller_material
            ),
            "pages_observation_controller": (
                pages_observation_controller_material
            ),
            "pages_observation_schema": pages_observation_schema_material,
            "assurance_receipt_controllers": (
                assurance_receipt_controller_materials
            ),
            "deployed_manifest_template": deployed_manifest_template_material,
            "deployed_probe_controller": deployed_probe_controller_material,
            "finalization_contract": finalization_contract_material,
            "finalization_schemas": finalization_schema_materials,
            "explorer_runtime_provenance": explorer_runtime_provenance,
            "profile": profile_material,
            "dependency_lock": environment["dependency_lock"],
            "dependencies": environment["dependencies"],
            "command_scripts": command_materials(checkout, profile),
            "commands": command_receipts,
            "environment": {
                "python": environment["python"],
                "zstandard": environment["zstandard"],
                "source_date_epoch": 0,
                "timezone": "UTC",
                "locale": "C",
                "credentials_inherited": False,
                "diagnostic_logs_identity_bearing": False,
                "network_guard": {
                    "kind": "python-sitecustomize-socket-and-cli-guard",
                    "sha256": sha256_bytes(
                        NETWORK_GUARD_BODY.encode("utf-8")
                    ),
                },
            },
            "network_policy": profile["network_policy"],
        }
        if required_receipts:
            provenance["required_receipts"] = required_receipts
        provenance_body = render(provenance)
        run_id = sha256_bytes(
            canonical_bytes(
                {
                    "commit": commit,
                    "profile": profile_material["sha256"],
                    "publication": rebuilt_inventory["inventory_sha256"],
                    "archive": archive["sha256"],
                    "provenance_inputs": sha256_bytes(provenance_body),
                    "dependency_lock_identity": environment[
                        "dependency_lock_identity"
                    ],
                    "required_receipts": [
                        row["material"]["sha256"] for row in required_receipts
                    ],
                }
            )
        )[:24]
        package_manifest = {
            "schema": "okf-release-package-manifest.v1",
            "commit": commit,
            "tree": tree,
            "archive": archive,
            "publication": {
                key: rebuilt_inventory[key]
                for key in ("files", "bytes", "inventory_sha256")
            },
            "semantic_digests": rebuilt_semantics,
            "promotion": {
                **profile["promotion"],
                "promote_by_sha256": archive["sha256"],
                "rule": (
                    "Attach the exact archive filename and bytes to the candidate "
                    "and final release tags. Promotion changes only the release "
                    "tag context; rebuilding or renaming is prohibited."
                ),
            },
        }

        schema_paths = {
            name: checkout_path(
                checkout,
                relative,
                label=f"{name} schema",
            )
            for name, relative in profile["output_schemas"].items()
        }
        validate_output(
            package_manifest,
            schema_paths["release_package_manifest"],
        )
        validate_output(
            provenance,
            schema_paths["provenance_inputs"],
        )
        package_body = render(package_manifest)
        provenance_path = output_dir / "provenance-inputs.json"
        package_path = output_dir / "release-package-manifest.json"
        write_once(provenance_path, provenance_body)
        write_once(package_path, package_body)

        eligible = bool(candidate_frozen and exact_ref and not fixture)
        evidence = {
            "run_id": run_id,
            "generated_at": commit_time,
            "timestamp_basis": (
                "The deterministic receipt uses the candidate commit time. "
                "Release-platform upload metadata records the external run time."
            ),
            "candidate": {
                "requested_ref": requested_ref,
                "commit": commit,
                "tree": tree,
                "exact_ref": exact_ref,
                "declared_frozen": candidate_frozen,
                "fixture": fixture,
            },
            "environment": {
                "python": environment["python"],
                "dependencies_exact": environment["dependencies_exact"],
                "zstandard": environment["zstandard"],
                "network_access_required": False,
                "network_access_guarded": True,
                "network_guard_sha256": sha256_bytes(
                    NETWORK_GUARD_BODY.encode("utf-8")
                ),
                "credentials_inherited": False,
            },
            "comparison": {
                "byte_identical": byte_identical,
                "semantic_identical": semantic_identical,
                "candidate_inventory_sha256": candidate_inventory[
                    "inventory_sha256"
                ],
                "rebuilt_inventory_sha256": rebuilt_inventory[
                    "inventory_sha256"
                ],
                "files": rebuilt_inventory["files"],
                "bytes": rebuilt_inventory["bytes"],
                "semantic_digests": rebuilt_semantics,
            },
            "archive": archive,
            "outputs": {
                "archive": archive["filename"],
                "release_package_manifest": {
                    "filename": package_path.name,
                    "bytes": len(package_body),
                    "sha256": sha256_bytes(package_body),
                },
                "provenance_inputs": {
                    "filename": provenance_path.name,
                    "bytes": len(provenance_body),
                    "sha256": sha256_bytes(provenance_body),
                },
            },
            "ledger_mutated": False,
        }
        if required_receipts:
            evidence["required_receipts"] = required_receipts
        if eligible:
            receipt = {
                "schema": "okf-reproduction-receipt.v1",
                "status": "passed",
                **evidence,
                "release_gate": {
                    "gate": "GATE-06",
                    "eligible": True,
                    "reason": (
                        "Exact frozen non-fixture commit reproduced byte-for-byte "
                        "and semantically."
                    ),
                },
            }
            validate_output(
                receipt,
                schema_paths["reproduction_receipt"],
            )
            attempt_path = output_dir / "reproduction-attempt.json"
            if attempt_path.exists():
                raise ReproductionError(
                    "refusing to upgrade an immutable non-release attempt "
                    "directory to an eligible receipt"
                )
            receipt_path = output_dir / "reproduction-receipt.json"
            write_once(receipt_path, render(receipt))
            return receipt

        reason = (
            "Fixture evidence cannot close a release gate."
            if fixture
            else "The candidate has not been explicitly frozen."
        )
        attempt = {
            "schema": "okf-reproduction-attempt.v1",
            "status": "not-release-eligible",
            **evidence,
            "release_gate": {
                "gate": "GATE-06",
                "eligible": False,
                "reason": reason,
            },
            "disqualifications": [reason],
        }
        receipt_path = output_dir / "reproduction-receipt.json"
        if receipt_path.exists():
            raise ReproductionError(
                "refusing to add a non-release attempt to an immutable "
                "eligible receipt directory"
            )
        write_once(
            output_dir / "reproduction-attempt.json",
            render(attempt),
        )
        return attempt
    finally:
        if added and not keep_worktree:
            run(
                ["git", "worktree", "remove", "--force", str(checkout)],
                cwd=repository,
            )
        if not keep_worktree:
            shutil.rmtree(worktree_parent, ignore_errors=True)


def copy_schema_fixture(destination: Path) -> None:
    source = ROOT / "release-assurance" / "schemas"
    destination.mkdir(parents=True, exist_ok=True)
    for name in (
        "reproduction-receipt.schema.json",
        "release-package-manifest.schema.json",
        "provenance-inputs.schema.json",
    ):
        shutil.copyfile(source / name, destination / name)


def copy_finalization_fixture(repository: Path) -> None:
    """Copy the canonical frozen finalization inputs into a fixture commit."""

    reproduction_controller = repository / "scripts" / CONTROLLER.name
    shutil.copyfile(CONTROLLER, reproduction_controller)

    finalization_controller = ROOT / CANONICAL_FINALIZATION_CONTROLLER
    observation_controller = ROOT / CANONICAL_RELEASE_OBSERVATION_CONTROLLER
    pages_observation_controller = (
        ROOT / CANONICAL_PAGES_OBSERVATION_CONTROLLER
    )
    assurance_controllers = [
        ROOT / relative for relative in CANONICAL_ASSURANCE_RECEIPT_CONTROLLERS
    ]
    deployed_manifest_template = ROOT / CANONICAL_DEPLOYED_MANIFEST_TEMPLATE
    deployed_probe_controller = ROOT / CANONICAL_DEPLOYED_PROBE_CONTROLLER
    finalization_contract = ROOT / CANONICAL_FINALIZATION_CONTRACT
    target_controller = repository / CANONICAL_FINALIZATION_CONTROLLER
    target_observation_controller = (
        repository / CANONICAL_RELEASE_OBSERVATION_CONTROLLER
    )
    target_pages_observation_controller = (
        repository / CANONICAL_PAGES_OBSERVATION_CONTROLLER
    )
    target_assurance_controllers = [
        repository / relative
        for relative in CANONICAL_ASSURANCE_RECEIPT_CONTROLLERS
    ]
    target_deployed_manifest_template = (
        repository / CANONICAL_DEPLOYED_MANIFEST_TEMPLATE
    )
    target_deployed_probe_controller = (
        repository / CANONICAL_DEPLOYED_PROBE_CONTROLLER
    )
    target_contract = repository / CANONICAL_FINALIZATION_CONTRACT
    target_controller.parent.mkdir(parents=True, exist_ok=True)
    target_observation_controller.parent.mkdir(parents=True, exist_ok=True)
    target_pages_observation_controller.parent.mkdir(
        parents=True, exist_ok=True
    )
    target_contract.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(finalization_controller, target_controller)
    shutil.copyfile(observation_controller, target_observation_controller)
    shutil.copyfile(
        pages_observation_controller,
        target_pages_observation_controller,
    )
    for source, target in zip(
        assurance_controllers,
        target_assurance_controllers,
        strict=True,
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    target_deployed_manifest_template.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        deployed_manifest_template,
        target_deployed_manifest_template,
    )
    target_deployed_probe_controller.parent.mkdir(
        parents=True, exist_ok=True
    )
    shutil.copyfile(
        deployed_probe_controller,
        target_deployed_probe_controller,
    )
    shutil.copyfile(finalization_contract, target_contract)

    contract = load(finalization_contract)
    if not isinstance(contract, dict):
        raise ReproductionError(
            "canonical finalization contract must be an object"
        )
    for relative in finalization_schema_declarations(contract):
        source = ROOT / relative
        target = repository / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def create_fixture_repository(root: Path) -> tuple[Path, str, Path]:
    repository = root / "fixture-repository"
    repository.mkdir(parents=True)
    (repository / "scripts").mkdir()
    (repository / "bundle").mkdir()
    (repository / "release-assurance" / "schemas").mkdir(parents=True)
    fixture_dependency_lock = parse_dependency_lock(
        ROOT / CANONICAL_DEPENDENCY_LOCK,
        ROOT / CANONICAL_DIRECT_REQUIREMENTS,
    )
    fixture_builder = """#!/usr/bin/env python3
import argparse
import hashlib
import json
import socket
from pathlib import Path

root = Path(__file__).resolve().parents[1]
bundle = root / "bundle"
parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
parser.add_argument("--assert-network-blocked", action="store_true")
args = parser.parse_args()
if args.assert_network_blocked:
    try:
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("127.0.0.1", 9))
    except RuntimeError as error:
        if "network access is disabled" not in str(error):
            raise
    else:
        raise SystemExit("offline reproduction socket guard is inactive")
data = b"stable fixture publication\\n"
payload = bundle / "data.txt"
checksums = {
    "schema": "okf-checksums.v1",
    "files": {
        "data.txt": {
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        "okf-bundle.jsonld": {
            "bytes": (bundle / "okf-bundle.jsonld").stat().st_size,
            "sha256": hashlib.sha256((bundle / "okf-bundle.jsonld").read_bytes()).hexdigest(),
        },
        "okf-bundle.yamlld": {
            "bytes": (bundle / "okf-bundle.yamlld").stat().st_size,
            "sha256": hashlib.sha256((bundle / "okf-bundle.yamlld").read_bytes()).hexdigest(),
        },
    },
}
expected = (json.dumps(checksums, indent=2, sort_keys=True) + "\\n").encode()
if args.check:
    if payload.read_bytes() != data or (bundle / "checksums.json").read_bytes() != expected:
        raise SystemExit("fixture is stale")
else:
    payload.write_bytes(data)
    (bundle / "checksums.json").write_bytes(expected)
"""
    (repository / "scripts" / "build_fixture.py").write_text(
        fixture_builder,
        encoding="utf-8",
    )
    yaml_document = """"@context":
  "@vocab": "https://example.test/okf#"
"@id": "https://example.test/fixture"
"@type": "Bundle"
title: "Reproduction fixture"
"""
    json_document = {
        "@context": {"@vocab": "https://example.test/okf#"},
        "@id": "https://example.test/fixture",
        "@type": "Bundle",
        "title": "Reproduction fixture",
    }
    (repository / "bundle" / "okf-bundle.yamlld").write_text(
        yaml_document,
        encoding="utf-8",
    )
    (repository / "bundle" / "okf-bundle.jsonld").write_bytes(
        render(json_document)
    )
    (repository / "bundle" / "data.txt").write_bytes(
        b"stable fixture publication\n"
    )
    profile = {
        "schema": "okf-reproduction-profile.v2",
        "profile_version": "fixture-1",
        "finalization_controller": CANONICAL_FINALIZATION_CONTROLLER,
        "finalization_contract": CANONICAL_FINALIZATION_CONTRACT,
        "release_observation_controller": (
            CANONICAL_RELEASE_OBSERVATION_CONTROLLER
        ),
        "pages_observation_controller": (
            CANONICAL_PAGES_OBSERVATION_CONTROLLER
        ),
        "pages_observation_schema": CANONICAL_PAGES_OBSERVATION_SCHEMA,
        "assurance_receipt_controllers": list(
            CANONICAL_ASSURANCE_RECEIPT_CONTROLLERS
        ),
        "deployed_manifest_template": CANONICAL_DEPLOYED_MANIFEST_TEMPLATE,
        "deployed_probe_controller": CANONICAL_DEPLOYED_PROBE_CONTROLLER,
        "publication_root": "bundle",
        "direct_requirements": CANONICAL_DIRECT_REQUIREMENTS,
        "dependency_lock": CANONICAL_DEPENDENCY_LOCK,
        "dependency_lock_parser": CANONICAL_DEPENDENCY_LOCK_PARSER,
        "dependency_lock_identity": dependency_lock_identity(
            fixture_dependency_lock
        ),
        "bootstrap_distribution_allowlist": list(
            CANONICAL_BOOTSTRAP_DISTRIBUTION_ALLOWLIST
        ),
        "python": {
            "major": sys.version_info.major,
            "minor": sys.version_info.minor,
            "micro": sys.version_info.micro,
        },
        "zstandard": {
            "distribution": "zstandard",
            "version": zstandard.__version__,
            "level": 3,
            "threads": 0,
            "write_checksum": True,
            "write_content_size": True,
            "write_dict_id": False,
        },
        "archive": {
            "prefix": "okf-fixture",
            "filename": "okf-fixture.tar.zst",
            "max_files": 20,
            "max_file_bytes": 1024 * 1024,
            "max_total_file_bytes": 4 * 1024 * 1024,
            "max_tar_bytes": 8 * 1024 * 1024,
            "max_compression_ratio": 200,
        },
        "promotion": {
            "candidate_tag": "fixture-rc",
            "final_tag": "fixture-final",
            "asset_filename": "okf-fixture.tar.zst",
            "asset_name_preserved": True,
            "archive_bytes_reused": True,
            "rebuild_prohibited": True,
            "rename_prohibited": True,
        },
        "semantic_pairs": [
            {
                "id": "fixture",
                "yaml_ld": "bundle/okf-bundle.yamlld",
                "json_ld": "bundle/okf-bundle.jsonld",
            }
        ],
        "build_commands": [["{python}", "scripts/build_fixture.py"]],
        "validation_commands": [
            [
                "{python}",
                "scripts/build_fixture.py",
                "--check",
                "--assert-network-blocked",
            ]
        ],
        "output_schemas": {
            "reproduction_receipt": "release-assurance/schemas/reproduction-receipt.schema.json",
            "release_package_manifest": "release-assurance/schemas/release-package-manifest.schema.json",
            "provenance_inputs": "release-assurance/schemas/provenance-inputs.schema.json",
        },
        "network_policy": {
            "dependency_installation_during_run": False,
            "build_commands_are_offline": True,
            "credentials_inherited": False,
            "python_socket_guard": True,
            "network_cli_guard": True,
        },
    }
    profile_path = repository / "release-assurance" / "reproduction-profile.json"
    profile_path.write_bytes(render(profile))
    shutil.copyfile(
        ROOT / CANONICAL_DIRECT_REQUIREMENTS,
        repository / CANONICAL_DIRECT_REQUIREMENTS,
    )
    shutil.copyfile(
        ROOT / CANONICAL_DEPENDENCY_LOCK,
        repository / CANONICAL_DEPENDENCY_LOCK,
    )
    shutil.copyfile(
        VALIDATION_LOCK_PARSER_CONTROLLER,
        repository / CANONICAL_DEPENDENCY_LOCK_PARSER,
    )
    copy_schema_fixture(repository / "release-assurance" / "schemas")
    copy_finalization_fixture(repository)

    result = run(
        [sys.executable, "scripts/build_fixture.py"],
        cwd=repository,
    )
    if result.returncode:
        raise ReproductionError(
            f"cannot initialize reproduction fixture: {result.stderr}"
        )
    run(["git", "init", "-q"], cwd=repository)
    run(["git", "add", "."], cwd=repository)
    commit_env = dict(os.environ)
    commit_env.update(
        {
            "GIT_AUTHOR_DATE": "2026-07-26T00:00:00Z",
            "GIT_COMMITTER_DATE": "2026-07-26T00:00:00Z",
        }
    )
    result = run(
        [
            "git",
            "-c",
            "user.name=OKF Fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "-q",
            "-m",
            "fixture",
        ],
        cwd=repository,
        env=commit_env,
    )
    if result.returncode:
        raise ReproductionError(
            f"cannot commit reproduction fixture: {result.stderr}"
        )
    commit = git(repository, "rev-parse", "HEAD")
    return repository, commit, profile_path


def fixture_dry_run(output_dir: Path) -> dict[str, Any]:
    fixture_root = Path(tempfile.mkdtemp(prefix="okf-reproduction-fixture-"))
    try:
        repository, commit, profile = create_fixture_repository(fixture_root)
        return run_reproduction(
            repository,
            commit,
            output_dir,
            controller_profile=profile,
            candidate_frozen=False,
            fixture=True,
            require_controller_binding=False,
        )
    finally:
        shutil.rmtree(fixture_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ref", help="Git ref or exact commit to reproduce.")
    mode.add_argument(
        "--fixture",
        action="store_true",
        help="Run the built-in clean-checkout packaging fixture.",
    )
    parser.add_argument(
        "--repository",
        type=Path,
        default=ROOT,
        help="Source Git repository (production mode only).",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=DEFAULT_PROFILE,
        help="Controller reproduction profile.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Empty or matching immutable output directory outside the repository.",
    )
    parser.add_argument(
        "--candidate-frozen",
        action="store_true",
        help=(
            "Declare that --ref is the exact frozen candidate commit. This is "
            "rejected for symbolic refs and is required for GATE-06 eligibility."
        ),
    )
    parser.add_argument(
        "--allow-build-execution",
        action="store_true",
        help="Explicitly authorize execution of the checked-out offline builders.",
    )
    parser.add_argument("--keep-worktree", action="store_true")
    args = parser.parse_args()
    try:
        if args.fixture:
            receipt = fixture_dry_run(args.output)
        else:
            if not args.allow_build_execution:
                raise ReproductionError(
                    "production reproduction requires --allow-build-execution"
                )
            receipt = run_reproduction(
                args.repository,
                args.ref,
                args.output,
                controller_profile=args.profile,
                candidate_frozen=args.candidate_frozen,
                fixture=False,
                require_controller_binding=True,
                keep_worktree=args.keep_worktree,
            )
    except ReproductionError as exc:
        print(f"Release reproduction failed closed: {exc}")
        return 1
    print(
        "Release reproduction passed: "
        f"run={receipt['run_id']} "
        f"files={receipt['comparison']['files']} "
        f"archive={receipt['archive']['sha256']} "
        f"gate_eligible={str(receipt['release_gate']['eligible']).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
