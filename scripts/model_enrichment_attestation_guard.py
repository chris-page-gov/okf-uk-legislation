#!/usr/bin/env python3
"""Offline verification for governed model-enrichment attestations.

The verifier accepts only a local artifact, a local Sigstore bundle and a
local trusted-root file.  GitHub CLI is invoked with an empty credential
environment, an unreachable proxy and identity constraints fixed by the
governance policy.  Supplying ``--bundle`` and ``--custom-trusted-root`` keeps
verification independent of the GitHub API.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any


MAX_VERIFIER_OUTPUT_BYTES = 4 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GH_VERSION_RE = re.compile(r"^gh version ([0-9]+\.[0-9]+\.[0-9]+)(?:\s|$)")


class AttestationVerificationError(ValueError):
    """Raised when trusted offline verification cannot be completed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise AttestationVerificationError(
            f"{label} must be a regular non-symlink file"
        )
    return path


def _offline_environment(gh_path: Path) -> dict[str, str]:
    return {
        "ALL_PROXY": "http://127.0.0.1:9",
        "GH_CONFIG_DIR": "/nonexistent",
        "GH_PROMPT_DISABLED": "1",
        "HOME": "/nonexistent",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "LANG": "C.UTF-8",
        "NO_COLOR": "1",
        "NO_PROXY": "",
        "PATH": str(gh_path.parent),
        "XDG_CONFIG_HOME": "/nonexistent",
    }


def _run_bounded(command: list[str], gh_path: Path) -> subprocess.CompletedProcess:
    try:
        completed = subprocess.run(
            command,
            check=False,
            cwd="/",
            env=_offline_environment(gh_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AttestationVerificationError(
            f"GitHub attestation verifier could not run: {exc}"
        ) from exc
    if (
        len(completed.stdout) > MAX_VERIFIER_OUTPUT_BYTES
        or len(completed.stderr) > MAX_VERIFIER_OUTPUT_BYTES
    ):
        raise AttestationVerificationError(
            "GitHub attestation verifier output exceeds the governed limit"
        )
    return completed


def _github_cli(
    expected_version: str,
    expected_binary_sha256: str,
) -> Path:
    located = shutil.which("gh")
    if located is None:
        raise AttestationVerificationError("GitHub CLI is not installed")
    gh_path = Path(located).resolve()
    _regular_file(gh_path, "GitHub CLI")
    if SHA256_RE.fullmatch(expected_binary_sha256) is None:
        raise AttestationVerificationError(
            "governed GitHub CLI binary SHA-256 is malformed"
        )
    observed_binary_sha256 = sha256_file(gh_path)
    if observed_binary_sha256 != expected_binary_sha256:
        raise AttestationVerificationError(
            "GitHub CLI executable differs from the governed binary: "
            f"expected {expected_binary_sha256}, "
            f"observed {observed_binary_sha256}"
        )
    version = _run_bounded([str(gh_path), "--version"], gh_path)
    if version.returncode != 0:
        raise AttestationVerificationError(
            "GitHub CLI version check failed"
        )
    first_line = version.stdout.decode("utf-8", errors="replace").splitlines()
    match = GH_VERSION_RE.match(first_line[0] if first_line else "")
    if match is None or match.group(1) != expected_version:
        observed = match.group(1) if match is not None else "unparseable"
        raise AttestationVerificationError(
            "GitHub CLI version differs from the governed version: "
            f"expected {expected_version}, observed {observed}"
        )
    return gh_path


def verify_external_attestation(
    *,
    subject_path: Path,
    subject_sha256: str,
    bundle_path: Path,
    trusted_root_path: Path,
    repository: str,
    signer_workflow: str,
    source_digest: str,
    predicate_type: str,
    cert_oidc_issuer: str,
    expected_gh_version: str,
    expected_gh_binary_sha256: str,
) -> dict[str, Any]:
    """Cryptographically verify one local subject under a pinned identity."""

    subject_path = _regular_file(subject_path, "attested subject")
    bundle_path = _regular_file(bundle_path, "attestation bundle")
    trusted_root_path = _regular_file(
        trusted_root_path, "attestation trusted root"
    )
    if SHA256_RE.fullmatch(subject_sha256) is None:
        raise AttestationVerificationError(
            "attested subject SHA-256 is malformed"
        )
    if sha256_file(subject_path) != subject_sha256:
        raise AttestationVerificationError(
            "attested subject SHA-256 does not match its bytes"
        )
    if SHA256_RE.fullmatch(source_digest) is None:
        raise AttestationVerificationError(
            "trusted workflow source digest is malformed"
        )
    gh_path = _github_cli(
        expected_gh_version,
        expected_gh_binary_sha256,
    )
    command = [
        str(gh_path),
        "attestation",
        "verify",
        str(subject_path),
        "--repo",
        repository,
        "--bundle",
        str(bundle_path),
        "--custom-trusted-root",
        str(trusted_root_path),
        "--signer-workflow",
        signer_workflow,
        "--source-digest",
        source_digest,
        "--predicate-type",
        predicate_type,
        "--cert-oidc-issuer",
        cert_oidc_issuer,
        "--deny-self-hosted-runners",
        "--format",
        "json",
    ]
    verified = _run_bounded(command, gh_path)
    if verified.returncode != 0:
        detail = verified.stderr.decode(
            "utf-8", errors="replace"
        ).strip()
        raise AttestationVerificationError(
            "GitHub/Sigstore attestation verification failed"
            + (f": {detail[:1000]}" if detail else "")
        )
    try:
        results = json.loads(verified.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AttestationVerificationError(
            "GitHub attestation verifier did not return JSON"
        ) from exc
    if not isinstance(results, list) or not results:
        raise AttestationVerificationError(
            "GitHub attestation verifier returned no verified attestation"
        )
    bound = False
    for result in results:
        if not isinstance(result, dict):
            continue
        verification = result.get("verificationResult")
        statement = (
            verification.get("statement")
            if isinstance(verification, dict)
            else None
        )
        subjects = (
            statement.get("subject") if isinstance(statement, dict) else None
        )
        if not isinstance(subjects, list):
            continue
        for subject in subjects:
            digest = (
                subject.get("digest")
                if isinstance(subject, dict)
                else None
            )
            if (
                isinstance(digest, dict)
                and digest.get("sha256") == subject_sha256
            ):
                bound = True
                break
        if bound:
            break
    if not bound:
        raise AttestationVerificationError(
            "verified attestation does not bind the expected subject digest"
        )
    return {
        "gh_cli_version": expected_gh_version,
        "verified_attestations": len(results),
        "subject_sha256": subject_sha256,
    }
