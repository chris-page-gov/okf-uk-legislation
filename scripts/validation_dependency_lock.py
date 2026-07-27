#!/usr/bin/env python3
"""Strict parsing helpers for the validation dependency lock.

The validation lock is both executable input to pip and release-assurance
evidence.  Treating it as an arbitrary requirements file would therefore be
too permissive: pip supports indexes, URLs, VCS references, editable installs,
environment markers, and unhashed requirements.  None of those forms belong
in this repository's deterministic validation closure.

This module accepts only the physical continuation format emitted by the
pinned ``uv pip compile`` command documented for ``requirements-validation``.
It also provides stable package/hash inventories and a pure installed-version
comparison helper for the release-assurance and SBOM integrations.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from packaging.version import InvalidVersion, Version


_SOURCE_NAME = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$"
)
_CANONICAL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DIRECT_PIN = re.compile(
    r"^(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"==(?P<version>[^\s;@\\]+)$"
)
_LOCKED_PIN = re.compile(
    r"^(?P<name>[a-z0-9]+(?:-[a-z0-9]+)*)"
    r"==(?P<version>[^\s;@\\]+) \\$"
)
_HASH_CONTINUATION = re.compile(
    r"^    --hash=sha256:(?P<hash>[0-9a-f]{64}) \\$"
)
_HASH_FINAL = re.compile(r"^    --hash=sha256:(?P<hash>[0-9a-f]{64})$")


class DependencyLockError(ValueError):
    """Raised when dependency evidence is ambiguous or non-canonical."""


@dataclass(frozen=True)
class DirectRequirement:
    """One exactly pinned direct validation dependency."""

    name: str
    version: str
    source_name: str

    @property
    def identity(self) -> str:
        return f"{self.name}=={self.version}"


@dataclass(frozen=True)
class LockedRequirement:
    """One package in the complete hash-locked validation closure."""

    name: str
    version: str
    hashes: tuple[str, ...]
    direct: bool = False

    @property
    def identity(self) -> str:
        return f"{self.name}=={self.version}"

    @property
    def purl(self) -> str:
        return f"pkg:pypi/{self.name}@{self.version}"

    def sbom_component(self) -> dict[str, object]:
        """Return the deterministic identity portion of an SBOM component.

        A lock can contain hashes for several mutually exclusive wheels and
        source archives.  Those alternative artifact hashes are deliberately
        exposed separately instead of being misrepresented as hashes of one
        installed component.
        """

        return {
            "bom-ref": self.purl,
            "type": "library",
            "name": self.name,
            "version": self.version,
            "purl": self.purl,
            "properties": [
                {
                    "name": "uk.gov.okf.validation-dependency-kind",
                    "value": "direct" if self.direct else "transitive",
                }
            ],
        }


@dataclass(frozen=True, order=True)
class LockedArtifactHash:
    """One allowed distribution artifact hash for a locked package."""

    package: str
    version: str
    sha256: str

    @property
    def identity(self) -> str:
        return f"{self.package}=={self.version}"


@dataclass(frozen=True, order=True)
class VersionMismatch:
    """An installed distribution whose version differs from the lock."""

    name: str
    expected: str
    actual: str


@dataclass(frozen=True)
class InstalledEnvironmentComparison:
    """Deterministic comparison between a lock and installed distributions."""

    missing: tuple[str, ...]
    mismatched: tuple[VersionMismatch, ...]
    unexpected: tuple[str, ...]

    @property
    def matches(self) -> bool:
        return not (self.missing or self.mismatched or self.unexpected)


@dataclass(frozen=True)
class ValidationDependencyLock:
    """Validated direct pins and their complete deterministic closure."""

    requirements: tuple[LockedRequirement, ...]
    direct_requirements: tuple[DirectRequirement, ...]

    @property
    def by_name(self) -> Mapping[str, LockedRequirement]:
        return MappingProxyType(
            {requirement.name: requirement for requirement in self.requirements}
        )

    @property
    def identities(self) -> tuple[str, ...]:
        return tuple(requirement.identity for requirement in self.requirements)

    @property
    def direct_names(self) -> tuple[str, ...]:
        return tuple(requirement.name for requirement in self.direct_requirements)

    @property
    def transitive_names(self) -> tuple[str, ...]:
        return tuple(
            requirement.name
            for requirement in self.requirements
            if not requirement.direct
        )

    @property
    def artifact_hashes(self) -> tuple[LockedArtifactHash, ...]:
        return tuple(
            LockedArtifactHash(
                package=requirement.name,
                version=requirement.version,
                sha256=digest,
            )
            for requirement in self.requirements
            for digest in requirement.hashes
        )

    @property
    def identity_digest(self) -> str:
        payload = "".join(f"{identity}\n" for identity in self.identities)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def artifact_hash_digest(self) -> str:
        payload = "".join(
            f"{artifact.identity} sha256:{artifact.sha256}\n"
            for artifact in self.artifact_hashes
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def sbom_components(self) -> tuple[dict[str, object], ...]:
        return tuple(
            requirement.sbom_component() for requirement in self.requirements
        )

    def inventory(self) -> dict[str, object]:
        """Return a stable, schema-neutral inventory for later projections."""

        return {
            "package_count": len(self.requirements),
            "direct_count": len(self.direct_requirements),
            "transitive_count": len(self.transitive_names),
            "artifact_hash_count": len(self.artifact_hashes),
            "identity_digest": self.identity_digest,
            "artifact_hash_digest": self.artifact_hash_digest,
            "direct_names": list(self.direct_names),
            "packages": [
                {
                    "identity": requirement.identity,
                    "name": requirement.name,
                    "version": requirement.version,
                    "direct": requirement.direct,
                    "purl": requirement.purl,
                    "sha256": list(requirement.hashes),
                }
                for requirement in self.requirements
            ],
        }


def canonicalize_distribution_name(value: str) -> str:
    """Return a PEP 503 canonical distribution name."""

    if not _SOURCE_NAME.fullmatch(value):
        raise DependencyLockError(f"invalid distribution name: {value!r}")
    return re.sub(r"[-_.]+", "-", value).lower()


def _canonical_version(
    value: str,
    *,
    source: str,
    line_number: int,
) -> str:
    try:
        parsed = Version(value)
    except InvalidVersion as error:
        raise DependencyLockError(
            f"{source}:{line_number}: invalid PEP 440 version {value!r}"
        ) from error
    canonical = str(parsed)
    if value != canonical:
        raise DependencyLockError(
            f"{source}:{line_number}: non-canonical version {value!r}; "
            f"expected {canonical!r}"
        )
    return canonical


def _validate_text_envelope(text: str, *, source: str) -> list[str]:
    if "\r" in text:
        raise DependencyLockError(f"{source}: CR/CRLF line endings are forbidden")
    if "\t" in text:
        raise DependencyLockError(f"{source}: tab characters are forbidden")
    if not text.endswith("\n"):
        raise DependencyLockError(f"{source}: file must end with one LF newline")

    lines = text.split("\n")
    for line_number, line in enumerate(lines[:-1], start=1):
        if line.endswith(" "):
            raise DependencyLockError(
                f"{source}:{line_number}: trailing whitespace is forbidden"
            )
    return lines[:-1]


def _is_comment(line: str) -> bool:
    return line.lstrip(" ").startswith("#")


def parse_direct_requirements_text(
    text: str,
    *,
    source: str = "<direct-requirements>",
) -> tuple[DirectRequirement, ...]:
    """Parse exact direct pins while retaining their authored display names."""

    requirements: list[DirectRequirement] = []
    seen: set[str] = set()
    previous_name: str | None = None

    for line_number, line in enumerate(
        _validate_text_envelope(text, source=source),
        start=1,
    ):
        if not line or _is_comment(line):
            continue
        match = _DIRECT_PIN.fullmatch(line)
        if match is None:
            raise DependencyLockError(
                f"{source}:{line_number}: expected one exact name==version pin; "
                "options, URLs, VCS/editable references, markers, and "
                "continuations are forbidden"
            )

        source_name = match.group("name")
        name = canonicalize_distribution_name(source_name)
        version = _canonical_version(
            match.group("version"),
            source=source,
            line_number=line_number,
        )
        if name in seen:
            raise DependencyLockError(
                f"{source}:{line_number}: duplicate direct dependency {name!r}"
            )
        if previous_name is not None and name <= previous_name:
            raise DependencyLockError(
                f"{source}:{line_number}: direct dependencies must be sorted "
                "by canonical name"
            )

        seen.add(name)
        previous_name = name
        requirements.append(
            DirectRequirement(
                name=name,
                version=version,
                source_name=source_name,
            )
        )

    if not requirements:
        raise DependencyLockError(f"{source}: no direct dependencies found")
    return tuple(requirements)


def parse_locked_requirements_text(
    text: str,
    *,
    source: str = "<dependency-lock>",
) -> tuple[LockedRequirement, ...]:
    """Parse the strict hash-continuation form of a compiled pip lock."""

    requirements: list[LockedRequirement] = []
    seen: set[str] = set()
    previous_name: str | None = None
    pending_name: str | None = None
    pending_version: str | None = None
    pending_line = 0
    pending_hashes: list[str] = []

    for line_number, line in enumerate(
        _validate_text_envelope(text, source=source),
        start=1,
    ):
        if pending_name is None:
            if not line or _is_comment(line):
                continue

            match = _LOCKED_PIN.fullmatch(line)
            if match is None:
                raise DependencyLockError(
                    f"{source}:{line_number}: expected canonical "
                    "name==version followed by a continuation; options, URLs, "
                    "VCS/editable references, markers, unhashed entries, and "
                    "stray continuations are forbidden"
                )
            name = match.group("name")
            if not _CANONICAL_NAME.fullmatch(name):
                raise DependencyLockError(
                    f"{source}:{line_number}: non-canonical package name {name!r}"
                )
            if canonicalize_distribution_name(name) != name:
                raise DependencyLockError(
                    f"{source}:{line_number}: non-canonical package name {name!r}"
                )
            if name in seen:
                raise DependencyLockError(
                    f"{source}:{line_number}: duplicate locked dependency {name!r}"
                )
            if previous_name is not None and name <= previous_name:
                raise DependencyLockError(
                    f"{source}:{line_number}: locked dependencies must be "
                    "sorted by canonical name"
                )

            pending_name = name
            pending_version = _canonical_version(
                match.group("version"),
                source=source,
                line_number=line_number,
            )
            pending_line = line_number
            pending_hashes = []
            continue

        if not line or _is_comment(line):
            raise DependencyLockError(
                f"{source}:{line_number}: continuation for {pending_name!r} "
                "must be followed immediately by a lowercase SHA-256 hash"
            )

        continuation = _HASH_CONTINUATION.fullmatch(line)
        final = _HASH_FINAL.fullmatch(line)
        match = continuation or final
        if match is None:
            raise DependencyLockError(
                f"{source}:{line_number}: expected exactly four spaces and "
                f"--hash=sha256:<64 lowercase hex> for {pending_name!r}"
            )

        digest = match.group("hash")
        if digest in pending_hashes:
            raise DependencyLockError(
                f"{source}:{line_number}: duplicate SHA-256 hash for "
                f"{pending_name!r}"
            )
        if pending_hashes and digest <= pending_hashes[-1]:
            raise DependencyLockError(
                f"{source}:{line_number}: hashes for {pending_name!r} must be "
                "strictly sorted"
            )
        pending_hashes.append(digest)

        if final is None:
            continue

        assert pending_version is not None
        requirements.append(
            LockedRequirement(
                name=pending_name,
                version=pending_version,
                hashes=tuple(pending_hashes),
            )
        )
        seen.add(pending_name)
        previous_name = pending_name
        pending_name = None
        pending_version = None
        pending_line = 0
        pending_hashes = []

    if pending_name is not None:
        raise DependencyLockError(
            f"{source}:{pending_line}: unterminated hash continuation for "
            f"{pending_name!r}"
        )
    if not requirements:
        raise DependencyLockError(f"{source}: no locked dependencies found")
    return tuple(requirements)


def _read_strict_utf8(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as error:
        raise DependencyLockError(f"{path}: file is not valid UTF-8") from error


def load_validation_dependency_lock(
    lock_path: Path,
    direct_path: Path,
) -> ValidationDependencyLock:
    """Load, validate, and join the complete lock with its direct pins."""

    direct_requirements = parse_direct_requirements_text(
        _read_strict_utf8(direct_path),
        source=str(direct_path),
    )
    parsed_lock = parse_locked_requirements_text(
        _read_strict_utf8(lock_path),
        source=str(lock_path),
    )
    direct_by_name = {
        requirement.name: requirement for requirement in direct_requirements
    }
    locked_by_name = {requirement.name: requirement for requirement in parsed_lock}

    missing = sorted(set(direct_by_name) - set(locked_by_name))
    if missing:
        raise DependencyLockError(
            f"{lock_path}: direct dependencies absent from lock: "
            + ", ".join(missing)
        )
    version_mismatches = [
        (
            name,
            direct_requirement.version,
            locked_by_name[name].version,
        )
        for name, direct_requirement in direct_by_name.items()
        if direct_requirement.version != locked_by_name[name].version
    ]
    if version_mismatches:
        details = ", ".join(
            f"{name} expected {expected}, locked {actual}"
            for name, expected, actual in version_mismatches
        )
        raise DependencyLockError(
            f"{lock_path}: direct dependency version mismatch: {details}"
        )

    requirements = tuple(
        replace(
            requirement,
            direct=requirement.name in direct_by_name,
        )
        for requirement in parsed_lock
    )
    return ValidationDependencyLock(
        requirements=requirements,
        direct_requirements=direct_requirements,
    )


def compare_installed_versions(
    dependency_lock: ValidationDependencyLock,
    installed: Mapping[str, str],
    *,
    allow_extra: Iterable[str] = (),
) -> InstalledEnvironmentComparison:
    """Compare installed versions with the lock without reading global state."""

    canonical_installed: dict[str, str] = {}
    for source_name, source_version in installed.items():
        name = canonicalize_distribution_name(source_name)
        if name in canonical_installed:
            raise DependencyLockError(
                f"installed distributions contain duplicate canonical name {name!r}"
            )
        try:
            version = str(Version(source_version))
        except InvalidVersion as error:
            raise DependencyLockError(
                f"installed distribution {source_name!r} has invalid version "
                f"{source_version!r}"
            ) from error
        canonical_installed[name] = version

    allowed = {canonicalize_distribution_name(name) for name in allow_extra}
    expected = dependency_lock.by_name
    missing = tuple(sorted(set(expected) - set(canonical_installed)))
    mismatched = tuple(
        VersionMismatch(
            name=name,
            expected=expected[name].version,
            actual=canonical_installed[name],
        )
        for name in sorted(set(expected) & set(canonical_installed))
        if Version(expected[name].version) != Version(canonical_installed[name])
    )
    unexpected = tuple(
        sorted(set(canonical_installed) - set(expected) - allowed)
    )
    return InstalledEnvironmentComparison(
        missing=missing,
        mismatched=mismatched,
        unexpected=unexpected,
    )


def installed_distribution_versions(
    distributions: Sequence[importlib.metadata.Distribution] | None = None,
) -> Mapping[str, str]:
    """Collect installed versions for explicit use by later assurance code."""

    selected = distributions
    if selected is None:
        selected = tuple(importlib.metadata.distributions())

    versions: dict[str, str] = {}
    for distribution in selected:
        source_name = distribution.metadata.get("Name")
        if not source_name:
            raise DependencyLockError(
                "installed distribution is missing required Name metadata"
            )
        name = canonicalize_distribution_name(source_name)
        if name in versions:
            raise DependencyLockError(
                f"installed distributions contain duplicate canonical name {name!r}"
            )
        versions[name] = distribution.version
    return MappingProxyType(dict(sorted(versions.items())))


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and summarize requirements-validation.txt",
    )
    repository = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--lock",
        type=Path,
        default=repository / "requirements-validation.txt",
    )
    parser.add_argument(
        "--direct",
        type=Path,
        default=repository / "requirements-validation.in",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_argument_parser().parse_args(argv)
    dependency_lock = load_validation_dependency_lock(
        arguments.lock,
        arguments.direct,
    )
    summary = {
        key: value
        for key, value in dependency_lock.inventory().items()
        if key != "packages"
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
