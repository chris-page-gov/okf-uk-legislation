from __future__ import annotations

import copy
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def dependency_checkout(
        self,
    ) -> tuple[Path, dict[str, object]]:
        checkout = Path(
            tempfile.mkdtemp(
                prefix="dependency-checkout-",
                dir=self.root,
            )
        )
        for relative in (
            reproduction.CANONICAL_DIRECT_REQUIREMENTS,
            reproduction.CANONICAL_DEPENDENCY_LOCK,
            reproduction.CANONICAL_DEPENDENCY_LOCK_PARSER,
        ):
            source = self.repository / relative
            target = checkout / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        profile = json.loads(self.profile.read_text(encoding="utf-8"))
        return checkout, profile

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
        self.assertEqual(
            contract["explorer"]["runtime_provenance"],
            provenance["explorer_runtime_provenance"],
        )
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
        self.assertEqual(
            list(reproduction.CANONICAL_ASSURANCE_RECEIPT_CONTROLLERS),
            [
                row["path"]
                for row in provenance["assurance_receipt_controllers"]
            ],
        )
        for row in provenance["assurance_receipt_controllers"]:
            with self.subTest(controller=row["path"]):
                actual = self.repository / row["path"]
                self.assertEqual(actual.stat().st_size, row["bytes"])
                self.assertEqual(
                    reproduction.sha256(actual),
                    row["sha256"],
                )

    def test_full_dependency_lock_identity_and_sources_are_receipted(
        self,
    ) -> None:
        provenance = json.loads(
            (self.eligible / "provenance-inputs.json").read_text(
                encoding="utf-8"
            )
        )
        profile = json.loads(self.profile.read_text(encoding="utf-8"))
        identity = profile["dependency_lock_identity"]
        self.assertEqual(
            {
                "package_count": 52,
                "direct_count": 7,
                "transitive_count": 45,
                "artifact_hash_count": 1159,
                "identity_sha256": (
                    "9542649bd62f7064e1bf6bfc82b4db0bc3260015649fd20cc804077076bc0c97"
                ),
                "artifact_hash_sha256": (
                    "e8a43fc379630e059925a1a892476a23b7bccd0ca459d07da2015594755a191c"
                ),
            },
            identity,
        )
        parsed = reproduction.parse_dependency_lock(
            self.repository / reproduction.CANONICAL_DEPENDENCY_LOCK,
            self.repository / reproduction.CANONICAL_DIRECT_REQUIREMENTS,
        )
        self.assertEqual(
            identity,
            reproduction.dependency_lock_identity(parsed),
        )
        self.assertEqual(52, len(provenance["dependencies"]))
        self.assertEqual(
            sorted(parsed.identities),
            sorted(
                f"{row['name']}=={row['required']}"
                for row in provenance["dependencies"]
            ),
        )
        command_materials = {
            row["path"]: row for row in provenance["command_scripts"]
        }
        for relative in (
            reproduction.CANONICAL_DIRECT_REQUIREMENTS,
            reproduction.CANONICAL_DEPENDENCY_LOCK_PARSER,
        ):
            with self.subTest(material=relative):
                path = self.repository / relative
                self.assertEqual(
                    reproduction.sha256(path),
                    command_materials[relative]["sha256"],
                )
        self.assertEqual(
            reproduction.sha256(
                self.repository / reproduction.CANONICAL_DEPENDENCY_LOCK
            ),
            provenance["dependency_lock"]["sha256"],
        )
        self.assertEqual(
            ["pip"],
            profile["bootstrap_distribution_allowlist"],
        )
        self.assertTrue(
            self.eligible_receipt["environment"]["dependencies_exact"]
        )
        deployed_template = provenance["deployed_manifest_template"]
        self.assertEqual(
            reproduction.CANONICAL_DEPLOYED_MANIFEST_TEMPLATE,
            deployed_template["path"],
        )
        deployed_template_path = (
            self.repository / deployed_template["path"]
        )
        self.assertEqual(
            reproduction.sha256(deployed_template_path),
            deployed_template["sha256"],
        )
        deployed_probe = provenance["deployed_probe_controller"]
        self.assertEqual(
            reproduction.CANONICAL_DEPLOYED_PROBE_CONTROLLER,
            deployed_probe["path"],
        )
        deployed_probe_path = self.repository / deployed_probe["path"]
        self.assertEqual(
            reproduction.sha256(deployed_probe_path),
            deployed_probe["sha256"],
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
        input_evidence = [
            "{python}",
            "scripts/build_model_enrichment_input_evidence.py",
        ]
        v2 = [
            "{python}",
            "scripts/build_codex_semantic_enrichment.py",
        ]
        effects = [
            "{python}",
            "scripts/build_legislation_effects.py",
            "--offline",
        ]
        v3_build = [
            "{python}",
            "scripts/build_codex_semantic_enrichment_v3.py",
            "build",
        ]
        v3_audit = [
            "{python}",
            "scripts/audit_codex_semantic_enrichment_v3.py",
            "audit",
        ]
        discovery = [
            "{python}",
            "scripts/rebuild_legislation_discovery.py",
        ]
        stages = [
            base,
            input_evidence,
            v2,
            effects,
            v3_build,
            v3_audit,
            discovery,
        ]
        for stage in stages:
            self.assertEqual(1, commands.count(stage))
        self.assertEqual(
            [commands.index(stage) for stage in stages],
            sorted(commands.index(stage) for stage in stages),
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

    def test_production_profile_uses_active_v3_audit_without_embedded_runtime(
        self,
    ) -> None:
        profile = json.loads(
            (
                ROOT
                / "release-assurance"
                / "reproduction-profile.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn(
            [
                "{python}",
                "scripts/audit_codex_semantic_enrichment_v3.py",
                "audit",
            ],
            profile["build_commands"],
        )
        self.assertNotIn(
            [
                "{python}",
                "scripts/audit_codex_semantic_enrichment_v3.py",
                "build",
            ],
            profile["build_commands"],
        )
        capabilities = {
            row["capability"]: row for row in profile["subsumed_checks"]
        }
        self.assertIn(
            "governed-v3-independent-enrichment-audit",
            capabilities,
        )
        self.assertIn(
            "historical-v1-rejection-and-v2-preservation",
            capabilities,
        )
        self.assertNotIn("required_receipts", profile)
        contract = json.loads(
            (
                ROOT
                / "release-assurance"
                / "external-finalization-contract.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual("v0.5.4", contract["explorer"]["required_tag"])
        self.assertEqual(
            "release-assurance/schemas/explorer-runtime-receipt.schema.json",
            contract["input_schemas"]["explorer_runtime_receipt"],
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

    def test_profile_requires_canonical_assurance_receipt_controllers(
        self,
    ) -> None:
        profile = json.loads(self.profile.read_text(encoding="utf-8"))
        profile["assurance_receipt_controllers"].reverse()
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "assurance_receipt_controllers must use the canonical",
        ):
            reproduction.validate_profile(profile)

    def test_profile_requires_canonical_deployed_manifest_template(
        self,
    ) -> None:
        profile = json.loads(self.profile.read_text(encoding="utf-8"))
        profile["deployed_manifest_template"] = "release-assurance/other.json"
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "deployed_manifest_template must use the canonical path",
        ):
            reproduction.validate_profile(profile)

    def test_profile_requires_canonical_deployed_probe_controller(
        self,
    ) -> None:
        profile = json.loads(self.profile.read_text(encoding="utf-8"))
        profile["deployed_probe_controller"] = "scripts/other-probe.py"
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "deployed_probe_controller must use the canonical path",
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

    def test_dependency_lock_inputs_and_parser_fail_closed_on_tamper(
        self,
    ) -> None:
        checkout, profile = self.dependency_checkout()
        lock_path = checkout / reproduction.CANONICAL_DEPENDENCY_LOCK
        lock_body = lock_path.read_text(encoding="utf-8")
        lock_path.write_text(
            lock_body.replace(
                "--hash=sha256:",
                "--hash=sha512:",
                1,
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "lock is invalid",
        ):
            reproduction.verify_environment(checkout, profile)

        checkout, profile = self.dependency_checkout()
        (
            checkout / reproduction.CANONICAL_DIRECT_REQUIREMENTS
        ).unlink()
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "direct validation requirements is missing",
        ):
            reproduction.verify_environment(checkout, profile)

        checkout, profile = self.dependency_checkout()
        parser_path = (
            checkout / reproduction.CANONICAL_DEPENDENCY_LOCK_PARSER
        )
        parser_path.write_text(
            parser_path.read_text(encoding="utf-8")
            + "\n# unauthorised parser mutation\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "parser differs",
        ):
            reproduction.verify_environment(checkout, profile)

    def test_installed_distribution_inventory_is_exhaustive(
        self,
    ) -> None:
        profile = json.loads(self.profile.read_text(encoding="utf-8"))
        actual = dict(
            reproduction.validation_lock.installed_distribution_versions()
        )
        missing = dict(actual)
        missing.pop("attrs")
        with mock.patch.object(
            reproduction.validation_lock,
            "installed_distribution_versions",
            return_value=missing,
        ):
            with self.assertRaisesRegex(
                reproduction.ReproductionError,
                "pinned dependencies are unavailable",
            ):
                reproduction.verify_environment(self.repository, profile)

        unexpected = dict(actual)
        unexpected["rogue-package"] = "1.0"
        with mock.patch.object(
            reproduction.validation_lock,
            "installed_distribution_versions",
            return_value=unexpected,
        ):
            with self.assertRaisesRegex(
                reproduction.ReproductionError,
                "undeclared installed distributions are forbidden",
            ):
                reproduction.verify_environment(self.repository, profile)

        allowlisted = dict(actual)
        allowlisted["pip"] = "99.0"
        with mock.patch.object(
            reproduction.validation_lock,
            "installed_distribution_versions",
            return_value=allowlisted,
        ):
            environment = reproduction.verify_environment(
                self.repository,
                profile,
            )
        self.assertTrue(environment["dependencies_exact"])
        self.assertEqual(
            ["pip"],
            environment["bootstrap_distributions_present"],
        )

    def test_profile_binds_turtle_only_for_whole_law(self) -> None:
        profile = json.loads(
            (
                ROOT
                / "release-assurance"
                / "reproduction-profile.json"
            ).read_text(encoding="utf-8")
        )
        reproduction.validate_profile(profile)
        pairs = {pair["id"]: pair for pair in profile["semantic_pairs"]}
        self.assertEqual(
            "bundle/whole-law/okf-bundle.ttl",
            pairs["whole-law"]["turtle"],
        )
        self.assertNotIn("turtle", pairs["uk-legislation"])

        missing = copy.deepcopy(profile)
        next(
            pair
            for pair in missing["semantic_pairs"]
            if pair["id"] == "whole-law"
        ).pop("turtle")
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "Whole-Law semantic pair",
        ):
            reproduction.validate_profile(missing)

        root_turtle = copy.deepcopy(profile)
        next(
            pair
            for pair in root_turtle["semantic_pairs"]
            if pair["id"] == "uk-legislation"
        )["turtle"] = "bundle/okf-bundle.ttl"
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "root UK Legislation",
        ):
            reproduction.validate_profile(root_turtle)

        expanded_allowlist = copy.deepcopy(profile)
        expanded_allowlist["bootstrap_distribution_allowlist"].append(
            "setuptools"
        )
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "minimal canonical allowlist",
        ):
            reproduction.validate_profile(expanded_allowlist)

    def test_turtle_semantics_are_parsed_receipted_and_fail_closed(
        self,
    ) -> None:
        checkout = Path(
            tempfile.mkdtemp(prefix="turtle-checkout-", dir=self.root)
        )
        bundle = checkout / "bundle"
        bundle.mkdir()
        for name in ("okf-bundle.yamlld", "okf-bundle.jsonld"):
            shutil.copyfile(self.repository / "bundle" / name, bundle / name)
        json_document = json.loads(
            (bundle / "okf-bundle.jsonld").read_text(encoding="utf-8")
        )
        canonical = reproduction.jsonld.normalize(
            json_document,
            {
                "algorithm": "URDNA2015",
                "format": "application/n-quads",
            },
        )
        turtle_path = bundle / "okf-bundle.ttl"
        turtle_path.write_text(canonical, encoding="utf-8")
        pair = {
            "id": "fixture-turtle",
            "yaml_ld": "bundle/okf-bundle.yamlld",
            "json_ld": "bundle/okf-bundle.jsonld",
            "turtle": "bundle/okf-bundle.ttl",
        }
        result = reproduction.semantic_digests(
            checkout,
            [pair],
            [],
        )[0]
        self.assertTrue(result["representations_equivalent"])
        self.assertEqual(
            reproduction.sha256(turtle_path),
            result["turtle"]["sha256"],
        )
        self.assertEqual(
            reproduction.sha256_bytes(canonical.encode("utf-8")),
            result["canonical_nquads_sha256"],
        )

        turtle_path.write_text(
            (
                "<https://example.test/fixture> "
                "<https://example.test/okf#title> \"Tampered\" .\n"
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "Turtle canonical graph differs",
        ):
            reproduction.semantic_digests(checkout, [pair], [])

        turtle_path.unlink()
        with self.assertRaisesRegex(
            reproduction.ReproductionError,
            "Turtle is missing",
        ):
            reproduction.semantic_digests(checkout, [pair], [])

    def test_turtle_preserves_canonical_utc_z_lexical_form(self) -> None:
        checkout = Path(
            tempfile.mkdtemp(prefix="whole-law-turtle-", dir=self.root)
        )
        bundle = checkout / "bundle" / "whole-law"
        bundle.mkdir(parents=True)
        for name in (
            "okf-bundle.yamlld",
            "okf-bundle.jsonld",
            "okf-bundle.ttl",
        ):
            shutil.copyfile(
                ROOT / "bundle" / "whole-law" / name,
                bundle / name,
            )
        turtle_path = bundle / "okf-bundle.ttl"
        turtle_body = turtle_path.read_text(encoding="utf-8")
        self.assertIn(
            '"2026-07-25T22:54:00Z"'
            "^^<http://www.w3.org/2001/XMLSchema#dateTime>",
            turtle_body,
        )
        result = reproduction.semantic_digests(
            checkout,
            [
                {
                    "id": "whole-law-utc-z",
                    "yaml_ld": "bundle/whole-law/okf-bundle.yamlld",
                    "json_ld": "bundle/whole-law/okf-bundle.jsonld",
                    "turtle": "bundle/whole-law/okf-bundle.ttl",
                }
            ],
            [],
        )[0]
        self.assertEqual(
            reproduction.sha256(turtle_path),
            result["canonical_nquads_sha256"],
        )
        self.assertTrue(result["representations_equivalent"])

    def test_active_python_entrypoint_preserves_virtualenv_symlink(
        self,
    ) -> None:
        executable = self.root / "virtualenv" / "bin" / "python"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.symlink_to(Path(sys.executable).resolve())
        with mock.patch.object(
            reproduction.sys,
            "executable",
            str(executable),
        ):
            self.assertEqual(
                str(executable),
                reproduction.active_python_executable(),
            )
            self.assertNotEqual(
                str(executable.resolve()),
                reproduction.active_python_executable(),
            )

    def test_active_python_entrypoint_fails_closed(self) -> None:
        for value in (None, "", "relative/python"):
            with self.subTest(value=value), mock.patch.object(
                reproduction.sys,
                "executable",
                value,
            ):
                with self.assertRaises(reproduction.ReproductionError):
                    reproduction.active_python_executable()

        missing = self.root / "missing-python"
        with mock.patch.object(
            reproduction.sys,
            "executable",
            str(missing),
        ):
            with self.assertRaises(reproduction.ReproductionError):
                reproduction.active_python_executable()

        non_executable = self.root / "non-executable-python"
        non_executable.write_bytes(b"not executable\n")
        non_executable.chmod(0o600)
        with mock.patch.object(
            reproduction.sys,
            "executable",
            str(non_executable),
        ):
            with self.assertRaises(reproduction.ReproductionError):
                reproduction.active_python_executable()

    def test_execute_commands_uses_verified_python_entrypoint(self) -> None:
        checkout = Path(
            tempfile.mkdtemp(prefix="python-command-", dir=self.root)
        )
        output = checkout / "output"
        script = checkout / "scripts" / "fixture.py"
        script.parent.mkdir()
        script.write_text("raise SystemExit(0)\n", encoding="utf-8")
        executable = self.root / "command-venv" / "bin" / "python"
        executable.parent.mkdir(parents=True)
        executable.symlink_to(Path(sys.executable).resolve())
        identity = reproduction.python_executable_identity(str(executable))
        profile = {
            "build_commands": [
                ["{python}", "scripts/fixture.py"],
            ],
            "validation_commands": [],
        }
        completed = mock.Mock(returncode=0)
        with mock.patch.object(
            reproduction,
            "run",
            return_value=completed,
        ) as run_mock:
            receipts = reproduction.execute_commands(
                checkout,
                output,
                profile,
                {},
                str(executable),
                identity,
            )
        self.assertEqual(1, len(receipts))
        self.assertEqual(
            [str(executable), "scripts/fixture.py"],
            run_mock.call_args.args[0],
        )

        def replace_entrypoint(*_args: object, **_kwargs: object) -> mock.Mock:
            executable.unlink()
            executable.symlink_to("/usr/bin/false")
            return completed

        executable.unlink()
        executable.symlink_to(Path(sys.executable).resolve())
        identity = reproduction.python_executable_identity(str(executable))
        with mock.patch.object(
            reproduction,
            "run",
            side_effect=replace_entrypoint,
        ):
            with self.assertRaisesRegex(
                reproduction.ReproductionError,
                "changed during command",
            ):
                reproduction.execute_commands(
                    checkout,
                    checkout / "mutated-output",
                    profile,
                    {},
                    str(executable),
                    identity,
                )

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
