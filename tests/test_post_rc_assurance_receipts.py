from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_post_rc_assurance_receipts as builder
import finalize_release_candidate as finalization

from tests.test_release_finalization import (
    FinalizationFixture,
    write_json,
)


class PostRCAssuranceReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="okf-post-rc-")
        self.root = Path(self.temporary.name)
        fixture_root = self.root / "fixture"
        fixture_root.mkdir()
        self.fixture = FinalizationFixture(fixture_root)
        self._complete_current_provenance_fixture()
        self.traceability_case_number = 0
        self.schema_dir = self.root / "codex-security-schemas"
        self.synthetic_schema_hashes = self._write_synthetic_security_schemas()
        self.real_load_candidate = builder.load_candidate
        self.load_candidate_patch = mock.patch.object(
            builder,
            "load_candidate",
            side_effect=self._load_candidate_with_test_schema_pins,
        )
        self.load_candidate_patch.start()
        self.addCleanup(self.load_candidate_patch.stop)
        self._prepare_security_scan()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _complete_current_provenance_fixture(self) -> None:
        """Keep this focused fixture compatible while the shared fixture evolves."""

        provenance = self.load(self.fixture.provenance_path)
        if "deployed_probe_controller" not in provenance:
            provenance["deployed_probe_controller"] = finalization.material(
                finalization.DEPLOYED_PROBE_CONTROLLER_PATH,
                finalization.CANONICAL_DEPLOYED_PROBE_CONTROLLER,
            )
        current_contract = finalization.load_json(finalization.DEFAULT_CONTRACT)
        provenance["explorer_runtime_provenance"] = copy.deepcopy(
            current_contract["explorer"]["runtime_provenance"]
        )
        write_json(self.fixture.provenance_path, provenance)
        reproduction = self.load(self.fixture.reproduction_path)
        reproduction["outputs"]["provenance_inputs"] = {
            "filename": self.fixture.provenance_path.name,
            "bytes": self.fixture.provenance_path.stat().st_size,
            "sha256": finalization.sha256_file(self.fixture.provenance_path),
        }
        write_json(self.fixture.reproduction_path, reproduction)

    def _write_synthetic_security_schemas(self) -> dict[str, str]:
        schemas = synthetic_security_schemas()
        self.schema_dir.mkdir()
        hashes: dict[str, str] = {}
        for role, filename in builder.SECURITY_SCHEMA_FILENAMES.items():
            body = finalization.render(schemas[role])
            (self.schema_dir / filename).write_bytes(body)
            hashes[role] = finalization.sha256_bytes(body)
        return hashes

    def _load_candidate_with_test_schema_pins(
        self,
        reproduction_dir: Path,
    ) -> dict[str, Any]:
        identity = copy.deepcopy(self.real_load_candidate(reproduction_dir))
        for role, sha256 in self.synthetic_schema_hashes.items():
            identity["contract"]["codex_security"]["schemas"][role]["sha256"] = sha256
        return identity

    def installed_security_schema_dir(self) -> Path | None:
        canonical_contract = finalization.load_json(finalization.DEFAULT_CONTRACT)
        version = canonical_contract["codex_security"]["producer"]["version"]
        candidates = []
        configured = os.environ.get("CODEX_SECURITY_SCHEMA_DIR")
        if configured:
            candidates.append(Path(configured))
        candidates.append(
            Path.home()
            / ".codex"
            / "plugins"
            / "cache"
            / "openai-curated-remote"
            / "codex-security"
            / version
            / "schemas"
        )
        return next(
            (
                candidate
                for candidate in candidates
                if all(
                    (candidate / filename).is_file()
                    for filename in builder.SECURITY_SCHEMA_FILENAMES.values()
                )
            ),
            None,
        )

    def _prepare_security_scan(self) -> None:
        self.fixture._write_security_evidence()
        (self.fixture.security_dir / "report.md").write_text(
            "# Codex Security Report\n\n"
            "This report is a deterministic projection of the sealed scan.\n\n"
            "| Result | Count |\n"
            "| --- | ---: |\n"
            "| Reportable findings | 0 |\n\n"
            "## Findings\n\n"
            "### No findings\n\n"
            "The completed scan contains no reportable findings.\n",
            encoding="utf-8",
        )
        artifact_relative = "artifacts/security-review.json"
        artifact_path = self.fixture.security_dir / artifact_relative
        artifact_path.parent.mkdir(exist_ok=True)
        write_json(
            artifact_path,
            {
                "status": "passed",
                "candidate": self.exact_candidate(),
                "summary": "Canonical security review evidence.",
            },
        )
        coverage_path = self.fixture.security_dir / "coverage.json"
        coverage = self.load(coverage_path)
        for surface in coverage["surfaces"]:
            surface["receiptRefs"] = [artifact_relative]
        write_json(coverage_path, coverage)

        findings_path = self.fixture.security_dir / "findings.json"
        manifest_path = self.fixture.security_dir / "scan-manifest.json"
        manifest = self.load(manifest_path)
        scan = manifest["scan"]
        scan["producer"] = copy.deepcopy(
            self.fixture.contract["codex_security"]["producer"]
        )
        scan["scope"] = {"includePaths": ["."], "excludePaths": []}
        scan["artifacts"] = [
            {
                "path": "findings.json",
                "sha256": finalization.sha256_file(findings_path),
                "mediaType": "application/json",
            },
            {
                "path": "coverage.json",
                "sha256": finalization.sha256_file(coverage_path),
                "mediaType": "application/json",
            },
            {
                "path": artifact_relative,
                "sha256": finalization.sha256_file(artifact_path),
                "mediaType": "application/json",
            },
        ]
        write_json(manifest_path, manifest)

    @staticmethod
    def load(path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    def exact_candidate(self) -> dict[str, str]:
        return {
            "repository": self.fixture.contract["candidate"]["repository"],
            "commit": self.fixture.commit,
            "tree": self.fixture.tree,
        }

    def deployed_args(self) -> argparse.Namespace:
        template = self.root / "deployed-entrypoints-manifest.template.json"
        template.write_bytes(deployed_template_bytes())
        return argparse.Namespace(
            reproduction_dir=self.fixture.reproduction_dir,
            template=template,
            rc_tag=self.fixture.contract["candidate"]["rc_tag"],
            output=self.root / "deployed" / builder.DEPLOYED_MANIFEST_NAME,
        )

    def security_args(self) -> argparse.Namespace:
        return argparse.Namespace(
            reproduction_dir=self.fixture.reproduction_dir,
            scan_dir=self.fixture.security_dir,
            codex_security_schema_dir=self.schema_dir,
            output_dir=self.root / "security-output",
        )

    def _write_security_manifest(self, manifest: dict[str, object]) -> None:
        write_json(self.fixture.security_dir / "scan-manifest.json", manifest)

    def _write_security_coverage(self, coverage: dict[str, object]) -> None:
        coverage_path = self.fixture.security_dir / "coverage.json"
        write_json(coverage_path, coverage)
        manifest_path = self.fixture.security_dir / "scan-manifest.json"
        manifest = self.load(manifest_path)
        for row in manifest["scan"]["artifacts"]:  # type: ignore[index]
            if row["path"] == "coverage.json":
                row["sha256"] = finalization.sha256_file(coverage_path)
        write_json(manifest_path, manifest)

    def _add_security_artifact(
        self,
        relative: str,
        sha256: str,
        media_type: str = "application/json",
    ) -> None:
        manifest_path = self.fixture.security_dir / "scan-manifest.json"
        manifest = self.load(manifest_path)
        manifest["scan"]["artifacts"].append(
            {
                "path": relative,
                "sha256": sha256,
                "mediaType": media_type,
            }
        )
        write_json(manifest_path, manifest)

    def traceability_args(self) -> argparse.Namespace:
        self.traceability_case_number += 1
        map_dir = self.root / f"traceability-input-{self.traceability_case_number}"
        map_dir.mkdir()
        evidence = map_dir / "final-release-evidence.json"
        write_json(
            evidence,
            {
                "status": "verified",
                "candidate": self.exact_candidate(),
            },
        )
        material = finalization.material(evidence, evidence.name)
        requirements = [
            {
                "id": requirement_id,
                "evidence": [material],
            }
            for requirement_id in self.fixture.contract["traceability"][
                "externally_closable_ids"
            ]
        ]
        mapping = {
            "schema": builder.TRACEABILITY_MAP_SCHEMA,
            "candidate": self.exact_candidate(),
            "requirements": requirements,
        }
        mapping_path = map_dir / "traceability-evidence-map.json"
        write_json(mapping_path, mapping)
        return argparse.Namespace(
            reproduction_dir=self.fixture.reproduction_dir,
            ledger=ROOT / "release-assurance" / "implementation-traceability.json",
            evidence_map=mapping_path,
            output_dir=self.root
            / f"traceability-output-{self.traceability_case_number}",
        )

    @staticmethod
    def tree_bytes(directory: Path) -> dict[str, bytes]:
        return {
            path.relative_to(directory).as_posix(): path.read_bytes()
            for path in directory.rglob("*")
            if path.is_file()
        }

    def test_locked_manifest_is_exact_valid_and_idempotent(self) -> None:
        args = self.deployed_args()
        output = builder.build_deployed_manifest(args)
        first = output.read_bytes()
        manifest = json.loads(first)
        self.assertEqual("locked", manifest["state"])
        self.assertEqual(self.fixture.commit, manifest["candidate"]["git_commit"])
        self.assertEqual(
            self.fixture.inventory,
            manifest["candidate"]["bundle_tree_sha256"],
        )
        self.assertEqual(
            self.fixture.contract["explorer"]["required_commit"],
            manifest["candidate"]["explorer_commit"],
        )
        self.assertEqual(
            [],
            builder.deployed_probe.validate_manifest(
                manifest,
                require_locked=True,
            ),
        )
        self.assertEqual(output, builder.build_deployed_manifest(args))
        self.assertEqual(first, output.read_bytes())

        manifest["candidate"]["release_tag"] = "v0.3.0-rc.2"
        output.write_bytes(finalization.render(manifest))
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "divergent overwrite",
        ):
            builder.build_deployed_manifest(args)

    def test_locked_manifest_rejects_arbitrary_valid_template_bytes(self) -> None:
        args = self.deployed_args()
        template = self.load(args.template)
        template["policy"]["timeout_seconds"] = 24
        write_json(args.template, template)
        self.assertEqual(
            [],
            builder.deployed_probe.validate_manifest(
                template,
                require_locked=False,
            ),
        )
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "template (?:bytes|SHA-256) differs",
        ):
            builder.build_deployed_manifest(args)
        self.assertFalse(args.output.exists())

    def test_security_wrapper_copies_complete_scan_atomically(self) -> None:
        args = self.security_args()
        output = builder.build_security_receipt(args)
        first = self.tree_bytes(args.output_dir)
        receipt = self.load(output)
        self.assertEqual("okf-security-assurance-receipt.v2", receipt["schema"])
        self.assertEqual(
            self.fixture.contract["required_security_checks"],
            receipt["checks"],
        )
        self.assertEqual(self.fixture.commit, receipt["candidate"]["commit"])
        self.assertEqual(
            {
                "scan_manifest",
                "findings",
                "coverage",
                "report",
                "scan_manifest_schema",
                "findings_schema",
                "coverage_schema",
                "artifact_inventory",
            },
            {row["role"] for row in receipt["materials"]},
        )
        inventory = self.load(args.output_dir / builder.SECURITY_INVENTORY_NAME)
        self.assertEqual(builder.SECURITY_INVENTORY_SCHEMA, inventory["schema"])
        self.assertEqual(
            {
                "findings.json",
                "coverage.json",
                "artifacts/security-review.json",
            },
            {row["source_path"] for row in inventory["entries"]},
        )
        for row in inventory["entries"]:
            copied = args.output_dir / row["path"]
            self.assertTrue(copied.is_file())
            self.assertEqual(row["bytes"], copied.stat().st_size)
            self.assertEqual(row["sha256"], finalization.sha256_file(copied))
        self.assertEqual(output, builder.build_security_receipt(args))
        self.assertEqual(first, self.tree_bytes(args.output_dir))

    def test_security_requires_canonical_git_revision_target(self) -> None:
        args = self.security_args()
        manifest_path = self.fixture.security_dir / "scan-manifest.json"

        manifest = self.load(manifest_path)
        manifest["scan"]["target"]["kind"] = "git_worktree"
        self._write_security_manifest(manifest)
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "exact immutable Git revision",
        ):
            builder.build_security_receipt(args)
        self.assertFalse(args.output_dir.exists())

        self._prepare_security_scan()
        manifest = self.load(manifest_path)
        manifest["scan"]["target"]["revision"] = "0" * 40
        self._write_security_manifest(manifest)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "security scan target revision differs",
        ):
            builder.build_security_receipt(args)
        self.assertFalse(args.output_dir.exists())

        self._prepare_security_scan()
        manifest = self.load(manifest_path)
        manifest["scan"]["target"]["snapshotDigest"] = (
            "codex-security-snapshot/v1:sha256:" + "0" * 64
        )
        self._write_security_manifest(manifest)
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "inapplicable coordinates: snapshotDigest",
        ):
            builder.build_security_receipt(args)
        self.assertFalse(args.output_dir.exists())

    def test_security_rejects_unpinned_or_malformed_schema(self) -> None:
        args = self.security_args()
        schema = self.schema_dir / builder.SECURITY_SCHEMA_FILENAMES["coverage"]
        schema.write_bytes(schema.read_bytes() + b"\n")
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "schema SHA-256 differs",
        ):
            builder.build_security_receipt(args)
        self.assertFalse(args.output_dir.exists())
        self.assertEqual([], list(self.root.glob(".security-output.*")))

        malformed_body = finalization.render({"type": 7})
        schema.write_bytes(malformed_body)
        self.synthetic_schema_hashes["coverage"] = finalization.sha256_bytes(
            malformed_body
        )
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "invalid pinned Codex Security schema coverage.schema.json",
        ):
            builder.build_security_receipt(args)
        self.assertFalse(args.output_dir.exists())

    def test_security_enforces_pinned_schema_on_scan_documents(self) -> None:
        args = self.security_args()
        coverage = self.load(self.fixture.security_dir / "coverage.json")
        coverage["documentType"] = "attacker.selected-coverage"
        self._write_security_coverage(coverage)
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "security coverage fails pinned coverage.schema.json",
        ):
            builder.build_security_receipt(args)
        self.assertFalse(args.output_dir.exists())
        self.assertEqual([], list(self.root.glob(".security-output.*")))

    def test_installed_canonical_security_schema_hashes_when_available(
        self,
    ) -> None:
        source = self.installed_security_schema_dir()
        if source is None:
            self.skipTest("optional installed Codex Security schemas unavailable")
        declarations = finalization.load_json(finalization.DEFAULT_CONTRACT)[
            "codex_security"
        ]["schemas"]
        for role, filename in builder.SECURITY_SCHEMA_FILENAMES.items():
            self.assertEqual(
                declarations[role]["sha256"],
                finalization.sha256_file(source / filename),
            )

    def test_security_rejects_contradictory_report_atomically(self) -> None:
        args = self.security_args()
        (self.fixture.security_dir / "report.md").write_text(
            "# Codex Security Report\n\n"
            "| Result | Count |\n"
            "| --- | ---: |\n"
            "| Reportable findings | 1 |\n\n"
            "## Findings\n\n"
            "### High-risk finding\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "security report contradicts",
        ):
            builder.build_security_receipt(args)
        self.assertFalse(args.output_dir.exists())
        self.assertEqual([], list(self.root.glob(".security-output.*")))

    def test_security_rejects_producer_times_and_partial_scope(self) -> None:
        args = self.security_args()
        manifest_path = self.fixture.security_dir / "scan-manifest.json"
        manifest = self.load(manifest_path)
        manifest["scan"]["producer"]["version"] = "1"
        self._write_security_manifest(manifest)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "security scan producer differs",
        ):
            builder.build_security_receipt(args)
        self.assertFalse(args.output_dir.exists())

        self._prepare_security_scan()
        manifest = self.load(manifest_path)
        manifest["scan"]["completedAt"] = "2026-07-26T03:59:59Z"
        self._write_security_manifest(manifest)
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "timestamps are not monotonically ordered",
        ):
            builder.build_security_receipt(args)
        self.assertFalse(args.output_dir.exists())

        self._prepare_security_scan()
        manifest = self.load(manifest_path)
        manifest["scan"]["startedAt"] = "not-a-date"
        self._write_security_manifest(manifest)
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "startedAt must be a canonical UTC date-time",
        ):
            builder.build_security_receipt(args)
        self.assertFalse(args.output_dir.exists())

        self._prepare_security_scan()
        coverage = self.load(self.fixture.security_dir / "coverage.json")
        coverage["mode"] = "commit"
        self._write_security_coverage(coverage)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "security coverage mode differs",
        ):
            builder.build_security_receipt(args)
        self.assertFalse(args.output_dir.exists())

        self._prepare_security_scan()
        manifest = self.load(manifest_path)
        manifest["scan"]["scope"]["includePaths"] = ["scripts"]
        self._write_security_manifest(manifest)
        coverage = self.load(self.fixture.security_dir / "coverage.json")
        coverage["includePaths"] = ["scripts"]
        coverage["mode"] = "scoped_path"
        coverage["inventoryStrategy"] = "scoped_path"
        self._write_security_coverage(coverage)
        with self.assertRaisesRegex(
            finalization.FinalizationError,
            "scope includePaths differs",
        ):
            builder.build_security_receipt(args)
        self.assertFalse(args.output_dir.exists())

    def test_security_rejects_absent_or_missing_receipt_refs_atomically(
        self,
    ) -> None:
        args = self.security_args()
        coverage = self.load(self.fixture.security_dir / "coverage.json")
        coverage["surfaces"][-1]["receiptRefs"] = []
        self._write_security_coverage(coverage)
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "receiptRefs are absent",
        ):
            builder.build_security_receipt(args)
        self.assertFalse(args.output_dir.exists())

        self._prepare_security_scan()
        coverage = self.load(self.fixture.security_dir / "coverage.json")
        coverage["surfaces"][-1]["receiptRefs"] = ["artifacts/does-not-exist.json"]
        self._write_security_coverage(coverage)
        self._add_security_artifact(
            "artifacts/does-not-exist.json",
            "0" * 64,
        )
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "cannot open security artifact",
        ):
            builder.build_security_receipt(args)
        self.assertFalse(args.output_dir.exists())

    def test_security_rejects_symlinked_and_hardlinked_artifacts(self) -> None:
        args = self.security_args()
        artifacts = self.fixture.security_dir / "artifacts"
        outside = self.fixture.security_dir / "outside-artifacts"
        outside.mkdir()
        write_json(outside / "linked.json", {"status": "passed"})
        try:
            os.symlink(outside, artifacts / "linked")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        coverage = self.load(self.fixture.security_dir / "coverage.json")
        coverage["surfaces"][-1]["receiptRefs"] = ["artifacts/linked/linked.json"]
        self._write_security_coverage(coverage)
        self._add_security_artifact(
            "artifacts/linked/linked.json",
            finalization.sha256_file(outside / "linked.json"),
        )
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "symbolic-link component",
        ):
            builder.build_security_receipt(args)
        self.assertFalse(args.output_dir.exists())

        (artifacts / "linked").unlink()
        self._prepare_security_scan()
        target = artifacts / "security-review.json"
        hardlink = artifacts / "hardlink.json"
        try:
            os.link(target, hardlink)
        except (OSError, NotImplementedError):
            self.skipTest("hard links are unavailable")
        coverage = self.load(self.fixture.security_dir / "coverage.json")
        coverage["surfaces"][-1]["receiptRefs"] = ["artifacts/hardlink.json"]
        self._write_security_coverage(coverage)
        self._add_security_artifact(
            "artifacts/hardlink.json",
            finalization.sha256_file(hardlink),
        )
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "must not be hard-linked",
        ):
            builder.build_security_receipt(args)
        self.assertFalse(args.output_dir.exists())

    def test_security_rejects_artifact_path_traversal(self) -> None:
        args = self.security_args()
        outside = self.fixture.security_dir / "outside.json"
        write_json(outside, {"status": "passed"})
        coverage = self.load(self.fixture.security_dir / "coverage.json")
        coverage["surfaces"][-1]["receiptRefs"] = ["artifacts/../../outside.json"]
        self._write_security_coverage(coverage)
        self._add_security_artifact(
            "artifacts/../../outside.json",
            finalization.sha256_file(outside),
        )
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "safe relative path",
        ):
            builder.build_security_receipt(args)
        self.assertFalse(args.output_dir.exists())

    def test_security_refuses_poisoned_existing_output(self) -> None:
        args = self.security_args()
        args.output_dir.mkdir()
        poison = args.output_dir / "attacker-controlled.json"
        poison.write_text("poison\n", encoding="utf-8")
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "divergent pre-existing.*file set",
        ):
            builder.build_security_receipt(args)
        self.assertEqual("poison\n", poison.read_text(encoding="utf-8"))

    def test_security_publish_race_cannot_replace_poisoned_directory(
        self,
    ) -> None:
        args = self.security_args()
        real_rename = builder.rename_directory_noreplace

        def racing_rename(source: Path, destination: Path) -> None:
            destination.mkdir()
            (destination / "attacker.txt").write_text(
                "poison\n",
                encoding="utf-8",
            )
            real_rename(source, destination)

        with (
            mock.patch.object(
                builder,
                "rename_directory_noreplace",
                side_effect=racing_rename,
            ),
            self.assertRaisesRegex(
                builder.ReceiptBuildError,
                "divergent pre-existing.*file set",
            ),
        ):
            builder.build_security_receipt(args)
        self.assertEqual(
            "poison\n",
            (args.output_dir / "attacker.txt").read_text(encoding="utf-8"),
        )
        self.assertEqual([], list(self.root.glob(".security-output.*")))

    def test_traceability_arbitrary_materials_only_yield_candidate(self) -> None:
        args = self.traceability_args()
        output = builder.build_traceability_receipt(args)
        first = self.tree_bytes(args.output_dir)
        receipt = self.load(output)
        closures = {row["id"]: row for row in receipt["closures"]}
        self.assertEqual("candidate", receipt["status"])
        self.assertNotEqual("passed", receipt["status"])
        self.assertIn(
            "only finalizer cross-binding",
            receipt["closure_rule"],
        )
        frozen = {row["id"]: row for row in self.load(args.ledger)["requirements"]}
        self.assertEqual(63, len(closures))
        for requirement_id in self.fixture.contract["traceability"][
            "externally_closable_ids"
        ]:
            self.assertEqual("passed", closures[requirement_id]["disposition"])
            self.assertEqual(
                frozen[requirement_id]["release_disposition"]["reason"],
                closures[requirement_id]["rationale"],
            )
            self.assertNotEqual(
                "implementation-traceability.json",
                closures[requirement_id]["evidence"][0]["path"],
            )
        for requirement_id in ("P05-02", "P05-06"):
            self.assertEqual(
                "superseded",
                closures[requirement_id]["disposition"],
            )
            self.assertEqual("D-13", closures[requirement_id]["superseded_by"])
        d06 = closures["D-06"]
        self.assertEqual("deferred", d06["disposition"])
        self.assertEqual(
            "implementation-traceability.json",
            d06["evidence"][0]["path"],
        )
        self.assertEqual(
            "implementation-traceability.json",
            d06["accepted_exception"]["decision_evidence"]["path"],
        )
        self.assertEqual(
            "Subsequent user decision",
            d06["accepted_exception"]["authority"],
        )
        self.assertEqual(output, builder.build_traceability_receipt(args))
        self.assertEqual(first, self.tree_bytes(args.output_dir))

    def test_traceability_rejects_caller_d06_and_closure_prose(self) -> None:
        args = self.traceability_args()
        mapping = self.load(args.evidence_map)
        mapping["requirements"].append(
            {
                "id": "D-06",
                "evidence": mapping["requirements"][0]["evidence"],
            }
        )
        write_json(args.evidence_map, mapping)
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "requirement IDs differ",
        ):
            builder.build_traceability_receipt(args)
        self.assertFalse(args.output_dir.exists())
        self.assertEqual(
            [],
            list(self.root.glob(f".{args.output_dir.name}.*")),
        )

        args = self.traceability_args()
        mapping = self.load(args.evidence_map)
        mapping["requirements"][0]["rationale"] = "Caller-selected closure."
        write_json(args.evidence_map, mapping)
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "keys differ",
        ):
            builder.build_traceability_receipt(args)
        self.assertFalse(args.output_dir.exists())

    def test_traceability_late_failure_leaves_no_partial_output(self) -> None:
        args = self.traceability_args()
        mapping = self.load(args.evidence_map)
        mapping["requirements"][-1]["evidence"][0]["path"] = "missing.json"
        write_json(args.evidence_map, mapping)
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "cannot open traceability",
        ):
            builder.build_traceability_receipt(args)
        self.assertFalse(args.output_dir.exists())
        self.assertEqual(
            [],
            list(self.root.glob(f".{args.output_dir.name}.*")),
        )

    def test_traceability_rejects_hardlinks_and_symlink_components(self) -> None:
        args = self.traceability_args()
        evidence = args.evidence_map.parent / "final-release-evidence.json"
        try:
            os.link(evidence, args.evidence_map.parent / "second-link.json")
        except (OSError, NotImplementedError):
            self.skipTest("hard links are unavailable")
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "must not be hard-linked",
        ):
            builder.build_traceability_receipt(args)
        self.assertFalse(args.output_dir.exists())

        args = self.traceability_args()
        real = self.root / "real-traceability-evidence"
        real.mkdir()
        linked_evidence = real / "evidence.json"
        write_json(
            linked_evidence,
            {"status": "passed", "candidate": self.exact_candidate()},
        )
        try:
            os.symlink(real, args.evidence_map.parent / "linked")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        mapping = self.load(args.evidence_map)
        material = finalization.material(
            linked_evidence,
            "linked/evidence.json",
        )
        for row in mapping["requirements"]:
            row["evidence"] = [material]
        write_json(args.evidence_map, mapping)
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "symbolic-link component",
        ):
            builder.build_traceability_receipt(args)
        self.assertFalse(args.output_dir.exists())

    def test_traceability_rejects_symlinked_output_parent(self) -> None:
        args = self.traceability_args()
        escape = self.root / "escape"
        escape.mkdir()
        linked_parent = self.root / "linked-output"
        try:
            os.symlink(escape, linked_parent)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        args.output_dir = linked_parent / "traceability"
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "symbolic-link component",
        ):
            builder.build_traceability_receipt(args)
        self.assertEqual([], list(escape.iterdir()))

    def test_traceability_rejects_hardlinked_existing_output(self) -> None:
        args = self.traceability_args()
        builder.build_traceability_receipt(args)
        evidence = next(
            path
            for path in args.output_dir.rglob("*.json")
            if "traceability-evidence" in path.parts
        )
        outside_link = self.root / "outside-output-link.json"
        try:
            os.link(evidence, outside_link)
        except (OSError, NotImplementedError):
            self.skipTest("hard links are unavailable")
        with self.assertRaisesRegex(
            builder.ReceiptBuildError,
            "contains a hard-linked file",
        ):
            builder.build_traceability_receipt(args)
        self.assertTrue(outside_link.is_file())


