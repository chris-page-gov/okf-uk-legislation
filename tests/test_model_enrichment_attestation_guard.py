from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import model_enrichment_attestation_guard as guard  # noqa: E402


H = "a" * 64


class ModelEnrichmentAttestationGuardTests(unittest.TestCase):
    def fixture(self, directory: Path) -> tuple[Path, Path, Path, str]:
        subject = directory / "subject.json"
        subject.write_bytes(b'{"governed":true}\n')
        bundle = directory / "bundle.jsonl"
        bundle.write_bytes(b'{"mediaType":"application/vnd.dev.sigstore.bundle+json"}\n')
        trusted_root = directory / "trusted-root.jsonl"
        trusted_root.write_bytes(b'{"mediaType":"application/vnd.dev.sigstore.trustedroot+json"}\n')
        gh = directory / "gh"
        gh.write_bytes(b"test executable")
        return subject, bundle, trusted_root, hashlib.sha256(
            subject.read_bytes()
        ).hexdigest()

    def test_verifies_with_offline_identity_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            subject, bundle, trusted_root, digest = self.fixture(
                Path(temporary)
            )
            version = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=b"gh version 2.96.0 (test)\n",
                stderr=b"",
            )
            result_body = [
                {
                    "verificationResult": {
                        "statement": {
                            "subject": [
                                {
                                    "name": subject.name,
                                    "digest": {"sha256": digest},
                                }
                            ]
                        }
                    }
                }
            ]
            verified = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(result_body).encode("utf-8"),
                stderr=b"",
            )
            with (
                mock.patch.object(
                    guard.shutil, "which", return_value=str(Path(temporary) / "gh")
                ),
                mock.patch.object(
                    guard.subprocess,
                    "run",
                    side_effect=[version, verified],
                ) as runner,
            ):
                receipt = guard.verify_external_attestation(
                    subject_path=subject,
                    subject_sha256=digest,
                    bundle_path=bundle,
                    trusted_root_path=trusted_root,
                    repository="chris-page-gov/okf-uk-legislation",
                    signer_workflow=(
                        "chris-page-gov/okf-uk-legislation/.github/workflows/"
                        "model-enrichment-evidence.yml"
                    ),
                    source_digest=H,
                    predicate_type="https://slsa.dev/provenance/v1",
                    cert_oidc_issuer=(
                        "https://token.actions.githubusercontent.com"
                    ),
                    expected_gh_version="2.96.0",
                    expected_gh_binary_sha256=hashlib.sha256(
                        (Path(temporary) / "gh").read_bytes()
                    ).hexdigest(),
                )
            self.assertEqual(digest, receipt["subject_sha256"])
            command = runner.call_args_list[1].args[0]
            self.assertIn("--bundle", command)
            self.assertIn("--custom-trusted-root", command)
            self.assertIn("--signer-workflow", command)
            self.assertIn("--source-digest", command)
            self.assertIn("--deny-self-hosted-runners", command)
            environment = runner.call_args_list[1].kwargs["env"]
            self.assertNotIn("GH_TOKEN", environment)
            self.assertEqual("http://127.0.0.1:9", environment["HTTPS_PROXY"])

    def test_rejects_subject_digest_mismatch_before_invoking_gh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            subject, bundle, trusted_root, _ = self.fixture(Path(temporary))
            with mock.patch.object(guard.subprocess, "run") as runner:
                with self.assertRaisesRegex(
                    guard.AttestationVerificationError,
                    "subject SHA-256 does not match",
                ):
                    guard.verify_external_attestation(
                        subject_path=subject,
                        subject_sha256=H,
                        bundle_path=bundle,
                        trusted_root_path=trusted_root,
                        repository="chris-page-gov/okf-uk-legislation",
                        signer_workflow="trusted/workflow.yml",
                        source_digest=H,
                        predicate_type="https://slsa.dev/provenance/v1",
                        cert_oidc_issuer=(
                            "https://token.actions.githubusercontent.com"
                        ),
                        expected_gh_version="2.96.0",
                        expected_gh_binary_sha256=hashlib.sha256(
                            (Path(temporary) / "gh").read_bytes()
                        ).hexdigest(),
                    )
            runner.assert_not_called()

    def test_rejects_version_impersonator_with_wrong_binary_digest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            subject, bundle, trusted_root, digest = self.fixture(
                Path(temporary)
            )
            fake_gh = Path(temporary) / "gh"
            with (
                mock.patch.object(
                    guard.shutil, "which", return_value=str(fake_gh)
                ),
                mock.patch.object(guard.subprocess, "run") as runner,
            ):
                with self.assertRaisesRegex(
                    guard.AttestationVerificationError,
                    "differs from the governed binary",
                ):
                    guard.verify_external_attestation(
                        subject_path=subject,
                        subject_sha256=digest,
                        bundle_path=bundle,
                        trusted_root_path=trusted_root,
                        repository="chris-page-gov/okf-uk-legislation",
                        signer_workflow="trusted/workflow.yml",
                        source_digest=H,
                        predicate_type="https://slsa.dev/provenance/v1",
                        cert_oidc_issuer=(
                            "https://token.actions.githubusercontent.com"
                        ),
                        expected_gh_version="2.96.0",
                        expected_gh_binary_sha256=H,
                    )
            runner.assert_not_called()

    def test_rejects_verified_output_without_expected_subject(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            subject, bundle, trusted_root, digest = self.fixture(
                Path(temporary)
            )
            responses = [
                subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=b"gh version 2.96.0\n",
                    stderr=b"",
                ),
                subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=json.dumps(
                        [
                            {
                                "verificationResult": {
                                    "statement": {
                                        "subject": [
                                            {"digest": {"sha256": H}}
                                        ]
                                    }
                                }
                            }
                        ]
                    ).encode("utf-8"),
                    stderr=b"",
                ),
            ]
            with (
                mock.patch.object(
                    guard.shutil, "which", return_value=str(Path(temporary) / "gh")
                ),
                mock.patch.object(
                    guard.subprocess, "run", side_effect=responses
                ),
            ):
                with self.assertRaisesRegex(
                    guard.AttestationVerificationError,
                    "does not bind",
                ):
                    guard.verify_external_attestation(
                        subject_path=subject,
                        subject_sha256=digest,
                        bundle_path=bundle,
                        trusted_root_path=trusted_root,
                        repository="chris-page-gov/okf-uk-legislation",
                        signer_workflow="trusted/workflow.yml",
                        source_digest=H,
                        predicate_type="https://slsa.dev/provenance/v1",
                        cert_oidc_issuer=(
                            "https://token.actions.githubusercontent.com"
                        ),
                        expected_gh_version="2.96.0",
                        expected_gh_binary_sha256=hashlib.sha256(
                            (Path(temporary) / "gh").read_bytes()
                        ).hexdigest(),
                    )


if __name__ == "__main__":
    unittest.main()
