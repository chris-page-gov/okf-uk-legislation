from __future__ import annotations

import copy
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import reproduce_release_candidate as reproduction  # noqa: E402


class ReleaseReproductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="okf-reproduction-test-"
        )
        cls.root = Path(cls.temporary.name)
        (
            cls.repository,
            cls.commit,
            cls.profile,
        ) = reproduction.create_fixture_repository(cls.root)
        cls.first = cls.root / "first"
        cls.second = cls.root / "second"
        cls.eligible = cls.root / "eligible"
        cls.first_receipt = reproduction.run_reproduction(
            cls.repository,
            cls.commit,
            cls.first,
            controller_profile=cls.profile,
            fixture=True,
            require_controller_binding=False,
        )
        cls.eligible_receipt = reproduction.run_reproduction(
            cls.repository,
            cls.commit,
            cls.eligible,
            controller_profile=cls.profile,
            candidate_frozen=True,
            fixture=False,
            require_controller_binding=False,
        )
        cls.second_receipt = reproduction.run_reproduction(
            cls.repository,
            cls.commit,
            cls.second,
            controller_profile=cls.profile,
            fixture=True,
            require_controller_binding=False,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_clean_committed_checkout_reproduces_bytes_and_semantics(self) -> None:
        receipt = self.eligible_receipt
        self.assertEqual("passed", receipt["status"])
        self.assertTrue(receipt["candidate"]["exact_ref"])
        self.assertTrue(receipt["candidate"]["declared_frozen"])
        self.assertFalse(receipt["candidate"]["fixture"])
        self.assertTrue(receipt["comparison"]["byte_identical"])
        self.assertTrue(receipt["comparison"]["semantic_identical"])
        self.assertEqual(
            receipt["comparison"]["candidate_inventory_sha256"],
            receipt["comparison"]["rebuilt_inventory_sha256"],
        )
        self.assertTrue(receipt["environment"]["dependencies_exact"])
        self.assertFalse(receipt["environment"]["network_access_required"])
        self.assertTrue(receipt["environment"]["network_access_guarded"])
        self.assertRegex(
            receipt["environment"]["network_guard_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertFalse(receipt["environment"]["credentials_inherited"])

    def test_tar_zst_and_receipts_are_byte_deterministic(self) -> None:
        for relative in (
            "okf-fixture.tar.zst",
            "release-package-manifest.json",
            "provenance-inputs.json",
            "reproduction-attempt.json",
        ):
            with self.subTest(path=relative):
                self.assertEqual(
                    (self.first / relative).read_bytes(),
                    (self.second / relative).read_bytes(),
                )
        manifest = json.loads(
            (self.first / "release-package-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(manifest["promotion"]["rebuild_prohibited"])
        self.assertTrue(manifest["promotion"]["archive_bytes_reused"])
        self.assertTrue(manifest["promotion"]["asset_name_preserved"])
        self.assertTrue(manifest["promotion"]["rename_prohibited"])
        self.assertEqual("fixture-rc", manifest["promotion"]["candidate_tag"])
        self.assertEqual("fixture-final", manifest["promotion"]["final_tag"])
        self.assertEqual(
            "okf-fixture.tar.zst",
            manifest["promotion"]["asset_filename"],
        )
        self.assertEqual(
            manifest["archive"]["sha256"],
            manifest["promotion"]["promote_by_sha256"],
        )
        self.assertTrue(
            manifest["archive"]["validation"]["all_member_hashes_match"]
        )
        self.assertEqual("application/zstd", manifest["archive"]["format"])
        self.assertEqual(
            "application/x-tar",
            manifest["archive"]["content_profile"],
        )

    def test_fixture_cannot_close_gate_six(self) -> None:
        self.assertEqual(
            "okf-reproduction-attempt.v1",
            self.first_receipt["schema"],
        )
        self.assertEqual(
            "not-release-eligible",
            self.first_receipt["status"],
        )
        self.assertFalse(self.first_receipt["release_gate"]["eligible"])
        self.assertEqual("GATE-06", self.first_receipt["release_gate"]["gate"])
        self.assertIn("Fixture", self.first_receipt["release_gate"]["reason"])
        self.assertTrue(self.first_receipt["disqualifications"])
        self.assertFalse(self.first_receipt["ledger_mutated"])
        self.assertTrue((self.first / "reproduction-attempt.json").is_file())
        self.assertFalse((self.first / "reproduction-receipt.json").exists())

    def test_eligible_receipt_schema_is_fail_closed(self) -> None:
        schema_path = (
            ROOT
            / "release-assurance"
            / "schemas"
            / "reproduction-receipt.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        self.assertFalse(list(validator.iter_errors(self.eligible_receipt)))

        mutations = {
            "failed status": lambda row: row.__setitem__("status", "failed"),
            "symbolic ref": lambda row: row["candidate"].__setitem__(
                "requested_ref",
                "HEAD",
            ),
            "inexact ref": lambda row: row["candidate"].__setitem__(
                "exact_ref",
                False,
            ),
            "not frozen": lambda row: row["candidate"].__setitem__(
                "declared_frozen",
                False,
            ),
            "fixture": lambda row: row["candidate"].__setitem__(
                "fixture",
                True,
            ),
            "byte mismatch": lambda row: row["comparison"].__setitem__(
                "byte_identical",
                False,
            ),
            "semantic mismatch": lambda row: row["comparison"].__setitem__(
                "semantic_identical",
                False,
            ),
            "ineligible": lambda row: row["release_gate"].__setitem__(
                "eligible",
                False,
            ),
            "unexpected root field": lambda row: row.__setitem__(
                "unexpected",
                True,
            ),
            "unexpected nested field": lambda row: row["candidate"].__setitem__(
                "unexpected",
                True,
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                candidate = copy.deepcopy(self.eligible_receipt)
                mutate(candidate)
                self.assertTrue(
                    list(validator.iter_errors(candidate)),
                    f"{label} unexpectedly satisfied the release schema",
                )

        self.assertTrue(
            list(validator.iter_errors(self.first_receipt)),
            "a non-release attempt must never satisfy the release schema",
        )

    def test_finalization_inputs_are_exactly_hash_bound(self) -> None:
        provenance = json.loads(
            (self.eligible / "provenance-inputs.json").read_text(
                encoding="utf-8"
            )
        )
        contract_path = (
            self.repository
            / "release-assurance"
            / "external-finalization-contract.json"
        )
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        expected_schemas = reproduction.finalization_schema_declarations(
            contract
        )
        self.assertEqual(
            expected_schemas,
            [row["path"] for row in provenance["finalization_schemas"]],
        )
        for key, relative in (
            (
                "finalization_controller",
                "scripts/finalize_release_candidate.py",
            ),
            (
                "finalization_contract",
                "release-assurance/external-finalization-contract.json",
            ),
            (
                "release_observation_controller",
                "scripts/capture_github_release_observation.py",
            ),
        ):
            with self.subTest(material=key):
                actual = self.repository / relative
                self.assertEqual(relative, provenance[key]["path"])
                self.assertEqual(actual.stat().st_size, provenance[key]["bytes"])
                self.assertEqual(
                    reproduction.sha256(actual),
                    provenance[key]["sha256"],
                )
        for row in provenance["finalization_schemas"]:
            with self.subTest(schema=row["path"]):
                actual = self.repository / row["path"]
                self.assertEqual(actual.stat().st_size, row["bytes"])
                self.assertEqual(
                    reproduction.sha256(actual),
                    row["sha256"],
                )

    def test_generated_evidence_contains_no_empty_arrays(self) -> None:
        def assert_no_empty_arrays(value: object, location: str) -> None:
            if isinstance(value, list):
                self.assertTrue(value, f"empty evidence array at {location}")
                for index, item in enumerate(value):
                    assert_no_empty_arrays(item, f"{location}/{index}")
            elif isinstance(value, dict):
                for key, item in value.items():
                    assert_no_empty_arrays(item, f"{location}/{key}")

        for directory, names in (
            (
                self.first,
                (
                    "release-package-manifest.json",
                    "provenance-inputs.json",
                    "reproduction-attempt.json",
                ),
            ),
            (
                self.eligible,
                (
                    "release-package-manifest.json",
                    "provenance-inputs.json",
                    "reproduction-receipt.json",
                ),
            ),
        ):
            for name in names:
                with self.subTest(path=name, directory=directory.name):
                    document = json.loads(
                        (directory / name).read_text(encoding="utf-8")
                    )
                    assert_no_empty_arrays(document, name)

    def test_all_evidence_schema_objects_reject_additional_properties(
        self,
    ) -> None:
        for name in (
            "reproduction-receipt.schema.json",
            "release-package-manifest.schema.json",
            "provenance-inputs.schema.json",
        ):
            schema = json.loads(
                (
                    ROOT / "release-assurance" / "schemas" / name
                ).read_text(encoding="utf-8")
            )

            def inspect(value: object, location: str) -> None:
                if isinstance(value, dict):
                    if value.get("type") == "object":
                        self.assertIs(
                            False,
                            value.get("additionalProperties"),
                            f"open object schema at {name}{location}",
                        )
                    for key, item in value.items():
                        inspect(item, f"{location}/{key}")
                elif isinstance(value, list):
                    for index, item in enumerate(value):
                        inspect(item, f"{location}/{index}")

            inspect(schema, "")

    def test_profile_requires_canonical_finalization_paths(self) -> None:
        profile = json.loads(self.profile.read_text(encoding="utf-8"))
        profile["finalization_controller"] = "scripts/other.py"
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "finalization_controller must use canonical path",
        ):
            reproduction.validate_profile(profile)

    def test_production_profile_rebuilds_base_and_bootstraps_assurance(
        self,
    ) -> None:
        profile = json.loads(
            (
                ROOT
                / "release-assurance"
                / "reproduction-profile.json"
            ).read_text(encoding="utf-8")
        )
        commands = profile["build_commands"]
        base = [
            "{python}",
            "scripts/build_legislation_okf.py",
            "--from-existing",
        ]
        self.assertEqual(base, commands[0])
        self.assertEqual(1, commands.count(base))
        self.assertLess(
            commands.index(base),
            commands.index(
                [
                    "{python}",
                    "scripts/build_codex_semantic_enrichment.py",
                ]
            ),
        )
        self.assertLess(
            commands.index(
                ["{python}", "scripts/build_whole_law_okf.py"]
            ),
            commands.index(
                [
                    "{python}",
                    "scripts/run_release_evaluation.py",
                    "--check",
                ]
            ),
        )
        self.assertEqual(
            [
                ["{python}", "scripts/build_checksums.py"],
                ["{python}", "scripts/build_release_assurance.py"],
                ["{python}", "scripts/build_checksums.py"],
            ],
            commands[-3:],
        )

    def test_profile_requires_canonical_release_observation_controller(
        self,
    ) -> None:
        profile = json.loads(self.profile.read_text(encoding="utf-8"))
        profile["release_observation_controller"] = "scripts/other.py"
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "release_observation_controller must use canonical path",
        ):
            reproduction.validate_profile(profile)

    def test_pinned_zstandard_version_mismatch_fails_closed(self) -> None:
        profile = json.loads(self.profile.read_text(encoding="utf-8"))
        profile["zstandard"]["version"] = "0.0.0"
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "Zstandard implementation differs",
        ):
            reproduction.verify_environment(self.repository, profile)

    def test_promotion_asset_name_must_match_archive(self) -> None:
        profile = json.loads(self.profile.read_text(encoding="utf-8"))
        profile["promotion"]["asset_filename"] = "renamed.tar.zst"
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "promotion asset filename",
        ):
            reproduction.validate_profile(profile)

    def test_publication_symlink_is_rejected(self) -> None:
        root = self.root / "symlink-publication"
        root.mkdir()
        target = root / "target.txt"
        target.write_text("target", encoding="utf-8")
        link = root / "link.txt"
        try:
            os.symlink(target.name, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        limits = {
            "max_files": 10,
            "max_file_bytes": 1024,
            "max_total_file_bytes": 4096,
        }
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "symlink",
        ):
            reproduction.inventory_publication(root, limits)

    def test_archive_traversal_member_is_rejected(self) -> None:
        malicious = self.root / "malicious.tar"
        body = b"escape"
        with tarfile.open(malicious, "w") as archive:
            info = tarfile.TarInfo("../escape.txt")
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
        inventory = {
            "rows": [
                {
                    "path": "escape.txt",
                    "bytes": len(body),
                    "sha256": reproduction.sha256_bytes(body),
                }
            ]
        }
        limits = {
            "max_files": 10,
            "max_file_bytes": 1024,
            "max_total_file_bytes": 4096,
        }
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "unsafe release tar member",
        ):
            reproduction.validate_tar(
                malicious,
                inventory,
                prefix="fixture",
                limits=limits,
            )

    def test_archive_member_size_limit_is_enforced(self) -> None:
        oversized = self.root / "oversized.tar"
        body = b"12345"
        with tarfile.open(oversized, "w") as archive:
            info = tarfile.TarInfo("fixture/bundle/data.txt")
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
        inventory = {
            "rows": [
                {
                    "path": "data.txt",
                    "bytes": len(body),
                    "sha256": reproduction.sha256_bytes(body),
                }
            ]
        }
        limits = {
            "max_files": 10,
            "max_file_bytes": 4,
            "max_total_file_bytes": 4096,
        }
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "exceeds byte limit",
        ):
            reproduction.validate_tar(
                oversized,
                inventory,
                prefix="fixture",
                limits=limits,
            )

    def test_frozen_candidate_rejects_symbolic_ref(self) -> None:
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "exact 40-character commit",
        ):
            reproduction.run_reproduction(
                self.repository,
                "HEAD",
                self.root / "symbolic-ref",
                controller_profile=self.profile,
                candidate_frozen=True,
                fixture=False,
                require_controller_binding=False,
            )

    def test_controller_profile_outside_repository_is_rejected(self) -> None:
        outside = self.root / "outside-profile.json"
        outside.write_bytes(self.profile.read_bytes())
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "profile must be inside",
        ):
            reproduction.run_reproduction(
                self.repository,
                self.commit,
                self.root / "outside-profile-output",
                controller_profile=outside,
                fixture=True,
                require_controller_binding=False,
            )

    def test_required_runtime_receipt_is_hash_bound_and_fail_closed(self) -> None:
        checkout = self.root / "receipt-checkout"
        checkout.mkdir()
        receipt_path = checkout / "runtime-receipt.json"
        receipt_path.write_text(
            json.dumps(
                {
                    "schema": "runtime.v1",
                    "status": "passed",
                    "summary": {"passed": 4, "total": 4},
                }
            ),
            encoding="utf-8",
        )
        declaration = {
            "id": "runtime",
            "path": "runtime-receipt.json",
            "schema": "runtime.v1",
            "assertions": [
                {"pointer": "/status", "equals": "passed"},
                {
                    "pointer": "/summary/passed",
                    "equals_pointer": "/summary/total",
                },
            ],
        }
        result = reproduction.verify_required_receipts(
            checkout,
            [declaration],
        )
        self.assertEqual("passed", result[0]["status"])
        self.assertEqual(
            reproduction.sha256(receipt_path),
            result[0]["material"]["sha256"],
        )
        receipt_path.write_text(
            json.dumps(
                {
                    "schema": "runtime.v1",
                    "status": "failed",
                    "summary": {"passed": 3, "total": 4},
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "assertion failed",
        ):
            reproduction.verify_required_receipts(
                checkout,
                [declaration],
            )


if __name__ == "__main__":
    unittest.main()