def synthetic_security_schemas() -> dict[str, dict[str, object]]:
    """Small hermetic producer schemas for the controller unit boundary."""

    artifact = {
        "type": "object",
        "required": ["path", "sha256", "mediaType"],
        "properties": {
            "path": {"type": "string", "minLength": 1},
            "sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "mediaType": {"type": "string", "minLength": 1},
        },
    }
    scan_manifest = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["documentType", "schemaVersion", "scan"],
        "properties": {
            "documentType": {"const": "codex-security.scan-manifest"},
            "schemaVersion": {"const": "1.0"},
            "scan": {
                "type": "object",
                "required": [
                    "id",
                    "producer",
                    "status",
                    "startedAt",
                    "completedAt",
                    "sealedAt",
                    "target",
                    "scope",
                    "coverageRef",
                    "findingsRef",
                    "artifacts",
                ],
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "producer": {
                        "type": "object",
                        "required": ["name", "version"],
                        "properties": {
                            "name": {"type": "string", "minLength": 1},
                            "version": {"type": "string", "minLength": 1},
                        },
                    },
                    "status": {"const": "completed"},
                    "startedAt": {"type": "string", "format": "date-time"},
                    "completedAt": {"type": "string", "format": "date-time"},
                    "sealedAt": {"type": "string", "format": "date-time"},
                    "target": {"type": "object"},
                    "scope": {"type": "object"},
                    "coverageRef": {"const": "coverage.json"},
                    "findingsRef": {"const": "findings.json"},
                    "artifacts": {
                        "type": "array",
                        "minItems": 1,
                        "items": artifact,
                    },
                },
            },
        },
    }
    findings = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["documentType", "schemaVersion", "scanId", "findings"],
        "properties": {
            "documentType": {"const": "codex-security.findings"},
            "schemaVersion": {"const": "1.0"},
            "scanId": {"type": "string", "minLength": 1},
            "findings": {"type": "array"},
        },
    }
    coverage = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": [
            "documentType",
            "schemaVersion",
            "scanId",
            "mode",
            "completeness",
            "inventoryStrategy",
            "includePaths",
            "excludePaths",
            "surfaces",
            "explicitExclusions",
            "deferred",
        ],
        "properties": {
            "documentType": {"const": "codex-security.coverage"},
            "schemaVersion": {"const": "1.0"},
            "scanId": {"type": "string", "minLength": 1},
            "mode": {"type": "string"},
            "completeness": {"type": "string"},
            "inventoryStrategy": {"type": "string"},
            "includePaths": {"type": "array", "items": {"type": "string"}},
            "excludePaths": {"type": "array", "items": {"type": "string"}},
            "surfaces": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "id",
                        "label",
                        "disposition",
                        "receiptRefs",
                    ],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "label": {"type": "string", "minLength": 1},
                        "disposition": {"type": "string"},
                        "receiptRefs": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
            "explicitExclusions": {"type": "array"},
            "deferred": {"type": "array"},
            "openQuestions": {"type": "array"},
        },
    }
    return {
        "scan_manifest": scan_manifest,
        "findings": findings,
        "coverage": coverage,
    }


def deployed_template_bytes() -> bytes:
    return (
        ROOT / "release-assurance" / "deployed-entrypoints-manifest.json"
    ).read_bytes()


if __name__ == "__main__":
    unittest.main()
